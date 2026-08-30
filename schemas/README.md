# JSON contracts

These files use JSON Schema Draft 2020-12. `common.schema.json` contains shared definitions; all other schemas reference it with a relative `$ref`.

## Artifact mapping

| Artifact | Schema |
|---|---|
| `run.json` | `run.schema.json` |
| `research/serp.json` | `serp-research.schema.json` |
| `research/competitor.json` | `product-research.schema.json` |
| `research/seobility.json` | `product-research.schema.json` |
| `brief/content-brief.json` | `content-brief.schema.json` |
| `drafts/*.meta.json` | `draft-metadata.schema.json` |
| `qa/fact-check-*.json` | `fact-check.schema.json` |
| `qa/seo-review-*.json` | `seo-review.schema.json` |
| `qa/quality-review-*.json` | `quality-review.schema.json` |
| `qa/revision-request-*.json` | `revision-request.schema.json` |
| `qa/final-report.json` | `final-report.schema.json` |
| `approval.json` | `human-approval.schema.json` |
| `publish/result.json` | `publish-result.schema.json` |
| `config/research-policy.json` | `research-policy.schema.json` |
| `knowledge/*/knowledge-base.json` | `knowledge-base.schema.json` |

Cross-file rules—such as every claim reference resolving to a verified evidence record—cannot be fully enforced by JSON Schema. They belong in the workflow validator.

## Validation

Install the optional development dependency and run:

```bash
python3 -m pip install -r requirements-dev.txt
python3 scripts/validate_sample.py
```

Without `jsonschema`, the script still checks JSON syntax, local `$ref` targets, artifact paths, claim/source references, score totals, gate outcomes, and version invariants. With it installed, the script also validates every sample instance against Draft 2020-12.
