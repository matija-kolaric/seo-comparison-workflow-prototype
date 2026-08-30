# Comparison selection and orchestration — POC specification

Status: Shareable prototype specification. Example inputs and synthetic fixtures demonstrate the process; real collection, production, and publishing remain approval-gated.
Version: 0.2 — 30 August 2026. Legacy 0.1 inputs remain supported.

## Purpose and scope

Choose the next five worthwhile comparison pages from recorded evidence, then send approved selections through the existing fixed production workflow. The selector chooses the topics; the human reviews its reasoning and authorizes production rather than manually building the shortlist.

Five is the default; the user-requested expansion and "Finish the queue" instruction set this batch's target to six. This does not authorize six articles or expand any API budget.

- Output page type: `versus` only, specifically **Seobility vs [one other SEO tool]**.
- Market/language: United States / English for the POC.
- Audience: SEO professionals, small businesses, and agencies choosing SEO software.
- Goal: purchase-decision usefulness and credible bottom-of-funnel (BOFU) potential, not maximum traffic or guaranteed conversions.
- Alternatives queries may reveal competing products and buyer concerns. They must never produce an alternatives/listicle page, become a comparison's primary keyword, or contribute their volume to a comparison's demand score.
- Exclude tutorials, generic trends, best-tool lists, multi-tool roundups, and competitor-vs-competitor pages without Seobility.
- Exclude the existing Seobility vs Ahrefs page from new-page selection. Record it as existing, not as a second opportunity with reversed product order.

## Responsibilities

**`comparison-topic-selection` skill:** discover candidates, inspect data and SERPs, apply the rules below, choose and rank eligible pages, and explain decisions. It does not draft articles, publish, or change its own rules. Project-local entrypoint: `skills/comparison-topic-selection/SKILL.md`; offline ranking and opt-in collection: `skills/comparison-topic-selection/scripts/select_topics.py`.

**Lightweight orchestrator (implemented):** consume the selector's confirmed queue, enforce approval/budget/handoff gates, and coordinate the five existing production skills in order for one page at a time. The project-local `comparison-orchestrator` skill executes work while the assistant task is active; `scripts/orchestrate.py` persists progress and validates receipts. No independent model process or scheduler is implied. It does not make up missing evidence, silently substitute a topic, or override QA. A new selection request still uses the topic-selection skill before a batch is initialized.

**Human:** approve the first selection batch before production; approve the reviewed website changes before any push that can deploy; separately approve removal of noindex. Rejection can trigger a bounded selection revision using retained evidence, not an unlimited search loop.

## Inputs and bounded collection

Each selection run records:

- market, language, audience, page type, and anchor brand;
- existing/planned article inventory: normalized product pair, title, slug, URL if available, and status;
- seed queries and allowed discovery patterns;
- target count (5), candidate limit (20 distinct product pairs), and SERP shortlist limit (10 pairs);
- a confirmed USD API budget cap, actual spend, and remaining budget;
- scoring-policy version and retrieval timestamps.

Proposed default selection budget: **$1 per run**, not an estimate or a new spending authorization. Confirm the cap before the first paid selection run; do not treat historical permission for different calls as unlimited authorization. The cap excludes subsequent full article research, which needs a separate approved budget.

Reuse matching raw responses up to seven days old for selection, keyed by endpoint, request parameters, location, language, and collection date. Record both the original retrieval date and reuse date. Reusing a response does not refresh its age. Selection freshness does not replace the stricter pricing/product verification rules in article research.

## Selection procedure

1. **Read the inventory.** Compare both deployed and queued work before discovering new pages. Normalize brand aliases and unordered product pairs; preserve a preferred reader-facing title.
2. **Discover up to 20 pairs.** Start with `seobility vs`, its reverse-order variants, and relevant `seobility alternatives` / `[competitor] alternatives` queries. Record how each product was discovered. An alternatives mention is a lead, not evidence that its head-to-head comparison has demand.
3. **Collect comparison keyword metrics.** Use DataForSEO discovery and keyword-overview capabilities as needed. Retain exact keyword, source, market, search-volume period, monthly history where available, CPC/currency, intent labels, and missing-data flags. The selection helper supports bounded keyword suggestions, keyword overview, and Google organic SERPs. It retains monthly history already included in responses; no standalone historical or AI/LLM endpoints are added in v1.
4. **Cluster and prefilter.** Combine reversed pairs, brand aliases, and closely equivalent comparison queries into one proposed page. Pick a primary head-to-head keyword. Record secondary queries separately. Use the highest reported volume among equivalent comparison variants as a conservative cluster demand proxy; do not sum overlapping variants or alternatives volumes. Keep original rows available for inspection.
5. **Shortlist up to 10 pairs.** Apply scope/existing-page checks and prioritize explicit comparison intent, audience fit, available comparison demand, and a plausible evidence base. Log prefilter reasons. Candidates not inspected are `not_evaluated`, not proven poor opportunities. Preliminary ordering must not be presented as final scores.
6. **Inspect current top-10 organic results.** Collect one primary comparison SERP per shortlisted pair; reuse matching cached results if allowed. Open relevant ranking pages to verify proposed gaps. Record URLs, positions, dominant intent/page format, publisher types, freshness, observed strengths, and supported gaps. Metrics or snippets alone cannot establish a content gap. A missing exact-match title by itself is not meaningful differentiation. Do not call weak results an easy ranking opportunity solely from a difficulty metric.
7. **Check evidence feasibility.** Confirm that official information exists for both products and identify at least one concrete buyer decision our page could clarify. This is a source-availability check, not the full product/claims research stage.
8. **Score, filter, and select.** Use the fixed rubric below. Return up to five eligible pages and ranked reserves; do not pad the list. State that these are the best-supported opportunities within the inspected candidate set, not all possible SEO topics.

If fewer than ten organic results are returned, document the exact limitation. A candidate with an incomplete selection SERP remains on hold for review rather than quietly qualifying. Zero reported volume does not automatically disqualify a useful comparison; unknown data must remain labeled unknown.

Collection correction approved 30 August 2026: allow depth 20 (initially or as one bounded fallback), retaining the first ten organic ranks from one response. The ten-organic-result eligibility requirement, ten-SERP-request cap, scoring and original monetary cap are unchanged. A provider-confirmed billed request with missing local results may be reconciled with retained matching metadata and explicit resume approval; its cost remains counted and it is never a cache hit. At most one explicit replacement is allowed. See the selection skill's DataForSEO reference for the guarded procedure.

Policy 0.2 queue-finalization correction supersedes the exact-ranks requirement above: review the first ten **distinct** organic URLs within the first twenty organic positions of a single retained response. Validate against the original response, preserve original positions and report duplicates as warnings. Do not skip unique pages, combine snapshots or fabricate results. Sistrix's tenth distinct result is original rank 11; it remains rank 11. Scope, rating weights and eligibility thresholds are unchanged.

Offline editorial ranking and paid collection have separate gates. A revised review may use a retained ledger snapshot and valid source evidence while explicitly reporting unresolved billing/reservations. This does not reconcile the charge, authorize spending or reopen collection. Revisions retain original timestamps/hashes, preserve old outputs and identify the superseded queue. The user-approved single Mangools retry was an explicit eleventh-attempt exception, not a general change to the ten-SERP ceiling.

## Scoring rules

Each dimension receives an integer 0–4 rating with a written rationale and evidence references. Weighted points = `weight × rating / 4`; sum to a maximum of 100. These are editorial prioritization heuristics, not validated conversion probabilities or forecasts.

| Dimension | Weight | Rating anchors |
|---|---:|---|
| Buying-decision intent | 30 | 0: irrelevant; 1: mostly informational; 2: mixed or weak evidence; 3: comparison query with SERP evidence of evaluation; 4: clear product-choice intent plus verified plan/workflow/trade-off questions to answer. |
| Audience and product fit | 25 | 0: outside scope; 1: marginal overlap; 2: partial overlap; 3: both products address a relevant recurring SEO job; 4: a concrete target-audience use case makes the choice consequential, supported by official positioning/capabilities. |
| Credible differentiation | 20 | 0: no verified gap; 1: cosmetic improvement only; 2: one substantive buyer question inadequately answered in inspected results; 3: multiple verified gaps or one strong gap with obtainable evidence; 4: a distinct, evidence-backed decision framework we can realistically deliver. |
| Comparison search demand | 15 | Conservative monthly comparison-cluster proxy: unknown = 0 points with an explicit missing-data flag; reported 0 = rating 1; 1–49 = 2; 50–199 = 3; 200+ = 4. Thresholds are POC heuristics, not market benchmarks. |
| Delivery and SERP feasibility | 10 | 0: cannot source a useful page; 1: major evidence/access barriers; 2: sourceable but high effort or strong SERP competition; 3: accessible official evidence and a practical angle; 4: reusable evidence/assets and a specific achievable improvement over inspected pages. This is not a ranking guarantee. |

Eligibility for the selected queue requires all of:

- correct scope, no existing/queued duplicate, completed selection SERP, and official-source availability for both products;
- total score at least 65/100;
- buying-decision intent at least 3/4, audience fit at least 3/4, differentiation at least 2/4, feasibility at least 2/4;
- medium or high confidence, with no unresolved scope/intent/evidence contradiction.

Confidence is separate from score: **high** = current complete core evidence with no material unresolved conflict; **medium** = core SERP and source checks complete but noncritical demand/history gaps remain; **low** = missing core evidence or unresolved conflicts, so not eligible. Missing volume reduces the conservative score but is not described as proof of no demand.

Tie-break order: buying-decision intent, differentiation, confidence, feasibility, then normalized product-pair name. No Seobility-favoring product verdict is required to select a comparison. Do not imply that selection predicts Seobility will win the article.

CPC is supporting context, not a scoring multiplier. Paid-ad competition is not organic difficulty. Keyword difficulty is contextual evidence only, especially for a new demo site. Monthly trends are descriptive in v1, not score bonuses; do not call a single snapshot “growing demand,” or confuse keyword growth with stronger purchase intent. AI/LLM demand estimation is deferred entirely.

## Decision report and minimal artifacts

Proposed folder: `runs/selection-<date>-<id>/`.

- `selection.md`: scope, collection dates and costs, ranked selections, reserves, exclusions, limitations, and approval checkpoint.
- `queue.json`: selected page IDs/ranks, product pairs, primary/secondary comparison queries, page type, proposed slug/angle, dimension ratings, score, confidence, evidence references, production status, and eventual article run ID. This is a small handoff record, not a new universal schema system.
- `evidence/`: credential-free provider responses and the SERP/page observations needed to reproduce decisions. Do not copy unrelated research or entire websites.

For every selected page, the report must answer: Why this pair? Why now, if supported? What buying decision does it help? What can we add? What remains uncertain? Why was it preferred over nearby candidates? If only three qualify, show three plus the reasons for the shortfall.

The article inventory can initially be a small table derived from website content and the active queue. No database, search-console integration, or separate internal-linking skill is required.

## Orchestrator boundaries

30 August batch-expansion amendment: `expand` appends explicit approval for newly selected IDs without replacing initial approval or modifying completed pilot outputs. Existing production allocation is shared, not multiplied by article count. The original USD 1 cap includes selection charges, the full unresolved USD 0.01 reservation, and new production costs.

User-requested billing recovery: one transport-only selection failure may use `review-selection-reservation` after a fresh, successful, free empty task-history lookup. This preserves unknown billing and the full reservation; it does not assert a zero charge or reopen selection collection. Original ledger and evidence are hash-bound; changed records, additional failures, reported costs or insufficient aggregate headroom stop new production calls. See the orchestrator runner reference for the exact narrow procedure. This supersedes the blanket selection-billing stop below only for that explicitly reviewed reservation.

Implementation: `src/seobility_workflow/orchestrator.py`, `scripts/orchestrate.py`, and `skills/comparison-orchestrator/`. Commands: init, approve, status, next, complete, resume, collect. There is intentionally no publish command. The runner uses a separate total research budget and at most 60 new requests per approved batch; API failures stop the batch, with no automatic retry. Existing selection billing must be reconciled before new paid collection. Handoff receipts add a small review record without replacing the five skills' Markdown/JSON outputs. Structural checks are not a substitute for semantic review. The CLI alone cannot write articles: the coordinating skill must execute each returned dispatch.

```text
comparison-topic-selection
    → selection report + ranked queue
    → human batch approval
    → next selected comparison
        → research → brief → assets → writer → QA
        → human publication approval
        → clean website export → build + tests → approved GitHub push
        → Cloudflare deployment verification
```

- Run manually on request. No scheduler, background monitoring, or recurring spending in v1.
- After selection, stop for the first batch review. Approval names the selected IDs, production scope (one page or the batch), and relevant research budget. It does not authorize deployment.
- Default production scope is the first selected page only. A five-page queue is not permission to produce five articles automatically. If batch production is approved, process pages sequentially.
- Preserve the five production skills and their existing handoff gates. Selection gives research a topic and hypothesis; full research can reject that angle or discover the pair is unsuitable. If it does, stop and report; never invent support or silently promote a reserve.
- Research must still cover its approved priority clusters; the smaller selection SERP pass is not a substitute. Reuse valid observations while collecting missing evidence, rather than repeating all API calls.
- QA may return to the writer once, followed by another QA check. A second failure, missing material evidence, or required factual refresh outside the budget stops that page for human review. Do not proceed to publication or silently skip it in a batch.
- Use a small persisted status record: `selected`, `approved`, `in_progress`, `needs_review`, `ready_for_publish`, `deployed_noindex`, or `rejected`. Record the current production step and output references; no generic state-machine framework is needed.
- Resume only from a verified completed handoff. Never treat file existence alone as a pass, overwrite user edits, rerun paid research merely because a later stage dislikes it, or duplicate a deployed article on resume.
- Check estimated incremental API cost against remaining approved budget before each call; use documented pricing at implementation time, with a conservative allowance. If cost cannot be bounded, stop. Track billed cost returned by the provider. Do not auto-top-up or expand endpoint/subscription access.
- At most one retry for a confirmed retryable failure when duplicate billing can be avoided or accounted for within the cap. An ambiguous timeout on a billable request is not permission for a blind retry; retain the request fingerprint and resolve status/cost or ask for review.
- No changes to scoring weights, scope, minimum thresholds, credentials, repository visibility, hosting account settings, or indexing policy without explicit approval.
- The orchestrator stays local. DataForSEO credentials are not needed by the public website or Cloudflare build.

## Publishing boundary: GitHub → Cloudflare Pages

Active preview: https://seobility-comparisons-site.pages.dev/.
Website publishing occurs from a separately scoped static-site repository; research files and credentials never enter that repository.

After QA and human publication approval, prepare an export without altering the reviewed draft: remove internal claim comments, preserve reader-facing citations/backlinks, tables, screenshot captions/alt/attribution, and metadata. Update the approved homepage/article inventory links. Build and test only the website project.

Pushing to the connected production branch can deploy automatically. Therefore **approval must come before the push**, and must name the reviewed changes and target. A private GitHub repository does not make the deployed website private.

Retain `noindex, nofollow` in both page HTML and HTTP headers throughout the POC. Noindex is not access control. Verify the deployed homepage and article, canonical URLs, page-specific sharing images, references, assets, and robots settings. Record approval reference, commit, deployed URL, verification time/results, and issues in `publish/result.json`; do not claim a live deployment succeeded just because a local build passed.

Removing noindex is a separate release decision after identity/affiliation, byline/disclosures, screenshot rights, time-sensitive facts, and final visual checks are approved. Do not add analytics, affiliate tracking, paid services, domains, or a CMS implicitly.

The old WordPress skill remains as inactive legacy material, not an orchestrator step. This specification defines the replacement publishing procedure; it does not claim that a new Cloudflare publishing skill already exists.

## Acceptance checks before the first live selection run

- Alternative-only keywords can discover a pair but cannot become output pages or inflate comparison demand.
- Reversed pairs, aliases, existing Seobility vs Ahrefs, and already queued pages are deduplicated.
- Fixed evidence produces repeatable arithmetic/order; subjective ratings retain traceable rationales.
- Sparse/unknown volume, missing SERPs, contradictory intent, ties, fewer than five qualifiers, and no qualifiers are handled explicitly.
- Cached calls preserve retrieval dates; budget exhaustion, provider errors, and ambiguous paid timeouts stop safely.
- The output creates valid `versus` inputs for existing production skills, with approval required before execution.
- Failed QA, interrupted runs, manual edits, and resume cannot bypass gates or duplicate output.
- No push, indexing change, or Cloudflare mutation happens merely because a topic was selected.

## Implementation order

1. Build and test the selection skill and minimal DataForSEO discovery adapter on fixtures.
2. Run one bounded live selection, return the evidence-backed queue, and review the decisions.
3. Add the small queue runner; prove it by producing the first approved comparison.
4. Export and deploy that article only after separate approval, then consider running the remaining queue.

Out of scope: alternatives pages, autonomous publication, free-text homepage recommender, LLM-demand monitoring, multiple research agents, general workflow frameworks, recurring jobs, and dynamic skill selection.
