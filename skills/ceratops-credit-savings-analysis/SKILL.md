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

## Design Reference

`README.md` is the authoritative architecture and maintenance reference. Read
it before changing or diagnosing this skill's workflow, schemas, persistence,
retry, recovery, or deployment behavior.

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
  `python scripts/credit-analysis-workflow.py run --request REQUEST`.
- On every fresh single-thread or per-thread-batch plan, validate the installed
  contract and bind its version and hash to controller state. Resume only from
  state whose immutable artifacts still validate. Require mutation authority
  `false`, use a task root under `<repo-parent>/tmp/<repo-name>/<thread-name>`,
  and keep retained evidence inside it.
  Analyze every available retained descendant discovered from source lineage as
  ordinary source runs; report unavailable references and exclude only
  descendants created by the current analysis.
- Planning retains complete protected evidence and read-only canonical
  snapshots. Full analysis treats every completed run as one semantic unit,
  freezes run order and UTF-8 byte counts, and divides only an oversized run
  into
  the minimum ordered input parts that each fit Luna. Calls remain attached to
  their run context. If seventy Luna attempts cannot cover all prepared
  evidence,
  prioritize the largest runs and their immediate successors, admit as many
  ordered parts as the remaining slots allow, and record the exact unreviewed
  remainder. Retain input bytes, planned Luna-output bytes, and actual output
  bytes for every run part. Reserve the controller prompt and output schema
  inside each proven UTF-8 input envelope.
- The end-to-end `run` command executes or resumes the frozen plan. Keep
  `plan --request` for planning-only inspection and `execute --state` for direct
  state-path resume. Treat controller state, evidence and manifest hashes, task
  identities, candidate membership, prompts, results, and attempt telemetry as
  authoritative. Execution never recollects the session. Never skip, repeat,
  reorder, or add a semantic task outside the manifest.
- Before freezing child tasks, read and retain the complete effective global
  and run-local `AGENTS.md` chain once. If a recorded canonical worktree cwd is
  gone, use its primary checkout only after exact repository-identity
  verification and record the substitution. Launch Luna from each verified run
  cwd and Sol from the verified primary cwd; retain the frozen chain hash on
  every task and attempt and give Sol the frozen hash and frozen differing
  run-local rule text. During execution and resume, validate the retained rule
  snapshot from its stored text and hashes without rereading live `AGENTS.md`;
  later live instruction changes do not invalidate accepted or pending analysis
  tasks. Stop on an unresolved source or rule-snapshot omission; never fall
  back to task temporary root.
- The controller validates `gpt-5.6-luna` and `gpt-5.6-sol` at maximum effort
  from the local Codex catalog. Luna and Sol children retain native rollout
  state. Every child is approval-free and read-only. The
  controller owns waiting, timeout, process-tree termination, non-model
  progress,
  prompts, evidence, results, and telemetry, and never spends model calls
  polling
  children. Accepted calls and attempts retain immutable hashes and resumable
  attempt records.
  Validate and durably checkpoint each completed child while siblings continue.
  Keep shared orchestration state mutations in the controller and final ordering
  deterministic.
- Luna performs high-recall discovery across all five fixed surfaces together.
  Run up to fifteen Luna children concurrently and admit no more than seventy
  Luna attempts for one frozen thread tree, including corrective reruns. Launch
  Luna with a retained native session so a later analysis can collect it as an
  ordinary descendant thread. Before launch, assign every admitted run part to
  one of up to six Sol reviewers. Calculate each Luna's output-byte allowance
  from its reviewer's fixed input and remaining proven capacity, then freeze and
  prove every assignment at its planned maximum. If a Luna result violates its
  schema or allowance, rerun that task once with a smaller output allowance; if
  it still fails, report that run part as unreviewed and continue. Never
  truncate
  a result, detach calls from their run context, or create per-surface Luna
  calls.
- A temporary-control review governs only its described owner/control subclaim
  and does not veto an independent finding carried by the same candidate. Route
  every retained Luna candidate exactly once to its preassigned reviewer. Apply
  the unassessed-call ceiling only to the aggregate routed call set. When that
  aggregate exceeds the ceiling and both Sol limits permit, review only
  the unassessed calls with their complete run-part context and replace those
  classifications; prioritize this recovery over optional direct-evidence
  review. After the parallel reviewers and any recovery or direct-evidence
  review finish, run one dependent final Sol to judge candidates without an
  accepted decision and deeply verify the top three deduplicated owner/control
  findings against exact evidence. Code carries accepted judgments into the
  final result and produces the report. Each rejected Sol task receives one
  automatic corrective retry when the sixteen-attempt ceiling permits. When the
  caller requests stop-on-validation-error, run model tasks serially and stop after
  the first rejection before another model call. After a non-final
  task fails validation twice, retain its exact unreviewed candidate, call, and
  byte inventory, exclude that inventory from final transport, and continue to
  the final merger. Plan at most eight Sol calls, excluding retries and
  corrective attempts; allow at most sixteen actual Sol invocations including
  initial calls, retries, and corrective attempts. The final Sol does not
  re-adjudicate every candidate or receive the complete source tree.
- Restore canonical identifiers, derive candidate dispositions from finding/risk
  links, and derive nonsemantic summaries, ordering, surfaces, workstreams,
  repeated evidence, final helper-category summaries, and savings arithmetic
  in code. The final Sol returns an empty
  helper-category review array; copy exact accepted reviewer records and
  assemble that section in the controller. Sol adjudicators merge overlaps and
  temporary controls, apply recurrence and ROI rules, and classify source calls
  in grouped form. Persist result-size,
  duration, visible-token, and reasoning-token telemetry as diagnostics. Run no
  model bookkeeping calls; stop before execution when the finite plan is
  malformed or changes admitted run, part, or candidate coverage.
  Generate model-facing schemas and Python shape checks from one shared response
  contract, preserving independent evidence and semantic validation. Give each
  existing corrective retry its complete retained prior response,
  exact validation errors, and deterministically diagnosed invalid-claim scope
  inside the proven input envelope. Reconsider only those invalid claims against
  the same evidence: correct supported estimates or withdraw unsupported
  findings
  with their dependent references and call accounting. Preserve accepted
  results,
  complete coverage, valid identifiers, and unaffected judgments; repair invalid
  identifiers consistently with their references. Do not invent savings to pass
  validation.
- The planner attempts every completed run. When the seventy-Luna cap prevents
  complete transport, retain exact partial-coverage records by run and part
  identity, record count, input bytes, candidate count, and output bytes.
  Continue
  with every admitted part and never imply that the unreviewed remainder was
  semantically reviewed. When eight planned Sol calls cannot preserve all
  accepted
  Luna findings, retain the exact candidate and byte inventory of the unreviewed
  overflow.
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
  multiplied by estimated affected-run frequency. A `model-calls` finding must
  save at least `floor(3% × frozen source-call count)` calls per similar run;
  zero is allowed only when that floor is zero. State assumptions, test ROI at
  the low end of the frequency range, and reject non-positive lifetime value
  unless correctness or safety independently requires the control.
- Report priced credit only when the controller accepted a valid caller-supplied
  pricing profile. Never describe token volume as monetary or credit cost
  without that profile.

## Cross-Surface Completion

### Completion Gate

- A surface is complete only when Luna has received every admitted run part,
  each retained candidate has one Sol adjudication, every confirmed finding and
  plausible risk for that lens remains in the final result, and every capacity
  omission is explicit. Do not require a semantic dismissal record for every
  call-surface pair.
- `full-analysis` is complete only after the frozen manifest accounts for every
  completed run as reviewed or exactly omitted, proves ordered non-overlapping
  parts and candidate routing, and records immutable Luna, Sol-reviewer,
  direct-evidence-reviewer, and final-task identities and hashes.
  Temporary-control contributions are merged once by owner/control; every
  retained candidate has one disposition;
  every confirmed finding remains; every reviewed source call has one primary
  grouped classification; capacity-omitted calls are excluded from semantic
  classification; overlaps do not double-count savings; and finalization
  succeeds idempotently.
- A standalone action is complete only after the selected surface result is
  accepted and controller finalization succeeds.

### Output Contract

- Retain every finding and its full assessment in machine evidence. In chat,
  select only the most useful still-actionable findings from the entire
  requested scope, including earlier runs when presenting a later recheck.
  Group findings only when the same fix addresses them without hiding a
  distinct owner or failure. Give the direct result first.
- Prioritize supported recurring net savings and verified one- or two-line
  fixes. By default, present at most five recommendations in chat; use a
  different limit when the user specifies one. Do not fill a quota. Keep minor
  and verified-resolved findings in machine evidence; provide details on request.
- Give each selected finding a concrete title and three short parts:
  - `Problem:` the observed episode, affected tasks and run dates, what failed,
    and the avoidable work.
  - `Proposed fix:` the exact change and where it belongs.
  - `Benefit and effort:` supported savings and implementation effort, with
    material assumptions and any uncertainty that changes the recommendation.
- For a script-related finding, name the verified repository-relative filename
  and relevant function, command, or setting in the problem and proposed fix.
  Replace generic labels such as "validation" with that concrete owner. For
  a non-file action, identify the exact action and correction instead.
- Distinguish maintained source from an installed copy or temporary caller.
  Attribute the failure to the component supported by evidence. If the file
  was deleted, say so; if the owner is unverified, state what must be checked
  before offering an implementation-ready fix. Never invent a persistent file.
- Explain the before-and-after behavior of the fix; a filename alone is not a
  recommendation. Retain exact supporting evidence and the behavior check for
  every included gap in machine evidence. Verify a one- or two-line effort
  claim against the actual change it requires.
- An existing rule or safeguard does not prove the observed problem is fixed.
  Distinguish its existence from evidence that the corrected behavior works;
  preserve the existing machine classification and ROI rules.
- Distinguish observed avoidable calls from forecast savings. Keep text-volume
  savings separate from call savings, and state when credit or token savings
  cannot be quantified. Retain full cost and complexity analysis in machine
  evidence without reproducing every field in chat.
- Report the audit's own recorded analysis-call count and token usage
  separately from source-task usage; mark unavailable usage as unavailable.
- Keep findings self-contained and use plain language before implementation
  terms. Show internal status labels or confidence ratings only on request.
  Show internal identifiers or helper taxonomy only on request. Give analysis
  artifact paths only on request and omit routine operational detail.
- Retain every plausible risk and its full assessment in machine evidence:
  what was observed and unknown, why it is not confirmed, and how to confirm
  it. In chat, surface a risk only when it materially changes
  the recommendation or the reliability of the conclusions. State its unknown
  and the exact check needed; exclude it from confirmed savings.
- For full analysis, the saved human report contains only the runs table
  defined by the action. Retain complete accounting and detailed findings in
  machine evidence; disclose consequential coverage gaps briefly in chat.
  Never imply omitted evidence was reviewed. For a standalone action, state
  its surface limit and that it is not a whole-thread reconciliation.

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
  selection is invalid, controller evidence is stale or mismatched, or required
  semantic evidence is unavailable. Do not substitute visible conversation
  context for controller evidence.
