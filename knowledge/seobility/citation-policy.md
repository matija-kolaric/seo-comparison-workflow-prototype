# Seobility comparison citation policy

Status: Working publication standard
Applies to: English comparison and alternative pages

## Purpose

Give readers enough source visibility to verify important claims without making a commercial article read like an academic paper. Keep the internal evidence trail separate from the reader-facing citation layer.

## Two-layer model

### Internal traceability

Every factual passage in `draft.md` retains one or more stable claim IDs in an HTML comment:

```markdown
Seobility provides prioritized audit recommendations. <!-- claims: SEO-001 -->
```

Claim IDs connect the draft to `research/claims.json` for QA and future updates. They are never used as reader-facing reference numbers and must not be sent to WordPress.

### Reader-facing references

Use the least intrusive treatment that still lets a reader verify the evidence:

1. **Descriptive link in the prose** for a natural first-party destination, especially pricing, product documentation, and plan limits.
2. **Numbered footnote** for exact figures, sensitive comparisons, third-party evidence, review themes, or a source that would interrupt the sentence as an inline link.
3. **Screenshot caption and attribution** when the visual itself is evidence.
4. **No visible citation** for clearly signposted editorial interpretation that is fully traceable internally and does not depend on a sensitive fact.

Do not add both an inline link and a footnote to the same source passage unless each serves a different purpose.

## What requires a visible reference

A reader-facing link, footnote, or screenshot attribution is required for:

- current prices, discounts, billing commitments, taxes, and material plan limits;
- exact counts, percentages, locations, update frequencies, database figures, and other numbers used to compare products;
- negative, limiting, potentially disputed, or surprising product claims;
- quotations and paraphrased experience evidence from review platforms, Reddit, LinkedIn, interviews, or other people;
- statements presented as review themes or broader user sentiment;
- third-party studies, benchmarks, surveys, or statistics;
- claims where the source identity materially affects how much confidence the reader should place in the statement.

Ordinary, stable feature descriptions may use one descriptive official link at the first meaningful mention rather than repeated footnotes throughout the page.

## Citation density

Cite the smallest useful passage, usually once per paragraph or comparison row. Do not attach a reference number to every sentence when several adjacent sentences use the same source. Repeat a source only when substantial distance or a new context makes the evidence unclear.

The number shown to readers reflects order of appearance. Stable claim IDs remain the canonical identifiers behind the draft.

## Footnote format in working Markdown

Use standard Markdown footnotes:

```markdown
Seobility says its Website Audit checks more than 300 factors per page.[^1]

[^1]: Seobility, [Website Audit](https://www.seobility.net/en/website-audit/), retrieved 29 August 2026.
```

For a review or third-party source, include the author or account name only when it is public, relevant, and appropriate to reproduce:

```markdown
Some reviewers describe the guided issue explanations as helpful when handing work to less experienced teammates.[^2]

[^2]: Review theme synthesized from individually attributed sources; see G2 review by [public display name](permalink), posted DATE, retrieved DATE. This is experience evidence, not a product fact or representative survey.
```

Do not use a footnote to convert a single anecdote into consensus. When several sources support a theme, list the relevant permalinks in one footnote and state the size and limitations of the sample in the prose or methodology note.

## Pricing

Pricing requires:

- a descriptive link to each official pricing page;
- the retrieval date in the visible article;
- currency and billing period;
- applicable tax, annual commitment, discount, and tier qualification;
- reverification on the publication date whenever possible.

A separate numbered footnote is optional when the descriptive pricing link and visible date already make verification clear.

## Screenshots

Every published screenshot must match `assets/manifest.md` and include:

- a useful alt description;
- a caption explaining what the reader should notice;
- the product, platform, or source name;
- capture date;
- a source link or reference entry where the publishing format permits it.

Example:

```markdown
![Prioritized issues in Seobility Website Audit](assets/seobility-audit-priorities.png)

*Seobility Website Audit groups and prioritizes detected issues. Screenshot captured 29 August 2026 from [Seobility](SOURCE_URL); interface may change.*
```

A screenshot proves only what was visible when captured. Its caption must not claim a result, endorsement, or broader user consensus that the image does not establish.

## Sources and methodology section

Finish the article with a compact `Sources and methodology` section that:

- says which evidence types were used;
- distinguishes official product facts from third-party experience evidence and editorial interpretation;
- states the main research or access limitations;
- contains the footnote definitions or a clean reference list for sources actually cited in the article.

Do not paste the entire internal claim registry or every URL visited. Include only sources used in the published copy or necessary to understand the method.

Suggested method note:

> Product capabilities and pricing were checked against official vendor pages on the dates shown. Third-party reviews, when used, describe individual experiences rather than representative product performance. Recommendations are editorial interpretations of the cited evidence; no unsupported hands-on testing is implied.

## Publication transformation

`draft.md` remains the traceable source artifact. During WordPress staging:

- remove only internal `<!-- claims: ... -->` comments from the publishing payload;
- preserve descriptive links, screenshot captions, and the methodology section;
- convert Markdown footnotes to native WordPress footnotes or accessible linked superscripts with return links;
- ensure every visible reference marker has one destination and every listed reference is used;
- never alter `draft.md` merely to create the clean publishing payload.

If the WordPress setup cannot render accessible footnotes reliably, use descriptive inline links and a numbered reference list with stable anchors instead.
