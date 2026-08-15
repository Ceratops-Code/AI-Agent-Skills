---
name: ceratops-credit-savings-analysis
description: Analyze one credit-waste surface or every completed run in one or more threads while preserving every confirmed finding without modifying the analyzed producer or workflow.
---

# Ceratops Credit Savings Analysis

## Goal

Analyze completed model-call evidence for avoidable credit spend. Use
`full-analysis` for a generic single-thread or closure request, and one named
surface only when the user names it. This skill recommends controls but never
applies them.

## Public Action Routing

### Action References

- Run the all-run fixed-surface analysis:
  `references/full-analysis.md`
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
- For a single-thread full or standalone analysis, run
  `python scripts/credit-analysis-workflow.py run --request REQUEST`. On a fresh
  request, the controller plans once; rerunning the exact request resumes its
  state. Require mutation authority `false`, current contract versions, and a
  caller-selected task root under
  `<repo-parent>/tmp/<repo-name>/<thread-name>`. Keep retained evidence inside
  that task root.
  Planning collects and parses the selected session exactly once, freezes its
  cutoff before child execution, and assigns exact controller lineage. Analysis
  A excludes only its own recorded descendants. A later analysis B may inspect
  A's retained prompts, model calls, latency, failures, token usage, and
  orchestration while excluding only B's descendants. Keep analysis-generated
  work separate from producer work and savings attribution.
- Planning retains complete protected evidence and read-only canonical
  snapshots. Full analysis treats every completed run as one semantic unit,
  freezes run order and UTF-8 byte counts, and partitions only an oversized run
  into the minimum ordered transport windows. Never analyze calls independently
  of their run. Retain the evidence bytes, planned Luna-output bytes, and actual
  Luna-output bytes for every run and window. Reserve the controller prompt and
  output schema inside each proven UTF-8 input envelope; do not budget the JSON
  evidence packet as though it were the child's entire visible input.
- The end-to-end `run` command executes or resumes the frozen plan. Keep
  `plan --request` for planning-only inspection and `execute --state` for direct
  state-path resume. Treat controller state, evidence and manifest hashes, task
  identities, candidate membership, prompts, results, and attempt telemetry as
  authoritative. Execution never recollects the session. Never skip, repeat,
  reorder, or add a semantic task outside the manifest.
- Before freezing child tasks, resolve and hash the effective global and
  run-local `AGENTS.md` chain. Launch each Luna task from its run's verified
  source cwd. Launch Sol from the source's primary cwd and include the effective
  rule hashes and the text of any differing run-local rules in its retained
  handoff. Bind the applicable chain hash to every task and attempt. Stop or
  report the exact rule-evidence omission rather than silently running from the
  task temporary root without the applicable project rules.
- The controller validates `gpt-5.6-luna` and `gpt-5.6-sol` at maximum effort
  from the local Codex catalog. Luna children are ephemeral; Sol children retain
  native rollout state. Every child is approval-free and read-only. The
  controller owns waiting, timeout, process-tree termination, non-model progress,
  prompts, evidence, results, and telemetry, and never spends model calls polling
  children. Accepted calls and attempts retain immutable hashes and resumable
  ledgers.
- Luna performs high-recall discovery across all five fixed surfaces together.
  Run up to ten Luna children concurrently and admit no more than fifty Luna
  model-call attempts for one source, including corrective reruns. Queue ordered
  run windows without a one-window-per-run scheduling barrier. If a Luna result
  violates its frozen schema or output-byte envelope, rerun that exact task once
  with a smaller output allowance; if it still cannot fit, record that complete
  window as omitted and continue within the fifty-attempt cap. Never truncate a
  result, split a run window, detach calls from their run context, or create
  per-surface Luna calls.
- Measure accepted Luna outputs before Sol planning. Route every retained Luna
  candidate exactly once among three Sol adjudicators; add a fourth only when
  three cannot fit the measured reports. Run one separate Sol audit against one
  unsurfaced raw window from the largest run and one deterministically
  highest-signal unsurfaced raw window. Run those four or five first-stage Sol
  tasks concurrently, then one dependent final Sol to merge their compact
  judgments, produce the report, and deeply verify the top three deduplicated
  owner/control findings against exact raw evidence. A normal plan uses five Sol
  calls and the overflow plan uses six; never exceed six. The final Sol does not
  re-adjudicate every candidate or receive the full source evidence.
- Restore canonical identifiers and derive nonsemantic summaries, ordering,
  surfaces, workstreams, repeated evidence, and savings arithmetic in code. Sol
  adjudicators merge overlaps and temporary controls, apply recurrence and ROI
  rules, and classify source calls in grouped form. Persist result-size,
  duration, visible-token, and reasoning-token telemetry as diagnostics. Run no
  model bookkeeping calls; stop before execution when the finite plan is
  malformed or changes admitted run, window, or candidate coverage.
- The planner attempts every completed run. If the fifty-Luna or six-Sol hard
  cap still prevents transport after the allowed Luna correction, retain exact
  capacity omissions by run and window identity, record count, evidence bytes,
  candidate count, and output bytes. Continue with every fitting task and never
  imply that omitted evidence or candidates were semantically reviewed.
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

- A surface is complete only when Luna has received every admitted run window,
  each retained candidate has one Sol adjudication, every confirmed finding and
  plausible risk for that lens remains in the final result, and every capacity
  omission is explicit. Do not require a semantic dismissal record for every
  call-surface pair.
- `full-analysis` is complete only after the frozen manifest accounts for every
  completed run as reviewed or exactly omitted, proves ordered non-overlapping
  windows and candidate routing, and records immutable Luna, Sol-adjudicator,
  audit, and final-task identities and hashes. Temporary-control contributions
  are merged once by owner/control; every retained candidate has one disposition;
  every confirmed finding remains; every reviewed source call has one primary
  grouped classification; capacity-omitted calls are excluded from semantic
  classification; overlaps do not double-count savings; and finalization
  succeeds idempotently.
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
- For full analysis, report necessary, protocol-overhead, avoidable,
  reviewed-no-confirmed-waste, and unassessed totals separately. Report completed
  runs, every admitted or omitted window's record count, input bytes, output
  allowance, actual output bytes, evidence and output totals, and semantic
  coverage. Never imply that omitted runs, windows, calls, or candidates were reviewed.

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
