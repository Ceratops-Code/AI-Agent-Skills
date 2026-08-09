# Tool Flow Action

## Goal

Detect avoidable tool, command, wait, and model-mediated transitions.

## Focused Review

- Review unnecessary tool or model handoffs, unbatched commands, poor tool
  selection, retries without diagnosis, unnecessary polling or waits, noisy
  or oversized command and tool output, missing deterministic orchestration,
  and avoidable model-mediated transitions.
- For an output-volume candidate, compare recorded argument and result sizes
  with the next decision's required payload. Record the excessive result, the
  bounded output that was needed, and the exact filter, quiet mode, projection,
  or compact result contract that would prevent it. Mark a volume-only finding
  `context-volume` and keep its call-savings arithmetic at zero.
- Treat event order, exact emitted process codes, fingerprints, and character
  counts as deterministic evidence. Use the model pass to decide whether the
  tool choice, handoff, retry, wait, or output volume was avoidable.
- Separate conversational tool-protocol overhead from executable helper
  defects. Classify protocol-only overhead as necessary and do not propose a
  helper solely to remove required protocol turns.
- Prefer an existing purpose-built tool, bounded batched command, deterministic
  orchestrator, compact result contract, or diagnosis-gated retry when it
  directly prevents the observed calls.

## Completion Gate

Account for every controller-exposed candidate, including protocol-only
exclusions. Write the compact decision and invoke `submit` in the same
orchestration tool call; the controller constructs and persists the complete
surface result.

## Output Contract

Present every outstanding tool-flow finding and plausible risk under the parent
output contract. For a standalone run, state that conclusions cover only tool
and handoff flow and are not a whole-thread credit reconciliation.
