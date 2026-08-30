"""Operational research-policy enforcement and knowledge-base materialization."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..errors import ValidationError, WorkflowError
from ..io import atomic_write_json, read_json
from ..runs import register_artifact
from ..time import utc_now


DEFAULT_POLICY = Path(__file__).resolve().parents[3] / "config" / "research-policy.json"


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def validate_product_research(
    document: dict,
    policy: dict,
    as_of: Optional[datetime] = None,
    allow_fixture: bool = False,
) -> dict:
    now = as_of or datetime.now(timezone.utc)
    errors: List[str] = []
    warnings: List[str] = []
    sources: Dict[str, dict] = {}

    for source in document.get("sources", []):
        source_id = source.get("source_id")
        if source_id in sources:
            errors.append("Duplicate source ID: {}".format(source_id))
        sources[source_id] = source
        if not source.get("url") and not source.get("internal_reference"):
            errors.append("Source {} has no URL or internal reference".format(source_id))
        if not allow_fixture and source.get("source_type") != "internal_approved":
            if not source.get("snapshot_path"):
                errors.append("External source {} has no retained snapshot".format(source_id))
            if not source.get("content_hash"):
                errors.append("External source {} has no content hash".format(source_id))

    verified_count = 0
    for claim in document.get("claims", []):
        claim_id = claim.get("claim_id", "<unknown>")
        fact_type = claim.get("fact_type")
        source_ids = claim.get("source_ids", [])
        claim_sources = [sources[source_id] for source_id in source_ids if source_id in sources]
        missing_sources = set(source_ids) - set(sources)
        if missing_sources:
            errors.append("{} references unknown sources: {}".format(claim_id, sorted(missing_sources)))
            continue
        if fact_type not in policy.get("freshness_days", {}):
            errors.append("{} has unsupported fact_type {}".format(claim_id, fact_type))
            continue
        if len(source_ids) < policy["minimum_sources"][fact_type]:
            errors.append(
                "{} requires at least {} source(s)".format(
                    claim_id, policy["minimum_sources"][fact_type]
                )
            )
        allowed_types = set(policy["allowed_source_types"][fact_type])
        disallowed = [
            source["source_type"]
            for source in claim_sources
            if source.get("source_type") not in allowed_types
        ]
        if disallowed:
            errors.append("{} uses disallowed source types: {}".format(claim_id, sorted(set(disallowed))))

        freshness_days = policy["freshness_days"][fact_type]
        for source in claim_sources:
            try:
                age_days = (now - _parse_timestamp(source["retrieved_at"])).days
            except (KeyError, TypeError, ValueError):
                errors.append("Source {} has an invalid retrieved_at".format(source.get("source_id")))
                continue
            if age_days > freshness_days:
                errors.append(
                    "{} uses stale source {} ({} days old; limit {})".format(
                        claim_id, source.get("source_id"), age_days, freshness_days
                    )
                )
        valid_until = claim.get("valid_until")
        if valid_until:
            try:
                if _parse_date(valid_until) < now.date():
                    errors.append("{} passed valid_until {}".format(claim_id, valid_until))
            except ValueError:
                errors.append("{} has invalid valid_until".format(claim_id))

        if claim.get("status") == "verified":
            if claim.get("verified_by") == "fixture" and not allow_fixture:
                errors.append("{} is fixture-verified in a live run".format(claim_id))
            if fact_type in policy.get("human_review_required", []) and claim.get("verified_by") != "human":
                errors.append("{} requires human verification".format(claim_id))
            verified_count += 1
        else:
            warnings.append("{} is not available to the planner: {}".format(claim_id, claim.get("status")))

    if errors:
        raise ValidationError(errors)
    return {
        "sources": len(sources),
        "claims": len(document.get("claims", [])),
        "verified_claims": verified_count,
        "warnings": warnings,
    }


def materialize_seobility_research(
    run_dir: Path,
    knowledge_base_path: Path,
    policy_path: Path = DEFAULT_POLICY,
    generated_at: Optional[str] = None,
) -> Path:
    run_dir = Path(run_dir)
    run = read_json(run_dir / "run.json")
    knowledge = read_json(Path(knowledge_base_path))
    policy = read_json(Path(policy_path))
    if knowledge.get("product") != "Seobility":
        raise WorkflowError("Knowledge base product must be Seobility")
    if knowledge.get("status") != "approved":
        raise WorkflowError("Seobility knowledge base must be human-approved before materialization")
    if not knowledge.get("claims"):
        raise WorkflowError("Approved knowledge base contains no claims")
    timestamp = generated_at or utc_now()
    as_of = _parse_timestamp(timestamp)
    validate_product_research(knowledge, policy, as_of=as_of, allow_fixture=False)
    verified_claims = [claim for claim in knowledge["claims"] if claim["status"] == "verified"]
    used_source_ids = {source_id for claim in verified_claims for source_id in claim["source_ids"]}
    output = {
        "schema_version": "1.0",
        "run_id": run["run_id"],
        "subject": {"name": "Seobility", "role": "seobility"},
        "generated_at": timestamp,
        "sources": [source for source in knowledge["sources"] if source["source_id"] in used_source_ids],
        "claims": verified_claims,
    }
    output_path = run_dir / "research" / "seobility.json"
    if output_path.exists():
        raise WorkflowError("Seobility research already exists; start a new run or version the artifact")
    atomic_write_json(output_path, output)
    register_artifact(
        run_dir,
        "seobility_research",
        "research/seobility.json",
        1,
        created_at=timestamp,
    )
    return output_path


def validate_research_layer(
    run_dir: Path,
    policy_path: Path = DEFAULT_POLICY,
    as_of: Optional[datetime] = None,
) -> dict:
    run_dir = Path(run_dir)
    run = read_json(run_dir / "run.json")
    policy = read_json(Path(policy_path))
    fixture_mode = run.get("data_mode") == "fixture"
    results = {}
    for name in ("competitor", "seobility"):
        document = read_json(run_dir / "research" / "{}.json".format(name))
        if document.get("run_id") != run.get("run_id"):
            raise ValidationError(["research/{}.json has a mismatched run_id".format(name)])
        results[name] = validate_product_research(
            document, policy, as_of=as_of, allow_fixture=fixture_mode
        )
    serp = read_json(run_dir / "research" / "serp.json")
    if serp.get("run_id") != run.get("run_id"):
        raise ValidationError(["research/serp.json has a mismatched run_id"])
    if not serp.get("queries"):
        raise ValidationError(["SERP research contains no queries"])
    return {
        "status": "pass",
        "run_id": run["run_id"],
        "mode": run.get("data_mode"),
        "queries": len(serp["queries"]),
        "competitor": results["competitor"],
        "seobility": results["seobility"],
    }
