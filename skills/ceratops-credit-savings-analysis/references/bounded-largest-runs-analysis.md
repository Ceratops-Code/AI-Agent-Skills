# Bounded Largest Runs Analysis Action

## Goal

Analyze the largest completed producer runs within one end-to-end capacity
envelope. Use one Luna discovery and one Sol adjudication while preserving the
immediate positional follow-up to every selected anchor. This is a bounded
largest-runs analysis, never a full-thread analysis.

## Deterministic Selection

- Freeze completed producer-run order before selection. Treat each run as one
  selectable unit and retain its original sequence ID and timestamp.
- Measure a run by the serialized compact evidence that would enter model
  context. Rank anchors by that run size descending, with original order as the
  deterministic tie-breaker; never rank by bundle size.
- For each candidate anchor, bundle the anchor with the immediately following
  completed run in frozen order. Determine the follower positionally without a
  model or semantic heuristic. A final anchor with no follower is a one-run
  bundle.
- Keep the anchor and follower indivisible. If a previously included follower
  later becomes an anchor, evaluate it with its own immediate successor. Store
  each selected run payload once, while preserving event order inside every run.
- Packing follows descending anchor size. Skip any bundle that cannot fit,
  record it as omitted for capacity, and continue evaluating smaller anchors.

## End-To-End Budget

- Before the first model call, prove the complete Luna input and projected Sol
  input/output envelope. Include fixed prompts and schemas, selected evidence,
  the maximum accepted Luna output, Sol instructions, and both output reserves.
- Never truncate a bundle or detach its successor. If no bundle fits after
  every eligible bundle is evaluated, return a deterministic capacity blocker
  before model execution.
- Freeze one Luna task and one dependent Sol task. Do not add bookkeeping,
  grouping, consolidation, or other semantic calls.

## Workflow

1. Run controller `run --request REQUEST` with action and mode
   `bounded-largest-runs-analysis`. On a fresh request it collects the selected
   session once, freezes run order and compact evidence, selects bundles
   deterministically, and persists the immutable selection manifest and both
   budget proofs.
2. The same controller run executes the frozen plan. Luna receives every
   selected run exactly once and performs high-recall discovery across all fixed
   surfaces. Sol receives its accepted output and the selected original
   evidence, adjudicates every candidate, and classifies only selected calls.
3. Rerun the exact request or use `execute --state STATE` after interruption.
   Validate immutable hashes, reuse accepted calls, never recollect evidence,
   and never repeat a completed Luna or Sol call. Use `plan --request REQUEST`
   only for planning-only inspection.

## Completion Gate

Complete only when the selection manifest proves anchor-size ranking,
positional followers, deduplicated selected payloads, deterministic later-bundle
skips, and fitting Luna and Sol budgets; exactly one Luna and one Sol result are
accepted; and finalization succeeds idempotently.

## Output Contract

- Label the result `bounded largest-runs analysis`, never full-thread analysis.
- Report selected anchor count, companion count, unique selected runs, total
  eligible runs, selected and total serialized evidence volume, and coverage
  percentage.
- Retain omitted runs only as IDs, original ordering, and size metrics. Do not
  send omitted evidence to a model, produce exhaustive whole-thread totals, or
  imply that omitted runs were reviewed.
- Present confirmed findings and selected-call classifications under the parent
  output contract and retain the selection-manifest path.
