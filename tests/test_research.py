from __future__ import annotations

import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from seobility_workflow.errors import ValidationError, WorkflowError
from seobility_workflow.io import read_json
from seobility_workflow.research.dataforseo import (
    DataForSEOClient,
    DataForSEOError,
    collect_dataforseo,
    collect_dataforseo_mvp,
    load_dataforseo_env,
    normalize_dataforseo,
    normalize_dataforseo_files,
)
from seobility_workflow.research.policy import (
    materialize_seobility_research,
    validate_product_research,
    validate_research_layer,
)
from seobility_workflow.runs import create_run


FIXTURES = ROOT / "tests" / "fixtures"
SAMPLE = ROOT / "samples" / "runs" / "seobility-vs-ahrefs-demo"
POLICY = read_json(ROOT / "config" / "research-policy.json")


class ResearchLayerTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_dataforseo_normalization_preserves_metrics_serps_and_provenance(self):
        overview = read_json(FIXTURES / "dataforseo" / "keyword-overview.json")
        serp = [
            read_json(FIXTURES / "dataforseo" / "serp-seobility-vs-ahrefs.json"),
            read_json(FIXTURES / "dataforseo" / "serp-ahrefs-alternative.json"),
        ]
        result = normalize_dataforseo(
            "research-test-run",
            overview,
            serp,
            raw_response_paths=["research/raw/keyword.json", "research/raw/serp-01.json"],
            generated_at="2026-08-27T12:00:00Z",
        )
        self.assertEqual(len(result["queries"]), 2)
        self.assertEqual(result["queries"][0]["search_volume"], 90)
        self.assertEqual(result["queries"][0]["results"][0]["domain"], "example.com")
        self.assertEqual(result["provider"]["total_cost"], 0.024)
        self.assertEqual(len(result["related_questions"]), 2)

    def test_dataforseo_normalization_accepts_nested_keyword_overview_items(self):
        overview = {
            "status_code": 20000,
            "status_message": "Ok.",
            "tasks": [
                {
                    "id": "keyword-task-production-shape",
                    "status_code": 20000,
                    "status_message": "Ok.",
                    "cost": 0.01,
                    "result": [
                        {
                            "location_code": 2840,
                            "language_code": "en",
                            "items": [
                                {
                                    "keyword": "website audit tools",
                                    "keyword_info": {
                                        "search_volume": 1300,
                                        "cpc": 27.82,
                                        "competition": 0.13,
                                    },
                                    "search_intent_info": {
                                        "main_intent": "commercial"
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        result = normalize_dataforseo(
            "nested-overview-test",
            overview,
            [],
            generated_at="2026-08-29T12:00:00Z",
        )
        self.assertEqual(len(result["queries"]), 1)
        self.assertEqual(result["queries"][0]["keyword"], "website audit tools")
        self.assertEqual(result["queries"][0]["search_volume"], 1300)
        self.assertEqual(result["queries"][0]["intent"], "commercial")
        self.assertEqual(result["provider"]["normalizer_version"], "1.1")

    def test_fixture_sample_passes_research_policy(self):
        result = validate_research_layer(
            SAMPLE, as_of=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["competitor"]["verified_claims"], 1)

    def test_file_normalization_registers_hashed_artifact_and_wont_overwrite(self):
        run_dir = create_run(
            self.root,
            topic="Seobility vs Ahrefs",
            page_type="versus",
            language="en",
            market="United States",
            run_id="normalization-test",
            data_mode="fixture",
            created_at="2026-08-27T10:00:00Z",
        )
        output = normalize_dataforseo_files(
            run_dir,
            FIXTURES / "dataforseo" / "keyword-overview.json",
            [FIXTURES / "dataforseo" / "serp-seobility-vs-ahrefs.json"],
            provider_name="dataforseo_mcp",
            generated_at="2026-08-27T12:00:00Z",
        )
        self.assertTrue(output.is_file())
        run = read_json(run_dir / "run.json")
        self.assertEqual(run["artifacts"][0]["path"], "research/serp.json")
        self.assertTrue(run["artifacts"][0]["sha256"])
        with self.assertRaises(DataForSEOError):
            normalize_dataforseo_files(
                run_dir,
                FIXTURES / "dataforseo" / "keyword-overview.json",
                [FIXTURES / "dataforseo" / "serp-seobility-vs-ahrefs.json"],
            )

    def test_stale_source_is_rejected(self):
        knowledge = read_json(FIXTURES / "seobility-approved-knowledge-base.json")
        knowledge["sources"][0]["retrieved_at"] = "2026-06-01T00:00:00Z"
        with self.assertRaises(ValidationError) as context:
            validate_product_research(
                knowledge,
                POLICY,
                as_of=datetime(2026, 8, 27, tzinfo=timezone.utc),
            )
        self.assertTrue(any("stale source" in error for error in context.exception.errors))

    def test_sensitive_fact_requires_human_verification(self):
        knowledge = read_json(FIXTURES / "seobility-approved-knowledge-base.json")
        knowledge["claims"][0]["fact_type"] = "pricing"
        knowledge["claims"][0]["verified_by"] = "automated"
        with self.assertRaises(ValidationError) as context:
            validate_product_research(
                knowledge,
                POLICY,
                as_of=datetime(2026, 8, 27, tzinfo=timezone.utc),
            )
        self.assertTrue(any("requires human verification" in error for error in context.exception.errors))

    def test_live_external_source_requires_snapshot_and_hash(self):
        knowledge = read_json(FIXTURES / "seobility-approved-knowledge-base.json")
        source = knowledge["sources"][0]
        source["source_type"] = "official_product_page"
        source["url"] = "https://example.com/product"
        source["internal_reference"] = null = None
        with self.assertRaises(ValidationError) as context:
            validate_product_research(
                knowledge,
                POLICY,
                as_of=datetime(2026, 8, 27, tzinfo=timezone.utc),
            )
        self.assertTrue(any("no retained snapshot" in error for error in context.exception.errors))
        self.assertTrue(any("no content hash" in error for error in context.exception.errors))

    def test_approved_knowledge_base_materializes_run_artifact(self):
        run_dir = create_run(
            self.root,
            topic="Seobility vs Ahrefs",
            page_type="versus",
            language="en",
            market="United States",
            run_id="materialize-test",
            data_mode="live",
            created_at="2026-08-27T10:00:00Z",
        )
        output = materialize_seobility_research(
            run_dir,
            FIXTURES / "seobility-approved-knowledge-base.json",
            policy_path=ROOT / "config" / "research-policy.json",
            generated_at="2026-08-27T12:00:00Z",
        )
        document = read_json(output)
        self.assertEqual(document["run_id"], "materialize-test")
        self.assertEqual(document["subject"]["role"], "seobility")
        self.assertEqual([claim["claim_id"] for claim in document["claims"]], ["SEO-TEST-001"])

    def test_draft_knowledge_base_cannot_materialize(self):
        run_dir = create_run(
            self.root,
            topic="Seobility vs Ahrefs",
            page_type="versus",
            language="en",
            market="United States",
            run_id="draft-kb-test",
            data_mode="live",
            created_at="2026-08-27T10:00:00Z",
        )
        with self.assertRaises(WorkflowError):
            materialize_seobility_research(
                run_dir,
                ROOT / "knowledge" / "seobility" / "knowledge-base.json",
            )

    def test_live_collection_requires_explicit_cost_confirmation(self):
        run_dir = create_run(
            self.root,
            topic="Seobility vs Ahrefs",
            page_type="versus",
            language="en",
            market="United States",
            run_id="cost-confirmation-test",
            data_mode="live",
            created_at="2026-08-27T10:00:00Z",
        )
        with self.assertRaises(DataForSEOError):
            collect_dataforseo(
                run_dir,
                ["seobility vs ahrefs"],
                "United States",
                "en",
                confirm_live_costs=False,
            )

    def test_mvp_live_collection_requires_explicit_cost_confirmation(self):
        run_dir = self.root / "mvp-live-test"
        run_dir.mkdir()
        (run_dir / "input.json").write_text(
            '{"topic":"Seobility vs Ahrefs","market":"United States","language":"en"}',
            encoding="utf-8",
        )
        with self.assertRaises(DataForSEOError):
            collect_dataforseo_mvp(
                run_dir,
                ["seobility vs ahrefs"],
                confirm_live_costs=False,
                env_file=self.root / ".env",
            )

    def test_env_loader_ignores_unrelated_keys(self):
        env_file = self.root / ".env"
        env_file.write_text(
            "DATAFORSEO_LOGIN=test-login\n"
            "DATAFORSEO_PASSWORD='test-password'\n"
            "UNRELATED_KEY=do-not-load\n",
            encoding="utf-8",
        )
        with patch.dict("os.environ", {}, clear=True):
            load_dataforseo_env(env_file)
            import os

            self.assertEqual(os.environ["DATAFORSEO_LOGIN"], "test-login")
            self.assertEqual(os.environ["DATAFORSEO_PASSWORD"], "test-password")
            self.assertNotIn("UNRELATED_KEY", os.environ)

    def test_mvp_sandbox_collection_retains_raw_and_normalized_data(self):
        run_dir = self.root / "mvp-sandbox-test"
        run_dir.mkdir()
        (run_dir / "input.json").write_text(
            '{"topic":"Seobility vs Ahrefs","market":"United States","language":"en"}',
            encoding="utf-8",
        )
        env_file = self.root / ".env"
        env_file.write_text(
            "DATAFORSEO_LOGIN=test-login\nDATAFORSEO_PASSWORD=test-password\n",
            encoding="utf-8",
        )
        overview = read_json(FIXTURES / "dataforseo" / "keyword-overview.json")
        serp_payloads = [
            read_json(FIXTURES / "dataforseo" / "serp-seobility-vs-ahrefs.json"),
            read_json(FIXTURES / "dataforseo" / "serp-ahrefs-alternative.json"),
        ]
        with patch.dict("os.environ", {}, clear=True), patch.object(
            DataForSEOClient, "keyword_overview", return_value=overview
        ), patch.object(
            DataForSEOClient, "serp_live_advanced", side_effect=serp_payloads
        ):
            output = collect_dataforseo_mvp(
                run_dir,
                ["seobility vs ahrefs", "ahrefs alternative"],
                sandbox=True,
                env_file=env_file,
                generated_at="2026-08-29T10:00:00Z",
            )
        document = read_json(output)
        self.assertEqual(document["provider"]["mode"], "sandbox")
        self.assertEqual(document["request"]["depth"], 10)
        self.assertEqual(document["request"]["location_name"], "United States")
        self.assertEqual(len(document["provider"]["raw_response_paths"]), 3)
        for relative_path in document["provider"]["raw_response_paths"]:
            self.assertTrue((run_dir / relative_path).is_file())


if __name__ == "__main__":
    unittest.main()
