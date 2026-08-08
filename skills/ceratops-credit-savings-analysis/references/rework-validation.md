# Rework Validation Action

## Goal

Detect avoidable artifact and validation loops while distinguishing required
controlled iteration.

## Focused Review

- Review failed artifact loops, repeated corrections, reversions, user-driven
  rework, misplaced QA, oversized or duplicate validation, repeated renders or
  tests, and failures a producer should have prevented.
- Treat a required proposal iteration, bounded visual refinement, or explicit
  regression gate as necessary when its scope and stopping rule were followed.
- Locate the earliest producer prevention point for savings accounting, but
  preserve additional confirmed workflow or validation gaps as secondary
  findings.
- Prefer producer-side preconditions, validation, atomic publication, or a
  narrower shared check over downstream cleanup or repeated QA.

## Completion Gate

Account for every controller-exposed candidate and record why controlled
iteration was necessary when excluded, then persist the result through
`advance`.

## Output Contract

Present every outstanding rework-validation finding and plausible risk under
the parent output contract. For a standalone run, state that conclusions cover
only rework and validation and are not a whole-thread credit reconciliation.
