# Promote Change Action

## Goal

Fast-forward selected committed task branches into `release/local`. For
`promote-and-deploy`, run the optional repository `deploy` operation, execute
its returned handoff when managed skills exist, and report a missing handoff
without blocking completed repository deployment.

## Context

### Script Bundle

- (D) Invocation contract: bind `<skill-root>` to the directory containing this
  action's parent `SKILL.md`; require
  `<skill-root>/scripts/promote-repository.py` once before the first call.
  Invoke that exact path with the working directory equal to its `--repo-root`
  value; stop if it is absent and never resolve it relative to that repository.
- (D) Promotion helper:
  `python
  "<skill-root>/scripts/promote-repository.py" --repo-root PATH
  --source-branch BRANCH [--source-branch BRANCH...] --main-branch main
  --release-branch release/local --remote-name origin --no-run-operation`.
- (D) Promotion plus deployment uses the same command with
  `--run-operation deploy` instead of `--no-run-operation`.
- (D) Fast-change callers may prepare a clean release checkout without
  promotion or deployment:
  `python
  "<skill-root>/scripts/promote-repository.py" --repo-root PATH
  --main-branch main --release-branch release/local --remote-name origin
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
- Before promotion, automatically rebase a selected clean, unpublished,
  linear-history task branch onto current `release/local`. If rebasing fails,
  abort it, verify the original head and clean worktree were restored, and
  block with the conflicting paths. Stop for other source mutation, review, or
  commit work.

### Workflow

1. Require clean selected worktrees. Through the promotion helper, establish
   Git ancestry with the eligible automatic rebase and run `git diff --check`.
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
`release/local` without merging main into it, and creates it from main when
missing. When release `HEAD` is not an ancestor, it rebases only an unpublished,
linear selected branch in its existing clean worktree. It refuses published or
nonlinear history. A failed attempt must restore the original branch head and
clean worktree before it reports the failure and conflicting paths. The helper
then runs `git diff --check`, fast-forwards each branch, records the exact
generic scope, and optionally executes the structured deployment operation.
Lifecycle deployment treats an undeclared `deploy` operation as a no-op; the
standalone `run-operation` action remains strict.
Preparation-only requires a clean `main` checkout and exits immediately after
`release/local` is ready, before source preflight, promotion, scope records,
or deployment.

## Done When

### Completion Gate

- The checkout is clean on `release/local`.
- Every selected branch is contained in the reported release commit.
- Every attempted automatic rebase either completed and reported both heads or
  restored the original clean source state before blocking.
- Repository deployment ran only when `promote-and-deploy` was selected; any
  returned handoff completed, and managed skills without one were reported as
  not deployed.
- The exact pending-work scope is retained for shipping.

### Output Contract

Report only:

- `release/local`, exact head, promoted branches, and automatic rebase results
- deployment outcome and returned or missing handoff when selected
- pending-work scope
- blockers or intentionally retained state
