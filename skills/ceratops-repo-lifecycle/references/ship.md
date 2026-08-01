# Ship Action

## Goal

Ship one staged integration branch through GitHub, synchronize local main,
recheck selected local work, execute `after_ship`, recheck again, and clean
only the selected merged source branches and worktrees.

## Context

### Script Bundle

- (D) Complete repository ship:
  `python scripts/ship-repository.py --repo-root PATH --repo OWNER/REPO
  --head-branch release/local --base-branch main --remote-name origin
  --pending-work-scope PATH --reusable-head`.
- Use `--no-pending-work-check` only when the caller explicitly selected that
  scope mode and no promotion scope applies.

### Inputs To Capture

- Repository checkout, staged head branch, base branch, remote, merge method,
  PR title/body, and exact pending-work scope mode.
- Whether the head is reusable after merge.

Infer missing values from the checkout, scope file, and live PR before asking.

## Constraints

### Boundaries

- Ship only a clean staged integration or release branch.
- Do not edit source or expand pending-work scope in this action.
- Keep standalone merge behavior under `merge-pr`; its admin choice is
  unchanged.

### Workflow

1. Run the complete ship helper once with the selected scope mode. The initial
   ship request authorizes its full deterministic workflow; do not request
   another confirmation after gates pass.
   When it yields a running cell without new output, resume it with a
   55-second wait; use a shorter wait only when a known completion or failure
   deadline is sooner.
2. When pending-work checking is enabled, the helper validates the exact scope
   before the first remote push. A `pending_work` result performs no remote
   mutation.
3. The delegated GitHub workflow ensures the PR, waits for readiness, CI, and
   Codex review, immediately rereads every gate, and verifies the exact head.
4. Only after those gates pass, integrated ship invokes the final merge with
   admin enabled so required-review protection cannot interrupt the authorized
   release. Admin never bypasses an earlier failed gate.
5. After merge, the helper synchronizes local main and restores a reusable
   integration branch when selected.
6. It rechecks the exact selected scope before `after_ship`, runs the operation
   from `deploy/deploy.yml`, rechecks once more, and removes only clean selected
   worktrees under the expected worktree root plus merged selected branches.
7. After successful `after_ship`, the helper checkpoints its result against the
   exact target, operation, and resolved contract before finalization. A retry
   reuses that result while cleanup remains pending and removes the checkpoint
   after cleanup succeeds. Deployment operations must still be retry-safe
   because interruption can occur between an external side effect and its
   checkpoint.

## Done When

### Completion Gate

- PR publication, all gates, exact-head admin merge, main synchronization, and
  `after_ship` completed.
- All enabled pending-work checks passed.
- Only selected clean merged source work was removed.

### Output Contract

Report only:

- PR URL and merge outcome
- synchronized main and deployment outcome
- finalized or retained selected scope with reasons
- blockers or anything important not verified
