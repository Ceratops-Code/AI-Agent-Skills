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
  Require mutation authority `false`, current contract versions, and a
  caller-selected task root under
  `<repo-parent>/tmp/<repo-name>/<thread-name>`. Keep retained evidence inside
  that task root.
  Planning collects and parses the selected session exactly once, freezes its
  cutoff before child execution, and assigns exact controller lineage. Analysis
  A excludes only its own recorded descendants. A later analysis B may inspect
  A's retained prompts, model calls, latency, failures, token usage, and
  orchestration while excluding only B's descendants. Keep analysis-generated
  work separate from producer work and savings attribution.
- Planning retains complete protected evidence and read-only canonical snapshots,
  builds one compact causal episode stream for every selected call, budgets each
  model packet from the effective local model context, splits that shared stream
  only when required, and reports projected Luna and Sol calls before execution.
- Run `python scripts/credit-analysis-workflow.py execute --state STATE` to
  execute or resume the frozen plan. Treat controller state, evidence and
  manifest hashes, task identities, candidate membership, prompts, results,
  and attempt telemetry as authoritative. Execution never recollects the
  session. Never skip, repeat, reorder, or add a semantic task outside the
  manifest.
- The controller validates `gpt-5.6-luna` at medium effort and
  `gpt-5.6-sol` at maximum effort from the local Codex catalog. It launches
  ephemeral, approval-free children and owns waiting, timeout, process-tree
  termination, non-model progress, prompts, evidence, results, and telemetry.
  Accepted calls and attempts retain immutable hashes and resumable ledgers.
- Every selected call appears exactly once in one ordered compact causal packet.
  Luna receives 100% of those packets and performs high-recall discovery across
  the five fixed surfaces, returning only plausible findings, risks, and
  temporary controls with candidate and evidence references. It does not emit a
  candidate-by-surface dismissal matrix or final savings. Complete oversized
  payloads remain on disk with length, hash, outcome, and bounded useful excerpts
  in model evidence; no selected call is silently omitted or truncated away.
- A normal full analysis runs one Luna discovery and one Sol adjudication. If
  the dynamically budgeted Luna packet cannot fit, partition the causal episodes
  once into the minimum ordered shared packets; do not impose a fixed Luna-call
  cap or create per-surface chunking or consolidation. Run exactly one Sol pass
  that verifies every Luna candidate against original evidence and returns only
  bounded semantic judgments through packet-local identifiers. Restore canonical
  identifiers and derive nonsemantic summaries, ordering, surfaces, workstreams,
  repeated evidence, and savings arithmetic in code; never bound findings,
  candidate coverage, or material variants. Sol merges overlaps and temporary
  controls, applies recurrence and ROI rules, classifies every source call in
  grouped form, and produces the final synthesis. Persist result-size, duration,
  visible-token, and reasoning-token telemetry as diagnostics only; treat the
  output reserve solely as overflow protection. Run no model bookkeeping calls;
  stop before execution when the finite plan is malformed, changes candidate
  coverage or order, or contains a packet boundary not required by the frozen
  evidence volume and effective context budget.
- Keep session evidence, accepted surface results, the append-only index, and
  the final machine result at their controller-retained paths. Do not echo raw
  session material or caller-local paths unnecessarily.
- Preserve the existing `prepare-batch`, `advance-batch`, `status-batch`, and
  `finalize-batch` compatibility interface for recent-thread selection and
  aggregation. `prepare-batch` plans one ordinary holistic controller per
  selected thread. Execute each pending child with `execute`, then pass its
  retained final result to `advance-batch`; never prepare or collect through a
  parallel child workflow. The batch-summary contract remains a lower-level
  interface; group similar findings for presentation while preserving each
  thread's findings and totals.

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
- Add the credit-specific evidence IDs, implementation status, call counts,
  recurrence, confidence, implementation cost, and ongoing-complexity fields
  required by the controller schema and Output Contract. Before proposing a
  missing control,
  validate its status against frozen current-source evidence for the relevant
  instructions, skills, automations, and helper contracts. When a durable
  safeguard already exists, mark the finding `implemented` and classify
  violating behavior as a compliance or runtime gap instead of proposing a
  duplicate control. Use Minimal only for a local one- or two-line correction
  with local verification; broader ownership, failure, or verification work is
  at least Low.
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

- A surface is complete only when Luna has received every applicable causal
  episode, Sol has adjudicated every surfaced candidate against original
  evidence, and all confirmed findings and plausible risks for that lens remain
  in the final result. Do not require a semantic dismissal record for every
  call-surface pair.
- `full-analysis` is complete only after the frozen manifest proves complete,
  ordered, non-overlapping call coverage; every Luna task and the single Sol task
  have immutable identity and content hashes; temporary-control contributions
  are merged once by owner/control; every confirmed finding remains; every source
  call has one primary grouped classification; unassessed calls stay within the
  contract limit; overlaps do not double-count savings; and finalization succeeds.
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
- Keep every finding concise, self-contained, and understandable without
  follow-up. Explain what happened and why the work was avoidable before using
  implementation jargon; define each necessary non-obvious term; name the
  broadest correct implementation scope and concrete next artifact or action;
  and omit routine operational detail.
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

### Research Boundaries

- Use frozen local evidence first. Run only a targeted official-source check
  when a concrete finding depends on current external behavior. Do not perform
  deep or broad research; when broader research is required, report the exact
  uncertainty and a concise paste-ready research prompt as the concrete next
  action.
- Treat intentional full skill-body injection as required runtime context, not
  avoidable spend. Never recommend changes to reasoning settings or levels.

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
