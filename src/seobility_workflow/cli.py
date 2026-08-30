"""Command-line interface for deterministic workflow operations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .errors import WorkflowError
from .gates import apply_gate_evaluation, evaluate_gates
from .research.dataforseo import (
    check_dataforseo_connection,
    collect_dataforseo,
    collect_dataforseo_mvp,
    normalize_dataforseo_files,
)
from .research.policy import materialize_seobility_research, validate_research_layer
from .runs import create_run, record_draft, register_artifact
from .state import ALLOWED_TRANSITIONS, transition_run
from .validation import validate_run


def print_json(value) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seobility-workflow")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="Create a new run directory")
    init.add_argument("--runs-dir", type=Path, default=Path("runs"))
    init.add_argument("--topic", required=True)
    init.add_argument("--page-type", choices=("versus", "alternative"), default="versus")
    init.add_argument("--language", default="en")
    init.add_argument("--market", required=True)
    init.add_argument("--audience")
    init.add_argument("--data-mode", choices=("fixture", "live"), default="fixture")
    init.add_argument("--run-id")
    init.add_argument("--max-draft-versions", type=int, default=3)

    validate = commands.add_parser("validate", help="Validate a run and cross-file invariants")
    validate.add_argument("run_dir", type=Path)

    transition = commands.add_parser("transition", help="Apply an allowed state transition")
    transition.add_argument("run_dir", type=Path)
    transition.add_argument("status", choices=tuple(ALLOWED_TRANSITIONS))
    transition.add_argument("--reason", required=True)

    register = commands.add_parser("register-artifact", help="Hash and register an existing artifact")
    register.add_argument("run_dir", type=Path)
    register.add_argument("--type", required=True, dest="artifact_type")
    register.add_argument("--path", required=True, dest="relative_path")
    register.add_argument("--version", type=int, required=True)

    draft = commands.add_parser("record-draft", help="Record a new draft and advance to draft_ready")
    draft.add_argument("run_dir", type=Path)
    draft.add_argument("--version", type=int, required=True)
    draft.add_argument("--content-path")
    draft.add_argument("--metadata-path")

    evaluate = commands.add_parser("evaluate", help="Calculate quality gates for the current draft")
    evaluate.add_argument("run_dir", type=Path)
    evaluate.add_argument("--draft-version", type=int, required=True)
    evaluate.add_argument("--apply", action="store_true", help="Write the decision artifact and transition the run")

    normalize = commands.add_parser("normalize-dataforseo", help="Normalize saved DataForSEO API or MCP responses")
    normalize.add_argument("run_dir", type=Path)
    normalize.add_argument("--keyword-response", type=Path, required=True)
    normalize.add_argument("--serp-response", type=Path, action="append", required=True)
    normalize.add_argument("--provider", choices=("dataforseo_api", "dataforseo_mcp"), default="dataforseo_api")

    collect = commands.add_parser("collect-dataforseo", help="Make explicitly authorized paid DataForSEO live calls")
    collect.add_argument("run_dir", type=Path)
    collect.add_argument("--keyword", action="append", required=True)
    collect.add_argument("--location", required=True)
    collect.add_argument("--language-code", default="en")
    collect.add_argument("--depth", type=int, default=10)
    collect.add_argument("--confirm-live-costs", action="store_true")

    check_mvp = commands.add_parser(
        "check-dataforseo", help="Make a free authentication and balance-availability check"
    )
    check_mvp.add_argument("--env-file", type=Path, default=Path(".env"))

    collect_mvp = commands.add_parser(
        "collect-dataforseo-mvp",
        help="Collect DataForSEO evidence for a simplified input.json run",
    )
    collect_mvp.add_argument("run_dir", type=Path)
    collect_mvp.add_argument("--keyword", action="append", required=True)
    collect_mvp.add_argument("--location")
    collect_mvp.add_argument("--language-code")
    collect_mvp.add_argument("--depth", type=int, default=10)
    collect_mvp.add_argument("--sandbox", action="store_true")
    collect_mvp.add_argument("--env-file", type=Path, default=Path(".env"))
    collect_mvp.add_argument("--confirm-live-costs", action="store_true")

    materialize = commands.add_parser("materialize-seobility", help="Create run research from an approved Seobility knowledge base")
    materialize.add_argument("run_dir", type=Path)
    materialize.add_argument("--knowledge-base", type=Path, default=Path("knowledge/seobility/knowledge-base.json"))
    materialize.add_argument("--policy", type=Path, default=Path("config/research-policy.json"))

    research = commands.add_parser("validate-research", help="Apply source policy and freshness rules to all research")
    research.add_argument("run_dir", type=Path)
    research.add_argument("--policy", type=Path, default=Path("config/research-policy.json"))
    research.add_argument("--apply", action="store_true", help="Advance research_ready to evidence_validated after a pass")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            run_dir = create_run(
                runs_dir=args.runs_dir,
                topic=args.topic,
                page_type=args.page_type,
                language=args.language,
                market=args.market,
                audience=args.audience,
                data_mode=args.data_mode,
                run_id=args.run_id,
                max_draft_versions=args.max_draft_versions,
            )
            print_json({"status": "created", "run_dir": str(run_dir.resolve())})
        elif args.command == "validate":
            print_json(validate_run(args.run_dir))
        elif args.command == "transition":
            run = transition_run(args.run_dir, args.status, args.reason)
            print_json({"run_id": run["run_id"], "status": run["status"]})
        elif args.command == "register-artifact":
            print_json(
                register_artifact(
                    args.run_dir, args.artifact_type, args.relative_path, args.version
                )
            )
        elif args.command == "record-draft":
            run = record_draft(
                args.run_dir,
                args.version,
                content_path=args.content_path,
                metadata_path=args.metadata_path,
            )
            print_json({"run_id": run["run_id"], "status": run["status"], "draft_version": args.version})
        elif args.command == "evaluate":
            evaluation = evaluate_gates(args.run_dir, args.draft_version)
            result = evaluation.as_dict()
            if args.apply:
                result["written_artifact"] = str(
                    apply_gate_evaluation(args.run_dir, evaluation).relative_to(args.run_dir)
                )
            print_json(result)
        elif args.command == "normalize-dataforseo":
            output = normalize_dataforseo_files(
                args.run_dir,
                args.keyword_response,
                args.serp_response,
                provider_name=args.provider,
            )
            print_json({"status": "normalized", "artifact": str(output)})
        elif args.command == "collect-dataforseo":
            output = collect_dataforseo(
                args.run_dir,
                args.keyword,
                args.location,
                args.language_code,
                depth=args.depth,
                confirm_live_costs=args.confirm_live_costs,
            )
            print_json({"status": "collected", "artifact": str(output)})
        elif args.command == "check-dataforseo":
            print_json(check_dataforseo_connection(args.env_file))
        elif args.command == "collect-dataforseo-mvp":
            output = collect_dataforseo_mvp(
                args.run_dir,
                args.keyword,
                location_name=args.location,
                language_code=args.language_code,
                depth=args.depth,
                sandbox=args.sandbox,
                confirm_live_costs=args.confirm_live_costs,
                env_file=args.env_file,
            )
            print_json(
                {
                    "status": "collected",
                    "mode": "sandbox" if args.sandbox else "live",
                    "artifact": str(output),
                }
            )
        elif args.command == "materialize-seobility":
            output = materialize_seobility_research(
                args.run_dir,
                args.knowledge_base,
                policy_path=args.policy,
            )
            print_json({"status": "materialized", "artifact": str(output)})
        elif args.command == "validate-research":
            result = validate_research_layer(args.run_dir, policy_path=args.policy)
            if args.apply:
                run = transition_run(
                    args.run_dir,
                    "evidence_validated",
                    "Research passed source, provenance, and freshness validation.",
                )
                result["run_status"] = run["status"]
            print_json(result)
        return 0
    except WorkflowError as exc:
        print_json({"status": "error", "error": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
