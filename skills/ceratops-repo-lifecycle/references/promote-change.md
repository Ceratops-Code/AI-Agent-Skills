# Promote Change Action

## Goal

Fast-forward selected committed task branches into one local `release/*`
branch. Run the repository's `after_promote` deployment operation only for the
`promote-and-deploy` action.

## Context

### Script Bundle

- (D) Promotion helper:
  `python scripts/promote-repository.py --repo-root PATH --source-branch BRANCH
  [--source-branch BRANCH...] --main-branch main --release-branch release/local
  --remote-name origin --no-run-operation`.
- (D) Promotion plus deployment uses the same command with
  `--run-operation after_promote` instead of `--no-run-operation`.
- (D) Fast-change callers may prepare a clean release checkout without
  promotion or deployment:
  `python scripts/promote-repository.py --repo-root PATH --main-branch main
  --release-branch release/local --remote-name origin
  --prepare-release-only`.

### Inputs To Capture

- Repository checkout, selected committed source branches, main branch,
  release branch, and remote.
- Whether the selected action is `promote` or `promote-and-deploy`.

Infer missing branch and checkout inputs from local Git state before asking.

## Constraints

### Boundaries

- Promote only explicitly selected task branches.
- Keep unrelated branches and worktrees outside inspection and cleanup scope.
- Stop when source mutation, review, or commit work is still required.

### Workflow

1. Complete a blocking local review of each selected source branch against the
   then-current release head.
2. For `promote`, run the helper with `--no-run-operation`.
3. For `promote-and-deploy`, run it with `--run-operation after_promote`.
4. Treat its pending-work scope as the only source scope later passed to ship.
5. Retain selected clean source worktrees and branches until terminal shipping.

The helper refreshes the remote, fast-forwards main, reuses an existing local
release branch without merging main into it, creates a missing release branch
from main, requires release `HEAD` to be an ancestor of every selected branch,
runs `git diff --check`, fast-forwards each branch, records the exact generic
scope, and optionally executes the structured deployment operation.
Preparation-only requires a clean `main` checkout and exits immediately after
the release branch is ready, before source preflight, promotion, scope records,
or deployment.

## Done When

### Completion Gate

- The checkout is clean on the selected release branch.
- Every selected branch is contained in the reported release commit.
- Deployment ran only when `promote-and-deploy` was selected.
- The exact pending-work scope is retained for shipping.

### Output Contract

Report only:

- release branch, exact head, and promoted branches
- deployment outcome when selected
- pending-work scope
- blockers or intentionally retained state
