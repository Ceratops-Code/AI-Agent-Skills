# Full Analysis Action

## Goal

Run the fixed controller queue with one shared evidence bundle, one focused
model pass per public surface, and one internal synthesis pass. Preserve every
confirmed finding and present every outstanding finding.

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
   applicable secondary mappings; and order every finding without suppression.
   For accounting, follow the controller's `classification_group_contract` and
   group calls with the same classification, primary finding, and reason in
   `classification_groups` using 1-based inventory positions; do not perform
   separate semantic review for each call. Keep `context-volume` findings
   outside call-savings mappings and write the synthesis result to the exact
   pending path.
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

Report only outstanding confirmed findings; retain every finding in machine
evidence. Follow the parent plain-language `Problem` and `Fix` format. Include
expected calls saved per affected and similar run, implementation cost, and
ongoing complexity. Report confirmed input/output-volume waste even when it
saves zero model calls, but exclude it from call-savings arithmetic.

Put Minimal findings first. Within Minimal and then all remaining findings,
sort by expected calls saved per similar run descending, using finding ID only
as the deterministic tie-breaker. Do not use producer, helper category, or
internal controller identity as a presentation group.

Explain plausible risks under the parent contract. Also report necessary and
protocol-overhead totals; outstanding avoidable calls versus total calls;
priced cost only when available; and the retained final machine-evidence path.
Never suppress an outstanding finding.

For a batch, group similar findings across threads under plain-language problem
titles, apply the same ordering, identify affected threads, report per-thread
totals, and provide the retained batch result.
