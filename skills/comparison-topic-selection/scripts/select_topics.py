#!/usr/bin/env python3
"""Project-local CLI. Rank is offline; collection requires a separate explicit opt-in."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from seobility_workflow.io import read_json
from seobility_workflow.topic_selection import SelectionError, select_topics, render_report
from seobility_workflow.selection_collection import request_for, collect_selection, reconcile_missing_result, selection_cost_summary
from seobility_workflow.research.dataforseo import load_dataforseo_env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    rank = sub.add_parser("rank", help="Offline scoring; never reads credentials or calls APIs")
    rank.add_argument("assessment", type=Path)
    rank.add_argument("--run-dir", type=Path, required=True)
    rank.add_argument("--ledger-snapshot", type=Path, help="Read-only evidence snapshot for a revised review; never a new collection budget")
    collect = sub.add_parser("collect", help="Preview one request by default; opt in to paid collection")
    collect.add_argument("plan", type=Path)
    collect.add_argument("--run-dir", type=Path, required=True)
    collect.add_argument("--budget-usd", default="1")
    collect.add_argument("--approval-ref", default="")
    collect.add_argument("--env-file", type=Path, default=ROOT / ".env")
    collect.add_argument("--confirm-live-costs", action="store_true")
    reconcile = sub.add_parser("reconcile", help="Record a verified charge without fabricating a missing result; no API call")
    reconcile.add_argument("plan", type=Path)
    reconcile.add_argument("--run-dir", type=Path, required=True)
    reconcile.add_argument("--evidence-ref", required=True)
    reconcile.add_argument("--resume-approval-ref", required=True)
    args = parser.parse_args()
    try:
        # Do not let selection helpers write into the deployable site or outside project runs.
        run = args.run_dir.resolve()
        run.relative_to((ROOT / "runs").resolve())
        if not run.name.startswith("selection-"):
            raise SelectionError("Use runs/selection-<date>-<id> for selection artifacts")
        if args.command == "reconcile":
            reconcile_missing_result(run, read_json(args.plan), args.evidence_ref, args.resume_approval_ref)
            print("Charge reconciled; result remains missing. Budget preserved. No API call made.")
            return 0
        if args.command == "collect":
            plan = read_json(args.plan)
            endpoint, task = request_for(plan)
            if not args.confirm_live_costs:
                print(json.dumps({"mode": "dry_run", "endpoint": endpoint, "request": task, "api_calls": 0}, indent=2))
                return 0
            load_dataforseo_env(args.env_file)
            print(collect_selection(plan, run, args.budget_usd, args.approval_ref, True))
            return 0
        if (run / "queue.json").exists() or (run / "selection.md").exists():
            raise SelectionError("Selection outputs already exist; create a revised run instead of overwriting")
        data = read_json(args.assessment)
        if data.get("data_mode") == "live":
            ledger_path = (args.ledger_snapshot or run / "evidence/collection-ledger.json").resolve()
            ledger_path.relative_to((run / "evidence").resolve())
            ledger = read_json(ledger_path)
            if ledger.get("data_mode") != "live":
                raise SelectionError("Live ranking requires a live collection ledger or retained snapshot")
            data["costs"] = selection_cost_summary(ledger, run)
            data["costs"]["ledger_ref"] = str(ledger_path.relative_to(run))
        queue = select_topics(data, run)
        run.mkdir(parents=True, exist_ok=True)
        # Exclusive creation preserves existing results even if another process just wrote them.
        with (run / "queue.json").open("x", encoding="utf-8") as handle:
            json.dump(queue, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        with (run / "selection.md").open("x", encoding="utf-8") as handle:
            handle.write(render_report(queue))
        print("Selected {} of {}; {} reserves. Awaiting human review. No production or publication started.".format(len(queue["selected"]), queue["target_count"], len(queue["reserves"])))
        return 0
    except Exception as exc:
        # Never print transport objects, credentials, headers, or raw provider responses.
        print("Selection stopped: {}".format(str(exc) if isinstance(exc, (SelectionError, FileExistsError)) else type(exc).__name__), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
