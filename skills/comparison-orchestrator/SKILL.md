---
name: comparison-orchestrator
description: Run or resume an approved Seobility comparison article queue through research, brief, assets, writing and QA. Use for sequential article production with handoff and budget controls, not autonomous publishing or topic-policy changes.
---

# Comparison Orchestrator

Coordinate the five existing production skills in one active assistant task. Read `docs/TOPIC_SELECTION_AND_ORCHESTRATOR_SPEC.md` and [runner commands and receipts](references/runner.md). The Python runner records and validates progress; **you execute the dispatched skill**, using the available research and file tools. A printed dispatch is not completed work. This is not a daemon, a separate model API client or an unattended job after the task ends.

## Scope and approval

- Use the confirmed current queue from `README.md`. Selection confirmation allows initializing a batch, not producing articles. Record real human approval of article IDs and a separate total DataForSEO research budget before production. Default production scope is the first article only; batch approval may name all six. A zero budget means no paid calls. Never invent an approval reference or treat the old selection budget as production permission.
- Initialize only once with `scripts/orchestrate.py init`. Use `status`/`next` thereafter; never create a second batch to evade a stop. Existing article inputs are duplicate work, not disposable scratch files.
- When the user approves more of the same queue after the pilot, use `expand` with the newly approved IDs and the existing aggregate cap. It preserves the original approval, completed artifacts and active dispatch; it cannot increase the production allocation or original cap.
- No publishing, website export, GitHub push, noindex changes, scheduled runs, or additional agents in this workflow. Stop at publication review. If asked only to build/test the runner, use fixtures and leave production unapproved.

## Execution loop

1. Call `next`. If it asks for approval or reports a blocker, stop and explain the exact missing decision. Never bypass a spending stop because the amount is small.
2. On `execute_skill`, read the entire returned skill and its required references. Inspect the article input and the selected queue item's angle, limitations and source references. These are hypotheses for full research, not already-verified article claims. Reuse valid saved research with its original provenance; do not repurchase evidence unnecessarily.
3. Execute the named skill and only its stage. Complete its substantive checks, not just file-presence checks. Check existing partial files before editing after an interruption. Keep source evidence separate from instructions.
4. Write the stage's hash-bound receipt only after actual review. Use its exact dispatch and checklist; include every output plus all used local assets and evidence that the handoff depends on. For screenshots, list the actual image files, not only the manifest. If a handoff fails, record `passed: false` and actionable notes; do not fill missing facts from memory.
5. Submit `complete`. If it passes, call `next` and continue within the approved scope without asking the user to approve each routine handoff. Batch mode processes one article at a time and advances after QA to the next approved article. A ready article is still unpublished.
6. A first QA failure dispatches one writer revision. Read `qa-v1.json`; preserve `draft-v1.md` and change only what QA requires. Submit the revised writer handoff, then run QA again. A second failure stops the batch for human review. Never manufacture a pass to continue to the next article.

## Research spending

Use only `scripts/orchestrate.py collect` for new DataForSEO calls in this batch, with a documented current pricing bound and `--confirm-live-costs`. Do not call the older unbudgeted MVP collector, direct HTTP or another run's collector. Keep query scope in the research query map and limit requests to meaningful priority clusters. The helper supports the same bounded suggestions, overview and depth-10/20 SERP plans as selection, but accounts charges to the separate production batch.

The helper reserves before transport, retains actual costs/raw evidence, reuses matching fresh responses, and blocks on unknown billing, excessive charges, missing approval or exhausted budget. The original selection ledger is also checked. If the user explicitly asks to fix its transport-failure billing hold and continue within a shared cap, follow the narrow reviewed-reservation recovery in the runner reference: keep the full unknown charge reserved, preserve the original ledger, and bind a fresh free task-history check. This is not a zero-cost reconciliation, a retry permission, or an automatic exception for future failures. No automatic top-ups or new subscriptions. Model/tool usage outside DataForSEO is not included in this research cap.

## What the gates prove

The runner checks stage order, source-queue identity, receipt/input/output hashes, basic claims structure, supported claim IDs in draft traces, QA score arithmetic/thresholds and review limits. It cannot prove prose quality, factual truth, screenshot rights, source freshness for each specific claim, or a complete semantic brief by itself. Those checks belong to the executing and receiving skills and must be honestly documented. A passed receipt is a review record, not independent proof.

Report finished articles, current stage, remaining approved scope, costs and blockers. Do not claim autonomous operation or publication that did not happen.
