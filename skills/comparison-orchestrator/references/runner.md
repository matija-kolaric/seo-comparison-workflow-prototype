# Runner commands and handoffs

Run from the project root. No package installation or additional model key is needed. `next` emits work instructions for the active assistant; it does not generate research or prose by itself.

```bash
python3 scripts/orchestrate.py init runs/orchestration-2026-08-30 --queue runs/selection-2026-08-30-live-02/queue.json --selection-approval "actual user queue confirmation"
python3 scripts/orchestrate.py status runs/orchestration-2026-08-30
python3 scripts/orchestrate.py next runs/orchestration-2026-08-30
```

Only after actual production approval, use `approve` with `--article <selected-id>` (repeat for several), or `--all`, plus `--budget-usd <approved-total>` and `--approval-ref <actual-approval>`. Omitting article/all approves the first selected article only. Approval is recorded once; changing scope/budget is a human decision, not an automatic overwrite. Initializing creates only `batch.json`, no article inputs. `next` creates an approved article's input just before dispatch.

### Expand after an approved pilot

Use `expand <batch> --article <new-selected-id>` (repeat per newly approved article), `--approval-ref <actual-user-approval>` and `--aggregate-budget-usd <existing-total-cap>`. This appends approval history, leaves the pilot and its initial approval unchanged, and only changes the new items from selected to approved. It rejects started/unknown/duplicate articles. The existing production budget remains one allocation shared by all approved articles, not a per-article allowance. Selection spend plus unresolved reservations plus this allocation must fit within the original cap; collection also checks the combined cap before each request. Do not collect concurrently through the old selection workflow.

### Explicit recovery with an unknown charge still reserved

When the user asks to fix the selection billing hold and continue, first inspect provider evidence through the free `/v3/serp/id_list` endpoint. A matching task with actual billing should follow the selection reconciliation procedure. A successful empty lookup does **not** prove the failed request cost zero.

For one transport-only SERP failure (URLError, no local response, no reported cost), `review-selection-reservation <batch> --evidence <batch/evidence/recovery.json> --approval-ref <actual-user-approval>` can authorize continued production while retaining its entire positive reservation. This requires a shared-cap expansion, no other unresolved selection entries, and sufficient funding of the full reservation. No new retry is authorized. The original ledger remains unchanged and the old selection collector remains blocked.

The evidence JSON identifies `fingerprint`, `original_started_at`, current timezone-aware `checked_at`, `retain_original_reservation: true`, and `history_lookup` with `endpoint: /v3/serp/id_list` and the actual raw `response`. The free successful empty response must cover the failed request in a completed time window of at least two minutes. Do not invent history results. Evidence and original ledger hashes are pinned; any later change stops new paid calls for review. Report actual spend and held reservation separately, never call the billing final or reconciled. Other failures keep the ordinary stop.

## Receipt

Each stage writes a new receipt inside its article directory, for example `handoffs/research-1.json`. Preserve receipts; changing a passed receipt or output invalidates resume. Use the exact `dispatch` object and `required_checks` returned by `next`:

```json
{
  "dispatch": {"article_id": "...", "stage": "research", "revision": 0, "input_hashes": {}, "dispatched_at": "..."},
  "passed": true,
  "checks": {"priority_serps_complete_or_limitations_explicit": true, "official_product_evidence": true, "reviews_qualified": true, "coverage_and_gaps_prioritized": true},
  "files": {"research/research.md": "sha256", "research/serp-analysis.md": "sha256", "research/claims.json": "sha256"},
  "notes": "Specific review findings, material limitations and any approved fallback."
}
```

This is the receipt shape, not a ready-to-submit approval. Hash actual files after review (`shasum -a 256 <file>`); copy exact dispatch inputs rather than the empty illustrative values. Include all required outputs returned by `next`, and local source captures/assets relied on by the handoff. Paths are relative to the article directory. Include screenshot image hashes during the assets handoff. Non-QA failures may omit output hashes when outputs are incomplete; failed QA still requires valid `qa.json` and its hash.

```bash
python3 scripts/orchestrate.py complete runs/orchestration-2026-08-30 --receipt runs/orchestration-2026-08-30/articles/<article-id>/handoffs/<stage>-1.json
```

Receipts must use unique filenames by stage/revision. The runner checks the QA JSON format defined in `skills/comparison-qa/references/qa-format.md`. A false pass flag or failed score threshold causes one revision, then a stop. Merely setting `passed: true` cannot override score or unsupported-claim blockers. The writer draft must retain supported `<!-- claims: ID -->` references.

After a failed nonterminal handoff is resolved, `resume --approval-ref <actual-human-review> --reason <resolution>` restarts that stage. It cannot override modified earlier artifacts or unlock another automatic revision after the second QA failure. These require an explicit editorial/recovery decision; do not delete history or reset the batch.

## Paid research

Prepare a one-request plan using the supported selection request shape: `operation`, query/keywords, optional `depth` 10/20 or suggestions `limit`, `cost_bound_usd`, official HTTPS `pricing_source` and actual `pricing_checked_at`. Then:

```bash
python3 scripts/orchestrate.py collect runs/orchestration-2026-08-30 --plan <request-plan.json> --confirm-live-costs --env-file .env
```

The batch has its own production allocation. After a shared-cap expansion, this is also constrained by the combined selection-plus-production cap (including reviewed reservations). One command sends at most one request; a batch has at most 60 new requests. A matching fresh cached request has no additional charge and retains its retrieval time. Original source evidence can also be reused without a call after scope/freshness review. Do not increase depth or query scope to work around missing evidence without checking budget and relevance.

Reservations and actual costs live in `batch.json`; provider responses live under the active article's `research/raw/`. A failed/ambiguous request blocks future calls and holds its reservation; no automatic reconciliation or retry command is provided. The selection ledger's existing stop remains enforced. No credentials enter saved plans, responses or dispatches.

## Runtime boundary

The coordination skill executes the next stage while the assistant task is active. The CLI provides persistence and gates, not an autonomous LLM service. After an interrupted task, invoke the skill again with this same batch; `next` returns the same dispatched stage and hashes. There is no background scheduler or guarantee of work continuing after the active task stops.
