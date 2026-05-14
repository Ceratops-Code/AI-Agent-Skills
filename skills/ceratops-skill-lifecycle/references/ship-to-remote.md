# Ship To Remote Action

## Goal

Ship an already-staged Ceratops skill batch from the skills repo checkout's active `release/*` branch, then restore the skills repo checkout and installed skills to synced `main`.

## Context

### Defaults

- Default release branch: `release/local`
- (D) Skill install/update entrypoint: `powershell -ExecutionPolicy Bypass -File .\scripts\install-skills.ps1`
- Installed Ceratops skill path: `$CODEX_HOME/skills/<skill-name>`

### Inputs To Capture

- Skills repo checkout path, active release branch, target `main` branch, PR title/body expectation, and merge method.
- Whether to create a new PR or reuse an existing PR for the active release branch.
- Whether the user requested cleanup beyond automatic GitHub branch deletion allowed by merge.

Infer missing inputs from the skills repo checkout and live GitHub state before asking.

## Constraints

### Boundaries

- Use this action only for shipping a staged skills repo branch through GitHub.
- If skill creation, skill update, or local staging work is still needed, return to the router and select the owning action.
- If the task is general non-skill repo shipping, use `$ceratops-gh-repo-lifecycle` with the `ship-change` action.
- Do not edit skill source here. This action only pushes, opens or updates the GitHub PR, merges, restores `main`, and rebuilds installed skills from `main`.
- Do not delete local task worktrees, source branches, release branches, packages, or artifacts unless the user explicitly requested cleanup.

### Workflow

#### 1. Verify staged branch

- Confirm the skills repo checkout is clean and on the intended local `release/*` branch.
- Confirm the release branch contains the intended staged skill commits.

#### 2. Push and open or update PR

- Push the local release branch to the same-named remote branch unless the user explicitly chose a different branch name.
- Create or update the GitHub PR from the release branch into `main`.
- Keep the PR body concise and let CI provide the required check result.

#### 3. Merge PR

- Use `$ceratops-gh-repo-lifecycle` with the `merge-pr` action for PR readiness, merge or auto-merge, and remote PR branch cleanup.
- Verify the live PR endpoint reports the PR merged before restoring `main`.

#### 4. Restore main and rebuild installed skills

- Run `git fetch --prune origin`, `git switch main`, and `git merge --ff-only origin/main` from the skills repo checkout.
- (D) Run `powershell -ExecutionPolicy Bypass -File .\scripts\install-skills.ps1` from `main` so `$CODEX_HOME/skills` is rebuilt from the merged main snapshot.
- Verify the skills repo checkout is clean on `main` and expected installed skill folders have current `.ceratops-runtime-manifest.json` files.

## Done When

### Completion Gate

- PR merge readiness and merge were handled by `$ceratops-gh-repo-lifecycle` with the `merge-pr` action.
- The PR is merged or the exact blocker is reported.
- The skills repo checkout is on `main`, fast-forwarded from `origin/main`, and clean.
- Installed skills were rebuilt from `main`.

### Output Contract

Report only:

- PR URL and final merge outcome
- PR readiness and CI result used
- skills repo main restore and install result
- retained local branches, worktrees, or release branches with reasons
- blockers or anything important not verified
