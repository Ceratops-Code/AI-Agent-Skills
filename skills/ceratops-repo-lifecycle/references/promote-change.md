# Promote Change Action

## Goal

Fast-forward selected committed task branches into `release/local`. For
`promote-and-deploy`, run the optional repository `deploy` operation, execute
its returned handoff when managed skills exist, and report a missing handoff
without blocking completed repository deployment.

## Context

### Script Bundle

- (D) Invocation contract: set the working directory to `<skill-root>`, the
  directory containing this action's parent `SKILL.md`; require
  `<skill-root>/scripts/promote-repository.py` once before the first call. Stop
  if it is absent; never try a helper path relative to the target repository.
- (D) Promotion helper:
  `python scripts/promote-repository.py --repo-root PATH --source-branch BRANCH
  [--source-branch BRANCH...] --main-branch main --release-branch release/local
  --remote-name origin --no-run-operation`.
- (D) Promotion plus deployment uses the same command with
  `--run-operation deploy` instead of `--no-run-operation`.
- (D) Fast-change callers may prepare a clean release checkout without
  promotion or deployment:
  `python scripts/promote-repository.py --repo-root PATH --main-branch main
  --release-branch release/local --remote-name origin
  --prepare-release-only`.

### Inputs To Capture

- Repository checkout, selected committed source branches, main branch,
  `release/local`, and remote.
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
3. For `promote-and-deploy`, run it with `--run-operation deploy`; an absent
   operation is an explicit no-op.
4. Use the helper's `managed_skills` and `handoff` result after the repository
   operation succeeds or no-ops. Execute a returned handoff against
   `release/local`; when managed skills exist without one, report them as not
   deployed and continue.
5. Treat the pending-work scope as the only source scope later passed to ship.
6. Retain selected clean source worktrees and branches until terminal shipping.

The helper refreshes the remote, fast-forwards main, reuses an existing local
`release/local` without merging main into it, creates it from main when missing,
requires release `HEAD` to be an ancestor of every selected branch,
runs `git diff --check`, fast-forwards each branch, records the exact generic
scope, and optionally executes the structured deployment operation. Lifecycle
deployment treats an undeclared `deploy` operation as a no-op; the standalone
`run-operation` action remains strict.
Preparation-only requires a clean `main` checkout and exits immediately after
`release/local` is ready, before source preflight, promotion, scope records,
or deployment.

## Done When

### Completion Gate

- The checkout is clean on `release/local`.
- Every selected branch is contained in the reported release commit.
- Repository deployment ran only when `promote-and-deploy` was selected; any
  returned handoff completed, and managed skills without one were reported as
  not deployed.
- The exact pending-work scope is retained for shipping.

### Output Contract

Report only:

- `release/local`, exact head, and promoted branches
- deployment outcome and returned or missing handoff when selected
- pending-work scope
- blockers or intentionally retained state
