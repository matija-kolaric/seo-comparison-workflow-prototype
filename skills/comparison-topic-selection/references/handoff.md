# Offline assessment and handoff

The skill writes the assessment after inspecting evidence; the helper does not invent candidates or editorial ratings. The canonical rubric remains in `docs/TOPIC_SELECTION_AND_ORCHESTRATOR_SPEC.md`. Helpers live in `src/seobility_workflow/topic_selection.py` and `selection_collection.py`; no package installation is needed.

Use `samples/topic-selection/assessment.json` as the input shape. Its data are synthetic and must never be presented as real tool recommendations. All referenced evidence paths are relative to the selection run, must start with `evidence/`, and must exist. Keep the assessment itself in `evidence/assessment.json`.

## Fields

- Top level: `policy_version: "0.2"` (legacy 0.1 remains supported), `data_mode: "live"` or `"fixture"`, `market: "United States"`, `language: "en"`, `inventory`, and `candidates` (at most 20). `target_count` defaults to 5; 6 requires policy 0.2 and an explicit `scope_approval_ref` matching the user's request.
- Inventory rows: `products` (two names), `status`, and optional title, slug, URL. Include active queued and drafted work, not only deployed URLs. Rejected rows do not block a pair. The existing Seobility/Ahrefs pair is always blocked.
- Candidate: unique lowercase `id`, two `products`, `page_type: "versus"`, `primary_keyword`, optional `secondary_keywords` / `discovery_queries`, and `evaluation: "inspected"` or `"not_evaluated"`.
- Uninspected candidates need `prefilter_reason`; do not fabricate ratings or SERPs for them.
- Inspected candidates: `angle`, `buyer_decision`, `why_this_pair`, `why_now` (say no trend conclusion when unsupported), `tradeoffs`, `limitations`, `unresolved_conflicts`, and `confidence`.
- `ratings`: `intent`, `fit`, `gap`, `feasibility`; each has integer `value` (0–4), a `rationale`, and `evidence_refs`. Demand is calculated, never supplied as a subjective rating.
- `serp`: exact primary `keyword`, ISO timezone-aware `retrieved_at`, `evidence_refs`, and ten distinct organic `results` containing original provider `rank` and `url`. Policy 0.2 requires `source_ref` to the single retained successful DataForSEO envelope. The helper derives the first ten distinct URLs from its contiguous organic ranks, within the first 20, and checks exact equality with `results`. Duplicates become `serp_duplicate_rows` warnings. Original rank 11 remains 11, not 10; never skip an earlier unique result. Legacy 0.1 requires ranks 1–10. Rank is organic rank, not absolute position including ads.
- `page_observations`: ranking-page `url`, `retrieved_at`, substantive `note`, `evidence_refs`. At least one opened ranking page is required; inspect enough pages to support each actual gap. File existence does not prove a note is true.
- `official_sources`: `product`, `url`, `retrieved_at`, `note`, `evidence_refs` for both products. Confirm first-party ownership yourself; the helper validates structure, not domain ownership.
- `metrics`: exact `keyword`, `search_volume` (integer or null), `market`, `language`, `period` (the provider's shared dataset date/window), `retrieved_at`, `evidence_refs`; retain `cpc`, currency, intent, and `monthly_searches` where available. Do not invent a currency/period. A provider update timestamp can identify the dataset snapshot; it is not necessarily the month represented by average search volume.

Only exact pair queries using `vs`, `vs.`, or `versus` qualify for the v1 volume proxy. Known aliases: `seo bility`, `sem rush`, `se-ranking`. Normalize additional aliases in the assessed pair/query mapping after review and retain original provider keywords in the evidence. Do not silently treat distinct products as aliases. Other useful modifiers can remain contextual secondary queries but do not inflate this conservative demand proxy. Mixed dataset periods become unknown until aligned.

The report ranks by total, intent, gap, confidence, feasibility, normalized pair name, then stable candidate ID. Equivalent eligible candidates collapse to the strongest record; no double counting. Missing/invalid core evidence excludes a candidate and caps confidence at low. Unknown demand caps confidence at medium but does not automatically disqualify it.

## Outputs and review

`queue.json` contains selected pages, reserves, exclusions (including not-evaluated candidates), dimension ratings, proxy volume, omitted demand rows, original evidence references, explanations, and `versus` research inputs. It always sets `production_authorized: false` and `publication_authorized: false`. No article run directory is created. The queue is input to the future runner, not a runner itself.

Offline revisions use `--ledger-snapshot` with `evidence/source-ledger.json`, a retained byte-identical copy of the original spending ledger, plus needed raw responses/reconciliation evidence. Do not create a fresh collection ledger or budget. Confirmed `actual_usd` and `unresolved_reserved_usd` are separate; `actual_is_final: false` and `further_collection_blocked: true` disclose pending billing without pretending it is free. Source-file hashes are verified. Unknown billing may stop spending without stopping offline editorial selection.

`selection.md` presents the same judgments. Review it before handing over: every selected topic needs a clear gap and buyer question; numerical order alone is not the rationale. Report dataset/retrieval dates, actual cost, uncertainty, and the selected-vs-reserve trade-offs. Keep any manual explanatory edits in the retained run.

The helper checks freshness against current UTC time. Old fixture timestamps will correctly fail freshness gates in a later run; tests inject a fixed clock. Do not use a historical clock to make a live selection look current.
