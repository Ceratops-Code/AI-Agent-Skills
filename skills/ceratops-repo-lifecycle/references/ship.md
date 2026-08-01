# Ship Action

## Goal

Ship one staged integration branch through GitHub, synchronize local main,
recheck selected local work, execute or explicitly no-op `after_ship`, recheck
again, and clean only the selected merged source branches and worktrees.

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
2. When pending-work checking is enabled, the helper validates the exact scope
   before the first remote push. A `pending_work` result performs no remote
   mutation.
3. The delegated GitHub workflow ensures the PR, waits for readiness, CI, and
   Codex review, immediately rereads every gate, and verifies the exact head.
4. Only after those gates pass, integrated ship delegates the final exact-head
   merge to `merge.merge_verified_pr(admin=True)`. It inherits the shared
   merge action's checkpointed dedicated-endpoint bypass, restoration, read-back,
   and critical recovery semantics; ship contains no independent toggle logic.
5. After merge, the helper synchronizes local main and restores a reusable
   integration branch when selected.
6. Before remote mutation, the wrapper classifies deployment. An absent default
   `deploy/deploy.yml` makes `after_ship` an explicit no-op; a missing custom
   contract blocks. After synchronization it rechecks the selected scope, runs
   a declared operation or records the no-op, rechecks, and removes only clean
   selected worktrees and merged selected branches.
7. After a declared `after_ship` succeeds, the helper checkpoints its result
   against the exact target, operation, and resolved contract before
   finalization. A retry reuses that result while cleanup remains pending and
   removes the checkpoint after cleanup succeeds. Deployment operations must
   remain retry-safe across interruption.

## Done When

### Completion Gate

- PR publication, all gates, exact-head admin merge, main synchronization, and
  declared or explicit no-op `after_ship` completed.
- All enabled pending-work checks passed.
- Only selected clean merged source work was removed.

### Output Contract

Report only:

- PR URL and merge outcome
- synchronized main and deployment outcome
- finalized or retained selected scope with reasons
- blockers or anything important not verified
