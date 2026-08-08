# Full Analysis Action

## Goal

Run the fixed controller queue with one shared evidence bundle, one focused
model pass per public surface, and one internal synthesis pass. Preserve and
present every confirmed finding.

## Inputs And Constraints

- Use the source, completed-run window, task temporary root, retained evidence
  path, optional pricing profile, and contract version required by the parent.
- For one source, accept an explicit thread ID or session path, the current
  thread, or one exact thread name. Resolve the current thread only from
  `CODEX_THREAD_ID`; resolve a name against the latest thread-index records and
  stop on zero or multiple matches.
- For a per-thread batch, accept either the latest positive thread count or all
  threads updated during a positive day interval, optionally filtered by one
  exact project name, absolute path, or repository URL. Freeze an exact UTC
  `as_of` boundary. Date selection uses thread-index `updated_at`; every
  selected thread is then analyzed over all of its completed runs.
- Use the controller-owned batch request schema with action `full-analysis`,
  mode `per-thread-batch`, selector, `as_of`, caller-selected task root and
  retained manifest output, optional pricing profile, both expected contract
  versions, and mutation authority fixed to false.
- Prepare with action and mode `full-analysis`. Do not run a standalone surface
  in parallel or collect another bundle.
- Follow only the pending surface. Do not draft findings for later surfaces.

## Workflow

1. Run controller `prepare` once and use its pending surface, context, and exact
   result path.
2. For each of the five public surfaces, load that surface's direct reference
   and pending context, perform one focused semantic pass, write one complete
   surface result, and call `advance`.
3. When `advance` opens `synthesis`, load only the complete call inventory,
   compact normalized accepted findings, dismissals, exclusions, and
   deterministic totals from its context. Do not reload raw session material.
4. Preserve every confirmed finding; group cohesive remediation by owning
   producer; assign each avoidable call to exactly one primary finding; retain
   applicable secondary mappings; classify every call exactly once; order every
   finding by expected value without suppressing any; and write the synthesis
   result to the exact pending path.
5. Run controller `finalize`. On interruption, retain state and accepted results
   and resume with `status`.

For a batch, run `prepare-batch` once to freeze the selection and prepare one
controller per thread. Complete each child through `advance-batch` and resume
with `status-batch`. After all children finish, run one internal `batch-summary`
pass that assigns every finding to one summary group, then advance and finalize.
Never recollect a prepared session or create a temporary discovery script.

## Completion Gate

Complete only when finalization returns `OK` and retained machine evidence
contains every accepted pass, finding, risk, dismissal, exclusion, primary and
secondary mapping, category and surface total, producer group, and ROI input.
For a batch, every selected child must also be finalized and indexed exactly
once before batch finalization succeeds.

## Output Contract

Group every confirmed finding by owning producer or control, ordered by
expected value. For each finding report its ID, contributing surfaces and
helper categories, concrete episode, affected calls, deduplicated avoidable
count, all confirmed gaps, implementation status, cohesive control, targeted
verification, expected calls saved per affected and similar run, implementation
cost, ongoing complexity, confidence, and assumptions.

Also report plausible unverified risks separately; necessary and
protocol-overhead totals; avoidable versus total calls; priced cost only when
available; and the retained final machine-evidence path. Never limit the output
to a champion or top recommendation.

For a batch, group similar findings across threads. List each finding with its
thread under exactly one summary group, report per-thread totals and the retained
batch result, and plan six passes per thread plus one `batch-summary` pass.
