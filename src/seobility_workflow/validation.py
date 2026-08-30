"""Deterministic cross-artifact validation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Set

from .errors import ArtifactError, ValidationError
from .io import read_json, resolve_artifact_path, sha256_file
from .state import ALLOWED_TRANSITIONS


CLAIM_REFERENCE = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")


def _load_if_present(path: Path):
    return read_json(path) if path.is_file() else None


def validate_run(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    errors: List[str] = []
    warnings: List[str] = []
    run = read_json(run_dir / "run.json")
    run_id = run.get("run_id")

    if run.get("status") not in ALLOWED_TRANSITIONS:
        errors.append("run.json has an unknown status")
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,79}", run_id):
        errors.append("run.json has an invalid run_id")

    seen_artifact_paths: Set[str] = set()
    for artifact in run.get("artifacts", []):
        relative_path = artifact.get("path", "")
        if relative_path in seen_artifact_paths:
            errors.append("Duplicate registered artifact: {}".format(relative_path))
            continue
        seen_artifact_paths.add(relative_path)
        try:
            artifact_path = resolve_artifact_path(run_dir, relative_path)
        except ArtifactError as exc:
            errors.append(str(exc))
            continue
        if not artifact_path.is_file():
            errors.append("Registered artifact is missing: {}".format(relative_path))
        elif artifact.get("sha256") and artifact["sha256"] != sha256_file(artifact_path):
            errors.append("Registered artifact hash changed: {}".format(relative_path))

    research_files = [
        run_dir / "research" / "competitor.json",
        run_dir / "research" / "seobility.json",
    ]
    claims: Dict[str, dict] = {}
    for research_path in research_files:
        research = _load_if_present(research_path)
        if research is None:
            warnings.append("Missing optional stage artifact: {}".format(research_path.relative_to(run_dir)))
            continue
        if research.get("run_id") != run_id:
            errors.append("{} has a mismatched run_id".format(research_path.relative_to(run_dir)))
        source_ids = {source.get("source_id") for source in research.get("sources", [])}
        for source in research.get("sources", []):
            if not source.get("url") and not source.get("internal_reference"):
                errors.append("Source {} has no URL or internal reference".format(source.get("source_id")))
        for claim in research.get("claims", []):
            claim_id = claim.get("claim_id")
            if not isinstance(claim_id, str) or not CLAIM_REFERENCE.fullmatch(claim_id):
                errors.append("Invalid claim ID in {}".format(research_path.relative_to(run_dir)))
                continue
            if claim_id in claims:
                errors.append("Duplicate claim ID: {}".format(claim_id))
            claims[claim_id] = claim
            missing_sources = set(claim.get("source_ids", [])) - source_ids
            if missing_sources:
                errors.append("{} references unknown sources: {}".format(claim_id, sorted(missing_sources)))

    serp = _load_if_present(run_dir / "research" / "serp.json")
    if serp is not None and serp.get("run_id") != run_id:
        errors.append("research/serp.json has a mismatched run_id")

    brief = _load_if_present(run_dir / "brief" / "content-brief.json")
    if brief is not None:
        if brief.get("run_id") != run_id:
            errors.append("brief/content-brief.json has a mismatched run_id")
        referenced_claims = []
        for section in brief.get("sections", []):
            referenced_claims.extend(section.get("claim_ids", []))
        for interpretation in brief.get("interpretations", []):
            referenced_claims.extend(interpretation.get("basis_claim_ids", []))
        for claim_id in set(referenced_claims):
            if claim_id not in claims:
                errors.append("Brief references unknown claim: {}".format(claim_id))
            elif claims[claim_id].get("status") != "verified":
                errors.append("Brief references a non-verified claim: {}".format(claim_id))

    draft_metadata_files = sorted((run_dir / "drafts").glob("*.meta.json"))
    for metadata_path in draft_metadata_files:
        metadata = read_json(metadata_path)
        if metadata.get("run_id") != run_id:
            errors.append("{} has a mismatched run_id".format(metadata_path.relative_to(run_dir)))
        for path_field in ("content_path", "brief_path"):
            try:
                linked_path = resolve_artifact_path(run_dir, metadata.get(path_field, ""))
            except ArtifactError as exc:
                errors.append(str(exc))
                continue
            if not linked_path.is_file():
                errors.append("{} points to missing {}".format(metadata_path.relative_to(run_dir), path_field))
        for claim_id in metadata.get("claim_ids_used", []):
            if claim_id not in claims:
                errors.append("{} uses unknown claim {}".format(metadata_path.name, claim_id))
            elif claims[claim_id].get("status") != "verified":
                errors.append("{} uses non-verified claim {}".format(metadata_path.name, claim_id))

    current_version = run.get("current_draft_version")
    if current_version is not None:
        content = run_dir / "drafts" / "comparison-v{}.md".format(current_version)
        metadata = run_dir / "drafts" / "comparison-v{}.meta.json".format(current_version)
        if not content.is_file() or not metadata.is_file():
            errors.append("Current draft version does not have both content and metadata")
    if run.get("revision_count", 0) != max((current_version or 1) - 1, 0):
        errors.append("revision_count is inconsistent with current_draft_version")
    if current_version is not None and current_version > run.get("max_draft_versions", 0):
        errors.append("current_draft_version exceeds max_draft_versions")

    if errors:
        raise ValidationError(errors)
    return {
        "status": "pass",
        "run_id": run_id,
        "registered_artifacts": len(run.get("artifacts", [])),
        "verified_claims": sum(1 for claim in claims.values() if claim.get("status") == "verified"),
        "warnings": warnings,
    }
