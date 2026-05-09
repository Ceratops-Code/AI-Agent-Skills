<!-- INTERNAL: include in skills that make GitHub-state decisions -->

## GH Current State

- (D) Use copied repo-maintenance scripts, especially `scripts/validation/github-validate-pr-readiness-contract.py` and the contract checkers, for bundled GitHub current-state checks when they cover the next decision.
- Use `gh`, GitHub API, copied repo-maintenance scripts, and contract evidence bundles as first-pass evidence for current GitHub state before checking official docs or `gh` help.
- Prefer current GitHub state over memory, prose summaries, or stale screenshots.
- Start with the narrowest live check that answers the next decision: bundled helper script, targeted `gh` query, or focused API call.
- Check current official GitHub docs or `gh` help only when the next decision remains concretely ambiguous after targeted live GitHub evidence, or when those sources materially conflict.
- Compare at most 1-2 strong current reference repos only for concrete ambiguous GitHub workflow, security, release, or packaging patterns that official docs and current GitHub state do not settle.
- Re-run the relevant live check after a GitHub change only when the successful mutation command does not already prove the exact result, the state is asynchronous, or the final claim is broader than the mutation.

## GH Findings

- Classify only findings actually inspected in this run. Do not expand reporting to untouched queues unless they become the next actionable work or the user explicitly asked for full coverage.
- For each inspected finding, decide whether it is safe, fix low-risk items directly when in scope, and for every finding left open report its name or id, whether it is blocking, why it remains open, and the concrete work needed to clear it.
- Do not collapse retained findings into a generic healthy result.
- Re-check findings whose status may have changed because of actions taken in this run.
