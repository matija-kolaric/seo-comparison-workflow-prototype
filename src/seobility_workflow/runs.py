"""Run creation and artifact registration."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .errors import ArtifactError, WorkflowError
from .io import atomic_write_json, read_json, resolve_artifact_path, sha256_file
from .time import utc_now


RUN_DIRECTORIES = ("research", "brief", "drafts", "qa", "publish")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80]


def create_run(
    runs_dir: Path,
    topic: str,
    page_type: str,
    language: str,
    market: str,
    audience: Optional[str] = None,
    data_mode: str = "fixture",
    run_id: Optional[str] = None,
    max_draft_versions: int = 3,
    created_at: Optional[str] = None,
) -> Path:
    if page_type not in {"versus", "alternative"}:
        raise WorkflowError("page_type must be 'versus' or 'alternative'")
    if data_mode not in {"fixture", "live"}:
        raise WorkflowError("data_mode must be 'fixture' or 'live'")
    if not 1 <= max_draft_versions <= 10:
        raise WorkflowError("max_draft_versions must be between 1 and 10")
    timestamp = created_at or utc_now()
    derived_id = "{}-{}".format(slugify(topic), timestamp.replace(":", "").replace("-", "").lower())
    selected_id = run_id or derived_id
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,79}", selected_id):
        raise WorkflowError("run_id does not satisfy the run schema")

    run_dir = Path(runs_dir) / selected_id
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise WorkflowError("Run already exists: {}".format(run_dir)) from exc
    for directory in RUN_DIRECTORIES:
        (run_dir / directory).mkdir()

    run = {
        "schema_version": "1.0",
        "run_id": selected_id,
        "topic": topic,
        "page_type": page_type,
        "language": language,
        "market": market,
        "audience": audience,
        "data_mode": data_mode,
        "status": "initialized",
        "created_at": timestamp,
        "updated_at": timestamp,
        "revision_count": 0,
        "max_draft_versions": max_draft_versions,
        "current_draft_version": None,
        "status_history": [
            {"status": "initialized", "at": timestamp, "reason": "Run created."}
        ],
        "artifacts": [],
    }
    atomic_write_json(run_dir / "run.json", run)
    return run_dir


def register_artifact(
    run_dir: Path,
    artifact_type: str,
    relative_path: str,
    version: int,
    created_at: Optional[str] = None,
) -> dict:
    run_dir = Path(run_dir)
    artifact_path = resolve_artifact_path(run_dir, relative_path)
    if not artifact_path.is_file():
        raise ArtifactError("Cannot register missing artifact: {}".format(relative_path))
    if version < 1:
        raise ArtifactError("Artifact version must be at least 1")

    run_path = run_dir / "run.json"
    run = read_json(run_path)
    if any(item["path"] == relative_path for item in run.get("artifacts", [])):
        raise ArtifactError("Artifact is already registered: {}".format(relative_path))

    timestamp = created_at or utc_now()
    artifact = {
        "type": artifact_type,
        "path": relative_path,
        "version": version,
        "created_at": timestamp,
        "sha256": sha256_file(artifact_path),
    }
    run.setdefault("artifacts", []).append(artifact)
    run["updated_at"] = timestamp
    atomic_write_json(run_path, run)
    return artifact


def record_draft(
    run_dir: Path,
    version: int,
    content_path: Optional[str] = None,
    metadata_path: Optional[str] = None,
    created_at: Optional[str] = None,
) -> dict:
    run_dir = Path(run_dir)
    content_relative = content_path or "drafts/comparison-v{}.md".format(version)
    metadata_relative = metadata_path or "drafts/comparison-v{}.meta.json".format(version)
    content = resolve_artifact_path(run_dir, content_relative)
    metadata_file = resolve_artifact_path(run_dir, metadata_relative)
    if not content.is_file() or not metadata_file.is_file():
        raise ArtifactError("Draft content and metadata must exist before recording")

    run_path = run_dir / "run.json"
    run = read_json(run_path)
    expected_status = "brief_ready" if version == 1 else "revision_required"
    if run.get("status") != expected_status:
        raise WorkflowError(
            "Draft v{} requires run status {}, found {}".format(
                version, expected_status, run.get("status")
            )
        )
    expected_version = 1 if run.get("current_draft_version") is None else run["current_draft_version"] + 1
    if version != expected_version:
        raise WorkflowError("Expected draft version {}, received {}".format(expected_version, version))
    if version > run["max_draft_versions"]:
        raise WorkflowError("Draft version exceeds max_draft_versions")

    metadata = read_json(metadata_file)
    if metadata.get("run_id") != run.get("run_id") or metadata.get("draft_version") != version:
        raise ArtifactError("Draft metadata does not match the run and version")
    if metadata.get("content_path") != content_relative:
        raise ArtifactError("Draft metadata content_path does not match the recorded path")

    timestamp = created_at or utc_now()
    existing_paths = {item["path"] for item in run.get("artifacts", [])}
    for artifact_type, relative, path in (
        ("draft", content_relative, content),
        ("draft_metadata", metadata_relative, metadata_file),
    ):
        if relative in existing_paths:
            raise ArtifactError("Artifact is already registered: {}".format(relative))
        run.setdefault("artifacts", []).append(
            {
                "type": artifact_type,
                "path": relative,
                "version": version,
                "created_at": timestamp,
                "sha256": sha256_file(path),
            }
        )
    run["current_draft_version"] = version
    run["revision_count"] = version - 1
    run["status"] = "draft_ready"
    run["updated_at"] = timestamp
    run.setdefault("status_history", []).append(
        {
            "status": "draft_ready",
            "at": timestamp,
            "reason": "Draft version {} recorded.".format(version),
        }
    )
    atomic_write_json(run_path, run)
    return run
