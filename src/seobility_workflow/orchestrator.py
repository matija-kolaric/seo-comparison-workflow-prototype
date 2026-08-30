"""Fixed, agent-driven article queue. No model calls, scheduler or publishing commands."""
from __future__ import annotations

import json
import os
import re
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .errors import WorkflowError
from .io import atomic_write_json, read_json, resolve_artifact_path, sha256_file
from .selection_collection import request_for, fingerprint, money, validate_collection_ledger, selection_cost_summary
from .topic_selection import fresh, pair, query_pair
from .research.dataforseo import DataForSEOClient, load_dataforseo_env

STAGES = ("research", "brief", "assets", "writer", "qa")
OUTPUTS = {"research": ["research/research.md", "research/serp-analysis.md", "research/claims.json"],
           "brief": ["brief.md"], "assets": ["assets/manifest.md"], "writer": ["draft.md"], "qa": ["qa.json"]}
CHECKS = {
    "research": ["priority_serps_complete_or_limitations_explicit", "official_product_evidence", "reviews_qualified", "coverage_and_gaps_prioritized"],
    "brief": ["sections_map_to_research", "differentiation_explicit", "images_planned", "citations_planned"],
    "assets": ["required_assets_ready_or_approved_fallback", "captions_alt_attribution_ready", "rights_and_context_checked"],
    "writer": ["brief_followed", "supported_claims_only", "citations_and_assets_match", "brand_voice_self_reviewed"],
    "qa": ["claims_sources_checked", "brief_gaps_covered", "copy_quality_checked", "citations_and_assets_checked"],
}


class OrchestrationError(WorkflowError):
    pass


def stamp():
    return datetime.now(timezone.utc).isoformat()


def require(value, message):
    if not value:
        raise OrchestrationError(message)


class Orchestrator:
    def __init__(self, root, batch):
        self.root = Path(root).resolve()
        self.batch = Path(batch).resolve()
        self.batch.relative_to(self.root / "runs")
        require(self.batch.name.startswith("orchestration-"), "Use runs/orchestration-<id>")
        self.file = self.batch / "batch.json"

    @contextmanager
    def locked(self):
        self.batch.mkdir(parents=True, exist_ok=True)
        lock = self.batch / ".lock"
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        except FileExistsError:
            raise OrchestrationError("Batch locked; inspect the active command before resuming")
        try:
            yield
        finally:
            lock.unlink()

    def save(self, state):
        state["updated_at"] = stamp()
        atomic_write_json(self.file, state)

    def load(self):
        state = read_json(self.file)
        source = resolve_artifact_path(self.root, state["queue_ref"])
        require(sha256_file(source) == state["queue_sha256"], "Confirmed queue changed; review before continuing")
        return state

    def initialize(self, queue_path, approval_ref):
        require(str(approval_ref).strip(), "Explicit selection confirmation required")
        queue_path = Path(queue_path).resolve()
        queue_path.relative_to(self.root / "runs")
        queue = read_json(queue_path)
        rows = queue.get("selected", [])
        require(queue.get("data_mode") in {"live", "fixture"} and 1 <= len(rows) <= 6, "Need a reviewed selection queue")
        require(not queue.get("production_authorized") and not queue.get("publication_authorized"), "Import selection only, not existing production")
        keys = [pair(c["products"]) for c in rows]
        require(len(set(keys)) == len(keys) and all("seobility" in k and "ahrefs" not in k for k in keys), "Duplicate or out-of-scope pair")
        for c in rows:
            require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,70}", c["id"]) and c["decision"] == "selected"
                    and c["confidence"] in {"medium", "high"} and c["score"] >= 65
                    and c["input"]["page_type"] == "versus" and c["input"].get("market") == "United States"
                    and c["input"].get("language") == "en"
                    and query_pair(c["input"]["topic"]) == pair(c["products"]), "Ineligible queue item")
        require(len({c["id"] for c in rows}) == len(rows), "Duplicate article IDs")
        with self.locked():
            require(not self.file.exists(), "Batch exists; use next/status, do not reset it")
            for other in (self.root / "runs").glob("orchestration-*/batch.json"):
                queued = {query_pair(i["topic"]) for i in read_json(other)["items"]}
                require(not set(keys) & queued, "Pair already belongs to another production batch")
            state = {"version": "0.1", "data_mode": queue["data_mode"], "queue_ref": str(queue_path.relative_to(self.root)),
                     "queue_sha256": sha256_file(queue_path), "selection_approval_ref": approval_ref,
                     "production_approval": None, "publication_authorized": False, "budget_usd": None,
                     "costs": [], "history": [], "items": []}
            # Follow a revision back to its authoritative spending ledger, never its read-only copy.
            source_run = queue.get("revision", {}).get("supersedes") if queue.get("revision") else None
            ledger = self.root / "runs" / source_run / "evidence/collection-ledger.json" if source_run else queue_path.parent / "evidence/collection-ledger.json"
            ledger.resolve().relative_to(self.root / "runs")
            state["selection_ledger_ref"] = str(ledger.relative_to(self.root)) if ledger.exists() else None
            if queue["data_mode"] == "live":
                require(state["selection_ledger_ref"], "Live queue needs its original spending ledger")
            for c in rows:
                state["items"].append({"id": c["id"], "topic": c["input"]["topic"], "input": c["input"],
                                       "status": "selected", "stage": "research", "revision_count": 0,
                                       "run_ref": "articles/" + c["id"], "completed": {}, "dispatch": None})
            self.save(state)
            return self.summary(state)

    def summary(self, state):
        spent = sum((money(c["actual_usd"]) for c in state["costs"] if c.get("actual_usd") is not None), Decimal(0))
        held = sum((money(c["reserved_usd"]) for c in state["costs"] if c["state"] != "complete" and c.get("actual_usd") is None), Decimal(0))
        blockers = []
        if state.get("production_stop"):
            blockers.append("Production stopped by user; new explicit approval required")
        if not state["production_approval"]:
            blockers.append("Production scope and separate research budget not approved")
        selection = None
        if state.get("selection_ledger_ref"):
            try:
                selection = self.selection_accounting(state)
            except (WorkflowError, ValueError, KeyError, OSError):
                blockers.append("Original selection billing needs reconciliation or a reviewed reservation")
        if any(c["state"] != "complete" for c in state["costs"]):
            blockers.append("Production API request needs reconciliation")
        return {"batch": str(self.batch), "selection_confirmed": True, "production_approval": state["production_approval"],
                "budget_usd": state["budget_usd"], "confirmed_spend_usd": str(spent), "held_usd": str(held),
                "publication_authorized": False, "paid_research_blockers": blockers,
                "production_stop": state.get("production_stop"),
                "publication_approval": state.get("publication_approval"),
                "selection_accounting": selection,
                "aggregate_budget_usd": state.get("aggregate_budget_usd"),
                "production_expansions": state.get("production_expansions", []),
                "items": [{k: i[k] for k in ("id", "status", "stage", "revision_count")} for i in state["items"]]}

    def approve(self, ids, budget_usd, approval_ref):
        require(str(approval_ref).strip(), "Actual human production approval required")
        budget = money(budget_usd)
        with self.locked():
            s = self.load()
            require(s["production_approval"] is None, "Production scope is fixed; review a change instead of replacing approval")
            chosen = ids or [s["items"][0]["id"]]
            require(chosen and len(set(chosen)) == len(chosen) and set(chosen) <= {i["id"] for i in s["items"]}, "Unknown or duplicate approved IDs")
            s["production_approval"] = {"ref": approval_ref, "ids": chosen, "approved_at": stamp()}
            s["budget_usd"] = str(budget)
            for i in s["items"]:
                if i["id"] in chosen:
                    i["status"] = "approved"
            self.save(s)
            return self.summary(s)

    def expand(self, ids, approval_ref, aggregate_budget_usd):
        """Add selected articles without replacing the pilot approval or increasing its allocation."""
        require(str(approval_ref).strip(), "Actual expansion approval required")
        cap = money(aggregate_budget_usd)
        require(cap > 0, "Positive aggregate budget required")
        with self.locked():
            s = self.load()
            require(s["production_approval"], "Approve the initial production scope first")
            require(ids and len(ids) == len(set(ids)), "Name distinct additional articles")
            rows = {i["id"]: i for i in s["items"]}
            require(set(ids) <= set(rows), "Unknown article in expansion")
            for item in s["items"]:
                if item.get("input_sha256"):
                    self.verify(item)
            require(all(rows[k]["status"] == "selected" for k in ids), "Expansion only accepts unstarted selected articles")
            require(all(not self.run_dir(rows[k]).exists() for k in ids), "Existing article directory requires review")
            if s.get("aggregate_budget_usd") is not None:
                require(money(s["aggregate_budget_usd"]) == cap, "Expansion cannot change the aggregate cap")
            require(s.get("selection_ledger_ref"), "Shared cap requires the original selection ledger")
            ledger_path = resolve_artifact_path(self.root, s["selection_ledger_ref"])
            ledger = read_json(ledger_path)
            require(cap <= money(ledger["budget_usd"]), "Expansion cannot increase the original cap")
            accounting = selection_cost_summary(ledger, ledger_path.parent.parent)
            require(money(accounting["accounted_usd"]) + money(s["budget_usd"]) <= cap,
                    "Production allocation plus selection costs/reservations exceeds aggregate cap")
            s["aggregate_budget_usd"] = str(cap)
            event = {"event": "production_scope_expanded", "ids": list(ids), "approval_ref": approval_ref,
                     "approved_at": stamp(), "aggregate_budget_usd": str(cap), "production_budget_usd": s["budget_usd"]}
            s["history"].append(event)
            s.setdefault("production_expansions", []).append(dict(event))
            for key in ids:
                rows[key]["status"] = "approved"
            self.save(s)
            return self.summary(s)

    def selection_accounting(self, state):
        """Normal validation or one explicitly reviewed transport-failure reservation; never free billing."""
        if not state.get("selection_ledger_ref"):
            return {"actual_usd": "0", "unresolved_reserved_usd": "0", "accounted_usd": "0"}
        path = resolve_artifact_path(self.root, state["selection_ledger_ref"])
        ledger = read_json(path)
        review = state.get("selection_billing_review")
        if not review:
            validate_collection_ledger(ledger, path.parent.parent)
            return selection_cost_summary(ledger, path.parent.parent)
        require(sha256_file(path) == review["ledger_sha256"], "Selection ledger changed after billing review")
        evidence_path = resolve_artifact_path(self.batch, review["evidence_ref"])
        require(sha256_file(evidence_path) == review["evidence_sha256"], "Billing review evidence changed")
        require(review.get("approval_ref") and review.get("mode") == "retain_reservation", "Invalid billing review")
        pending = [r for r in ledger["requests"] if r["state"] == "unresolved"]
        require(len(pending) == 1 and pending[0]["fingerprint"] == review["fingerprint"]
                and pending[0]["started_at"] == review["started_at"]
                and money(pending[0]["reserved_usd"]) == money(review["reserved_usd"]), "Unreviewed billing change")
        totals = selection_cost_summary(ledger, path.parent.parent)
        totals["status"] = "unknown_charge_reserved_after_review"
        totals["further_collection_blocked"] = False  # This batch only; original selection collector remains blocked.
        return totals

    def review_selection_reservation(self, evidence_path, approval_ref):
        """Retain a failed request's entire reservation after a free, empty provider history check."""
        require(str(approval_ref).strip(), "Actual billing recovery approval required")
        with self.locked():
            s = self.load()
            require(s.get("aggregate_budget_usd") and s.get("production_expansions"), "Approve shared-cap batch expansion first")
            require(not s.get("selection_billing_review"), "Billing review already recorded; do not overwrite it")
            ledger_path = resolve_artifact_path(self.root, s["selection_ledger_ref"])
            ledger = read_json(ledger_path)
            pending = [r for r in ledger["requests"] if r["state"] == "unresolved"]
            require(len(pending) == 1, "Need exactly one unresolved selection transport failure")
            old = pending[0]
            require(old.get("cause_type") == "URLError" and old.get("operation") == "serp"
                    and not old.get("filename") and old.get("actual_cost_usd") is None
                    and money(old["reserved_usd"]) > 0, "Not a bounded transport-only failure")
            path = Path(evidence_path).resolve()
            relative = str(path.relative_to(self.batch))
            require(relative.startswith("evidence/"), "Keep recovery evidence in the batch evidence directory")
            evidence = read_json(path)
            require(evidence.get("fingerprint") == old["fingerprint"]
                    and evidence.get("original_started_at") == old["started_at"]
                    and evidence.get("retain_original_reservation") is True,
                    "Recovery evidence must identify the original reserved request")
            require(fresh(evidence.get("checked_at"), datetime.now(timezone.utc)), "Fresh recovery lookup required")
            lookup = evidence["history_lookup"]
            p = lookup["response"]
            tasks = p.get("tasks", [])
            require(lookup.get("endpoint") == "/v3/serp/id_list" and p.get("status_code") == 20000
                    and p.get("tasks_error") == 0 and p.get("cost") == 0 and len(tasks) == 1
                    and tasks[0].get("cost") == 0 and tasks[0].get("status_code") == 20000
                    and tasks[0].get("result") == [] and tasks[0].get("data", {}).get("function") == "id_list",
                    "Need a successful free empty provider history lookup; no zero-charge inference")
            data = tasks[0]["data"]
            started = datetime.fromisoformat(old["started_at"])
            lower, upper = (datetime.fromisoformat(data[k]) for k in ("datetime_from", "datetime_to"))
            require(lower <= started <= upper <= datetime.fromisoformat(evidence["checked_at"].replace("Z", "+00:00"))
                    and (upper - lower).total_seconds() >= 120, "Lookup window must cover the failed request")
            totals = selection_cost_summary(ledger, ledger_path.parent.parent)
            require(money(totals["accounted_usd"]) + money(s["budget_usd"]) <= money(s["aggregate_budget_usd"]),
                    "Full selection reservation must remain funded within the shared cap")
            review = {"mode": "retain_reservation", "approval_ref": approval_ref, "reviewed_at": stamp(),
                      "ledger_sha256": sha256_file(ledger_path), "fingerprint": old["fingerprint"],
                      "started_at": old["started_at"], "reserved_usd": old["reserved_usd"],
                      "evidence_ref": relative, "evidence_sha256": sha256_file(path)}
            s["selection_billing_review"] = review
            s["history"].append(dict(review, event="selection_reservation_reviewed"))
            self.save(s)
            return self.summary(s)

    def active(self, state):
        return next((i for i in state["items"] if i["status"] in {"approved", "in_progress", "needs_review"}), None)

    def run_dir(self, item):
        return resolve_artifact_path(self.batch, item["run_ref"])

    def hashes(self, run, refs):
        result = {}
        for ref in refs:
            path = resolve_artifact_path(run, ref)
            require(path.is_file() and path.stat().st_size > 0, "Missing or empty artifact: " + ref)
            result[ref] = sha256_file(path)
        return result

    def verify(self, item):
        run = self.run_dir(item)
        for record in item["completed"].values():
            require(self.hashes(run, record["files"]) == record["files"], "Completed artifacts changed; stop for review")
            require(sha256_file(resolve_artifact_path(run, record["receipt"])) == record["receipt_sha256"], "Completed handoff receipt changed")
        if item.get("input_sha256"):
            require(sha256_file(run / "input.json") == item["input_sha256"], "Article input changed")

    def next(self):
        with self.locked():
            s = self.load()
            if s.get("production_stop"):
                return {"action": "stopped_by_user", "reason": s["production_stop"]["reason"]}
            for item in s["items"]:
                if item.get("input_sha256"):
                    self.verify(item)
            if not s["production_approval"]:
                return {"action": "await_production_approval", "required": "Approved article IDs and separate research budget (zero for no paid calls)"}
            if any(c["state"] != "complete" for c in s["costs"]):
                return {"action": "needs_review", "reason": "Unresolved production API request; reconcile billing before resuming"}
            i = self.active(s)
            if not i:
                return {"action": "await_publication_review", "summary": self.summary(s)}
            if i["status"] == "needs_review":
                return {"action": "needs_review", "article_id": i["id"], "reason": i["review_reason"]}
            run = self.run_dir(i)
            if i["status"] == "approved":
                require(not run.exists(), "Article directory already exists; never overwrite an interrupted/untracked run")
                # Catch duplicates in real run inputs, including another batch.
                for path in (self.root / "runs").rglob("input.json"):
                    if path.is_file() and query_pair(read_json(path).get("topic", "")) == query_pair(i["topic"]):
                        raise OrchestrationError("Existing article input for this topic: " + str(path))
                run.mkdir(parents=True)
                atomic_write_json(run / "input.json", i["input"])
                i["input_sha256"] = sha256_file(run / "input.json")
                i["status"] = "in_progress"
            self.verify(i)
            inputs = {"input.json": i["input_sha256"]}
            for record in i["completed"].values():
                inputs.update(record["files"])
            if i["revision_count"]:
                inputs.update(self.hashes(run, ["draft-v1.md", "qa-v1.json"]))
            if not i["dispatch"]:
                i["dispatch"] = {"article_id": i["id"], "stage": i["stage"], "revision": i["revision_count"],
                                 "input_hashes": inputs, "dispatched_at": stamp()}
            else:
                require(self.hashes(run, i["dispatch"]["input_hashes"]) == i["dispatch"]["input_hashes"], "Dispatched inputs changed; review before resume")
            self.save(s)
            return {"action": "execute_skill", "run_dir": str(run),
                    "skill": str(self.root / "skills" / ("comparison-" + i["stage"]) / "SKILL.md"),
                    "selection_queue": str(self.root / s["queue_ref"]), "dispatch": i["dispatch"],
                    "required_outputs": OUTPUTS[i["stage"]], "required_checks": CHECKS[i["stage"]],
                    "instruction": "Read and execute the named skill, then submit a reviewed, hash-bound receipt. Do not mark a gate passed merely because files exist."}

    def qa_passes(self, qa):
        names = {"factual_accuracy", "search_intent_match", "comparative_usefulness", "specificity", "originality", "positioning_clarity"}
        scores = qa.get("scores", {})
        require(set(scores) == names and all(type(v) is int and 1 <= v <= 5 for v in scores.values()), "Invalid QA dimensions")
        require(qa.get("total_score") == sum(scores.values()) and type(qa.get("passed")) is bool, "Invalid QA total/pass flag")
        require(all(isinstance(qa.get(k), list) for k in ("issues", "unsupported_claims", "required_changes", "human_review_notes")), "Incomplete QA record")
        require(qa.get("draft") == "draft.md", "QA must review current draft.md")
        for issue in qa["issues"]:
            require(issue.get("severity") in {"low", "medium", "high"} and issue.get("category"), "Invalid QA issue")
        # Medium issues outside copy/citation quality remain an explicit human review note.
        copy_categories = {"copy_quality", "citation_integrity", "originality", "positioning_clarity", "brand_voice", "generic_ai_language",
                           "specificity", "style", "clarity", "balance", "brand_fidelity", "repetition", "keyword_stuffing", "unsupported_experience"}
        blocked = any(x["severity"] == "high" or (x["severity"] == "medium" and x["category"] in copy_categories) for x in qa["issues"])
        return (qa["passed"] and not qa["unsupported_claims"] and not qa["required_changes"] and not blocked
                and min(scores.values()) >= 3 and sum(scores.values()) >= 25
                and scores["originality"] >= 4 and scores["positioning_clarity"] >= 4)

    def complete(self, receipt_path):
        with self.locked():
            s = self.load()
            require(not s.get("production_stop"), "Production stopped by user; new explicit approval required")
            require(not any(c["state"] != "complete" for c in s["costs"]), "Unresolved production billing; handoff paused")
            i = self.active(s)
            require(i and i["status"] == "in_progress" and i["dispatch"], "No dispatched work to complete")
            self.verify(i)
            run = self.run_dir(i)
            require(self.hashes(run, i["dispatch"]["input_hashes"]) == i["dispatch"]["input_hashes"], "Dispatched inputs changed during the stage")
            path = Path(receipt_path).resolve()
            path.relative_to(run)
            r = read_json(path)
            require(r.get("dispatch") == i["dispatch"], "Receipt is stale or for another article/stage")
            require(isinstance(r.get("notes"), str) and r["notes"].strip() and type(r.get("passed")) is bool, "Reviewed receipt needs notes and a boolean result")
            require(set(r.get("checks", {})) == set(CHECKS[i["stage"]]) and all(type(v) is bool for v in r["checks"].values()), "Receipt checklist incomplete")
            if not r["passed"] and i["stage"] != "qa":
                i.update(status="needs_review", review_reason=r["notes"])
                s["history"].append({"event": "handoff_failed", "article_id": i["id"], "stage": i["stage"], "receipt": r})
                self.save(s)
                return self.summary(s)
            files = r.get("files", {})
            require(set(OUTPUTS[i["stage"]]) <= set(files), "Receipt omits a required output")
            require(self.hashes(run, files) == files, "Reviewed output hashes do not match current files")
            require(all(r["checks"].values()) or i["stage"] == "qa", "A required handoff check failed")
            if i["stage"] == "research":
                claims = read_json(run / "research/claims.json")
                require(claims.get("topic") == i["topic"] and claims.get("claims"), "Research claims do not match topic")
                ids = [c["claim_id"] for c in claims["claims"]]
                require(len(ids) == len(set(ids)), "Duplicate claim IDs")
                for c in claims["claims"]:
                    require(c.get("status") in {"supported", "needs_human_review", "conflicting", "unsupported"}, "Invalid claim status")
                    if c["status"] == "supported":
                        require(c.get("statement") and c.get("sources") and all(x.get("url", "").startswith("https://") and x.get("title") and x.get("retrieved_at") and x.get("evidence") for x in c["sources"]), "Supported claim lacks source evidence")
            if i["stage"] == "writer":
                claims = read_json(run / "research/claims.json")["claims"]
                supported = {c["claim_id"] for c in claims if c["status"] == "supported"}
                blocks = re.findall(r"<!--\s*claims:\s*(.*?)\s*-->", (run / "draft.md").read_text())
                used = {x for b in blocks for x in re.split(r"[,\s]+", b) if x}
                require(used and used <= supported, "Draft traces missing or include unsupported/unknown claim IDs")
            if i["stage"] == "qa":
                passed = self.qa_passes(read_json(run / "qa.json")) and r["passed"] and all(r["checks"].values())
                if not passed:
                    s["history"].append({"event": "qa_failed", "article_id": i["id"], "revision": i["revision_count"], "receipt": r})
                    if i["revision_count"] == 0:
                        for name, dest in [("draft.md", "draft-v1.md"), ("qa.json", "qa-v1.json")]:
                            require(not (run / dest).exists(), "Revision archive already exists; review before overwriting")
                            shutil.copyfile(run / name, run / dest)
                        i["revision_count"] = 1
                        i["completed"].pop("writer")
                        i.update(stage="writer", dispatch=None)
                    else:
                        i.update(status="needs_review", review_reason="Second QA failure; no further automatic revision")
                    self.save(s)
                    return self.summary(s)
            i["completed"][i["stage"]] = {"files": files, "receipt": str(path.relative_to(run)), "receipt_sha256": sha256_file(path)}
            s["history"].append({"event": "handoff_passed", "article_id": i["id"], "stage": i["stage"], "at": stamp()})
            if i["stage"] == "qa":
                i["status"] = "ready_for_publish"
            else:
                i["stage"] = STAGES[STAGES.index(i["stage"]) + 1]
            i["dispatch"] = None
            self.save(s)
            return self.summary(s)

    def resume(self, approval_ref, reason):
        require(str(approval_ref).strip() and str(reason).strip(), "Human review approval and resolution required")
        with self.locked():
            s = self.load()
            require(not s.get("production_stop"), "Production stopped by user; new explicit approval required")
            i = self.active(s)
            require(i and i["status"] == "needs_review", "No blocked handoff to resume")
            require(not (i["stage"] == "qa" and i["revision_count"] == 1), "Second QA failure requires a new editorial decision, not another automatic revision")
            self.verify(i)
            s["history"].append({"event": "human_resume", "article_id": i["id"], "approval_ref": approval_ref, "reason": reason})
            i.update(status="in_progress", dispatch=None)
            self.save(s)
            return self.summary(s)

    def collect(self, plan, env_file=None, client=None):
        """One budget-guarded DataForSEO call; no transport retry or implicit top-up."""
        with self.locked():
            s = self.load()
            require(not s.get("production_stop"), "Production stopped by user; new explicit approval required")
            i = self.active(s)
            require(s["production_approval"] and i and i["status"] == "in_progress" and i["stage"] == "research", "Paid collection only during approved research")
            self.verify(i)
            require(not any(c["state"] != "complete" for c in s["costs"]), "Unresolved production billing; no further calls")
            selection = self.selection_accounting(s)
            require((s["data_mode"] == "fixture") == (client is not None), "Fixture clients and live budgets cannot be mixed")
            endpoint, task = request_for(plan)
            key = fingerprint(endpoint, task)
            cached = next((c for c in s["costs"] if c["fingerprint"] == key and fresh(c["retrieved_at"], datetime.now(timezone.utc))), None)
            if cached:
                path = resolve_artifact_path(self.batch, cached["response_ref"])
                require(sha256_file(path) == cached["sha256"], "Cached response changed")
                return {"reused": True, "response": str(path), "retrieved_at": cached["retrieved_at"]}
            bound = money(plan.get("cost_bound_usd"))
            require(bound > 0 and fresh(plan.get("pricing_checked_at"), datetime.now(timezone.utc)), "Fresh pricing and positive bound required")
            require(plan.get("pricing_source", "").startswith(("https://dataforseo.com/", "https://docs.dataforseo.com/")), "Official pricing source required")
            spent = sum((money(c["actual_usd"]) for c in s["costs"]), Decimal(0))
            require(spent + bound <= money(s["budget_usd"]), "Request exceeds approved production budget")
            if s.get("aggregate_budget_usd") is not None:
                require(money(selection["accounted_usd"]) + spent + bound <= money(s["aggregate_budget_usd"]),
                        "Request exceeds shared selection-plus-production cap")
            require(len(s["costs"]) < 60, "Batch request ceiling reached; review research scope")
            entry = {"article_id": i["id"], "fingerprint": key, "request": task, "endpoint": endpoint,
                     "reserved_usd": str(bound), "state": "pending", "retrieved_at": stamp()}
            s["costs"].append(entry)
            self.save(s)  # Durable reservation before credentials/network.
            try:
                if client is None:
                    load_dataforseo_env(Path(env_file or self.root / ".env"))
                    client = DataForSEOClient.from_environment()
                require(getattr(client, "base_url", "https://api.dataforseo.com") == "https://api.dataforseo.com", "Production endpoint required")
                payload = client.post(endpoint, [task])
                dest = self.run_dir(i) / "research/raw" / (key[:16] + "-" + str(len(s["costs"])) + ".json")
                atomic_write_json(dest, {"data_mode": s["data_mode"], "request": task, "endpoint": endpoint, "retrieved_at": entry["retrieved_at"], "response": payload})
                entry.update(response_ref=str(dest.relative_to(self.batch)), sha256=sha256_file(dest))
                tasks = payload.get("tasks", [])
                require(payload.get("status_code") == 20000 and len(tasks) == 1 and tasks[0].get("status_code") == 20000, "Unsuccessful provider result")
                amounts = [money(v) for v in (payload.get("cost"), tasks[0].get("cost")) if v is not None]
                require(amounts, "Missing actual cost")
                actual = max(amounts)
                entry["actual_usd"] = str(actual)
                require(actual <= bound and spent + actual <= money(s["budget_usd"]), "Provider charge exceeds reservation; review billing")
                entry["state"] = "complete"
                self.save(s)
                return {"reused": False, "response": str(dest), "actual_usd": str(actual)}
            except Exception as exc:
                entry.update(state="unresolved", error_type=type(exc).__name__)
                self.save(s)
                raise OrchestrationError("Collection stopped; inspect retained billing evidence before another call") from None
