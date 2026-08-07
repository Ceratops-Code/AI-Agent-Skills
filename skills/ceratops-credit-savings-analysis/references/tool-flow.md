# Tool Flow Action

## Goal

Detect avoidable tool, command, wait, and model-mediated transitions.

## Focused Review

- Review unnecessary tool or model handoffs, unbatched commands, poor tool
  selection, retries without diagnosis, unnecessary polling or waits, noisy
  output, missing deterministic orchestration, and avoidable model-mediated
  transitions.
- Separate conversational tool-protocol overhead from executable helper
  defects. Classify protocol-only overhead as necessary and do not propose a
  helper solely to remove required protocol turns.
- Prefer an existing purpose-built tool, bounded batched command, deterministic
  orchestrator, compact result contract, or diagnosis-gated retry when it
  directly prevents the observed calls.

## Completion Gate

Account for every controller-exposed candidate, including protocol-only
exclusions, then persist the complete result through `advance`.

## Output Contract

Present every confirmed tool-flow finding and plausible risk. For a standalone
run, state that conclusions cover only tool and handoff flow and are not a
whole-thread credit reconciliation.
