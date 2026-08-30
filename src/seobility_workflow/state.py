"""Workflow state machine."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, FrozenSet, Optional

from .errors import InvalidTransitionError
from .io import atomic_write_json, read_json
from .time import utc_now


ALLOWED_TRANSITIONS: Dict[str, FrozenSet[str]] = {
    "initialized": frozenset({"research_ready", "blocked_invalid_evidence"}),
    "research_ready": frozenset({"evidence_validated", "blocked_invalid_evidence"}),
    "evidence_validated": frozenset({"brief_ready", "blocked_invalid_evidence"}),
    "brief_ready": frozenset({"draft_ready", "blocked_invalid_evidence"}),
    "draft_ready": frozenset({"reviewing", "blocked_qa_failure"}),
    "reviewing": frozenset({"revision_required", "qa_passed", "blocked_qa_failure", "needs_human_review"}),
    "revision_required": frozenset({"draft_ready", "needs_human_review", "blocked_qa_failure"}),
    "qa_passed": frozenset({"awaiting_human_approval"}),
    "awaiting_human_approval": frozenset({"approved_for_staging", "needs_human_review"}),
    "approved_for_staging": frozenset({"staging_draft_created", "blocked_integration_failure"}),
    "staging_draft_created": frozenset({"completed", "blocked_integration_failure"}),
    "completed": frozenset(),
    "blocked_invalid_evidence": frozenset(),
    "blocked_qa_failure": frozenset(),
    "blocked_integration_failure": frozenset(),
    "needs_human_review": frozenset(),
}


def transition_run(
    run_dir: Path,
    new_status: str,
    reason: str,
    at: Optional[str] = None,
) -> dict:
    if not reason or not reason.strip():
        raise InvalidTransitionError("A non-empty transition reason is required")
    run_path = Path(run_dir) / "run.json"
    run = read_json(run_path)
    current_status = run.get("status")
    if current_status not in ALLOWED_TRANSITIONS:
        raise InvalidTransitionError("Unknown current state: {}".format(current_status))
    if new_status not in ALLOWED_TRANSITIONS[current_status]:
        raise InvalidTransitionError(
            "Transition {} -> {} is not allowed".format(current_status, new_status)
        )
    timestamp = at or utc_now()
    run["status"] = new_status
    run["updated_at"] = timestamp
    run.setdefault("status_history", []).append(
        {"status": new_status, "at": timestamp, "reason": reason.strip()}
    )
    atomic_write_json(run_path, run)
    return run
