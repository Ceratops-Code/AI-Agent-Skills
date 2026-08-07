---
name: ceratops-credit-savings-analysis
description: Analyze one credit-waste surface or run comprehensive per-thread analyses for the current thread, a named thread, or recent threads overall or in one project, preserving every confirmed finding without modifying the analyzed producer or workflow.
---

# Ceratops Credit Savings Analysis

## Goal

Analyze completed model-call evidence for avoidable credit spend. Use
`full-analysis` for a generic or comprehensive request and select one named
surface only when the user names it. This skill recommends controls but never
applies them.

## Public Action Routing

### Action References

- Run the complete fixed-surface analysis: `references/full-analysis.md`
- Analyze deterministic helper contracts: `references/helper-contracts.md`
- Analyze context and evidence reuse: `references/context-evidence.md`
- Analyze rework and validation: `references/rework-validation.md`
- Analyze tool and handoff flow: `references/tool-flow.md`
- Analyze instructions and reasoning flow: `references/instruction-reasoning.md`

## Shared Evidence And Controller Invariants

- Resolve one exact source or one controller-frozen per-thread source set. The
  current thread is only the valid `CODEX_THREAD_ID`; never infer it from
  recency. Exact-name and recent-thread selection use the versioned source
  contract. An incremental closure begins strictly after the previous completed
  closure; active runs and the boundary run are excluded.
- Run `python scripts/credit-analysis-workflow.py prepare --request REQUEST`
  once per selected thread, directly or through controller-owned batch
  preparation. Each request must use the controller-owned schema, set
  `mutation_authority` to `false`, name a caller-selected task temporary root
  and retained evidence output, and use the current contract versions.
- Treat the controller's structured contract, state, evidence fingerprint,
  pending surface, pass ID, context path, and result path as authoritative.
  Never skip, repeat, reorder, pre-analyze, or append a pass outside the
  controller.
- For each pending pass, load only its direct action reference and controller
  context, write one structured result to the required path, and invoke the
  commanded `advance` or `finalize` operation. Use `status` to resume without
  recollecting evidence.
- Keep session evidence, accepted surface results, the append-only index, and
  the final machine result at their controller-retained paths. Do not echo raw
  session material or caller-local paths unnecessarily.
- In a batch, keep every thread as an independent analysis and aggregate only
  validated final machine results. Never claim cross-thread semantic synthesis
  or savings deduplication.

## Common Classification And ROI Rules

- Count spend as avoidable only when available instructions, fresh evidence,
  stable contracts, direct helper composition, same-pass revision, or a cheap
  targeted check could have prevented or reduced it. Exclude ordinary model
  mistakes unless a concise durable producer control would materially reduce
  recurrence.
- Exclude calls required by active freshness, safety, verification, controlled
  iteration, or workflow gates. Record conversational tool-protocol overhead as
  necessary rather than as a helper defect.
- Tie every confirmed finding to evidence call IDs, its producer and concrete
  owner when known, one durable control, implementation status, targeted
  verification, observed avoidable calls, recurrence range, confidence,
  one-time implementation cost, and Low, Medium, or High ongoing complexity.
- Compute net calls saved per affected run as prevented calls minus recurring
  calls introduced by the fix, and calls saved per similar run as that net
  multiplied by estimated affected-run frequency. State assumptions, test ROI
  at the low end of the frequency range, and reject non-positive lifetime value
  unless correctness or safety independently requires the control.
- Report priced credit only when the controller accepted a valid caller-supplied
  pricing profile. Never describe token volume as monetary or credit cost
  without that profile.

## Cross-Surface Completion

### Completion Gate

- A pass is complete only after the controller accepts its exact candidate
  coverage and immutable result. A zero-finding pass must dismiss or exclude
  every exposed candidate with a reason.
- `full-analysis` is complete only after all five public surfaces and internal
  synthesis are accepted exactly once, every model call has one primary
  classification, every confirmed surface finding remains in the final result,
  secondary overlaps are retained without double-counting savings, and
  controller finalization succeeds.
- A standalone action is complete only after the selected surface result is
  accepted and controller finalization succeeds.

### Output Contract

- Present every confirmed finding retained for the selected action and every
  plausible unverified risk. For standalone actions, state that the conclusion
  is limited to the selected surface and is not a whole-thread reconciliation.

## Analysis-Only Boundaries

### Boundaries

- Never modify the analyzed prompt, helper, script, skill, instructions,
  repository, automation, workflow, or tool configuration. Route any later
  implementation through the owning lifecycle after a separate execution
  request.
- Collection and synthesis are internal controller phases. Do not expose
  `collect`, `reconcile`, `synthesis`, `apply`, or `modify` as public actions.
- Stop blocked when a selected source cannot be resolved, the completed-run
  window is invalid, controller evidence is stale or mismatched, or required
  semantic evidence is unavailable. Do not substitute visible conversation
  context for controller evidence.
