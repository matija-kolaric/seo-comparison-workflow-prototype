from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
import shutil
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from seobility_workflow.topic_selection import select_topics, SelectionError, query_pair, render_report, distinct_serp_results
from seobility_workflow.selection_collection import collect_selection, request_for, normalized_rows, reconcile_missing_result, validate_collection_ledger, selection_cost_summary

NOW = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
SAMPLE = ROOT / "samples/topic-selection"


class TopicSelectionTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((SAMPLE / "assessment.json").read_text())

    def run_selection(self, data=None):
        return select_topics(data or self.data, SAMPLE, NOW)

    def test_scores_maximum_not_sum_and_alternatives_excluded(self):
        q = self.run_selection()
        self.assertEqual(len(q["selected"]), 1)
        self.assertEqual(q["selected"][0]["comparison_volume_proxy"], 90)
        self.assertEqual(q["selected"][0]["score"], 82.5)
        self.assertEqual(q["shortfall"], 4)
        self.assertEqual(q["selected"][0]["input"]["page_type"], "versus")
        self.assertFalse(q["production_authorized"])
        self.assertFalse(q["publication_authorized"])
        self.assertIn("not_equivalent_comparison", str(q["selected"][0]["excluded_metrics"]))

    def test_reversed_pair_aliases(self):
        self.assertEqual(query_pair("SEM RUSH vs. SEO BILITY"), ("semrush", "seobility"))
        self.assertIsNone(query_pair("seobility alternatives"))

    def test_zero_and_unknown_are_different_and_do_not_force_rejection(self):
        c = self.data["candidates"][0]
        c["metrics"] = []
        q = self.run_selection()
        self.assertEqual(q["selected"][0]["dimension_ratings"]["demand"], 0)
        self.assertIsNone(q["selected"][0]["comparison_volume_proxy"])
        c["metrics"] = copy.deepcopy(json.loads((SAMPLE / "assessment.json").read_text())["candidates"][0]["metrics"][:1])
        c["metrics"][0]["search_volume"] = 0
        self.assertEqual(self.run_selection()["selected"][0]["dimension_ratings"]["demand"], 1)

    def test_low_confidence_is_never_upgraded(self):
        c = self.data["candidates"][0]
        c["confidence"] = "low"
        c["metrics"] = []
        self.assertEqual(self.run_selection()["selected"], [])

    def test_alternatives_never_become_primary_or_secondary_targets(self):
        c = self.data["candidates"][0]
        c["secondary_keywords"].append("seobility alternatives")
        self.assertNotIn("seobility alternatives", self.run_selection()["selected"][0]["secondary_keywords"])
        c["primary_keyword"] = "seobility alternatives"
        self.assertFalse(self.run_selection()["selected"])

    def test_cpc_does_not_change_ranking_score(self):
        before = self.run_selection()["selected"][0]["score"]
        for row in self.data["candidates"][0]["metrics"]:
            row["cpc"] = 999999
        self.assertEqual(before, self.run_selection()["selected"][0]["score"])

    def test_wrong_market_stale_future_and_mixed_period_metrics_ignored(self):
        for change in [{"market": "Germany"}, {"retrieved_at": "2026-08-01T00:00:00Z"}, {"retrieved_at": "2026-09-30T00:00:00Z"}]:
            data = copy.deepcopy(self.data)
            for row in data["candidates"][0]["metrics"]:
                row.update(change)
            self.assertIsNone(self.run_selection(data)["selected"][0]["comparison_volume_proxy"])
        self.data["candidates"][0]["metrics"][0]["period"] = "different"
        self.assertIsNone(self.run_selection()["selected"][0]["comparison_volume_proxy"])

    def test_incomplete_stale_duplicate_and_wrong_query_serps_hold(self):
        for kind in ["short", "stale", "duplicate", "query"]:
            data = copy.deepcopy(self.data)
            s = data["candidates"][0]["serp"]
            if kind == "short": s["results"].pop()
            if kind == "stale": s["retrieved_at"] = "2026-08-01T00:00:00Z"
            if kind == "duplicate": s["results"][0]["url"] = s["results"][1]["url"]
            if kind == "query": s["keyword"] = "seobility alternatives"
            self.assertEqual(self.run_selection(data)["selected"], [], kind)

    def test_missing_official_opened_page_conflict_and_gap_threshold(self):
        for field, value in [("official_sources", []), ("page_observations", []), ("unresolved_conflicts", ["unresolved intent"] )]:
            data = copy.deepcopy(self.data)
            data["candidates"][0][field] = value
            self.assertFalse(self.run_selection(data)["selected"])
        self.data["candidates"][0]["ratings"]["gap"]["value"] = 1
        self.assertFalse(self.run_selection()["selected"])

    def test_missing_and_outside_evidence_cannot_pass(self):
        for ref in ["evidence/missing.md", "../README.md", "/etc/passwd"]:
            self.data["candidates"][0]["ratings"]["gap"]["evidence_refs"] = [ref]
            self.assertFalse(self.run_selection()["selected"])

    def test_existing_queued_and_duplicate_candidates_not_selected_twice(self):
        c = self.data["candidates"][0]
        duplicate = copy.deepcopy(c)
        duplicate.update(id="reverse", products=list(reversed(c["products"])))
        self.data["candidates"].append(duplicate)
        self.assertEqual(len(self.run_selection()["selected"]), 1)
        self.data["inventory"].append({"products": c["products"], "status": "selected"})
        self.assertFalse(self.run_selection()["selected"])

    def test_top_five_reserves_and_order_independent_ties(self):
        c = self.data["candidates"][0]
        candidates = []
        for letter in "gfedcba":
            serialized = json.dumps(c).replace("Example Audit", "Example " + letter).replace("example audit", "example " + letter)
            row = json.loads(serialized)
            row["id"] = "example-" + letter
            candidates.append(row)
        self.data["candidates"] = candidates
        q = self.run_selection()
        self.assertEqual(len(q["selected"]), 5)
        self.assertEqual(len(q["reserves"]), 2)
        self.assertEqual(q["selected"][0]["id"], "example-a")
        self.data["candidates"].reverse()
        self.assertEqual([c["id"] for c in q["selected"]], [c["id"] for c in self.run_selection()["selected"]])

    def test_invalid_ratings_and_limits_fail_closed(self):
        self.data["candidates"][0]["ratings"]["gap"]["value"] = True
        with self.assertRaises(SelectionError): self.run_selection()
        self.data["candidates"] = [self.data["candidates"][0]] * 21
        with self.assertRaises(SelectionError): self.run_selection()

    def test_report_is_labeled_fixture_and_explains_shortfall(self):
        report = render_report(self.run_selection())
        self.assertIn("**fixture**", report)
        self.assertIn("Shortfall: 4", report)
        self.assertIn("Awaiting human review", report)


class RevisedSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copytree(SAMPLE / "evidence", self.root / "evidence")
        self.data = json.loads((SAMPLE / "assessment.json").read_text())
        self.data.update(policy_version="0.2", target_count=6, scope_approval_ref="user six topics")
        self.data["candidates"] = self.data["candidates"][:1]
        self.serp = self.data["candidates"][0]["serp"]
        self.serp["source_ref"] = "evidence/serp.json"
        rows = [{"type": "organic", "rank_group": r["rank"], "url": r["url"]} for r in self.serp["results"]]
        # A duplicate occupies rank 10; original rank 11 is the tenth distinct page.
        rows.insert(9, dict(rows[8], rank_group=10))
        rows[10]["rank_group"] = 11
        self.raw = {"data_mode": "fixture", "endpoint": "/v3/serp/google/organic/live/advanced",
                    "retrieved_at": self.serp["retrieved_at"], "request": {"keyword": self.serp["keyword"],
                    "location_name": "United States", "language_code": "en", "device": "desktop", "depth": 20},
                    "response": {"status_code": 20000, "tasks": [{"status_code": 20000, "result": [{"items": rows}]}]}}
        self.write_raw()
        self.serp["results"], _ = distinct_serp_results(self.serp, self.root, "fixture")

    def tearDown(self):
        self.temp.cleanup()

    def write_raw(self):
        (self.root / "evidence/serp.json").write_text(json.dumps(self.raw))

    def test_duplicate_warning_preserves_original_rank_and_six_target(self):
        q = select_topics(self.data, self.root, NOW)
        self.assertEqual(q["target_count"], 6)
        self.assertEqual(q["shortfall"], 5)
        self.assertEqual(q["selected"][0]["serp"]["results"][-1]["rank"], 11)
        self.assertEqual(q["selected"][0]["serp_duplicate_rows"][0]["rank"], 10)
        self.assertFalse(q["production_authorized"])

    def test_renumbering_or_skipping_a_unique_result_cannot_pass(self):
        self.serp["results"][-1]["rank"] = 10
        self.assertFalse(select_topics(self.data, self.root, NOW)["selected"])
        self.serp["results"][-1]["rank"] = 11
        self.raw["response"]["tasks"][0]["result"][0]["items"][9]["url"] = "https://example.com/different"
        self.write_raw()
        self.assertFalse(select_topics(self.data, self.root, NOW)["selected"])

    def test_short_and_wrong_snapshot_and_missing_approval_fail(self):
        for field, value in [("retrieved_at", "2026-08-29T00:00:00Z"), ("data_mode", "live")]:
            original = self.raw[field]
            self.raw[field] = value
            self.write_raw()
            self.assertFalse(select_topics(self.data, self.root, NOW)["selected"])
            self.raw[field] = original
        self.raw["response"]["tasks"][0]["result"][0]["items"].pop()
        self.write_raw()
        self.assertFalse(select_topics(self.data, self.root, NOW)["selected"])
        self.data.pop("scope_approval_ref")
        with self.assertRaises(SelectionError): select_topics(self.data, self.root, NOW)


class FakeClient:
    def __init__(self, payload=None, fail=False):
        self.calls = 0
        self.fail = fail
        self.payload = payload or {"status_code": 20000, "cost": 0.02, "tasks": [{"status_code": 20000, "cost": 0.02, "result": [{"items": [{"keyword": "seobility vs example", "keyword_info": {"search_volume": 20, "monthly_searches": [{"year": 2026, "month": 7, "search_volume": 20}]}}]}]}]}

    def post(self, endpoint, tasks):
        self.calls += 1
        if self.fail: raise TimeoutError("private transport diagnostic must not be printed")
        return self.payload


class SelectionCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.run = Path(self.temp.name)
        self.plan = {"operation": "suggestions", "keyword": "seobility vs", "limit": 20,
                     "cost_bound_usd": "0.03", "pricing_source": "https://dataforseo.com/pricing",
                     "pricing_checked_at": NOW.isoformat()}
        self.client = FakeClient()

    def tearDown(self):
        self.temp.cleanup()

    def collect(self, **kwargs):
        args = dict(plan=self.plan, run_dir=self.run, budget_usd="1", approval_ref="fixture approval", confirm_live=True, client=self.client, now=NOW)
        args.update(kwargs)
        return collect_selection(**args)

    def test_requests_are_bounded_and_no_unknown_endpoint_or_scope(self):
        endpoint, task = request_for(self.plan)
        self.assertIn("keyword_suggestions", endpoint)
        self.assertEqual(task["location_name"], "United States")
        self.assertFalse(task["include_clickstream_data"])
        for changes in [{"operation": "llm"}, {"limit": 1000}, {"location_name": "Germany"}]:
            with self.assertRaises(SelectionError): request_for(dict(self.plan, **changes))
        endpoint, task = request_for({"operation": "overview", "keywords": ["seobility vs example"]})
        self.assertIn("keyword_overview", endpoint)
        self.assertEqual(task["keywords"], ["seobility vs example"])
        endpoint, task = request_for({"operation": "serp", "keyword": "seobility vs example"})
        self.assertEqual(task["depth"], 10)

    def test_no_approval_or_budget_means_no_call(self):
        for changes in [{"confirm_live": False}, {"approval_ref": ""}, {"budget_usd": "0.01"}]:
            with self.assertRaises(SelectionError): self.collect(**changes)
        self.assertEqual(self.client.calls, 0)

    def test_offline_revision_cannot_open_a_new_spending_ledger(self):
        (self.run / "evidence").mkdir()
        (self.run / "evidence/source-ledger.json").write_text("{}")
        with self.assertRaisesRegex(SelectionError, "Offline review snapshot"):
            self.collect()
        self.assertFalse((self.run / "evidence/collection-ledger.json").exists())
        self.assertEqual(self.client.calls, 0)

    def test_depth_twenty_is_bounded_and_not_a_depth_ten_cache_hit(self):
        p = dict(self.plan, operation="serp", depth=20)
        self.assertEqual(request_for(p)[1]["depth"], 20)
        for depth in [True, 0, 11, 30, 100]:
            with self.assertRaises(SelectionError): request_for(dict(p, depth=depth))
        with self.assertRaises(SelectionError): request_for(dict(self.plan, depth=20))
        first = self.collect(plan=dict(p, depth=10))
        second = self.collect(plan=p)
        self.assertNotEqual(first, second)
        self.assertEqual(self.client.calls, 2)

    def prepare_reconciliation(self):
        self.plan.update(operation="serp", keyword="seobility vs example")
        with self.assertRaises(SelectionError): self.collect(client=FakeClient(fail=True), budget_usd="0.04")
        endpoint, task = request_for(self.plan)
        evidence = {"history_lookup": {"response": {"status_code": 20000, "tasks_error": 0, "tasks": [{"result": [{
            "id": "fixture-task", "url": endpoint, "metadata": task, "status": 20000,
            "datetime_posted": NOW.isoformat(), "cost": 0.02}]}]}}}
        path = self.run / "evidence/reconciliation.json"
        path.write_text(json.dumps(evidence))
        return path, evidence

    def test_reconciled_missing_result_counts_cost_never_hits_cache_and_one_replacement(self):
        self.prepare_reconciliation()
        reconcile_missing_result(self.run, self.plan, "evidence/reconciliation.json", "user resume approval")
        ledger_path = self.run / "evidence/collection-ledger.json"
        ledger = json.loads(ledger_path.read_text())
        self.assertEqual(ledger["requests"][0]["state"], "billed_missing_result")
        self.assertNotIn("filename", ledger["requests"][0])
        # Existing 0.02 charge + 0.03 reservation exceeds the original 0.04 cap.
        with self.assertRaises(SelectionError): self.collect(budget_usd="0.04")
        self.assertEqual(self.client.calls, 0)
        p = dict(self.plan, cost_bound_usd="0.02", depth=20)
        self.client.payload["cost"] = 0.01
        self.client.payload["tasks"][0]["cost"] = 0.01
        self.collect(budget_usd="0.04", plan=p)
        self.assertEqual(self.client.calls, 1)
        # Valid cache reuse remains free, but a second replacement cannot be posted.
        self.collect(budget_usd="0.04", plan=p)
        # This reservation fits the remaining budget: the replacement gate must block it.
        with self.assertRaisesRegex(SelectionError, "replacement already attempted"):
            self.collect(budget_usd="0.04", plan=dict(p, depth=10, cost_bound_usd="0.005"))
        self.assertEqual(self.client.calls, 1)

    def test_reconciliation_requires_matching_evidence_and_approval(self):
        path, evidence = self.prepare_reconciliation()
        with self.assertRaises(SelectionError): reconcile_missing_result(self.run, self.plan, "evidence/reconciliation.json", "")
        evidence["history_lookup"]["response"]["tasks"][0]["result"][0]["metadata"]["keyword"] = "wrong pair"
        path.write_text(json.dumps(evidence))
        with self.assertRaises(SelectionError): reconcile_missing_result(self.run, self.plan, "evidence/reconciliation.json", "approval")
        self.assertEqual(json.loads((self.run / "evidence/collection-ledger.json").read_text())["requests"][0]["state"], "unresolved")

    def test_changed_reconciliation_blocks_spend_and_ranking(self):
        path, evidence = self.prepare_reconciliation()
        reconcile_missing_result(self.run, self.plan, "evidence/reconciliation.json", "approval")
        path.write_text("{}")
        with self.assertRaises(SelectionError): self.collect(budget_usd="0.04")
        with self.assertRaises(SelectionError): validate_collection_ledger(json.loads((self.run / "evidence/collection-ledger.json").read_text()), self.run)

    def test_failure_diagnostics_do_not_store_private_message(self):
        self.prepare_reconciliation()
        content = (self.run / "evidence/collection-ledger.json").read_text()
        self.assertNotIn("private transport", content)
        self.assertEqual(json.loads(content)["requests"][0]["error_type"], "TimeoutError")

    def prepare_transport_retry(self):
        self.prepare_reconciliation()
        path = self.run / "evidence/collection-ledger.json"
        ledger = json.loads(path.read_text())
        ledger["requests"][0]["cause_type"] = "URLError"
        path.write_text(json.dumps(ledger))
        review = {"fingerprint": ledger["requests"][0]["fingerprint"],
                  "original_started_at": NOW.isoformat(), "reviewed_at": NOW.isoformat(),
                  "approval_ref": "explicit one retry", "allow_one_extra_serp_attempt": True,
                  "retain_original_reservation": True,
                  "history_lookup": {"response": {"status_code": 20000, "tasks_error": 0, "cost": 0,
                    "tasks": [{"status_code": 20000, "result": [], "data": {"function": "id_list",
                      "datetime_from": (NOW - timedelta(minutes=1)).isoformat(), "datetime_to": NOW.isoformat()}}]}}}
        (self.run / "evidence/retry.json").write_text(json.dumps(review))
        return path, review

    def test_approved_transport_retry_keeps_reservation_and_cannot_repeat(self):
        path, _ = self.prepare_transport_retry()
        with self.assertRaisesRegex(SelectionError, "exceed approved budget"):
            self.collect(budget_usd="0.04", retry_evidence_ref="evidence/retry.json")
        self.client.payload["cost"] = 0.005
        self.client.payload["tasks"][0]["cost"] = 0.005
        self.collect(budget_usd="0.04", plan=dict(self.plan, cost_bound_usd="0.01"), retry_evidence_ref="evidence/retry.json")
        ledger = json.loads(path.read_text())
        self.assertEqual(ledger["requests"][0]["state"], "unresolved")
        self.assertNotIn("actual_cost_usd", ledger["requests"][0])
        self.assertEqual(ledger["requests"][1]["actual_cost_usd"], "0.005")
        self.assertEqual(ledger["requests"][1]["retry_of"], NOW.isoformat())
        with self.assertRaises(SelectionError): self.collect(budget_usd="0.04", retry_evidence_ref="evidence/retry.json")
        with self.assertRaises(SelectionError): validate_collection_ledger(ledger, self.run)
        self.assertEqual(self.client.calls, 1)

    def test_transport_retry_rejects_wrong_scope_and_missing_review(self):
        self.prepare_transport_retry()
        for kwargs in [{}, {"retry_evidence_ref": "evidence/retry.json", "plan": dict(self.plan, keyword="wrong query")},
                       {"retry_evidence_ref": "../retry.json"}]:
            with self.assertRaises(SelectionError): self.collect(budget_usd="0.04", **kwargs)
        self.assertEqual(self.client.calls, 0)

    def test_offline_cost_report_preserves_unresolved_billing_and_collection_stop(self):
        path, _ = self.prepare_transport_retry()
        ledger = json.loads(path.read_text())
        before = path.read_bytes()
        summary = selection_cost_summary(ledger, self.run)
        self.assertEqual(summary["actual_usd"], "0")
        self.assertEqual(summary["unresolved_reserved_usd"], "0.03")
        self.assertFalse(summary["actual_is_final"])
        self.assertTrue(summary["further_collection_blocked"])
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(SelectionError): validate_collection_ledger(ledger, self.run)
        with self.assertRaises(SelectionError): self.collect(budget_usd="0.04")

    def test_transport_retry_allows_only_one_extra_serp_slot(self):
        path, _ = self.prepare_transport_retry()
        ledger = json.loads(path.read_text())
        complete = {"operation": "serp", "state": "complete", "actual_cost_usd": "0",
                    "fingerprint": "other"}
        ledger["requests"] = [dict(complete) for _ in range(10)] + ledger["requests"]
        path.write_text(json.dumps(ledger))
        p = dict(self.plan, cost_bound_usd="0.01")
        with self.assertRaisesRegex(SelectionError, "SERP limit"):
            self.collect(budget_usd="0.04", plan=p, retry_evidence_ref="evidence/retry.json")
        ledger["requests"].pop(0)
        path.write_text(json.dumps(ledger))
        self.client.payload["cost"] = 0.005
        self.client.payload["tasks"][0]["cost"] = 0.005
        self.collect(budget_usd="0.04", plan=p, retry_evidence_ref="evidence/retry.json")
        self.assertEqual(len(json.loads(path.read_text())["requests"]), 11)
        self.assertEqual(self.client.calls, 1)

    def test_current_pricing_and_finite_bound_required(self):
        for changes in [{"cost_bound_usd": "NaN"}, {"cost_bound_usd": "-1"}, {"pricing_checked_at": "2020-01-01T00:00:00Z"}]:
            with self.assertRaises(SelectionError): self.collect(plan=dict(self.plan, **changes))
        self.assertEqual(self.client.calls, 0)

    def test_cache_reuses_without_refreshing_collection_date_or_cost(self):
        path = self.collect()
        cached = self.collect(now=NOW + timedelta(days=1))
        self.assertEqual(path, cached)
        self.assertEqual(self.client.calls, 1)
        envelope = json.loads(path.read_text())
        self.assertEqual(envelope["retrieved_at"], NOW.isoformat())
        self.assertEqual(envelope["data_mode"], "fixture")
        ledger = json.loads((self.run / "evidence/collection-ledger.json").read_text())
        self.assertEqual(ledger["requests"][0]["actual_cost_usd"], "0.02")
        self.assertEqual(len(ledger["requests"][0]["reused_at"]), 1)
        self.assertEqual(envelope["rows"][0]["keyword_info"]["monthly_searches"][0]["search_volume"], 20)

    def test_stale_cache_recollects_within_cap_and_preserves_old_response(self):
        first = self.collect()
        future = NOW + timedelta(days=8)
        second = self.collect(now=future, plan=dict(self.plan, pricing_checked_at=future.isoformat()))
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists())
        self.assertEqual(self.client.calls, 2)

    def test_changed_request_does_not_reuse_cache(self):
        self.collect()
        self.collect(plan=dict(self.plan, keyword="seobility alternatives"))
        self.assertEqual(self.client.calls, 2)

    def test_modified_cache_rejected_without_network(self):
        path = self.collect()
        path.write_text("{}")
        with self.assertRaises(SelectionError): self.collect()
        self.assertEqual(self.client.calls, 1)

    def test_reservation_is_written_before_call_and_timeout_blocks_resume(self):
        outer = self
        class Interrupted(FakeClient):
            def post(self, endpoint, tasks):
                ledger = json.loads((outer.run / "evidence/collection-ledger.json").read_text())
                outer.assertEqual(ledger["requests"][0]["state"], "pending")
                return super().post(endpoint, tasks)
        broken = Interrupted(fail=True)
        with self.assertRaises(SelectionError): self.collect(client=broken)
        with self.assertRaises(SelectionError): self.collect()
        self.assertEqual(self.client.calls, 0)

    def test_billed_overrun_and_missing_cost_halt_next_call(self):
        self.client.payload["cost"] = 2
        with self.assertRaises(SelectionError): self.collect()
        with self.assertRaises(SelectionError): self.collect()
        self.assertEqual(self.client.calls, 1)

    def test_missing_cost_and_failed_task_cannot_resume(self):
        for payload in [
            {"status_code": 20000, "tasks": [{"status_code": 20000, "result": []}]},
            {"status_code": 20000, "cost": 0.01, "tasks": [{"status_code": 40000, "cost": 0.01, "result": []}]}]:
            with tempfile.TemporaryDirectory() as folder:
                fake = FakeClient(payload)
                with self.assertRaises(SelectionError): self.collect(run_dir=Path(folder), client=fake)
                with self.assertRaises(SelectionError): self.collect(run_dir=Path(folder), client=fake)
                self.assertEqual(fake.calls, 1)

    def test_accumulated_cost_and_serp_limit(self):
        self.collect(budget_usd="0.04")
        with self.assertRaises(SelectionError):
            self.collect(budget_usd="0.04", plan=dict(self.plan, keyword="new query"))
        self.assertEqual(self.client.calls, 1)
        with tempfile.TemporaryDirectory() as folder:
            fake = FakeClient()
            for i in range(10):
                p = dict(self.plan, operation="serp", keyword="seobility vs tool " + str(i))
                self.collect(run_dir=Path(folder), client=fake, plan=p)
            with self.assertRaises(SelectionError):
                self.collect(run_dir=Path(folder), client=fake, plan=dict(p, keyword="seobility vs tool 11"))
            self.assertEqual(fake.calls, 10)

    def test_lock_blocks_other_writers(self):
        (self.run / ".selection-collection.lock").touch()
        with self.assertRaises(SelectionError): self.collect()
        self.assertEqual(self.client.calls, 0)

    def test_budget_and_approval_cannot_change_on_resume(self):
        self.collect()
        with self.assertRaises(SelectionError): self.collect(budget_usd="2")
        with self.assertRaises(SelectionError): self.collect(approval_ref="different")
        self.assertEqual(self.client.calls, 1)

    def test_normalizer_retains_seed_and_does_not_invent_metrics(self):
        p = {"tasks": [{"result": [{"seed_keyword_data": {"keyword": "seed"}, "items": [{"keyword": "seed vs other"}]}]}]}
        rows = normalized_rows(p)
        self.assertEqual(len(rows), 2)
        self.assertNotIn("search_volume", rows[0])


class SelectionCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="selection-test-", dir=str(ROOT / "runs"))
        self.run = Path(self.temp.name)
        shutil.copytree(SAMPLE / "evidence", self.run / "evidence")
        self.assessment = self.run / "evidence/assessment.json"
        now = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.assessment.write_text((SAMPLE / "assessment.json").read_text().replace("2026-08-30T00:00:00Z", now))
        self.cli = ROOT / "skills/comparison-topic-selection/scripts/select_topics.py"

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *args):
        return subprocess.run([sys.executable, str(self.cli), *map(str, args)], capture_output=True, text=True, cwd=ROOT)

    def test_rank_creates_review_only_outputs_and_never_overwrites(self):
        result = self.invoke("rank", self.assessment, "--run-dir", self.run)
        self.assertEqual(result.returncode, 0, result.stderr)
        content = (self.run / "queue.json").read_bytes()
        self.assertFalse(json.loads(content)["production_authorized"])
        result = self.invoke("rank", self.assessment, "--run-dir", self.run)
        self.assertEqual(result.returncode, 1)
        self.assertEqual((self.run / "queue.json").read_bytes(), content)

    def test_collect_defaults_to_dry_run_without_loading_env(self):
        request = self.run / "evidence/request.json"
        request.write_text(json.dumps({"operation": "suggestions", "keyword": "seobility vs"}))
        result = self.invoke("collect", request, "--run-dir", self.run, "--env-file", "/nonexistent/credentials.env")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["api_calls"], 0)
        self.assertFalse((self.run / "evidence/collection-ledger.json").exists())

    def test_refuses_website_output_and_live_without_ledger(self):
        result = self.invoke("rank", self.assessment, "--run-dir", ROOT / "website")
        self.assertEqual(result.returncode, 1)
        data = json.loads(self.assessment.read_text())
        data["data_mode"] = "live"
        self.assessment.write_text(json.dumps(data))
        result = self.invoke("rank", self.assessment, "--run-dir", self.run)
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.run / "queue.json").exists())


if __name__ == "__main__":
    unittest.main()
