from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from seobility_workflow.errors import InvalidTransitionError, ValidationError
from seobility_workflow.gates import apply_gate_evaluation, evaluate_gates
from seobility_workflow.io import atomic_write_json, read_json
from seobility_workflow.runs import create_run, record_draft
from seobility_workflow.state import transition_run
from seobility_workflow.validation import validate_run


SAMPLE = ROOT / "samples" / "runs" / "seobility-vs-ahrefs-demo"


class WorkflowTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def copy_sample(self) -> Path:
        destination = self.root / "sample"
        shutil.copytree(SAMPLE, destination)
        return destination

    def test_create_run_and_enforce_state_machine(self):
        run_dir = create_run(
            self.root,
            topic="Seobility vs Ahrefs",
            page_type="versus",
            language="en",
            market="United States",
            run_id="test-run",
            created_at="2026-08-27T10:00:00Z",
        )
        run = transition_run(
            run_dir,
            "research_ready",
            "Research artifacts exist.",
            "2026-08-27T10:01:00Z",
        )
        self.assertEqual(run["status"], "research_ready")
        with self.assertRaises(InvalidTransitionError):
            transition_run(run_dir, "completed", "Skip all gates.")

    def test_record_first_draft_updates_version_and_hashes(self):
        run_dir = create_run(
            self.root,
            topic="Seobility vs Ahrefs",
            page_type="versus",
            language="en",
            market="United States",
            run_id="draft-run",
            created_at="2026-08-27T10:00:00Z",
        )
        for status in ("research_ready", "evidence_validated", "brief_ready"):
            transition_run(run_dir, status, "Test transition.", "2026-08-27T10:01:00Z")
        (run_dir / "brief" / "content-brief.json").write_text("{}\n", encoding="utf-8")
        (run_dir / "drafts" / "comparison-v1.md").write_text("# Draft\n", encoding="utf-8")
        atomic_write_json(
            run_dir / "drafts" / "comparison-v1.meta.json",
            {
                "schema_version": "1.0",
                "run_id": "draft-run",
                "draft_version": 1,
                "content_path": "drafts/comparison-v1.md",
                "brief_path": "brief/content-brief.json",
                "created_at": "2026-08-27T10:02:00Z",
                "claim_ids_used": [],
                "word_count": 1,
            },
        )
        run = record_draft(run_dir, 1, created_at="2026-08-27T10:03:00Z")
        self.assertEqual(run["status"], "draft_ready")
        self.assertEqual(run["current_draft_version"], 1)
        self.assertEqual(run["revision_count"], 0)
        self.assertEqual(len(run["artifacts"]), 2)
        self.assertTrue(all(item["sha256"] for item in run["artifacts"]))

    def test_sample_passes_cross_artifact_validation(self):
        result = validate_run(SAMPLE)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["verified_claims"], 2)

    def test_unknown_brief_claim_is_rejected(self):
        run_dir = self.copy_sample()
        brief_path = run_dir / "brief" / "content-brief.json"
        brief = read_json(brief_path)
        brief["sections"][0]["claim_ids"].append("UNKNOWN-001")
        atomic_write_json(brief_path, brief)
        with self.assertRaises(ValidationError) as context:
            validate_run(run_dir)
        self.assertIn("Brief references unknown claim: UNKNOWN-001", context.exception.errors)

    def test_failed_first_draft_requests_revision(self):
        run_dir = self.copy_sample()
        run_path = run_dir / "run.json"
        run = read_json(run_path)
        run["status"] = "reviewing"
        run["current_draft_version"] = 1
        run["revision_count"] = 0
        atomic_write_json(run_path, run)

        evaluation = evaluate_gates(run_dir, 1)
        self.assertEqual(evaluation.status, "fail")
        self.assertEqual(evaluation.next_status, "revision_required")
        request_path = apply_gate_evaluation(
            run_dir, evaluation, generated_at="2026-08-27T11:00:00Z"
        )
        self.assertEqual(request_path.name, "revision-request-v1.json")
        self.assertEqual(read_json(run_path)["status"], "revision_required")

    def test_passing_second_draft_awaits_human_approval(self):
        run_dir = self.copy_sample()
        run_path = run_dir / "run.json"
        run = read_json(run_path)
        run["status"] = "reviewing"
        atomic_write_json(run_path, run)

        evaluation = evaluate_gates(run_dir, 2)
        self.assertEqual(evaluation.status, "pass")
        report_path = apply_gate_evaluation(
            run_dir, evaluation, generated_at="2026-08-27T11:00:00Z"
        )
        self.assertEqual(report_path.name, "final-report.json")
        self.assertEqual(read_json(run_path)["status"], "awaiting_human_approval")

    def test_failed_final_allowed_draft_stops_for_human_review(self):
        run_dir = self.copy_sample()
        run_path = run_dir / "run.json"
        run = read_json(run_path)
        run["status"] = "reviewing"
        run["current_draft_version"] = 1
        run["revision_count"] = 0
        run["max_draft_versions"] = 1
        atomic_write_json(run_path, run)

        evaluation = evaluate_gates(run_dir, 1)
        self.assertEqual(evaluation.next_status, "needs_human_review")
        self.assertEqual(evaluation.gate_results["revision_limit"], "fail")
        apply_gate_evaluation(run_dir, evaluation, generated_at="2026-08-27T11:00:00Z")
        self.assertEqual(read_json(run_path)["status"], "needs_human_review")


if __name__ == "__main__":
    unittest.main()
