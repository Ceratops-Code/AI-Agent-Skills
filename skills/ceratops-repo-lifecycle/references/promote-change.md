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

1. Require clean selected worktrees, Git ancestry, and `git diff --check`
   through the promotion helper.
2. For `promote`, run the helper with `--no-run-operation`.
3. For `promote-and-deploy`, run it with `--run-operation after_promote`.
4. Treat its pending-work scope as the only source scope later passed to ship.
5. Retain selected clean source worktrees and branches until terminal shipping.

The helper refreshes the remote and fast-forwards main in its existing clean
checkout or, when main is not checked out, by a guarded branch-ref update.
Normal promotion never creates or switches a checkout: it reuses a clean
existing release checkout when present and otherwise creates or advances only
the local release branch ref from main. It requires the current release commit
to be an ancestor of every selected branch, runs `git diff --check`,
fast-forwards each branch, records the exact generic scope, and optionally
executes the structured deployment operation. For `after_promote`, it uses the
supplied checkout only when that checkout is already clean on the release branch
at the promoted commit; otherwise it uses the final promoted source-branch
worktree. It requires that exact-head deployment checkout before changing the
release branch and offers the release-start commit as conditional
`base_revision` context. The operation runner supplies it only when the
selected operation declares that parameter, so compatible parameterless
operations remain valid.
Preparation-only requires a clean `main` checkout, may switch that supplied
checkout to the ready release branch, never adds a worktree, and exits before
source preflight, promotion, scope records, or deployment.

## Done When

### Completion Gate

- Every checkout used for promotion or deployment is clean; preparation-only
  leaves the supplied checkout clean on the selected release branch.
- Every selected branch is contained in the reported release commit.
- Deployment ran only when `promote-and-deploy` was selected.
- The exact pending-work scope is retained for shipping.

### Output Contract

Report only:

- release branch, exact head, and promoted branches
- deployment outcome when selected
- pending-work scope
- blockers or intentionally retained state
