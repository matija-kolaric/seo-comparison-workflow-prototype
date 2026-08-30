# Bounded DataForSEO collection

Use only after explicit approval of the selection budget and scope. The proposed $1 cap is not a price estimate. Confirm current official per-task and per-item pricing and reserve a conservative upper bound covering the entire configured request. The helper enforces the declared bound against the cap but cannot guarantee a provider's billing formula is correct. No price is hardcoded as current.

Documentation checked during implementation (30 August 2026):

- [Keyword Suggestions](https://docs.dataforseo.com/v3/dataforseo_labs/google/keyword_suggestions/live/): expands a seed; response items and seed data can contain keyword metrics and monthly history.
- [Keyword Overview](https://docs.dataforseo.com/v3/dataforseo_labs/google/keyword_overview/live/): specified comparison keywords; keep missing data explicit.
- [Organic live advanced SERPs](https://docs.dataforseo.com/v3/serp/google/organic/live/advanced/): collect desktop, US, English, depth 10 or 20. Policy 0.2 reviews ten distinct organic URLs from one retained response, preserving original ranks and flagging exact duplicates. A depth of 10 may return fewer than ten distinct organic results. Use a single bounded depth-20 fallback, or start at 20 when this limitation is known. If still incomplete, hold the candidate; never pad ranks or mix snapshots.

There is no separate historical/LLM endpoint in this implementation. Use monthly history already returned by overview/suggestions where available; no history means no trend conclusion. Suggestions from alternatives seeds do not themselves prove comparison demand.

## One-request plan

Prepare a JSON file with `operation` (`suggestions`, `overview`, or `serp`), `keyword` (suggestions/SERP) or `keywords` (overview), and `limit` (suggestions only, at most 100). Also include `cost_bound_usd`, `pricing_source` (official HTTPS URL), and `pricing_checked_at` (ISO datetime with timezone). A date is your record of an actual pricing check, not permission to invent a cost.

SERP plans accept optional `depth: 10` (default) or `depth: 20`. Budget the full depth, including fallback costs. The ten-SERP-request run limit includes replacements and deeper fallbacks.

Preview safely, without loading credentials or making any API calls:

```bash
python3 skills/comparison-topic-selection/scripts/select_topics.py collect \
  runs/<selection-run>/evidence/request.json --run-dir runs/<selection-run>
```

Only after approval, execute that request:

```bash
python3 skills/comparison-topic-selection/scripts/select_topics.py collect \
  runs/<selection-run>/evidence/request.json --run-dir runs/<selection-run> \
  --budget-usd 1 --approval-ref "reference to the user's actual approval" \
  --confirm-live-costs --env-file .env
```

The credential loader reads only DataForSEO environment keys and never sources shell code. Request bodies are built from allowlisted fields; arbitrary endpoints and scope overrides are rejected. No credential values belong in plans, evidence, or reports. The public website never calls DataForSEO.

## Ledger and cache

`evidence/collection-ledger.json` records approval, fixed cap, request fingerprint, cost reservation, state, actual cost, response file hash, retrieval date, and reuse dates. A request is reserved durably before transport. Retained envelopes contain the raw response and extracted provider rows without assigning editorial scores.

Exact endpoint/body cache matches within **the same selection run** can be reused for seven days. No new API request or cost is added. The original retrieval timestamp is retained; changed evidence hashes or future dates do not qualify. Cross-run cache lookup is not automated in v1: manually reuse existing evidence only after matching scope/age and documenting provenance, and do not represent a historical billed cost as new spending.

The collector is single-writer and refuses a second process. It allows at most 30 new requests and ten SERP requests per selection run, in addition to the monetary cap. Rank-time candidate limits remain 20 candidates/10 inspected pairs. Budget/approval/mode cannot be silently changed on resume.

Timeouts, partial provider failures, absent cost, or billing above a reservation stop further requests. No automatic retry is implemented. Inspect retained evidence and reconcile billing with the user before any new call; do not delete locks/ledgers or create new runs to bypass this stop. A provider may bill above an estimate; report actual cost and stop rather than pretending the preflight cap guaranteed the invoice.

### Reconciled charge, missing result

Use the free `/v3/serp/id_list` lookup for a narrow request-time window to recover task metadata/status/cost. A completed Live task is not proof that local results exist; Live results may not be retrievable. After a recovery attempt and explicit user resume approval, retain the ID-list response under `history_lookup.response` in an evidence JSON file. Reconcile offline:

```bash
python3 skills/comparison-topic-selection/scripts/select_topics.py reconcile \
  runs/<selection-run>/evidence/original-request.json --run-dir runs/<selection-run> \
  --evidence-ref evidence/billing-reconciliation.json --resume-approval-ref "actual user approval"
```

The helper matches endpoint, request parameters, time and cost; records a hash of the evidence; and changes only the affected ledger entry to `billed_missing_result`. It preserves the charge and budget, never creates a fake response/cache, and allows at most one explicitly invoked replacement for that missing keyword. Both charges count. Missing-result entries do not satisfy a candidate's SERP evidence gate. Changed reconciliation evidence blocks collection/ranking. Other unresolved entries still stop the run.

Error and cause class names are retained without private exception messages. Free diagnostic lookups belong in reconciliation evidence, not as newly billed search tasks.

Live ranking uses this ledger, or an explicitly retained read-only snapshot for a revision, for cost reporting. Unresolved reservations remain distinct from confirmed costs and continue to block ordinary paid collection, but do not block offline ranking of existing evidence. The collector rejects revision directories containing `evidence/source-ledger.json`; return to the original spending run for any approved future collection. Offline fixtures use injected fake clients in tests and are marked `fixture`; they cannot populate a live cache.

The user-approved Mangools retry on 30 August 2026 was a narrowly recorded exception: one exact transport retry with retained task-history checks, the original reservation still counted, and one extra SERP slot. It does not grant a general retry or request-limit increase. That original unresolved billing entry remains unresolved.
