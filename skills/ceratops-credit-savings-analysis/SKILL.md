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
- For a single-thread full analysis or standalone surface, run
  `python scripts/credit-analysis-workflow.py plan --request REQUEST` once.
  Each request must set `mutation_authority` to `false`, name a caller-selected
  task temporary root and retained evidence output, and use the current contract
  versions. Planning collects and parses the selected session exactly once;
  records an immutable collection cutoff and source lineage; rejects
  controller-generated analysis-child sessions through a stable marker; retains
  complete protected evidence;
  snapshots referenced final canonical artifacts read-only; builds causally
  adjacent episodes once; maps every candidate to its applicable surfaces;
  freezes finite shared chunks; and reports projected Luna and Sol calls before
  model execution.
- Run `python scripts/credit-analysis-workflow.py execute --state STATE` to
  execute or resume the frozen plan. Treat controller state, evidence and
  manifest hashes, task identities, candidate membership, prompts, results,
  and attempt telemetry as authoritative. Execution never recollects the
  session. Never skip, repeat, reorder, or add a semantic task outside the
  manifest.
- The controller validates `gpt-5.6-luna` and `gpt-5.6-sol` with maximum
  reasoning effort from the local Codex catalog. It launches explicit-model,
  ephemeral, read-only, approval-free child executions, waits internally,
  emits non-model progress, and persists controller-owned prompt, schema,
  evidence, event, and result files. Accepted semantic calls and all attempted
  calls have separate ledgers; failed attempts remain hashed and resumable.
  Child prompts are self-contained and prohibit tools and mutation.
- Every selected call belongs to exactly one shared Luna primary chunk. A Luna
  call receives one causally ordered episode packet and accounts for every
  applicable candidate-surface pair as provisional-finding evidence, plausible
  risk, dismissed with reason, or necessary exclusion with evidence.
  Deterministic code validates identifiers and complete coverage but makes no
  semantic classification. No selected call is omitted from Luna or truncated
  from retained evidence to make a packet fit.
- Run exactly one `gpt-5.6-sol` confirmation per public surface against original
  evidence for all Luna findings and risks, every observably high-signal episode
  even when Luna dismissed it, and a deterministic audit sample of ordinary
  dismissals. If this material exceeds one surface packet, use only the finite
  Luna consolidation queue and preserve every selected candidate ID and material
  variant. Run exactly one `gpt-5.6-sol` synthesis and no GPT-5.6 bookkeeping
  calls. Stop before model execution when the shared plan is empty, malformed,
  or exceeds the contract's semantic-call cap; never truncate source coverage.
- Keep session evidence, accepted surface results, the append-only index, and
  the final machine result at their controller-retained paths. Do not echo raw
  session material or caller-local paths unnecessarily.
- Preserve the existing `prepare-batch`, `advance-batch`, `status-batch`, and
  `finalize-batch` compatibility interface for recent-thread selection and
  aggregation. Its child-controller and batch-summary contracts remain
  lower-level interfaces; group similar findings for presentation while
  preserving each thread's findings and totals.

## Common Classification And ROI Rules

- Count spend as avoidable only when available instructions, fresh evidence,
  stable contracts, direct helper composition, same-pass revision, or a cheap
  targeted check could have prevented or reduced it. Exclude ordinary model
  mistakes unless a concise durable producer control would materially reduce
  recurrence.
- Exclude calls required by active freshness, safety, verification, controlled
  iteration, or workflow gates. Record conversational tool-protocol overhead as
  necessary rather than as a helper defect. Surface passes and synthesis make
  evidence-backed semantic classifications; deterministic code only groups
  observable evidence, expands selected clusters, and validates the result.
  Calls with an explicit decision-blocking evidence gap remain `unassessed`.
  Calls reviewed by every relevant surface without confirmed waste or a
  necessary exclusion are `reviewed-no-confirmed-waste`; this category is
  neither necessity nor savings.
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

- A surface is complete only after Luna covers every applicable
  candidate-surface pair exactly once and the controller accepts one immutable
  Sol confirmation covering every selected material, high-signal, and audited
  candidate against original evidence. A zero-finding surface must still retain
  Luna's dismissal, risk, or exclusion for every applicable candidate.
- `full-analysis` is complete only after the frozen manifest proves complete,
  ordered, non-overlapping shared primary coverage; every Luna task and exactly
  five Sol confirmations plus one Sol synthesis have immutable identity and
  content hashes; temporary-control contributions are merged once by
  owner/control; every confirmed finding remains; every model call has one
  primary classification; overlaps do not double-count savings; and controller
  finalization succeeds.
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
- Report necessary, protocol-overhead, avoidable,
  reviewed-no-confirmed-waste, and unassessed call totals separately. Never
  describe reviewed or unassessed calls as necessary.

## Analysis-Only Boundaries

### Boundaries

- Never modify the analyzed prompt, helper, script, skill, instructions,
  repository, automation, workflow, or tool configuration. Route any later
  implementation through the owning lifecycle after a separate execution
  request.
- Collection and synthesis are internal controller phases. Do not expose Luna
  chunking, consolidation, `collect`, `reconcile`, `synthesis`, `apply`, or
  `modify` as public actions.
- Stop blocked when a selected source cannot be resolved, the completed-run
  window is invalid, controller evidence is stale or mismatched, or required
  semantic evidence is unavailable. Do not substitute visible conversation
  context for controller evidence.
