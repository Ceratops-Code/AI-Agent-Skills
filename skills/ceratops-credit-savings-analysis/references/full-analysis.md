# Full Analysis Action

## Goal

Run the fixed controller queue with one shared evidence bundle, one focused
model pass per public surface, and one internal synthesis pass. Preserve and
present every confirmed finding.

## Inputs And Constraints

- Use the source, completed-run window, task temporary root, retained evidence
  path, optional pricing profile, and contract version required by the parent.
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

## Completion Gate

Complete only when finalization returns `OK` and retained machine evidence
contains every accepted pass, finding, risk, dismissal, exclusion, primary and
secondary mapping, category and surface total, producer group, and ROI input.

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
