#!/usr/bin/env python3
"""Validate JSON syntax, schema references, and cross-artifact sample invariants."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urldefrag

try:
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
except ImportError:  # Full schema validation is optional; structural checks still run.
    Draft202012Validator = None
    Registry = None
    Resource = None


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
SAMPLE = ROOT / "samples" / "runs" / "seobility-vs-ahrefs-demo"
sys.path.insert(0, str(ROOT / "src"))

from seobility_workflow.research.dataforseo import normalize_dataforseo

SCHEMA_BY_ARTIFACT = {
    "run.json": "run.schema.json",
    "research/serp.json": "serp-research.schema.json",
    "research/competitor.json": "product-research.schema.json",
    "research/seobility.json": "product-research.schema.json",
    "brief/content-brief.json": "content-brief.schema.json",
    "drafts/comparison-v1.meta.json": "draft-metadata.schema.json",
    "drafts/comparison-v2.meta.json": "draft-metadata.schema.json",
    "qa/fact-check-v1.json": "fact-check.schema.json",
    "qa/fact-check-v2.json": "fact-check.schema.json",
    "qa/seo-review-v1.json": "seo-review.schema.json",
    "qa/seo-review-v2.json": "seo-review.schema.json",
    "qa/quality-review-v1.json": "quality-review.schema.json",
    "qa/quality-review-v2.json": "quality-review.schema.json",
    "qa/revision-request-v1.json": "revision-request.schema.json",
    "qa/final-report.json": "final-report.schema.json"
}

EXTRA_SCHEMA_INSTANCES = {
    ROOT / "config" / "research-policy.json": "research-policy.schema.json",
    ROOT / "knowledge" / "seobility" / "knowledge-base.json": "knowledge-base.schema.json",
    ROOT / "tests" / "fixtures" / "seobility-approved-knowledge-base.json": "knowledge-base.schema.json",
}


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def resolve_pointer(document: object, pointer: str) -> object:
    current = document
    if not pointer:
        return current
    if not pointer.startswith("/"):
        raise ValueError(f"Unsupported JSON pointer: #{pointer}")
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


def walk_refs(value: object):
    if isinstance(value, dict):
        if "$ref" in value:
            yield value["$ref"]
        for child in value.values():
            yield from walk_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_refs(child)


def main() -> int:
    errors: list[str] = []
    schema_files = sorted(SCHEMAS.glob("*.schema.json"))
    schemas = {path.name: load(path) for path in schema_files}

    for path in schema_files:
        schema = schemas[path.name]
        for reference in walk_refs(schema):
            target_name, fragment = urldefrag(reference)
            target_name = target_name or path.name
            if target_name not in schemas:
                errors.append(f"{path}: missing referenced schema {target_name}")
                continue
            try:
                resolve_pointer(schemas[target_name], fragment)
            except (KeyError, IndexError, ValueError) as exc:
                errors.append(f"{path}: invalid reference {reference}: {exc}")

    json_files = sorted(SAMPLE.rglob("*.json"))
    documents = {path.relative_to(SAMPLE).as_posix(): load(path) for path in json_files}

    dataforseo_fixture = ROOT / "tests" / "fixtures" / "dataforseo"
    normalized_provider_fixture = normalize_dataforseo(
        run_id="provider-fixture-run",
        keyword_overview_response=load(dataforseo_fixture / "keyword-overview.json"),
        serp_responses=[
            load(dataforseo_fixture / "serp-seobility-vs-ahrefs.json"),
            load(dataforseo_fixture / "serp-ahrefs-alternative.json"),
        ],
        generated_at="2026-08-27T12:00:00Z",
    )

    if Draft202012Validator is not None:
        registry = Registry().with_resources(
            (schema_name, Resource.from_contents(schema))
            for schema_name, schema in schemas.items()
        )
        for schema_name, schema in schemas.items():
            try:
                Draft202012Validator.check_schema(schema)
            except Exception as exc:  # jsonschema exposes several validation exceptions.
                errors.append(f"{schema_name}: invalid Draft 2020-12 schema: {exc}")
        for relative_path, schema_name in SCHEMA_BY_ARTIFACT.items():
            validator = Draft202012Validator(
                schemas[schema_name],
                registry=registry,
                format_checker=Draft202012Validator.FORMAT_CHECKER,
            )
            for error in validator.iter_errors(documents[relative_path]):
                location = "/".join(str(part) for part in error.absolute_path) or "<root>"
                errors.append(f"{relative_path}:{location}: {error.message}")
        for instance_path, schema_name in EXTRA_SCHEMA_INSTANCES.items():
            validator = Draft202012Validator(
                schemas[schema_name],
                registry=registry,
                format_checker=Draft202012Validator.FORMAT_CHECKER,
            )
            for error in validator.iter_errors(load(instance_path)):
                location = "/".join(str(part) for part in error.absolute_path) or "<root>"
                errors.append(f"{instance_path.relative_to(ROOT)}:{location}: {error.message}")
        provider_validator = Draft202012Validator(
            schemas["serp-research.schema.json"],
            registry=registry,
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )
        for error in provider_validator.iter_errors(normalized_provider_fixture):
            location = "/".join(str(part) for part in error.absolute_path) or "<root>"
            errors.append(f"normalized DataForSEO fixture:{location}: {error.message}")

    run = documents["run.json"]
    run_id = run["run_id"]

    for relative_path, document in documents.items():
        if document.get("run_id") != run_id:
            errors.append(f"{relative_path}: run_id does not match run.json")

    claims: dict[str, dict] = {}
    for relative_path in ("research/competitor.json", "research/seobility.json"):
        research = documents[relative_path]
        source_ids = {source["source_id"] for source in research["sources"]}
        for claim in research["claims"]:
            claim_id = claim["claim_id"]
            if claim_id in claims:
                errors.append(f"Duplicate claim ID: {claim_id}")
            claims[claim_id] = claim
            missing_sources = set(claim["source_ids"]) - source_ids
            if missing_sources:
                errors.append(f"{claim_id}: unknown source IDs {sorted(missing_sources)}")

    brief = documents["brief/content-brief.json"]
    referenced_claims = {
        claim_id
        for section in brief["sections"]
        for claim_id in section["claim_ids"]
    }
    referenced_claims.update(
        claim_id
        for interpretation in brief["interpretations"]
        for claim_id in interpretation["basis_claim_ids"]
    )
    for claim_id in referenced_claims:
        if claim_id not in claims:
            errors.append(f"Brief references unknown claim {claim_id}")
        elif claims[claim_id]["status"] != "verified":
            errors.append(f"Brief references non-verified claim {claim_id}")

    for version in (1, 2):
        metadata = documents[f"drafts/comparison-v{version}.meta.json"]
        for claim_id in metadata["claim_ids_used"]:
            if claim_id not in claims or claims[claim_id]["status"] != "verified":
                errors.append(f"Draft v{version} uses unavailable claim {claim_id}")
        for path_field in ("content_path", "brief_path"):
            if not (SAMPLE / metadata[path_field]).is_file():
                errors.append(f"Draft v{version} has missing {path_field}")

        quality = documents[f"qa/quality-review-v{version}.json"]
        expected_total = sum(quality["scores"].values())
        if quality["total_score"] != expected_total:
            errors.append(f"Quality review v{version}: total_score is not the score sum")
        expected_quality_status = (
            "pass"
            if expected_total >= 25 and min(quality["scores"].values()) >= 3
            else "fail"
        )
        if quality["status"] != expected_quality_status:
            errors.append(f"Quality review v{version}: status conflicts with thresholds")

        fact = documents[f"qa/fact-check-v{version}.json"]
        expected_fact_status = "pass" if fact["unsupported_claims_count"] == 0 else "fail"
        if fact["status"] != expected_fact_status:
            errors.append(f"Fact check v{version}: status conflicts with unsupported count")

    final = documents["qa/final-report.json"]
    final_version = final["final_draft_version"]
    if final_version != run["current_draft_version"]:
        errors.append("Final report version does not match current draft version")
    if run["revision_count"] != final_version - 1:
        errors.append("revision_count does not match the final draft version")
    if final_version > run["max_draft_versions"]:
        errors.append("Final draft version exceeds max_draft_versions")

    for artifact in run["artifacts"]:
        if not (SAMPLE / artifact["path"]).is_file():
            errors.append(f"run.json references missing artifact {artifact['path']}")

    if errors:
        print("Validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    schema_note = "including Draft 2020-12 instances" if Draft202012Validator else "without the optional jsonschema package"
    print(f"Validated {len(schema_files)} schema files, {len(json_files)} sample JSON files, the DataForSEO normalization fixture, {schema_note}, local references, and cross-artifact invariants.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
