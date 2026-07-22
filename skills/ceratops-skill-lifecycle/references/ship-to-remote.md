# Ship To Remote Action

## Goal

Ship an already-staged Ceratops skill batch from the skills repo checkout's
active `release/*` branch, then restore the skills repo checkout and installed
skills to synced `main`.

## Context

### Defaults

- Default release branch: `release/local`
- (D) Repository installer: `python scripts/install-skills.py`, which uses the
  supported installed lifecycle bundle.
- Installed managed skill path: `$CODEX_HOME/skills/<skill-name>`

### GitHub Lifecycle Handoffs

- Push and PR publication: use `$ceratops-gh-repo-lifecycle` with the
  `ensure-pr` action.
- (D) Post-merge sync helper, run from
  `skills/ceratops-gh-repo-lifecycle/scripts` in a source checkout or `scripts`
  in the installed GH lifecycle skill folder:
  `python -m github_pr_workflow sync --repo-root <repo> --main-branch main
  --remote-name origin --align-branch release/local`.

### Inputs To Capture

- Skills repo checkout path, active release branch, target `main` branch, PR
  title/body expectation, and merge method.
- Whether to create a new PR or reuse an existing PR for the active release
  branch.
- Whether the user requested cleanup beyond automatic GitHub branch deletion
  allowed by merge.

Infer missing inputs from the skills repo checkout and live GitHub state before
asking.

## Constraints

### Boundaries

- Use this action only for shipping a staged skills repo branch through GitHub.
- If skill creation, skill update, or local staging work is still needed, return
  to the parent skill and select the owning action.
- If the task is general non-skill repo shipping, use
  `$ceratops-gh-repo-lifecycle` with the `ship-change` action.
- Do not edit skill source here. This action only pushes, opens or updates the
  GitHub PR, merges, restores `main`, and rebuilds installed skills from `main`.
- Do not delete local task worktrees, source branches, release branches,
  packages, or artifacts unless the user explicitly requested cleanup.

### Workflow

#### 1. Verify staged branch

- Confirm the skills repo checkout is clean and on the intended local
  `release/*` branch.
- Confirm the release branch contains the intended staged skill commits.

#### 2. Push and open or update PR

- Use `$ceratops-gh-repo-lifecycle` with the `ensure-pr` action; it owns clean
  release-branch verification, ahead-of-main verification, same-named remote
  push, PR create-or-update behavior, and compact PR summary output.

#### 3. Merge PR

- Use `$ceratops-gh-repo-lifecycle` with the `merge-pr` action for PR readiness,
  merge or auto-merge, and remote PR branch cleanup.
- Verify the live PR endpoint reports the PR merged before restoring `main`.

#### 4. Restore main and rebuild installed skills

- (D) Run `python -m github_pr_workflow sync --repo-root <repo> --align-branch
  release/local` to fetch/prune, switch to `main`, fast-forward from
  `origin/main`, align the reusable local release branch, and emit compact sync
  output.
- (D) Run `python scripts/install-skills.py --repo-root <repo>` after restoring
  `main`, so this source repository's managed skills are rebuilt from the
  merged main snapshot and same-source stale runtime folders are removed.
- Verify the skills repo checkout is clean on `main` and expected installed
  skill folders have current `.runtime-manifest.json` files.

## Done When

### Completion Gate

- PR publication was handled by `$ceratops-gh-repo-lifecycle` with the
  `ensure-pr` action.
- PR merge readiness and merge were handled by `$ceratops-gh-repo-lifecycle`
  with the `merge-pr` action.
- The PR is merged or the exact blocker is reported.
- The skills repo checkout is on `main`, fast-forwarded from `origin/main`, and
  clean.
- Installed skills were rebuilt from `main`.

### Output Contract

Report only:

- PR URL and final merge outcome
- PR readiness and CI result used
- skills repo main restore and install result
- retained local branches, worktrees, or release branches with reasons
- blockers or anything important not verified
