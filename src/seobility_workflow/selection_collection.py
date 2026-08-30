"""Small selection-only DataForSEO adapter with durable spend reservations. No retries."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

from .io import atomic_write_json, read_json, resolve_artifact_path
from .research.dataforseo import DataForSEOClient
from .topic_selection import SelectionError, fresh

ENDPOINTS = {
    "suggestions": "/v3/dataforseo_labs/google/keyword_suggestions/live",
    "overview": "/v3/dataforseo_labs/google/keyword_overview/live",
    "serp": "/v3/serp/google/organic/live/advanced",
}


def money(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise SelectionError("Costs must be finite nonnegative USD values")
    if not result.is_finite() or result < 0:
        raise SelectionError("Costs must be finite nonnegative USD values")
    return result


def request_for(plan):
    op = plan.get("operation")
    if op not in ENDPOINTS:
        raise SelectionError("Only suggestions, overview, and organic SERP requests are allowed")
    common = {"location_name": "United States", "language_code": "en"}
    if op == "overview":
        keywords = plan.get("keywords")
        if not isinstance(keywords, list) or not 1 <= len(keywords) <= 40 or any(not isinstance(k, str) or not k.strip() for k in keywords):
            raise SelectionError("Overview requires 1–40 keywords")
        task = dict(common, keywords=keywords, include_serp_info=False, include_clickstream_data=False)
    else:
        keyword = plan.get("keyword")
        if not isinstance(keyword, str) or not keyword.strip() or len(keyword) > 200:
            raise SelectionError("A nonempty keyword of at most 200 characters is required")
        if op == "suggestions":
            limit = plan.get("limit", 100)
            if type(limit) is not int or not 1 <= limit <= 100:
                raise SelectionError("Suggestion limit must be 1–100")
            task = dict(common, keyword=keyword, limit=limit, include_seed_keyword=True,
                        include_serp_info=False, include_clickstream_data=False)
        else:
            depth = plan.get("depth", 10)
            if type(depth) is not int or depth not in {10, 20}:
                raise SelectionError("SERP depth must be 10 or 20; retain only the first ten organic results for selection")
            task = dict(common, keyword=keyword, depth=depth, device="desktop")
    allowed = {"operation", "keyword", "keywords", "limit", "cost_bound_usd", "pricing_source", "pricing_checked_at"}
    if op == "serp":
        allowed.add("depth")
    if set(plan) - allowed:
        raise SelectionError("Unknown request fields; scope cannot be overridden through a plan")
    return ENDPOINTS[op], task


def fingerprint(endpoint, task):
    return hashlib.sha256(json.dumps([endpoint, task], sort_keys=True).encode()).hexdigest()


def normalized_rows(payload):
    """Keep provider metrics (including available monthly history) without fabricating missing rows."""
    rows = []
    for task in payload.get("tasks") or []:
        for result in task.get("result") or []:
            seed = result.get("seed_keyword_data")
            if isinstance(seed, dict):
                rows.append(seed)
            if isinstance(result.get("items"), list):
                rows.extend(result["items"])
            elif result.get("keyword"):
                rows.append(result)
    return rows


def validate_collection_ledger(ledger, run_dir):
    """Resolved billing is distinct from available/cachable results."""
    for entry in ledger["requests"]:
        if entry["state"] == "billed_missing_result":
            path = resolve_artifact_path(run_dir, entry["reconciliation_ref"])
            if (not entry["reconciliation_ref"].startswith("evidence/")
                    or not entry.get("resume_approval_ref")
                    or hashlib.sha256(path.read_bytes()).hexdigest() != entry["reconciliation_sha256"]
                    or money(entry["actual_cost_usd"]) > money(entry["reserved_usd"])):
                raise SelectionError("Invalid or changed reconciliation evidence")
        elif entry["state"] != "complete":
            raise SelectionError("Unresolved request/billing: do not retry or start another run to bypass it")
        money(entry["actual_cost_usd"])
    if sum((money(r["actual_cost_usd"]) for r in ledger["requests"]), Decimal(0)) > money(ledger["budget_usd"]):
        raise SelectionError("Ledger spend exceeds the approved cap")


def selection_cost_summary(ledger, run_dir):
    """Read-only reporting can disclose unresolved billing without permitting more spending."""
    unresolved = [r for r in ledger["requests"] if r["state"] == "unresolved"]
    resolved = [r for r in ledger["requests"] if r["state"] != "unresolved"]
    validate_collection_ledger(dict(ledger, requests=resolved), run_dir)
    for entry in resolved:
        if entry["state"] == "complete":
            path = resolve_artifact_path(run_dir, "evidence/" + entry["filename"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                raise SelectionError("Retained response hash differs from billing ledger")
    if any(r.get("actual_cost_usd") is not None for r in unresolved):
        raise SelectionError("Unresolved entry with reported cost requires manual reconciliation")
    actual = sum((money(r["actual_cost_usd"]) for r in resolved), Decimal(0))
    held = sum((money(r["reserved_usd"]) for r in unresolved), Decimal(0))
    return {"budget_usd": ledger["budget_usd"], "actual_usd": str(actual),
            "actual_is_final": not unresolved, "unresolved_reserved_usd": str(held),
            "unresolved_request_count": len(unresolved),
            "accounted_usd": str(actual + held),
            "status": "billing_review_pending" if unresolved else "reconciled",
            "further_collection_blocked": bool(unresolved), "approval_ref": ledger["approval_ref"]}


def reconcile_missing_result(run_dir, plan, evidence_ref, resume_approval_ref):
    """Offline, explicit reconciliation against retained provider ID-list evidence."""
    if not str(resume_approval_ref).strip() or not evidence_ref.startswith("evidence/"):
        raise SelectionError("Reconciliation requires evidence and explicit resume approval")
    root = Path(run_dir).resolve()
    endpoint, task = request_for(plan)
    key = fingerprint(endpoint, task)
    path = resolve_artifact_path(root, evidence_ref)
    body = path.read_bytes()
    evidence = json.loads(body)
    response = evidence["history_lookup"]["response"]
    if response.get("status_code") != 20000 or response.get("tasks_error") != 0:
        raise SelectionError("Reconciliation lookup was not successful")
    matches = [row for group in response.get("tasks", []) for row in group.get("result", [])
               if row.get("url", "").lstrip("/") == endpoint.lstrip("/")
               and all(row.get("metadata", {}).get(k) == v for k, v in task.items())]
    if len(matches) != 1 or str(matches[0].get("status")) != "20000":
        raise SelectionError("Need one completed provider task matching every request parameter")
    row = matches[0]
    actual = money(row.get("cost"))
    lock = root / ".selection-collection.lock"
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError:
        raise SelectionError("Collector locked; cannot reconcile during collection")
    try:
        ledger_path = root / "evidence/collection-ledger.json"
        ledger = read_json(ledger_path)
        entries = [r for r in ledger["requests"] if r["fingerprint"] == key and r["state"] == "unresolved"]
        if len(entries) != 1:
            raise SelectionError("Need exactly one unresolved matching request")
        entry = entries[0]
        posted = datetime.fromisoformat(row["datetime_posted"])
        started = datetime.fromisoformat(entry["started_at"])
        if abs((posted - started).total_seconds()) > 120 or actual > money(entry["reserved_usd"]):
            raise SelectionError("Provider time or charge does not match the reserved request")
        if entry.get("actual_cost_usd") is not None and money(entry["actual_cost_usd"]) != actual:
            raise SelectionError("Previously recorded cost conflicts with provider evidence")
        if entry.get("filename"):
            raise SelectionError("Response already retained; inspect it instead of marking it missing")
        entry.update(state="billed_missing_result", actual_cost_usd=str(actual),
                     provider_task_id=row["id"], result_status="missing", billing_status="reconciled",
                     reconciliation_ref=evidence_ref, reconciliation_sha256=hashlib.sha256(body).hexdigest(),
                     resume_approval_ref=resume_approval_ref, endpoint=endpoint, request=task,
                     reconciled_at=datetime.now(timezone.utc).isoformat())
        validate_collection_ledger(ledger, root)
        atomic_write_json(ledger_path, ledger)
    finally:
        lock.unlink()


def approved_transport_retry(ledger, root, key, evidence_ref, now):
    """One explicitly reviewed retry; unknown original billing stays reserved, not zeroed."""
    if not str(evidence_ref).startswith("evidence/"):
        raise SelectionError("Retry approval must be retained under evidence/")
    path = resolve_artifact_path(root, evidence_ref)
    body = path.read_bytes()
    review = json.loads(body)
    if (review.get("fingerprint") != key or not review.get("approval_ref")
            or review.get("allow_one_extra_serp_attempt") is not True
            or review.get("retain_original_reservation") is not True
            or not fresh(review.get("reviewed_at"), now)):
        raise SelectionError("Missing matching, current, explicit retry approval")
    pending = [r for r in ledger["requests"] if r["state"] == "unresolved"]
    if len(pending) != 1:
        raise SelectionError("Retry requires exactly one reviewed unresolved request")
    old = pending[0]
    if (old["fingerprint"] != key or old["operation"] != "serp" or old.get("filename")
            or old.get("cause_type") != "URLError" or old.get("actual_cost_usd") is not None
            or old["started_at"] != review.get("original_started_at")
            or ledger["requests"][-1] is not old):
        raise SelectionError("Retry is limited to the latest matching transport failure")
    lookup = review["history_lookup"]
    response = lookup["response"]
    groups = response.get("tasks", [])
    if (response.get("status_code") != 20000 or response.get("tasks_error") != 0
            or response.get("cost") != 0 or len(groups) != 1
            or groups[0].get("status_code") != 20000 or groups[0].get("result") != []
            or groups[0].get("data", {}).get("function") != "id_list"):
        raise SelectionError("Retry requires a successful empty task-history check")
    data = groups[0]["data"]
    start = datetime.fromisoformat(old["started_at"])
    lower = datetime.fromisoformat(data["datetime_from"])
    upper = datetime.fromisoformat(data["datetime_to"])
    if not lower <= start <= upper <= datetime.fromisoformat(review["reviewed_at"]):
        raise SelectionError("Task-history window must cover the failed request and finish before review")
    # Validate every other charge normally; do not fabricate an actual cost for the failure.
    validate_collection_ledger(dict(ledger, requests=[r for r in ledger["requests"] if r is not old]), root)
    return {"retry_of": old["started_at"], "retry_approval_ref": review["approval_ref"],
            "retry_evidence_ref": evidence_ref, "retry_evidence_sha256": hashlib.sha256(body).hexdigest()}


def collect_selection(plan, run_dir, budget_usd, approval_ref, confirm_live=False, client=None, now=None,
                      retry_evidence_ref=None):
    """One request per invocation. Injected clients are for fixture testing only."""
    if not confirm_live or not str(approval_ref).strip():
        raise SelectionError("Collection requires explicit cost confirmation and approval reference")
    now = now or datetime.now(timezone.utc)
    budget = money(budget_usd)
    if budget <= 0:
        raise SelectionError("A positive approved budget cap is required")
    endpoint, task = request_for(plan)
    key = fingerprint(endpoint, task)
    run_dir = Path(run_dir).resolve()
    evidence = run_dir / "evidence"
    if (evidence / "source-ledger.json").exists():
        raise SelectionError("Offline review snapshot: collect only in the original spending run")
    evidence.mkdir(parents=True, exist_ok=True)
    lock = run_dir / ".selection-collection.lock"
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError:
        raise SelectionError("Collector locked; inspect any interrupted request before resuming")
    try:
        ledger_path = evidence / "collection-ledger.json"
        mode = "fixture" if client is not None else "live"
        ledger = read_json(ledger_path) if ledger_path.exists() else {
            "data_mode": mode, "budget_usd": str(budget), "approval_ref": approval_ref, "requests": []}
        if ledger["data_mode"] != mode or money(ledger["budget_usd"]) != budget or ledger["approval_ref"] != approval_ref:
            raise SelectionError("Run mode, budget, and approval are fixed; review before changing them")
        retry = approved_transport_retry(ledger, run_dir, key, retry_evidence_ref, now) if retry_evidence_ref else None
        if not retry:
            validate_collection_ledger(ledger, run_dir)
        cached = next((r for r in reversed(ledger["requests"]) if r["state"] == "complete" and r["fingerprint"] == key and fresh(r["retrieved_at"], now)), None)
        if cached:
            raw_path = evidence / cached["filename"]
            body = raw_path.read_bytes()
            if hashlib.sha256(body).hexdigest() != cached["sha256"]:
                raise SelectionError("Cached evidence changed; review rather than silently recollect")
            raw = json.loads(body)
            if (raw["fingerprint"] != key or raw["endpoint"] != endpoint or raw["request"] != task
                    or raw["data_mode"] != mode or raw["retrieved_at"] != cached["retrieved_at"]):
                raise SelectionError("Cached request provenance mismatch")
            cached.setdefault("reused_at", []).append(now.isoformat())
            atomic_write_json(ledger_path, ledger)
            return raw_path
        bound = money(plan.get("cost_bound_usd"))
        pricing = urlparse(str(plan.get("pricing_source", "")))
        if bound <= 0 or pricing.scheme != "https" or pricing.hostname not in {"dataforseo.com", "docs.dataforseo.com"} or not fresh(plan.get("pricing_checked_at"), now):
            raise SelectionError("A positive conservative request-cost bound and recently checked official pricing URL/date are required")
        spent = sum((money(r["reserved_usd"] if retry and r["state"] == "unresolved" else r["actual_cost_usd"])
                     for r in ledger["requests"]), Decimal(0))
        if spent + bound > budget:
            raise SelectionError("Request would exceed approved budget; no API call made")
        if len(ledger["requests"]) >= 30:
            raise SelectionError("Selection request limit reached; review scope")
        if plan["operation"] == "serp" and sum(r["operation"] == "serp" for r in ledger["requests"]) >= (11 if retry else 10):
            raise SelectionError("Selection SERP limit reached; no API call made")
        # A missing result gets at most one explicit replacement, even at a different depth.
        for index, old in enumerate(ledger["requests"]):
            if (old["state"] == "billed_missing_result" and old.get("request", {}).get("keyword") == task.get("keyword")
                    and any(r.get("request", {}).get("keyword") == task.get("keyword") for r in ledger["requests"][index + 1:])):
                raise SelectionError("Missing-result replacement already attempted; review before another call")
        entry = {"fingerprint": key, "operation": plan["operation"], "reserved_usd": str(bound),
                 "endpoint": endpoint, "request": task,
                 "state": "pending", "started_at": now.isoformat(),
                 "pricing_source": plan["pricing_source"], "pricing_checked_at": plan["pricing_checked_at"]}
        if retry:
            entry.update(retry)
        ledger["requests"].append(entry)
        atomic_write_json(ledger_path, ledger)  # Durable before the billable side effect.
        try:
            api = client or DataForSEOClient.from_environment()
            if getattr(api, "base_url", "https://api.dataforseo.com") != "https://api.dataforseo.com":
                raise SelectionError("This collector uses production only; use fixture tests for offline validation")
            payload = api.post(endpoint, [task])
            filename = "dataforseo-{}-{}.json".format(key[:16], len(ledger["requests"]))
            raw_path = evidence / filename
            envelope = {"data_mode": mode, "fingerprint": key, "endpoint": endpoint, "request": task,
                        "retrieved_at": now.isoformat(), "response": payload, "rows": normalized_rows(payload)}
            atomic_write_json(raw_path, envelope)
            entry.update(filename=filename, sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(), retrieved_at=now.isoformat())
            tasks = payload.get("tasks") or []
            if payload.get("status_code") != 20000 or len(tasks) != 1 or tasks[0].get("status_code") != 20000:
                raise SelectionError("Provider response not a successful single-task result")
            # Use the larger reported total when both forms are present; never assume absent cost is free.
            costs = []
            if payload.get("cost") is not None:
                costs.append(money(payload["cost"]))
            if all(t.get("cost") is not None for t in tasks):
                costs.append(sum((money(t["cost"]) for t in tasks), Decimal(0)))
            if not costs:
                raise SelectionError("Missing billed cost; review before another request")
            actual = max(costs)
            entry.update(actual_cost_usd=str(actual), state="complete")
            if actual > bound or spent + actual > budget:
                entry["state"] = "cost_review"
                raise SelectionError("Provider billed above the reserved bound; collection halted")
            atomic_write_json(ledger_path, ledger)
            return raw_path
        except Exception as exc:
            # Record categories, never exception strings that may contain credentials/URLs.
            entry["error_type"] = type(exc).__name__
            entry["cause_type"] = type(exc.__cause__).__name__ if exc.__cause__ else None
            if entry["state"] == "pending":
                entry["state"] = "unresolved"
            atomic_write_json(ledger_path, ledger)
            raise SelectionError("Collection stopped; inspect the retained ledger/evidence before any further paid call") from None
    finally:
        lock.unlink()
