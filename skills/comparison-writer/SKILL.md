---
name: comparison-writer
description: Write or revise an SEO product-comparison page from an approved brief and supported claim records. Use for initial drafts and one QA-directed revision; do not research missing facts while writing.
---

# Comparison Writer

Read `brief.md`, `research/research.md`, `research/claims.json`, `assets/manifest.md`, `knowledge/seobility/brand-voice.md`, `knowledge/seobility/copy-qa.md`, and `knowledge/seobility/citation-policy.md`. Confirm that every required asset is ready or has an approved text fallback before writing `draft.md`.

Use only claims whose status is `supported`. Add an internal trace after each factual passage:

```markdown
The product provides ... <!-- claims: SEO-001 -->
```

Internal claim IDs and reader-facing reference numbers are separate systems. Keep claim comments in `draft.md` for QA. Apply the brief's citation plan using descriptive links, Markdown footnotes, and screenshot attribution only where the citation policy requires them; do not expose `SEO-001`-style IDs to readers.

Write for the reader's decision, not for a feature-count contest. Explain meaningful differences, acknowledge when the available evidence cannot establish a winner, and avoid universal recommendations.

The draft should:

- satisfy the brief's intent and reader outcome;
- be specific, balanced, and easy to scan;
- distinguish product facts from editorial interpretation;
- avoid fabricated experience, generic AI phrasing, repetition, and keyword stuffing;
- include the proposed metadata at the top for review;
- use only assets listed in the manifest, with the approved caption, alt text, attribution, and source link;
- include a compact `Sources and methodology` section with only the evidence used in the published copy and the material limitations of the research;
- avoid redundant citations when one visible reference supports a complete nearby passage;
- follow the canonical Seobility voice without copying or closely imitating any source article;
- end with a proportionate next step rather than an unsupported sales claim.

If required evidence is missing, state the limitation or omit the claim. Do not invoke research implicitly.

Before handing off, self-review against the automatic blockers and editorial checks in `knowledge/seobility/copy-qa.md`. Also confirm that every claim requiring visible verification has the planned link, footnote, or attribution; every footnote is used exactly once as a reference definition; and the internal claim comments remain complete. Revise weak passages, but do not manufacture variation or personality at the expense of clarity.

For a revision, change only what QA requires unless another passage becomes inaccurate as a result. Preserve the previous draft as `draft-v1.md` before replacing `draft.md`.
