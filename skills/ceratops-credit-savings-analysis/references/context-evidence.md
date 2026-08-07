# Context Evidence Action

## Goal

Detect avoidable evidence rediscovery and context loading without treating
required freshness or safety work as waste.

## Focused Review

- Review exposed calls for repeated reads, broad searches, redundant
  confirmation, stale checks, ignored fresh context, repeated session
  collection, and evidence loaded beyond the current decision.
- Compare each candidate with the fresh selected-session context available when
  it occurred. Exclude reads or refreshes required by active freshness, safety,
  verification, or workflow gates.
- Prefer a durable control that reuses an existing bundle, narrows a path,
  section, selector, or query, or records the evidence boundary once.

## Completion Gate

Account for every controller-exposed candidate as confirmed, plausible,
dismissed, or necessary, then persist the complete surface result through
`advance`.

## Output Contract

Present every confirmed context-evidence finding and all plausible risks. For a
standalone run, state that conclusions cover only context and evidence reuse and
are not a whole-thread credit reconciliation.
