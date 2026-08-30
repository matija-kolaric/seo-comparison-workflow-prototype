#!/usr/bin/env python3
"""Agent-driven MVP runner. 'next' dispatches work; it does not itself run an LLM."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from seobility_workflow.orchestrator import Orchestrator
from seobility_workflow.io import read_json
from seobility_workflow.errors import WorkflowError


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Record confirmed selection without starting articles")
    init.add_argument("batch", type=Path)
    init.add_argument("--queue", type=Path, required=True)
    init.add_argument("--selection-approval", required=True)
    approve = sub.add_parser("approve", help="Record actual production scope and separate total research budget")
    approve.add_argument("batch", type=Path)
    group = approve.add_mutually_exclusive_group()
    group.add_argument("--article", action="append")
    group.add_argument("--all", action="store_true")
    approve.add_argument("--budget-usd", required=True)
    approve.add_argument("--approval-ref", required=True)
    expand = sub.add_parser("expand", help="Add approved selected articles, preserving existing work and the shared cap")
    expand.add_argument("batch", type=Path)
    expand.add_argument("--article", action="append", required=True)
    expand.add_argument("--approval-ref", required=True)
    expand.add_argument("--aggregate-budget-usd", required=True)
    review = sub.add_parser("review-selection-reservation", help="Retain one unknown charge after explicit review of free history evidence")
    review.add_argument("batch", type=Path)
    review.add_argument("--evidence", type=Path, required=True)
    review.add_argument("--approval-ref", required=True)
    for name in ("status", "next"):
        sub.add_parser(name).add_argument("batch", type=Path)
    complete = sub.add_parser("complete", help="Check a reviewed receipt and advance one stage")
    complete.add_argument("batch", type=Path)
    complete.add_argument("--receipt", type=Path, required=True)
    resume = sub.add_parser("resume", help="Resume a failed nonterminal handoff after human review")
    resume.add_argument("batch", type=Path)
    resume.add_argument("--approval-ref", required=True)
    resume.add_argument("--reason", required=True)
    collect = sub.add_parser("collect", help="One explicitly authorized, budget-guarded research request")
    collect.add_argument("batch", type=Path)
    collect.add_argument("--plan", type=Path, required=True)
    collect.add_argument("--env-file", type=Path, default=ROOT / ".env")
    collect.add_argument("--confirm-live-costs", action="store_true")
    args = p.parse_args()
    try:
        runner = Orchestrator(ROOT, args.batch)
        if args.command == "init":
            result = runner.initialize(args.queue, args.selection_approval)
        elif args.command == "approve":
            ids = [i["id"] for i in runner.load()["items"]] if args.all else args.article
            result = runner.approve(ids, args.budget_usd, args.approval_ref)
        elif args.command == "status":
            result = runner.summary(runner.load())
        elif args.command == "expand":
            result = runner.expand(args.article, args.approval_ref, args.aggregate_budget_usd)
        elif args.command == "review-selection-reservation":
            result = runner.review_selection_reservation(args.evidence, args.approval_ref)
        elif args.command == "next":
            result = runner.next()
        elif args.command == "complete":
            result = runner.complete(args.receipt)
        elif args.command == "resume":
            result = runner.resume(args.approval_ref, args.reason)
        else:
            if not args.confirm_live_costs:
                p.error("collect requires --confirm-live-costs and recorded production approval")
            result = runner.collect(read_json(args.plan), args.env_file)
        print(json.dumps(result, indent=2))
        return 0
    except (WorkflowError, ValueError, KeyError, OSError, TypeError) as exc:
        # No transport exception strings or credential-bearing objects.
        print(json.dumps({"status": "stopped", "reason": str(exc) if isinstance(exc, WorkflowError) else type(exc).__name__}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
