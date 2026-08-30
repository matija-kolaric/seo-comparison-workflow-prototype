"""Quality-gate calculation and revision routing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from .errors import ValidationError, WorkflowError
from .io import atomic_write_json, read_json
from .state import transition_run
from .time import utc_now


@dataclass(frozen=True)
class GateEvaluation:
    run_id: str
    draft_version: int
    status: str
    gate_results: Dict[str, str]
    quality_total: int
    unsupported_claims_count: int
    required_changes: List[dict]
    remaining_warnings: List[str]
    next_status: str

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "draft_version": self.draft_version,
            "status": self.status,
            "gate_results": self.gate_results,
            "quality_total": self.quality_total,
            "unsupported_claims_count": self.unsupported_claims_count,
            "required_changes": self.required_changes,
            "remaining_warnings": self.remaining_warnings,
            "next_status": self.next_status,
        }


def _review_path(run_dir: Path, review_type: str, version: int) -> Path:
    return run_dir / "qa" / "{}-v{}.json".format(review_type, version)


def _changes(review: dict, priority: str) -> List[dict]:
    result = []
    findings = review.get("findings", [])
    finding_claims = []
    for finding in findings:
        if finding.get("required"):
            finding_claims.extend(finding.get("claim_ids", []))
    for instruction in review.get("required_changes", []):
        result.append(
            {
                "priority": priority,
                "instruction": instruction,
                "claim_ids": sorted(set(finding_claims)),
            }
        )
    return result


def evaluate_gates(run_dir: Path, draft_version: int) -> GateEvaluation:
    run_dir = Path(run_dir)
    run = read_json(run_dir / "run.json")
    fact = read_json(_review_path(run_dir, "fact-check", draft_version))
    seo = read_json(_review_path(run_dir, "seo-review", draft_version))
    quality = read_json(_review_path(run_dir, "quality-review", draft_version))
    errors = []

    for name, review in (("fact", fact), ("SEO", seo), ("quality", quality)):
        if review.get("run_id") != run.get("run_id"):
            errors.append("{} review run_id does not match run.json".format(name))
        if review.get("draft_version") != draft_version:
            errors.append("{} review draft_version does not match".format(name))
    if draft_version != run.get("current_draft_version"):
        errors.append("Gate evaluation must target current_draft_version")

    unsupported_count = fact.get("unsupported_claims_count", 0)
    fact_claim_statuses = {item.get("support_status") for item in fact.get("claims_evaluated", [])}
    fact_pass = (
        fact.get("status") == "pass"
        and unsupported_count == 0
        and not fact_claim_statuses.intersection({"unsupported", "contradicted", "partially_supported"})
    )

    required_seo_checks = [check for check in seo.get("checks", []) if check.get("required")]
    seo_pass = (
        seo.get("status") == "pass"
        and bool(required_seo_checks)
        and all(check.get("status") == "pass" for check in required_seo_checks)
    )

    scores = quality.get("scores", {})
    calculated_total = sum(scores.values()) if scores else 0
    if calculated_total != quality.get("total_score"):
        errors.append("quality total_score does not equal the sum of dimension scores")
    quality_pass = (
        quality.get("status") == "pass"
        and calculated_total >= 25
        and bool(scores)
        and min(scores.values()) >= 3
    )

    if errors:
        raise ValidationError(errors)

    other_gates_pass = fact_pass and seo_pass and quality_pass
    can_revise = draft_version < run.get("max_draft_versions", 0)
    revision_limit_pass = other_gates_pass or can_revise
    status = "pass" if other_gates_pass else "fail"
    next_status = (
        "awaiting_human_approval"
        if other_gates_pass
        else ("revision_required" if can_revise else "needs_human_review")
    )

    required_changes = []
    if not fact_pass:
        required_changes.extend(_changes(fact, "critical"))
    if not seo_pass:
        required_changes.extend(_changes(seo, "required"))
    if not quality_pass:
        required_changes.extend(_changes(quality, "required"))
    if status == "fail" and not required_changes:
        required_changes.append(
            {
                "priority": "required",
                "instruction": "Resolve the failed review gates before continuing.",
                "claim_ids": [],
            }
        )

    warnings = []
    for review in (fact, seo, quality):
        warnings.extend(
            finding["message"]
            for finding in review.get("findings", [])
            if not finding.get("required")
        )

    return GateEvaluation(
        run_id=run["run_id"],
        draft_version=draft_version,
        status=status,
        gate_results={
            "fact_check": "pass" if fact_pass else "fail",
            "seo_review": "pass" if seo_pass else "fail",
            "quality_review": "pass" if quality_pass else "fail",
            "revision_limit": "pass" if revision_limit_pass else "fail",
        },
        quality_total=calculated_total,
        unsupported_claims_count=unsupported_count,
        required_changes=required_changes,
        remaining_warnings=warnings,
        next_status=next_status,
    )


def apply_gate_evaluation(
    run_dir: Path,
    evaluation: GateEvaluation,
    generated_at: str = None,
) -> Path:
    run_dir = Path(run_dir)
    run = read_json(run_dir / "run.json")
    if run.get("status") != "reviewing":
        raise WorkflowError("Gate results can only be applied while the run is reviewing")
    if run.get("run_id") != evaluation.run_id:
        raise WorkflowError("Gate evaluation belongs to a different run")
    timestamp = generated_at or utc_now()

    if evaluation.status == "pass":
        report_path = run_dir / "qa" / "final-report.json"
        atomic_write_json(
            report_path,
            {
                "schema_version": "1.0",
                "run_id": evaluation.run_id,
                "final_draft_version": evaluation.draft_version,
                "generated_at": timestamp,
                "status": "pass",
                "gate_results": evaluation.gate_results,
                "quality_total": evaluation.quality_total,
                "unsupported_claims_count": evaluation.unsupported_claims_count,
                "remaining_warnings": evaluation.remaining_warnings,
                "recommended_next_status": "awaiting_human_approval",
            },
        )
        transition_run(run_dir, "qa_passed", "All mandatory quality gates passed.", timestamp)
        transition_run(
            run_dir,
            "awaiting_human_approval",
            "Final QA report created; staging requires human approval.",
            timestamp,
        )
        return report_path

    if evaluation.next_status == "revision_required":
        request_path = run_dir / "qa" / "revision-request-v{}.json".format(evaluation.draft_version)
        atomic_write_json(
            request_path,
            {
                "schema_version": "1.0",
                "run_id": evaluation.run_id,
                "source_draft_version": evaluation.draft_version,
                "target_draft_version": evaluation.draft_version + 1,
                "generated_at": timestamp,
                "source_reviews": [
                    "qa/fact-check-v{}.json".format(evaluation.draft_version),
                    "qa/seo-review-v{}.json".format(evaluation.draft_version),
                    "qa/quality-review-v{}.json".format(evaluation.draft_version),
                ],
                "required_changes": evaluation.required_changes,
            },
        )
        transition_run(run_dir, "revision_required", "One or more quality gates failed.", timestamp)
        return request_path

    report_path = run_dir / "qa" / "final-report.json"
    atomic_write_json(
        report_path,
        {
            "schema_version": "1.0",
            "run_id": evaluation.run_id,
            "final_draft_version": evaluation.draft_version,
            "generated_at": timestamp,
            "status": "fail",
            "gate_results": evaluation.gate_results,
            "quality_total": evaluation.quality_total,
            "unsupported_claims_count": evaluation.unsupported_claims_count,
            "remaining_warnings": evaluation.remaining_warnings,
            "recommended_next_status": "needs_human_review",
        },
    )
    transition_run(
        run_dir,
        "needs_human_review",
        "Quality gates failed and the revision limit was reached.",
        timestamp,
    )
    return report_path
