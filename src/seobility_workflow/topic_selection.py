"""Offline selection gates and deterministic ranking. Editorial evidence is agent-reviewed."""
from __future__ import annotations

import re
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

from .io import resolve_artifact_path
from .errors import WorkflowError

VERSION = "0.2"
WEIGHTS = {"intent": 30, "fit": 25, "gap": 20, "demand": 15, "feasibility": 10}
ALIASES = {"seo bility": "seobility", "sem rush": "semrush", "se-ranking": "se ranking"}
AUDIENCE = "SEO professionals and small businesses comparing SEO platforms"


class SelectionError(ValueError):
    pass


def text(value):
    return " ".join(str(value).lower().split()).strip()


def brand(value):
    value = text(value)
    return ALIASES.get(value, value)


def pair(products):
    if not isinstance(products, list) or len(products) != 2:
        raise SelectionError("Each product pair must contain exactly two names")
    result = tuple(sorted(brand(p) for p in products))
    if not all(result) or result[0] == result[1]:
        raise SelectionError("Invalid product pair")
    return result


def query_pair(keyword):
    parts = re.split(r"\s+(?:vs\.?|versus)\s+", text(keyword))
    if len(parts) != 2 or re.search(r"\balternatives?\b", text(keyword)):
        return None
    try:
        return pair(parts)
    except SelectionError:
        return None


def fresh(value, now):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return False
        return timedelta(0) <= now - stamp <= timedelta(days=7)
    except (ValueError, TypeError):
        return False


def public_url(value):
    u = urlparse(str(value))
    return u.scheme in {"https", "http"} and bool(u.hostname) and not u.username and not u.password


def evidence_refs(refs, root):
    if not isinstance(refs, list) or not refs:
        return False
    for ref in refs:
        try:
            path = resolve_artifact_path(root, ref)
            if not str(ref).startswith("evidence/") or not path.is_file() or path.stat().st_size == 0:
                return False
        except (ValueError, OSError, TypeError, WorkflowError):
            return False
    return True


def demand_rating(volume):
    if volume is None:
        return 0
    if volume == 0:
        return 1
    return 2 if volume < 50 else 3 if volume < 200 else 4


def distinct_serp_results(serp, root, mode):
    """Derive first ten distinct URLs from one retained response; never renumber Google ranks."""
    ref = serp.get("source_ref")
    if not evidence_refs([ref], root):
        raise SelectionError("A retained SERP response is required")
    raw = json.loads(resolve_artifact_path(root, ref).read_text())
    request = raw.get("request", {})
    if (raw.get("data_mode") != mode or raw.get("endpoint") != "/v3/serp/google/organic/live/advanced"
            or request.get("keyword") != serp.get("keyword")
            or request.get("location_name") != "United States" or request.get("language_code") != "en"
            or request.get("device") != "desktop" or request.get("depth") not in (10, 20)
            or raw.get("retrieved_at") != serp.get("retrieved_at")):
        raise SelectionError("SERP provenance does not match the assessment")
    groups = raw.get("response", {}).get("tasks", [])
    if (raw.get("response", {}).get("status_code") != 20000 or len(groups) != 1
            or groups[0].get("status_code") != 20000 or len(groups[0].get("result") or []) != 1):
        raise SelectionError("Need one successful SERP snapshot")
    rows = [r for r in groups[0]["result"][0].get("items", []) if r.get("type") == "organic"]
    selected, duplicates, seen = [], [], set()
    for rank, row in enumerate(rows, 1):
        if rank > 20:
            break
        if type(row.get("rank_group")) is not int or row["rank_group"] != rank or not public_url(row.get("url")):
            raise SelectionError("SERP ranks must be contiguous and preserve provider order")
        record = {"rank": rank, "url": row["url"]}
        if row["url"] in seen:
            duplicates.append(record)
        else:
            selected.append(record)
            seen.add(row["url"])
        if len(selected) == 10:
            return selected, duplicates
    raise SelectionError("Fewer than ten distinct organic pages in the bounded snapshot")


def select_topics(data, evidence_root, now=None):
    now = now or datetime.now(timezone.utc)
    root = Path(evidence_root)
    version = data.get("policy_version")
    if version not in {"0.1", VERSION} or data.get("market") != "United States" or data.get("language") != "en":
        raise SelectionError("This policy supports versions 0.1/0.2, United States, English only")
    target = data.get("target_count", 5)
    if type(target) is not int or target not in (5, 6) or (target == 6 and (version != VERSION or not data.get("scope_approval_ref"))):
        raise SelectionError("Default target is five; six requires version 0.2 and explicit scope approval")
    if data.get("data_mode") not in {"fixture", "live"}:
        raise SelectionError("Explicit fixture/live data_mode required")
    candidates = data.get("candidates", [])
    if not isinstance(candidates, list) or len(candidates) > 20:
        raise SelectionError("At most 20 candidates per run")
    if sum(c.get("evaluation") == "inspected" for c in candidates) > 10:
        raise SelectionError("At most 10 inspected candidates per run")
    ids = [c.get("id", "") for c in candidates]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,70}", i) for i in ids):
        raise SelectionError("Unique lowercase candidate IDs required")
    inventory = data.get("inventory")
    if not isinstance(inventory, list):
        raise SelectionError("Inventory must be explicitly provided")
    existing = {pair(["Seobility", "Ahrefs"])}
    for item in inventory:
        if item.get("status") != "rejected":
            existing.add(pair(item["products"]))
    assessed = []
    for candidate in candidates:
        c = dict(candidate)
        products = pair(c.get("products"))
        c["normalized_pair"] = list(products)
        reasons = []
        if "seobility" not in products or c.get("page_type") != "versus":
            reasons.append("outside_comparison_scope")
        if query_pair(c.get("primary_keyword", "")) != products:
            reasons.append("primary_keyword_not_exact_pair")
        if products in existing:
            reasons.append("existing_or_queued_pair")
        if c.get("evaluation") != "inspected":
            c.update(score=None, confidence="low", decision="not_evaluated", reasons=reasons + [c.get("prefilter_reason") or "not_inspected"])
            assessed.append(c)
            continue
        scores = c.get("ratings", {})
        for dim in ("intent", "fit", "gap", "feasibility"):
            rating = scores.get(dim, {})
            if type(rating.get("value")) is not int or not 0 <= rating["value"] <= 4:
                raise SelectionError("{}: {} rating must be integer 0–4".format(c["id"], dim))
            if not str(rating.get("rationale", "")).strip() or not evidence_refs(rating.get("evidence_refs"), root):
                reasons.append("unsupported_rating_" + dim)
        serp = c.get("serp", {})
        rows = serp.get("results", [])
        ranks = [r.get("rank") for r in rows]
        urls = [r.get("url") for r in rows]
        ranks_valid = all(type(r) is int for r in ranks) and set(ranks) == set(range(1, 11))
        if version == VERSION:
            try:
                expected, duplicates = distinct_serp_results(serp, root, data["data_mode"])
                ranks_valid = rows == expected
                c["serp_duplicate_rows"] = duplicates
            except (SelectionError, ValueError, OSError, KeyError, TypeError):
                ranks_valid = False
        complete = (len(rows) == 10 and ranks_valid and len(set(urls)) == 10
                    and all(public_url(u) for u in urls) and fresh(serp.get("retrieved_at"), now)
                    and text(serp.get("keyword", "")) == text(c.get("primary_keyword", ""))
                    and evidence_refs(serp.get("evidence_refs"), root))
        if not complete:
            reasons.append("incomplete_or_stale_serp")
        observations = c.get("page_observations", [])
        if not any(o.get("url") in urls and fresh(o.get("retrieved_at"), now) and o.get("note")
                   and evidence_refs(o.get("evidence_refs"), root) for o in observations):
            reasons.append("no_verified_ranking_page_observation")
        official = {brand(o.get("product", "")) for o in c.get("official_sources", [])
                    if public_url(o.get("url")) and fresh(o.get("retrieved_at"), now) and o.get("note")
                    and evidence_refs(o.get("evidence_refs"), root)}
        if not set(products).issubset(official):
            reasons.append("missing_official_source")
        metrics = []
        excluded_metrics = []
        for row in c.get("metrics", []):
            if query_pair(row.get("keyword", "")) != products:
                excluded_metrics.append({"keyword": row.get("keyword"), "reason": "not_equivalent_comparison"})
                continue
            volume = row.get("search_volume")
            if (volume is not None and (type(volume) is not int or volume < 0)):
                raise SelectionError("search_volume must be null or a nonnegative integer")
            usable = (row.get("market") == data["market"] and row.get("language") == data["language"]
                      and fresh(row.get("retrieved_at"), now) and row.get("period")
                      and evidence_refs(row.get("evidence_refs"), root))
            if usable and volume is not None:
                metrics.append(row)
            else:
                excluded_metrics.append({"keyword": row.get("keyword"), "reason": "unknown_stale_or_untraceable_metric"})
        # Different dataset periods must not be blended into one cluster estimate.
        if len({m["period"] for m in metrics}) > 1:
            excluded_metrics.extend({"keyword": m["keyword"], "reason": "mixed_dataset_periods"} for m in metrics)
            metrics = []
        volume = max((m["search_volume"] for m in metrics), default=None)
        values = {k: scores[k]["value"] for k in ("intent", "fit", "gap", "feasibility")}
        values["demand"] = demand_rating(volume)
        score = sum(WEIGHTS[k] * v / 4 for k, v in values.items())
        confidence = c.get("confidence")
        if confidence not in {"high", "medium", "low"}:
            raise SelectionError("Confidence must be high, medium, or low")
        if c.get("unresolved_conflicts"):
            reasons.append("unresolved_conflict")
        if not all(str(c.get(k, "")).strip() for k in ("angle", "buyer_decision", "why_this_pair", "why_now", "tradeoffs")):
            reasons.append("incomplete_editorial_explanation")
        if reasons:
            confidence = "low"
        elif confidence == "high" and (volume is None or c.get("limitations")):
            confidence = "medium"
        if score < 65:
            reasons.append("below_total_threshold")
        for dim, minimum in {"intent": 3, "fit": 3, "gap": 2, "feasibility": 2}.items():
            if values[dim] < minimum:
                reasons.append("below_" + dim + "_threshold")
        if confidence == "low":
            reasons.append("low_confidence")
        c.update(score=score, confidence=confidence, dimension_ratings=values,
                 comparison_volume_proxy=volume, excluded_metrics=excluded_metrics,
                 reasons=reasons, decision="excluded" if reasons else "eligible")
        assessed.append(c)
    confidence_rank = {"high": 2, "medium": 1, "low": 0}
    eligible = sorted((c for c in assessed if c["decision"] == "eligible"), key=lambda c: (
        -c["score"], -c["dimension_ratings"]["intent"], -c["dimension_ratings"]["gap"],
        -confidence_rank[c["confidence"]], -c["dimension_ratings"]["feasibility"],
        c["normalized_pair"], c["id"]))
    unique = []
    seen = set()
    for c in eligible:
        key = tuple(c["normalized_pair"])
        if key in seen:
            c.update(decision="excluded", reasons=["duplicate_candidate_pair"])
        else:
            seen.add(key)
            unique.append(c)
    for rank, c in enumerate(unique, 1):
        c["decision"] = "selected" if rank <= target else "reserve"
        c["rank"] = rank
        c["status"] = "selected" if rank <= target else "reserve"
        c["article_run_id"] = None
        other = next(p for p in c["products"] if brand(p) != "seobility")
        c["secondary_keywords"] = [k for k in c.get("secondary_keywords", []) if query_pair(k) == tuple(c["normalized_pair"])]
        c["input"] = {"topic": "Seobility vs " + other, "page_type": "versus", "language": "en",
                      "market": "United States", "audience": AUDIENCE}
        c["slug"] = "seobility-vs-" + re.sub(r"[^a-z0-9]+", "-", brand(other)).strip("-")
    return {"policy_version": version, "target_count": target, "scope_approval_ref": data.get("scope_approval_ref"),
            "revision": data.get("revision"),
            "data_mode": data["data_mode"], "generated_at": now.isoformat(),
            "market": data["market"], "language": data["language"], "status": "awaiting_human_review",
            "production_authorized": False, "publication_authorized": False,
            "selected": unique[:target], "reserves": unique[target:],
            "excluded": sorted((c for c in assessed if c["decision"] in {"excluded", "not_evaluated"}), key=lambda c: c["id"]),
            "shortfall": max(0, target - len(unique)), "inventory": inventory,
            "costs": data.get("costs", {"status": "not_recorded"})}


def render_report(queue):
    lines = ["# Comparison topic selection", "", "Mode: **{}**. Policy: {}.".format(queue["data_mode"], queue["policy_version"]),
             "", "Generated: {}. Market: {}; language: {}.".format(queue["generated_at"], queue["market"], queue["language"]),
             "", "Awaiting human review. No article production or publication is authorized.",
             "", "Best-supported opportunities within the inspected candidate set; scores are editorial heuristics, not conversion forecasts.",
             "", "Selected: {} / {}. Shortfall: {}. Do not pad the list.".format(len(queue["selected"]), queue.get("target_count", 5), queue["shortfall"]),
             "", "Costs: {}".format(queue["costs"])]
    for category in ("selected", "reserves", "excluded"):
        lines.extend(["", "## " + category.title(), ""])
        for c in queue[category]:
            lines.extend(["### " + c["id"], "", "- Decision: " + c["decision"],
                          "- Keyword: " + c.get("primary_keyword", ""),
                          "- Score: {}; confidence: {}".format(c.get("score"), c["confidence"])])
            if c.get("reasons"):
                lines.append("- Reasons: " + ", ".join(c["reasons"]))
            if c.get("serp_duplicate_rows"):
                lines.append("- Duplicate rows retained as warnings (original ranks): {}".format(c["serp_duplicate_rows"]))
            for key in ("angle", "buyer_decision", "why_this_pair", "why_now", "tradeoffs", "limitations"):
                if c.get(key):
                    lines.append("- {}: {}".format(key.replace("_", " ").capitalize(), c[key]))
            for dim, rating in c.get("ratings", {}).items():
                refs = ", ".join("[{}]({})".format(r, r) for r in rating.get("evidence_refs", []))
                lines.append("- {} {}/4: {} ({})".format(dim, rating.get("value"), rating.get("rationale"), refs))
            if "comparison_volume_proxy" in c:
                lines.append("- Comparison volume proxy: {} (maximum, not sum).".format(c["comparison_volume_proxy"]))
                lines.append("- Selection SERP retrieved: {}.".format(c.get("serp", {}).get("retrieved_at", "unknown")))
                for source in c.get("official_sources", []):
                    lines.append("- Official-source record for {}: {} (retrieved {}).".format(source.get("product"), source.get("url"), source.get("retrieved_at")))
                for metric in c.get("metrics", []):
                    lines.append("- Metric provenance: {} — dataset {}, retrieved {}.".format(metric.get("keyword"), metric.get("period", "unknown"), metric.get("retrieved_at", "unknown")))
            if c.get("excluded_metrics"):
                lines.append("- Excluded demand rows: {}".format(c["excluded_metrics"]))
    return "\n".join(lines) + "\n"
