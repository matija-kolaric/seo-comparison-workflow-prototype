---
name: comparison-qa
description: Review an SEO comparison draft for factual support, intent match, usefulness, balance, and editorial quality. Use before human approval or after one revision; do not rewrite the article inside the review.
---

# Comparison QA

Read `input.json`, `research/serp-analysis.md`, `brief.md`, `assets/manifest.md`, `draft.md`, `research/claims.json`, `knowledge/seobility/brand-voice.md`, `knowledge/seobility/copy-qa.md`, and `knowledge/seobility/citation-policy.md`. Verify every material factual statement against the cited claim IDs and evidence.

Check:

- unsupported, overstated, contradicted, or stale claims;
- title, metadata, headings, and search-intent alignment;
- comparative usefulness and meaningful decision criteria;
- specificity, clarity, balance, and positioning;
- repetition, keyword stuffing, and generic AI language;
- whether interpretations are presented as facts;
- whether required gaps, clusters, and information-gain commitments from the brief were actually fulfilled;
- whether claims requiring reader-facing verification have an accurate descriptive link, footnote, or screenshot attribution without excessive citation density;
- whether every visible reference resolves to the supporting source, every footnote definition is used, retrieval and publication dates are accurate, and the `Sources and methodology` section states material evidence limitations;
- whether every used image matches the manifest, has useful alt text/caption/source context, and avoids unsupported endorsement or review consensus;
- every automatic blocker and editorial check in the Seobility copy-quality gate.

Write `qa.json` using [references/qa-format.md](references/qa-format.md). Do not edit `draft.md`.

Pass only when there are zero unsupported material claims, no high-severity issue, a score of at least 25/30, no dimension below 3/5, `originality` is at least 4/5, `positioning_clarity` is at least 4/5, and no high- or medium-severity copy-quality or citation-integrity issue remains. Otherwise list concrete required changes. After a revised draft fails again, recommend human review rather than another automatic revision.
