# Full Analysis Action

## Goal

Run the all-run controller plan. Treat every completed run as one semantic unit,
use Luna for high-recall discovery across all five surfaces together, then use
capacity-sized Sol adjudication, audit, and final synthesis. Preserve every
confirmed finding and report every capacity omission.

## Inputs And Constraints

- Use the source, completed-run window, task temporary root, retained evidence
  path inside that root, optional pricing profile, and contract version required
  by the parent.
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
  retained manifest output inside that root, optional pricing profile, both
  expected contract versions, and mutation authority fixed to false.
- Prepare with action and mode `full-analysis`. Do not run a standalone surface
  in parallel or collect another bundle.
- Execute only frozen controller tasks. Luna discovers across the fixed surface
  set; Sol adjudicators, the separate audit, and the final merge remain internal
  phases of `full-analysis`.

## Workflow

1. Run controller `run --request REQUEST`. On a fresh request it resolves,
   collects, and parses the selected session once; freezes its cutoff and exact
   lineage before children; retains complete evidence from every completed run,
   including corrective follow-ups, and read-only canonical snapshots; separates
   prior analysis-generated activity from producer work; resolves and hashes the
   effective global and run-local `AGENTS.md` chain; and builds one ordered
   semantic run record per completed run. Measure UTF-8 bytes, not characters,
   and retain each run's record count, evidence bytes, planned Luna-output bytes,
   and actual output bytes. Reserve the visible controller prompt and output
   schema inside each child input envelope. Analysis A excludes only its own
   descendants; a later B may inspect A's retained analysis activity and excludes
   only B's.
2. The same controller run executes the frozen plan without recollection. In the
   normal case it sends one complete run record to one `gpt-5.6-luna` task at
   maximum effort. Split only an oversized run into the minimum ordered transport
   windows, preserve run order and cross-window metadata, and recombine the
   accepted windows into one run report. Never use calls as independent semantic
   units or create per-surface Luna tasks. Keep up to ten Luna tasks running
   concurrently without a one-window-per-run admission barrier. Admit at most
   fifty Luna model-call attempts for one source, including corrective reruns.
   Allocate flexible output bytes per task from the measured downstream Sol
   envelope rather than requiring one fixed output size.
3. Reject a Luna result only when it violates the frozen schema or output-byte
   envelope, not because it found many supported candidates. Rerun the exact task
   once with a smaller output allowance; if it still cannot fit, record that
   complete window as omitted and continue within the fifty-attempt cap. Record
   every unlaunched or unaccepted run window as omitted for capacity with its run
   and window identity, record count, evidence bytes, candidate count when known,
   output bytes when produced, and reason. Never split or truncate a run window.
4. Measure the retained Luna reports before Sol assignment. Route every retained
   candidate exactly once to one of three `gpt-5.6-sol` adjudicators at maximum
   effort. Each receives self-contained Luna reports and their embedded evidence
   references, not the complete source thread. A candidate with one or more
   confirmed subclaims uses `confirmed-finding` and may also link separate
   plausible risks from the same candidate. Require at least one
   temporary-control review for every temporary-control candidate; preserve
   multiple reviews when they describe distinct owner/control pairs.
   Add a fourth adjudicator only when
   the measured reports cannot fit three. In parallel, run one separate audit Sol
   against one unsurfaced raw window from the largest run and one
   deterministically highest-signal unsurfaced raw window. The three adjudicators
   plus audit normally form four concurrent first-stage Sol tasks; overflow uses
   four adjudicators plus audit.
5. Apply the unassessed-call ceiling to the complete routed call set, never to
   one preliminary Sol shard in isolation. Run one dependent final Sol after all
   first-stage Sol tasks finish. It merges compact judgments, temporary-control
   reviews, classifications, risks, and ROI
   inputs. Deduplicate likely owner/control identity before ranking, then deeply
   verify and expand the top three findings against exact raw evidence. The final
   Sol does not re-adjudicate every candidate, and the top-three review is not a
   cap on confirmed findings or presentation. A normal plan uses five total Sol
   calls; measured-output overflow uses six. Never exceed six. If six cannot fit,
   omit only deterministic overflow, retain its exact run/window/candidate and
   byte inventory, and never claim it was adjudicated.
6. Persist immutable identities, prompts, results, attempts, latency, and usage.
   Before surfacing one parallel sibling failure, record every already-completed
   sibling attempt. On resume, revalidate complete task-owned attempt artifacts
   against the frozen prompt, schema, identity, input hash, and result contract
   before launching; block incomplete or conflicting artifacts. Wait without
   model polling, terminate the complete child process tree on interruption or
   timeout, and resume accepted phases idempotently. Run no model bookkeeping
   calls.

Every child Codex execution uses an explicit model, a read-only sandbox, no
approvals, a self-contained no-tools prompt, and controller-owned schema, event,
and result files. Launch Luna from the verified source cwd for its run with
ephemeral state. Launch Sol from the source's primary cwd without ephemeral
state, and include retained effective-rule hashes plus the text of any differing
run-local rules in its handoff. Bind the applicable rule-chain hash to every task
and attempt. The controller waits internally and emits periodic
non-model progress. Resume the exact request. Alternatively use
`execute --state STATE`; never recollect prepared evidence or overwrite an
accepted result. Use `plan` only for planning-only inspection.

For a batch, run `prepare-batch` once; it freezes selection and plans one
ordinary holistic child per selected thread. For the pending child returned by
`status-batch`, run `execute --state CHILD_STATE`, then pass its retained final
result to `advance-batch`. Repeat until the batch-summary phase, satisfy that
existing summary contract, advance it, and run `finalize-batch`. This preserves
the existing batch manifest and summary contracts and does not expose Luna
windows, Sol adjudication, audit, or merge as public actions. Never collect a
child through a parallel controller or create a temporary discovery script.

## Completion Gate

Complete only when orchestration status reports `complete: true` and retained
evidence contains the frozen manifest; the identity, byte accounting, and result
of every admitted Luna window and Sol task; one disposition for every retained
Luna candidate; every confirmed finding, plausible risk, temporary-control
review and merge, call classification, producer group, and ROI input; and the
exact inventory of every capacity omission. Label semantic coverage incomplete
when any omission exists.
For a batch, every selected child must also be finalized and indexed exactly
once before batch finalization succeeds.

## Output Contract

Start with coverage: completed runs and semantic run units; planned, reviewed,
and omitted windows; evidence bytes reviewed and total; coverage percentage;
actual Luna and Sol calls; and one row per window with records, input bytes,
output allowance, actual output bytes, and status. For every omission, show
`Run | Window | Records | Evidence bytes | Candidate count | Output bytes |
Reason`. Do not render a capacity omission as zero findings or zero avoidable
calls.

First show this exact run table:

`Completed run | Total model calls | Avoidable calls - Fix Implemented |
Avoidable calls - Fix Unimplemented | Token usage (total; input % of total/cached
% of input/output % of total/reasoning output % of output)`.

Use each run's `started_at`, not its turn ID, and include a totals row. Show total
tokens as an integer and percentages to two decimal places; do not show raw
category token counts. Use numeric classification values only for reviewed
calls. When a run is wholly or partly omitted, state `not reviewed` or the
reviewed and capacity-omitted call counts in the affected cells rather than
zero.

For every still-unimplemented control, show this exact control table:

`Proposed control | Calls saved per affected run | Est. Percent of Affected
Similar Runs | Additional Calls per Affected Run for Implemented Fix | Est.
Calls Saving by Fix per Similar Run | New Complexity Introduced by Fix |
One-time implementation cost (model calls) | Recommendation`.

Retain every confirmed finding in machine evidence. Present every verified
unimplemented Minimal finding whose durable correction is one or two lines,
regardless of count, and every other unimplemented finding whose low-end
expected saving exceeds one model call per similar run. Follow the parent
plain-language `Problem` and `Fix` format. Present remaining confirmed controls
in the control table and counts without claiming they received deep review.

Before selecting the top three for extra verification, deduplicate by likely
owner/control. Rank deterministically by recurrence across runs, affected-call
count, evidence bytes, direct error/retry/user-correction sequence, identifiable
owner, then stable finding ID. Deeply verify and expand the top three, but do not
suppress any other qualifying finding.

Report confirmed input/output-volume waste even when it saves zero model calls,
but exclude it from call-savings arithmetic. For every such finding, report its
aggregate input, cached-input, output, tool-argument, and tool-result evidence;
state when none was confirmed.

Explain plausible risks under the parent contract. Also report necessary,
protocol-overhead, reviewed-no-confirmed-waste, and unassessed totals;
outstanding avoidable calls versus total calls; priced cost only when
available; and the retained analysis-result path.

For a batch, group similar findings across threads under plain-language problem
titles, apply the same ordering, identify affected threads, report per-thread
totals, and provide the retained batch result.
