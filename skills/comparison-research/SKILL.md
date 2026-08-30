---
name: comparison-research
description: Research SEO product comparison or alternative pages using current SERP evidence and source-backed product facts. Use for new comparisons or when existing research is stale; do not use merely to rewrite an already supported draft.
---

# Comparison Research

Produce a strict SEO and evidence package that tells the planner what the page must cover, where it can add information gain, and which claims remain off-limits. Read [references/serp-research.md](references/serp-research.md) before collecting SERP evidence and `knowledge/seobility/citation-policy.md` before finalizing source metadata.

## Required input

Read `input.json`. Reuse existing research when its sources still answer the request and remain current.

## Research

1. Build a query map containing the primary query and only the secondary queries or clusters that materially affect the reader's decision. Record why each priority query is included and which discovered clusters were excluded.
2. Analyze the current top 10 organic results for every priority query. Deduplicate fetched pages, but preserve each query's rank and SERP appearance.
3. Compare SERP title, HTML title, meta description, H1, format, freshness, authorship, source quality, comparison dimensions, pricing, first-hand evidence, visuals, structured data, and direct-answer usefulness where retrievable.
4. Identify repeated patterns and evidence-backed gaps. Missing exact-match keywords or common sections are observations, not automatic recommendations; prioritize a gap only when it helps the reader and fits available evidence.
5. Research both products from current official pages and documentation. Use reliable independent sources only when they add necessary context or corroboration.
6. Sample reputable public user-experience sources when available, including established review platforms and relevant public forum or professional posts. Classify them as anecdotal experience evidence, retain the permalink/date/context, prefer paraphrase, and never infer consensus from isolated reviews.
7. Record atomic product and experience claims with evidence that directly supports their wording. Preserve the source title, canonical URL, retrieval date, visible publication or review date when relevant, and enough attribution context to create a reader-facing reference later. State uncertainty and never infer that an unmentioned feature is absent.
8. Research pricing from each vendor's official pricing page on the current run date whenever possible. Record the retrieval date, currency, billing period, taxes, and material plan qualifications. Mark a clear official pricing claim `supported`; do not reject it merely because prices may later change.
9. Treat other volatile metrics, limitations, and negative competitor claims as `needs_human_review` unless the evidence is unusually clear and the user has approved the fact.

Search snippets and model memory are discovery aids, not product evidence. Prefer first-party sources and record retrieval dates.

## Outputs

Write:

- `research/research.md`: intent, SERP patterns, audience needs, useful comparison dimensions, product findings, uncertainties, and linked sources;
- `research/serp-analysis.md`: the query map, top-10 result tables, cross-SERP patterns, gap IDs, and prioritized opportunities defined in the SERP reference;
- `research/claims.json`: the claim records defined in [references/evidence-format.md](references/evidence-format.md).

Create source snapshots only when they materially help with volatile or difficult-to-recover evidence. Do not create extra manifests or schemas.

Finish `research/research.md` with a handoff gate stating whether every priority top 10 is complete, experience evidence is correctly qualified, gaps are supported, and the planner's required, optional, and prohibited topics are explicit. Do not pass incomplete research silently.
