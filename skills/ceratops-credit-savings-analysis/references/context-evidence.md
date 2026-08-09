# Context Evidence Action

## Goal

Detect avoidable evidence rediscovery and context loading without treating
required freshness or safety work as waste.

## Focused Review

- Review exposed calls for repeated reads, broad searches, redundant
  confirmation, stale checks, ignored fresh context, repeated session
  collection, and evidence loaded beyond the current decision. Use recorded
  result-size and token evidence to identify files, command results, or evidence
  bundles materially larger than the decision required.
- Treat chronology, call relationships, fingerprints, and recorded sizes as
  deterministic evidence. Decide semantically whether context was fresh,
  sufficient, required, or excessive; the collector does not make that judgment.
- For a confirmed context-volume gap, record what was loaded, the bounded subset
  that was needed, and the exact selector or reuse boundary that would prevent
  it. Mark the finding `context-volume`, keep call-savings arithmetic at zero,
  and do not convert character volume into priced credit without a valid
  pricing profile.
- Compare each candidate with the fresh selected-session context available when
  it occurred. Exclude reads or refreshes required by active freshness, safety,
  verification, or workflow gates.
- Prefer a durable control that reuses an existing bundle, narrows a path,
  section, selector, or query, or records the evidence boundary once.

## Completion Gate

Account for every controller-exposed candidate as confirmed, plausible,
dismissed, or necessary. Write the compact decision and invoke `submit` in the
same orchestration tool call; the controller constructs and persists the
complete surface result.

## Output Contract

Present every outstanding context-evidence finding and all plausible risks under
the parent output contract. For a standalone run, state that conclusions cover
only context and evidence reuse and are not a whole-thread credit
reconciliation.
