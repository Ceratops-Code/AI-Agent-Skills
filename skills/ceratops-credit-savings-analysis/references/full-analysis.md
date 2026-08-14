# Full Analysis Action

## Goal

Run the explicit exhaustive two-tier controller plan. Give Luna every compact
causal episode for high-recall discovery across all five surfaces, then use one
Sol pass to verify those candidates against original evidence and produce the
final synthesis. Preserve and present every confirmed finding.

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
- Execute only the next frozen controller task. Luna discovers across the fixed
  surface set and Sol adjudicates that complete set in one pass.

## Workflow

1. Run controller `plan` once. It resolves, collects, and parses the selected
   session once; freezes its cutoff and exact lineage before children; retains
   complete evidence from every completed run, including corrective follow-ups,
   and read-only canonical snapshots; separates prior analysis-generated
   activity from producer work; builds compact causal episodes once; dynamically
   budgets against the local model context; and reports the finite projected
   call count. Analysis A excludes only its own descendants; a later B may inspect
   A's retained analysis activity and excludes only B's.
2. Run controller `execute`. It never recollects. In the normal case it sends
   every causal episode in one packet to `gpt-5.6-luna` at medium effort. If the
   packet cannot fit, it uses the minimum ordered shared partition, never splits
   by surface or imposes a fixed Luna-call cap. Luna performs sparse high-recall
   discovery across the five fixed lenses without a dismissal for every call and
   lens combination.
3. Run exactly one `gpt-5.6-sol` pass at maximum effort. It receives every Luna
   candidate plus original evidence excerpts, verifies or rejects each candidate,
   performs the mandatory temporary-control review, merges overlaps by owner,
   applies recurrence and ROI gates, preserves every confirmed finding, and
   classifies every source call in compact groups while limiting `unassessed`.
4. Persist immutable identities, prompts, results, attempts, latency, and usage.
   Wait without model polling, terminate the complete child process tree on
   interruption or timeout, and resume accepted phases idempotently. A normal
   full analysis uses two semantic calls; oversize fallback adds only the minimum
   necessary Luna partitions, with one Sol call and no bookkeeping calls.

Every child Codex execution uses an explicit model, a read-only sandbox, no
approvals, ephemeral state, a self-contained no-tools prompt, and
controller-owned schema, event, and result files. The controller waits
internally and emits periodic non-model progress. On interruption, rerun
`execute`; never recollect prepared evidence or overwrite an accepted result.

For a batch, run `prepare-batch` once; it freezes selection and plans one
ordinary holistic child per selected thread. For the pending child returned by
`status-batch`, run `execute --state CHILD_STATE`, then pass its retained final
result to `advance-batch`. Repeat until the batch-summary phase, satisfy that
existing summary contract, advance it, and run `finalize-batch`. This preserves
the existing batch manifest and summary contracts and does not expose Luna
chunking, consolidation, or synthesis as public actions. Never collect a child
through a parallel controller or create a temporary discovery script.

## Completion Gate

Complete only when orchestration status reports `complete: true` and retained
evidence contains the frozen shared manifest, every hashed Luna and Sol result,
every Luna candidate adjudication, confirmed finding, plausible risk,
temporary-control review and merge, call classification, producer group, and
ROI input.
For a batch, every selected child must also be finalized and indexed exactly
once before batch finalization succeeds.

## Output Contract

Report only outstanding confirmed findings; retain every finding in machine
evidence. Follow the parent plain-language `Problem` and `Fix` format. Include
expected calls saved per affected and similar run, implementation cost, and
ongoing complexity. Report confirmed input/output-volume waste even when it
saves zero model calls, but exclude it from call-savings arithmetic.
For every such finding, report its aggregate input, cached-input, output,
tool-argument, and tool-result evidence; state when none was confirmed.

Put Minimal findings first. Within Minimal and then all remaining findings,
sort by expected calls saved per similar run descending, using finding ID only
as the deterministic tie-breaker. Do not use producer, helper category, or
internal controller identity as a presentation group.

Explain plausible risks under the parent contract. Also report necessary,
protocol-overhead, reviewed-no-confirmed-waste, and unassessed totals;
outstanding avoidable calls versus total calls; priced cost only when
available; and the retained analysis-result path. Never suppress an
outstanding finding.

For a batch, group similar findings across threads under plain-language problem
titles, apply the same ordering, identify affected threads, report per-thread
totals, and provide the retained batch result.
