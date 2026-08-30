# Seobility Comparison Page MVP

Status: Shareable prototype; the orchestrator is implemented and covered by offline tests. Production collection and publishing remain approval-gated.
Example comparison: **Seobility vs Ahrefs**

## Goal

Create useful, source-grounded Seobility-versus-one-tool comparison pages through a fixed workflow that is easy to inspect. The first article is deployed on Cloudflare Pages; the next extension is a bounded topic selector and lightweight queue runner, not general-purpose orchestration.

Selection rules, scoring, budget controls, and execution boundaries are defined in [Topic selection and orchestrator specification](docs/TOPIC_SELECTION_AND_ORCHESTRATOR_SPEC.md). Only `versus` pages may be selected. Alternatives keywords are discovery evidence only, never output page types or comparison-volume inputs.

## Fixed workflow

```text
comparison-topic-selection
    -> ranked queue + human batch approval
    -> comparison-research
    -> comparison-brief
    -> comparison-assets
    -> comparison-writer
    -> comparison-qa
    -> human publication approval
    -> website export + build/tests
    -> approved GitHub push -> Cloudflare Pages verification
```

The five existing production skills, from research through QA, always run in order for a new page. The selection skill sits before them; its helpers rank evidence offline and collect DataForSEO responses only with explicit paid-call opt-in. The `comparison-orchestrator` skill and `scripts/orchestrate.py` now coordinate these stages with durable state and hash-bound handoff receipts. The active assistant executes the skills; the CLI alone is not an autonomous worker. `comparison-qa` may send the draft back to `comparison-writer` once. A selected queue does not authorize production or deployment; the default approved production scope is one page at a time.

Each skill can also be called independently when its required inputs already exist.

## Inputs

`input.json` contains:

```json
{
  "topic": "Seobility vs Ahrefs",
  "page_type": "versus",
  "language": "en",
  "market": "United States",
  "audience": "SEO professionals and small businesses comparing SEO platforms"
}
```

## Skills and outputs

### 1. comparison-research

Collect current keyword, SERP, competitor, product, and user-experience evidence. Analyze the top 10 organic results for the primary query and every approved priority query or cluster. Deduplicate URLs while preserving rankings by query. Prefer official product pages for product facts; search results and human reviews provide intent, content-pattern, and experience evidence—not settled product facts.

Outputs:

- `research/research.md`: concise human-readable findings, intent, comparison dimensions, uncertainties, and source list;
- `research/serp-analysis.md`: query map, top-10 observations, page-level patterns, content gaps, and prioritized opportunities;
- `research/claims.json`: factual claims with claim IDs, source URLs, retrieval dates, and supporting evidence;
- `research/sources/`: retained source captures when practical.

Research must pass its handoff gate before briefing: every priority query has a complete top 10 or an explicit collection limitation; product and review evidence is correctly classified; gaps are evidence-backed and prioritized; and `research.md` states what the brief must cover, may cover, and must avoid.

### 2. comparison-brief

Turn the research into an editorial plan without adding facts. Refuse the handoff and list missing research when the research gate is incomplete. Every major section must map to a supported claim, reader need, SERP gap, or priority query identified in research.

Output: `brief.md`, containing audience, intent, query/cluster map, page angle, differentiated information gain, comparison dimensions, outline, claim and gap IDs available to each section, metadata proposal, image plan, citation plan, and claims to avoid. The citation plan identifies which evidence needs a descriptive link, numbered footnote, screenshot attribution, or internal trace only.

### 3. comparison-assets

Prepare only the visuals requested by the approved brief. Prefer current screenshots from official product pages. Third-party review screenshots require a clear editorial purpose, source attribution, retained context, and a privacy/copyright check; paraphrase plus a permalink is the default for personal Reddit or LinkedIn posts.

Outputs:

- `assets/manifest.md`: asset ID, purpose, source URL, capture date, filename, caption, alt text, attribution, reference mapping, and use notes;
- `assets/`: approved image files.

The asset handoff passes when every planned image is either ready and sourced or explicitly marked unavailable with a safe text fallback.

### 4. comparison-writer

Write the page from `brief.md` and verified claims only. Follow the canonical Seobility brand voice, copy-quality standard, and citation policy in `knowledge/seobility/`. Working drafts retain internal claim-ID comments for QA and add selective reader-facing links, footnotes, screenshot attribution, and a compact `Sources and methodology` section. Internal claim IDs never become visible reference numbers.

Output: `draft.md`.

### 5. comparison-qa

Perform one combined review covering factual support, citation integrity, search-intent match, usefulness, specificity, balance, clarity, repetition, and generic AI language.

Output: `qa.json` containing:

- `passed`;
- `unsupported_claims`;
- `issues` with severity and required correction;
- a six-dimension quality score;
- `required_changes`;
- `human_review_notes`.

A draft passes when it has no unsupported material claims, no high-severity issue, a quality score of at least 25/30, no dimension below 3/5, and the stricter originality and brand-positioning scores defined in `knowledge/seobility/copy-qa.md`. One revision is allowed in the MVP; a second failure stops for human review.

### Publishing procedure: website export and Cloudflare Pages

After QA and explicit human approval of the reviewed changes, export the article and approved assets into the standalone `website/` project without changing `draft.md`. Remove internal claim-ID comments, preserve descriptive links, screenshot attribution, and accessible footnotes with return links. Update approved homepage/article links, build the static Astro site, and pass its publishing tests.

Push only the website repository to GitHub after approval: the connected `main` branch triggers Cloudflare Pages deployment. Never push the parent research workspace or credentials. The site is publicly accessible but remains `noindex, nofollow` in both HTML and HTTP headers; noindex is not password protection. Keep the confirmed `SITE_URL` for canonical and social-image URLs. Verify the deployed pages, citations, assets, metadata, and noindex settings. Removing noindex requires separate launch approval.

Output: `publish/result.json` with approval reference, article run ID, commit, deployed URL, verification timestamp/results, and warnings. This is the required record for future orchestrated runs; existing manual deployment does not imply this artifact already exists. The legacy `wordpress-staging` skill is inactive and not called by this workflow.

## Handoff gates

| Handoff | Must be true before continuing |
|---|---|
| Selection → Production | Comparison-only eligibility and scoring pass; queue and evidence are recorded; human approves selected IDs, production scope, and research budget. |
| Research → Brief | Priority-query SERPs are complete or limitations are explicit; product facts and review anecdotes are separated; gaps and required coverage are prioritized. |
| Brief → Assets | Every major section maps to research; differentiation is explicit; every proposed image has a purpose and source preference; sensitive evidence has a reader-facing citation treatment. |
| Assets → Writer | Every required asset is ready and sourced or has an approved text fallback; captions and attribution are publication-ready. |
| Writer → QA | The draft follows the brief, traces factual passages to supported claim IDs, and applies the reader-facing citation plan; no implicit research was added. |
| QA → Deployment | QA and website build/tests pass; a human explicitly approves reviewed website changes before the deployment-triggering GitHub push. |
| Deployment → Verified preview | Live URLs, references, assets, canonical/social metadata, and both noindex directives are checked. |

The receiving skill performs the preflight. Deterministic checks support the gates; no separate validation agent is required for this POC.

## Run directory

```text
runs/<run-id>/
├── input.json
├── research/
│   ├── research.md
│   ├── serp-analysis.md
│   ├── claims.json
│   └── sources/
├── brief.md
├── assets/
│   └── manifest.md
├── draft.md
├── qa.json
└── publish/
    └── result.json
```

Only create files that serve the next skill, human review, factual traceability, or publishing validation.

## Non-negotiable rules

- Product facts require a recorded source; model memory is not evidence.
- Do not infer that a competitor lacks a feature because one page does not mention it.
- Pricing must come from each vendor's official pricing page, be retrieved on the current run date whenever possible, and state its retrieval date, currency, billing period, and tax qualification where shown.
- Limitations, metrics, and negative competitor claims require especially careful verification.
- Reader-facing citations follow `knowledge/seobility/citation-policy.md`; citation density follows verification need rather than attaching a number to every factual sentence.
- Internal claim comments remain in the source draft for QA but are stripped from the website export.
- Research cannot be repeated merely because a later skill dislikes the answer; unresolved uncertainty must be stated.
- QA cannot be skipped for a new comparison page.
- No public or staging publication occurs without explicit human approval.
- Credentials remain in environment variables and are never written to run artifacts.

## Definition of done for the first run

The first Seobility vs Ahrefs run has produced a reviewed article, sourced screenshots, references, and passing QA, and was deployed to Cloudflare Pages after approval. Canonical/social metadata and noindex were verified; the user confirmed desktop/mobile visual checks. The next milestone is an evidence-backed comparison-only selection queue, followed by one approved page through the unchanged five production skills and the gated website deployment procedure.

## Deferred until real runs justify them

- dynamic skill selection;
- a general state machine;
- schemas for every intermediate file;
- generic artifact registries;
- multiple independent review agents;
- automated retry trees;
- support for additional page types and publishing targets.

The previous infrastructure-heavy specification is preserved at `docs/ARCHIVE_WORKFLOW_SPEC_V0.1.md` for reference, but it is not the active MVP design.
