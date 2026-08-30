# Seobility knowledge base

`knowledge-base.json` is the maintained source for approved Seobility claims. It intentionally starts empty: no product fact becomes `verified` merely because an automated process found it.

A human product owner should review candidate claims, confirm the supporting source and wording, set `verified_by` to `human`, and change the knowledge-base status to `approved`. The run materializer accepts only an approved knowledge base and only claims whose status is `verified` and whose evidence remains fresh under `config/research-policy.json`.

Editorial standards used across runs:

- `brand-voice.md`: canonical English voice and comparison posture;
- `copy-qa.md`: observable copy-quality gate;
- `citation-policy.md`: internal claim tracing, reader-facing references, screenshot attribution, and publishing transformation;
- `style-sources.md`: evidence used to derive the voice standard.
