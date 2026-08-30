# QA output format

Write `qa.json` as:

```json
{
  "draft": "draft.md",
  "reviewed_at": "2026-08-27T12:00:00Z",
  "passed": false,
  "unsupported_claims": [
    {
      "text": "Unsupported statement",
      "location": "Section heading",
      "reason": "No matching supported claim"
    }
  ],
  "issues": [
    {
      "severity": "high",
      "category": "factual_support",
      "location": "Section heading",
      "description": "What is wrong",
      "required_change": "Concrete correction"
    }
  ],
  "scores": {
    "factual_accuracy": 1,
    "search_intent_match": 1,
    "comparative_usefulness": 1,
    "specificity": 1,
    "originality": 1,
    "positioning_clarity": 1
  },
  "total_score": 6,
  "required_changes": [],
  "human_review_notes": []
}
```

Severity is `high`, `medium`, or `low`. Each score is an integer from 1–5, and `total_score` must equal their sum. Keep issues actionable and avoid stylistic preferences that do not materially improve the page.

Use `citation_integrity` as the issue category for a missing, misleading, mismatched, inaccessible, redundant, or orphaned reader-facing reference. Internal claim support problems remain `factual_support`.
