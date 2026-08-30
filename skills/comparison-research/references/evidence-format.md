# Evidence format

`research/claims.json` is a JSON object:

```json
{
  "topic": "Seobility vs Ahrefs",
  "researched_at": "2026-08-27T12:00:00Z",
  "claims": [
    {
      "claim_id": "SEO-001",
      "subject": "Seobility",
      "fact_type": "feature",
      "statement": "A narrowly worded factual claim.",
      "status": "supported",
      "sources": [
        {
          "title": "Official page title",
          "url": "https://example.com/page",
          "retrieved_at": "2026-08-27",
          "evidence": "A short passage or structured value supporting the claim."
        }
      ],
      "notes": null
    }
  ]
}
```

Allowed statuses:

- `supported`: the source directly supports the exact wording and the writer may use it;
- `needs_human_review`: sensitive, ambiguous, or volatile; do not use as settled fact;
- `conflicting`: sources disagree; do not use without resolving the conflict;
- `unsupported`: investigated but not established; do not use.

Keep claims atomic. One source may support several claims, and one claim may cite several sources. Evidence excerpts should be short and used for verification, not copied into the article.

For user reviews, use `fact_type: "user_experience"` and phrase the claim as an attributed observation, such as “One reviewer described…”. Record the platform, permalink, post/review date when visible, retrieval date, and relevant product/workflow context. Prefer a short paraphrase. Do not convert one or several anecdotes into “users generally say” unless a documented, reproducible sampling method supports that conclusion.

Official vendor sources establish product facts. Review platforms, Reddit, LinkedIn, and similar sources establish only that a person reported an experience or opinion.

Source metadata must be complete enough to produce the visible references required by `knowledge/seobility/citation-policy.md`. When a public author or display name is not appropriate to reproduce, record the platform and permalink without exposing unnecessary personal data.
