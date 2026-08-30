from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from seobility_workflow.orchestrator import Orchestrator, OrchestrationError, CHECKS, OUTPUTS, stamp
from seobility_workflow.io import atomic_write_json, sha256_file
from seobility_workflow.errors import WorkflowError


class FakeAPI:
    def __init__(self, cost=0.004, fail=False):
        self.calls = 0
        self.cost = cost
        self.fail = fail

    def post(self, endpoint, tasks):
        self.calls += 1
        if self.fail:
            raise TimeoutError("private credentials must not be logged")
        return {"status_code": 20000, "cost": self.cost, "tasks": [{"status_code": 20000, "cost": self.cost, "result": []}]}


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.batch = self.root / "runs/orchestration-fixture"
        self.queue = self.root / "runs/selection-fixture/queue.json"
        rows = []
        for tool in ["Example A", "Example B"]:
            rows.append({"id": "seobility-vs-" + tool.lower().replace(" ", "-"),
                         "products": ["Seobility", tool], "decision": "selected", "confidence": "medium", "score": 75,
                         "input": {"topic": "Seobility vs " + tool, "page_type": "versus", "language": "en", "market": "United States"}})
        atomic_write_json(self.queue, {"data_mode": "fixture", "selected": rows, "production_authorized": False, "publication_authorized": False})
        self.runner = Orchestrator(self.root, self.batch)
        self.runner.initialize(self.queue, "fixture selection approval")

    def tearDown(self):
        self.temp.cleanup()

    def test_user_stop_blocks_dispatch_and_paid_collection(self):
        self.approve(budget="0.1")
        self.runner.next()
        state = self.runner.load()
        state["production_stop"] = {"reason": "User limited POC to completed articles"}
        self.runner.save(state)
        api = FakeAPI()
        self.assertEqual(self.runner.next()["action"], "stopped_by_user")
        with self.assertRaisesRegex(OrchestrationError, "stopped by user"):
            self.runner.collect({}, client=api)
        self.assertEqual(api.calls, 0)
        with self.assertRaisesRegex(OrchestrationError, "stopped by user"):
            self.runner.complete(self.batch / "missing-receipt.json")
        with self.assertRaisesRegex(OrchestrationError, "stopped by user"):
            self.runner.resume("old approval", "generic resume must not clear scope stop")
        self.assertIn("Production stopped by user; new explicit approval required", self.runner.summary(state)["paid_research_blockers"])

    def approve(self, all_articles=False, budget="0"):
        ids = [i["id"] for i in self.runner.load()["items"]] if all_articles else None
        return self.runner.approve(ids, budget, "fixture production approval")

    def qa(self, passed=True):
        scores = {k: 5 for k in ["factual_accuracy", "search_intent_match", "comparative_usefulness", "specificity", "originality", "positioning_clarity"]}
        return {"draft": "draft.md", "reviewed_at": stamp(), "passed": passed, "scores": scores, "total_score": 30,
                "unsupported_claims": [], "issues": [], "required_changes": [] if passed else ["Make the example concrete"], "human_review_notes": []}

    def prepare_receipt(self, work, passed=True, qa=None):
        run = Path(work["run_dir"])
        stage = work["dispatch"]["stage"]
        topic = json.loads((run / "input.json").read_text())["topic"]
        for ref in OUTPUTS[stage]:
            path = run / ref
            path.parent.mkdir(parents=True, exist_ok=True)
            if ref.endswith("claims.json"):
                atomic_write_json(path, {"topic": topic, "researched_at": stamp(), "claims": [{"claim_id": "TEST-001", "subject": "Seobility", "fact_type": "feature", "statement": "Synthetic test fact", "status": "supported", "sources": [{"title": "Fixture", "url": "https://example.com/official", "retrieved_at": stamp(), "evidence": "Synthetic fixture evidence"}]}]})
            elif ref == "qa.json":
                atomic_write_json(path, qa or self.qa(passed))
            elif ref == "draft.md":
                path.write_text("Synthetic fixture draft, never publish. <!-- claims: TEST-001 -->\n")
            else:
                path.write_text("Synthetic fixture artifact, not real research.\n")
        receipt = {"dispatch": work["dispatch"], "passed": passed,
                   "checks": {k: passed for k in CHECKS[stage]},
                   "files": {ref: sha256_file(run / ref) for ref in OUTPUTS[stage]},
                   "notes": "Synthetic test-only handoff; no real source or editorial claim."}
        path = run / "handoffs" / (stage + "-" + str(work["dispatch"]["revision"]) + ".json")
        atomic_write_json(path, receipt)
        return path

    def step(self, passed=True, qa=None):
        work = self.runner.next()
        self.assertEqual(work["action"], "execute_skill")
        self.runner.complete(self.prepare_receipt(work, passed, qa))
        return work

    def plan(self):
        return {"operation": "serp", "keyword": "seobility vs example a", "depth": 20,
                "cost_bound_usd": "0.01", "pricing_source": "https://dataforseo.com/pricing", "pricing_checked_at": stamp()}

    def test_initialization_confirms_queue_but_starts_nothing(self):
        self.assertEqual(self.runner.next()["action"], "await_production_approval")
        self.assertFalse((self.batch / "articles").exists())
        self.assertIsNone(self.runner.load()["budget_usd"])
        with self.assertRaises(OrchestrationError): self.runner.initialize(self.queue, "again")

    def test_default_scope_is_one_and_interruption_resumes_same_dispatch(self):
        self.approve()
        first = self.runner.next()
        again = Orchestrator(self.root, self.batch).next()
        self.assertEqual(first["dispatch"], again["dispatch"])
        self.assertEqual(self.runner.load()["items"][1]["status"], "selected")

    def test_two_article_offline_end_to_end_and_publication_stop(self):
        self.approve(all_articles=True)
        stages = [self.step()["dispatch"]["stage"] for _ in range(10)]
        self.assertEqual(stages, ["research", "brief", "assets", "writer", "qa"] * 2)
        self.assertEqual(self.runner.next()["action"], "await_publication_review")
        self.assertTrue(all(i["status"] == "ready_for_publish" for i in self.runner.load()["items"]))
        self.assertFalse(self.runner.load()["publication_authorized"])
        self.assertEqual(self.runner.load()["costs"], [])

    def test_missing_artifact_stale_receipt_and_stage_skip_rejected(self):
        self.approve()
        work = self.runner.next()
        path = self.prepare_receipt(work)
        receipt = json.loads(path.read_text())
        receipt["dispatch"]["stage"] = "qa"
        atomic_write_json(path, receipt)
        with self.assertRaises(OrchestrationError): self.runner.complete(path)
        path = self.prepare_receipt(work)
        (Path(work["run_dir"]) / "research/research.md").unlink()
        with self.assertRaises(OrchestrationError): self.runner.complete(path)

    def test_changed_completed_output_and_source_queue_block_resume(self):
        self.approve()
        work = self.step()
        (Path(work["run_dir"]) / "research/research.md").write_text("Unreviewed edit")
        with self.assertRaises(OrchestrationError): self.runner.next()
        q = json.loads(self.queue.read_text())
        q["selected"].reverse()
        atomic_write_json(self.queue, q)
        with self.assertRaises(OrchestrationError): self.runner.load()

    def test_failed_handoff_stops_entire_batch_until_explicit_resume(self):
        self.approve(all_articles=True)
        self.step(passed=False)
        self.assertEqual(self.runner.next()["action"], "needs_review")
        self.assertEqual(self.runner.load()["items"][1]["status"], "approved")
        with self.assertRaises(OrchestrationError): self.runner.resume("", "resolved")
        self.runner.resume("fixture approval", "Research limitation corrected")
        self.assertEqual(self.runner.next()["dispatch"]["stage"], "research")

    def test_one_qa_revision_preserves_original_then_second_failure_stops(self):
        self.approve(all_articles=True)
        for _ in range(4): self.step()
        firstqa = self.step(passed=False)
        run = Path(firstqa["run_dir"])
        self.assertTrue((run / "draft-v1.md").exists())
        self.assertFalse(json.loads((run / "qa-v1.json").read_text())["passed"])
        self.assertEqual(self.step()["dispatch"]["stage"], "writer")
        self.step(passed=False)
        self.assertEqual(self.runner.next()["action"], "needs_review")
        with self.assertRaises(OrchestrationError): self.runner.resume("approval", "try again")

    def test_qa_true_cannot_override_failed_scores_or_citation_issue(self):
        q = self.qa()
        q["scores"]["originality"] = 3
        q["total_score"] = 28
        self.assertFalse(self.runner.qa_passes(q))
        q = self.qa()
        q["issues"] = [{"severity": "medium", "category": "citation_integrity"}]
        self.assertFalse(self.runner.qa_passes(q))
        q = self.qa()
        q["total_score"] = 29
        with self.assertRaises(OrchestrationError): self.runner.qa_passes(q)

    def test_existing_article_and_path_escape_are_not_overwritten(self):
        self.approve()
        atomic_write_json(self.root / "runs/existing/input.json", {"topic": "Example A vs Seobility"})
        with self.assertRaises(OrchestrationError): self.runner.next()
        with self.assertRaises(ValueError): Orchestrator(self.root, self.root / "website/orchestration-bad")

    def test_duplicate_queue_cannot_start_another_batch(self):
        other = Orchestrator(self.root, self.root / "runs/orchestration-duplicate")
        with self.assertRaises(OrchestrationError): other.initialize(self.queue, "new approval")
        self.assertFalse(other.file.exists())

    def test_qa_revision_can_pass_without_research_replay(self):
        self.approve()
        for _ in range(4): self.step()
        self.step(passed=False)
        self.step()
        self.step()
        self.assertEqual(self.runner.next()["action"], "await_publication_review")
        events = [x["stage"] for x in self.runner.load()["history"] if x["event"] == "handoff_passed"]
        self.assertEqual(events.count("research"), 1)
        self.assertEqual(events.count("writer"), 2)

    def test_budget_blocks_before_api_and_cache_is_free(self):
        self.approve(budget="0.01")
        self.runner.next()
        client = FakeAPI()
        self.runner.collect(self.plan(), client=client)
        self.assertTrue(self.runner.collect(self.plan(), client=client)["reused"])
        self.assertEqual(client.calls, 1)
        p = self.plan()
        p["keyword"] = "other priority query"
        with self.assertRaises(OrchestrationError): self.runner.collect(p, client=client)
        self.assertEqual(client.calls, 1)

    def test_failure_retains_reservation_and_prevents_duplicate_charge(self):
        self.approve(budget="1")
        self.runner.next()
        client = FakeAPI(fail=True)
        with self.assertRaises(OrchestrationError): self.runner.collect(self.plan(), client=client)
        self.assertEqual(self.runner.load()["costs"][0]["state"], "unresolved")
        self.assertEqual(self.runner.next()["action"], "needs_review")
        self.assertNotIn("private credentials", self.runner.file.read_text())
        with self.assertRaises(OrchestrationError): self.runner.collect(self.plan(), client=client)
        self.assertEqual(client.calls, 1)

    def test_over_reservation_bill_is_reported_not_hidden(self):
        self.approve(budget="1")
        self.runner.next()
        client = FakeAPI(cost=0.02)
        with self.assertRaises(OrchestrationError): self.runner.collect(self.plan(), client=client)
        summary = self.runner.summary(self.runner.load())
        self.assertEqual(summary["confirmed_spend_usd"], "0.02")
        self.assertTrue(summary["paid_research_blockers"])
        with self.assertRaises(OrchestrationError): self.runner.collect(self.plan(), client=client)
        self.assertEqual(client.calls, 1)

    def test_original_selection_billing_stop_is_still_enforced(self):
        self.approve(budget="1")
        self.runner.next()
        ledger = self.root / "runs/selection-original/evidence/collection-ledger.json"
        atomic_write_json(ledger, {"budget_usd": "1", "requests": [{"state": "unresolved"}]})
        s = self.runner.load()
        s["selection_ledger_ref"] = str(ledger.relative_to(self.root))
        self.runner.save(s)
        client = FakeAPI()
        with self.assertRaises(ValueError): self.runner.collect(self.plan(), client=client)
        self.assertEqual(client.calls, 0)

    def attach_selection_ledger(self, unresolved=False):
        ledger = self.root / "runs/selection-original/evidence/collection-ledger.json"
        started = datetime.now(timezone.utc) - timedelta(minutes=10)
        old = {"state": "unresolved", "cause_type": "URLError", "operation": "serp",
               "fingerprint": "fixture-fingerprint", "started_at": started.isoformat(), "reserved_usd": "0.01"}
        atomic_write_json(ledger, {"budget_usd": "1", "approval_ref": "fixture", "requests": [old] if unresolved else []})
        state = self.runner.load()
        state["selection_ledger_ref"] = str(ledger.relative_to(self.root))
        self.runner.save(state)
        evidence = self.batch / "evidence/recovery.json"
        response = {"status_code": 20000, "tasks_error": 0, "cost": 0,
                    "tasks": [{"status_code": 20000, "cost": 0, "result": [], "data": {
                        "function": "id_list", "datetime_from": (started - timedelta(minutes=2)).isoformat(),
                        "datetime_to": (started + timedelta(minutes=2)).isoformat()}}]}
        atomic_write_json(evidence, {"fingerprint": old["fingerprint"], "original_started_at": old["started_at"],
                                    "checked_at": stamp().replace("+00:00", "Z"), "retain_original_reservation": True,
                                    "history_lookup": {"endpoint": "/v3/serp/id_list", "response": response}})
        return ledger, evidence

    def test_expansion_preserves_completed_pilot_and_initial_approval(self):
        self.approve(budget="0.8")
        for _ in range(5): self.step()
        self.attach_selection_ledger()
        before = copy.deepcopy(self.runner.load())
        second = before["items"][1]["id"]
        self.runner.expand([second], "explicit new approval", "1")
        after = self.runner.load()
        self.assertEqual(before["production_approval"], after["production_approval"])
        self.assertEqual(before["items"][0], after["items"][0])
        self.assertEqual(before["budget_usd"], after["budget_usd"])
        self.assertEqual(after["items"][1]["status"], "approved")
        self.assertEqual(self.runner.next()["dispatch"]["article_id"], second)

    def test_expansion_does_not_restart_active_dispatch(self):
        self.approve(budget="0.8")
        first = self.runner.next()
        self.attach_selection_ledger()
        self.runner.expand([self.runner.load()["items"][1]["id"]], "approval", "1")
        self.assertEqual(first["dispatch"], self.runner.next()["dispatch"])

    def test_expansion_rejects_unknown_duplicate_started_or_unfunded_scope(self):
        self.approve(budget="0.995")
        self.attach_selection_ledger(unresolved=True)
        ids = [i["id"] for i in self.runner.load()["items"]]
        original = self.runner.file.read_bytes()
        for selected, ref, cap in [(["unknown"], "approval", "1"), ([ids[1], ids[1]], "approval", "1"),
                                   ([ids[0]], "approval", "1"), ([ids[1]], "", "1"),
                                   ([ids[1]], "approval", "1"), ([ids[1]], "approval", "2")]:
            with self.assertRaises(WorkflowError): self.runner.expand(selected, ref, cap)
            self.assertEqual(self.runner.file.read_bytes(), original)

    def prepare_reviewed_reservation(self):
        self.approve(budget="0.8")
        ledger, evidence = self.attach_selection_ledger(unresolved=True)
        self.runner.expand([self.runner.load()["items"][1]["id"]], "batch approval", "1")
        return ledger, evidence

    def test_review_keeps_unknown_cost_and_original_ledger_while_allowing_bounded_collection(self):
        ledger, evidence = self.prepare_reviewed_reservation()
        original = ledger.read_bytes()
        self.runner.review_selection_reservation(evidence, "billing recovery approval")
        summary = self.runner.summary(self.runner.load())
        self.assertFalse(summary["paid_research_blockers"])
        self.assertEqual(summary["selection_accounting"]["unresolved_reserved_usd"], "0.01")
        self.assertEqual(summary["selection_accounting"]["actual_usd"], "0")
        self.assertFalse(summary["selection_accounting"]["actual_is_final"])
        self.runner.next()
        client = FakeAPI()
        self.runner.collect(self.plan(), client=client)
        self.assertEqual(client.calls, 1)
        self.assertEqual(original, ledger.read_bytes())

    def test_review_rejects_failed_nonempty_unrelated_or_unfunded_evidence(self):
        ledger, evidence = self.prepare_reviewed_reservation()
        original = json.loads(evidence.read_text())
        for mutation in ("nonempty", "wrong_window", "wrong_fingerprint", "nonfree", "unapproved"):
            body = copy.deepcopy(original)
            if mutation == "nonempty": body["history_lookup"]["response"]["tasks"][0]["result"] = [{"id": "task"}]
            if mutation == "wrong_window": body["history_lookup"]["response"]["tasks"][0]["data"]["datetime_from"] = stamp()
            if mutation == "wrong_fingerprint": body["fingerprint"] = "other"
            if mutation == "nonfree": body["history_lookup"]["response"]["cost"] = 1
            atomic_write_json(evidence, body)
            with self.assertRaises(WorkflowError):
                self.runner.review_selection_reservation(evidence, "" if mutation == "unapproved" else "approval")
        self.assertNotIn("selection_billing_review", self.runner.load())

    def test_reviewed_evidence_or_ledger_changes_block_paid_calls(self):
        ledger, evidence = self.prepare_reviewed_reservation()
        self.runner.review_selection_reservation(evidence, "approval")
        self.runner.next()
        original = evidence.read_bytes()
        evidence.write_text("{}")
        client = FakeAPI()
        with self.assertRaises(WorkflowError): self.runner.collect(self.plan(), client=client)
        evidence.write_bytes(original)
        data = json.loads(ledger.read_text())
        data["requests"].append(dict(data["requests"][0], fingerprint="new failure"))
        atomic_write_json(ledger, data)
        with self.assertRaises(WorkflowError): self.runner.collect(self.plan(), client=client)
        self.assertEqual(client.calls, 0)

    def test_shared_cap_is_enforced_even_if_production_allocation_changes(self):
        ledger, evidence = self.prepare_reviewed_reservation()
        self.runner.review_selection_reservation(evidence, "approval")
        self.runner.next()
        state = self.runner.load()
        state["budget_usd"] = "2"  # Simulate a mistakenly enlarged local allocation.
        self.runner.save(state)
        plan = self.plan()
        plan["cost_bound_usd"] = "1"
        client = FakeAPI()
        with self.assertRaises(WorkflowError): self.runner.collect(plan, client=client)
        self.assertEqual(client.calls, 0)


if __name__ == "__main__":
    unittest.main()
