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
- Run `python scripts/credit-analysis-workflow.py start --request REQUEST`
  once per selected thread, directly or through controller-owned batch
  preparation. This collects the session once and returns the first complete
  semantic-pass packet. Each request must use the controller-owned schema, set
  `mutation_authority` to `false`, name a caller-selected task temporary root
  and retained evidence output, and use the current contract versions.
- Treat the controller's structured contract, state, evidence fingerprint,
  pending surface, pass ID, context path, and result path as authoritative.
  Never skip, repeat, reorder, pre-analyze, or append a pass outside the
  controller.
- For each pending packet, make the semantic judgment once, write only its
  compact decision to the exact path, and invoke the packet's `submit` command
  in the same orchestration tool call. The controller constructs and validates
  the full result, persists it, advances or finalizes, cleans transient files,
  and returns the next packet. Do not spend separate model turns on those
  bookkeeping steps. Resume with `status --packet` without recollecting.
- Keep session evidence, accepted surface results, the append-only index, and
  the final machine result at their controller-retained paths. Do not echo raw
  session material or caller-local paths unnecessarily.
- For batches, group similar findings for presentation while preserving each
  thread's findings and totals.

## Common Classification And ROI Rules

- Count spend as avoidable only when available instructions, fresh evidence,
  stable contracts, direct helper composition, same-pass revision, or a cheap
  targeted check could have prevented or reduced it. Exclude ordinary model
  mistakes unless a concise durable producer control would materially reduce
  recurrence.
- Exclude calls required by active freshness, safety, verification, controlled
  iteration, or workflow gates. Record conversational tool-protocol overhead as
  necessary rather than as a helper defect. Semantic passes propose supported
  necessary exclusions; deterministic code only validates those exclusions.
  Calls with neither an accepted finding nor a supported exclusion are
  `unassessed`, never assumed necessary.
- Tie every confirmed finding to evidence call IDs, its producer and concrete
  owner when known, a plain-language problem summary, one durable control,
  implementation status, targeted verification, observed avoidable calls,
  recurrence range, confidence, one-time implementation cost, and Minimal,
  Low, Medium, or High ongoing complexity. Use Minimal only for a local one- or
  two-line correction with local verification; broader ownership, failure, or
  verification work is at least Low.
- Treat an overbroad command or tool result contract as tool-flow waste and
  unnecessarily selected or loaded model context as context-evidence waste.
  Preserve a supported overlap as secondary evidence without double-counting
  model calls. Mark a volume-only finding as `context-volume`, keep all of its
  call-savings fields at zero, and classify its evidence calls independently.
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
  synthesis are accepted exactly once, every assessed model call has one
  primary classification, the remainder is explicitly `unassessed`, every
  confirmed surface finding remains in the final result, secondary overlaps are
  retained without double-counting savings, and controller finalization
  succeeds.
- A standalone action is complete only after the selected surface result is
  accepted and controller finalization succeeds.

### Output Contract

- Retain every confirmed finding in machine evidence. Before the detailed list,
  report `Confirmed: N; outstanding: M; already addressed: K`. Show details only
  for outstanding findings unless the user requests all findings.
- Give each outstanding finding a plain-language title followed by:
  - `Problem:` two to four sentences naming the owner, concrete episode, what
    failed, and why the resulting work was avoidable.
  - `Evidence:` the affected-call count and relevant command, tool, artifact,
    answer, and user-correction sequence; show IDs only on request.
  - `Fix:` the exact durable control, its owner, and how it completes the flow
    end to end.
  - `Verification:` the exact behavior test proving every included gap.
  - `Savings:` observed calls, expected similar-run savings, implementation
    cost, ongoing complexity, and material assumptions.
- Do not show status labels, confidence, internal IDs, or helper taxonomy unless
  requested.
- Present each plausible risk separately with `Observed:` for the concrete
  sequence, `Unknown:` for competing explanations, `Why not confirmed:` for the
  exact missing fact and why choosing an explanation would be speculation, and
  `How to confirm:` for the exact metadata or test. Do not merge risks when that
  hides a distinct unknown or evidence source, and do not include a risk in
  confirmed savings. For standalone actions, state that the conclusion is
  limited to the selected surface and is not a whole-thread reconciliation.
- Report necessary, protocol-overhead, avoidable, and unassessed call totals
  separately. Never describe unassessed calls as necessary.

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
