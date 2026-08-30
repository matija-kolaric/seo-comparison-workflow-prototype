"""Safe JSON and file helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

from .errors import ArtifactError


def read_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError as exc:
        raise ArtifactError("Missing JSON artifact: {}".format(path)) from exc
    except json.JSONDecodeError as exc:
        raise ArtifactError("Invalid JSON in {}: {}".format(path, exc)) from exc
    if not isinstance(value, dict):
        raise ArtifactError("Expected a JSON object in {}".format(path))
    return value


def atomic_write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".{}-".format(path.name), suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(path))
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def resolve_artifact_path(run_dir: Path, relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise ArtifactError("Artifact path must be a non-empty relative path")
    resolved_run = run_dir.resolve()
    resolved_artifact = (run_dir / relative_path).resolve()
    try:
        common = Path(os.path.commonpath([str(resolved_run), str(resolved_artifact)]))
    except ValueError as exc:
        raise ArtifactError("Artifact path is outside the run directory") from exc
    if common != resolved_run:
        raise ArtifactError("Artifact path is outside the run directory: {}".format(relative_path))
    return resolved_artifact


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
