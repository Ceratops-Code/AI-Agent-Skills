# Full Analysis Action

## Goal

Run one complete two-tier controller plan with shared evidence, Spark discovery
over every candidate chunk, one GPT-5.6 confirmation per public surface, and
one internal GPT-5.6 synthesis. Preserve and present every confirmed finding.

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

1. Run controller `plan` once. It resolves, collects, and parses the selected
   session once; retains complete protected evidence; formats every candidate
   for all five surfaces in fixed order; snapshots referenced final canonical
   artifacts read-only with protected content and immutable hashes; partitions
   adjacent candidates into finite model-sized chunks; freezes primary and
   consolidation manifests; and reports projected Spark calls before model
   execution. Stop on malformed, empty, or clearly runaway planning.
2. Run controller `execute`. It processes the finite ordered resumable Spark
   queue with `gpt-5.3-codex-spark`. Every primary result must account for every
   chunk candidate exactly once, and every consolidation must preserve all
   candidate IDs and material variants. The controller persists identity and
   content hashes and validates complete Spark coverage before GPT-5.6 begins.
3. In fixed surface order, the controller runs exactly one `gpt-5.6-sol`
   confirmation per surface. Each self-contained packet includes every Spark
   candidate and original evidence excerpts or explicit retained-payload
   projections. Never suppress or silently truncate a candidate to fit.
4. The controller runs exactly one `gpt-5.6-sol` synthesis. It merges duplicate
   owner/control findings and temporary-control contributions once, preserves
   contributing surfaces, assigns savings once, classifies every call, and
   retains every confirmed finding. A full analysis therefore uses exactly six
   GPT-5.6 semantic calls; Spark calls are additional and manifest-derived.

Every child Codex execution uses an explicit model, a read-only sandbox, no
approvals, ephemeral state, a self-contained no-tools prompt, and
controller-owned schema, event, and result files. The controller waits
internally and emits periodic non-model progress. On interruption, rerun
`execute`; never recollect prepared evidence or overwrite an accepted result.

For a batch, use the existing `prepare-batch`, `advance-batch`, `status-batch`,
and `finalize-batch` compatibility interface. It freezes selection and each
lower-level child controller once, preserves the existing batch manifest and
summary contracts, and does not expose Spark chunking or synthesis as public
actions. Never create a temporary discovery script.

## Completion Gate

Complete only when orchestration status reports `complete: true` and retained
evidence contains the frozen chunk manifest, every hashed Spark and GPT-5.6
result, finding, risk, dismissal, exclusion, temporary-control review and
merge, reviewed-no-confirmed-waste and unassessed call, producer group, and ROI
input.
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
