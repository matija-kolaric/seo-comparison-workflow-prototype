# Research and evidence policy

## Goal

The research layer discovers potential facts, records provenance, and decides which evidence may enter planning and writing. It does not write comparison copy or infer unsupported product conclusions.

## Source order

1. Official documentation and current product or pricing pages
2. Approved internal Seobility records and other first-party material
3. Reliable independent sources where first-party evidence is unavailable or needs corroboration

Search results and AI output may help discover sources, but neither is evidence by itself.

## Claim workflow

```text
discovered -> captured with provenance -> policy checked -> human-reviewed if required -> verified -> available to planner
```

Each claim must be atomic enough to verify independently. Evidence should contain the smallest passage or structured value that supports the wording. Interpretation belongs in the content brief, not in the evidence record.

For live research, every external source must retain a snapshot path and SHA-256 content hash. This preserves what the researcher actually saw even if the page changes later. Internal approved records may use an internal reference instead.

## Freshness defaults

The executable defaults live in `config/research-policy.json`. Pricing expires after 7 days; metrics after 14 days; features, limitations, integrations, support facts, and uncategorized facts after 30 days; audience and positioning claims after 90 days.

These are prototype defaults, not universal truths. A claim can use an earlier `valid_until` date when its source or context warrants it.

## Sensitive comparative claims

Pricing, limitations, and quantitative metrics require human review. The current prototype requires at least two sources for every competitor limitation; any future exception must be represented explicitly in the policy rather than handled informally. Universal winner claims, unqualified superlatives, and inferred absences are not permitted.

The absence of a feature from a page is not evidence that the feature does not exist.

## Competitor research procedure

1. Discover candidate official pages from the SERP layer and direct product navigation.
2. Capture the relevant page or structured response under the run's research directory.
3. Record its retrieval timestamp, snapshot path, and content hash.
4. Extract atomic claims with the smallest supporting evidence passage.
5. Leave uncertain claims `unverified`; mark conflicts explicitly.
6. Apply source-count, source-type, freshness, and human-review rules before a claim becomes available to the planner.

Playwright may capture pages that cannot be read reliably through a normal HTTP request. It is a capture mechanism, not a source of truth: the original URL and retained snapshot remain required.

## DataForSEO boundary

DataForSEO supplies search demand, intent, and SERP observations. It does not verify product capabilities. Provider responses are retained as raw run artifacts and normalized into `research/serp.json` before downstream use.

The prototype uses:

- DataForSEO Labs Google Keyword Overview Live for search volume, CPC, competition, and intent;
- Google Organic SERP Live Advanced for current result items and related questions.

Live calls incur provider charges and therefore require an explicit CLI confirmation flag. Credentials are read only from `DATAFORSEO_LOGIN` and `DATAFORSEO_PASSWORD`.
