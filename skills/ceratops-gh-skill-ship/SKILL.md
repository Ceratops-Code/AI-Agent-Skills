---
name: ceratops-gh-skill-ship
description: Ship staged Ceratops skills repo changes through GitHub, merge the PR after CI and PR readiness pass, then restore the skills repo checkout to main and rebuild installed skills from main.
---

# Ceratops GH Ship Skills Changes

## Goal

Ship an already-staged Ceratops skill batch from the skills repo checkout's active `release/*` branch, then restore the skills repo checkout and installed skills to synced `main`.

## Context

### Defaults

- Default release branch: `release/local`
- (D) Skill install/update entrypoint: `powershell -ExecutionPolicy Bypass -File .\\scripts\\install-skills.ps1`
- Installed Ceratops skill path: `$CODEX_HOME/skills/<skill-name>`

### Inputs To Capture

- Skills repo checkout path, active release branch, target `main` branch, PR title/body expectation, and merge method.
- Whether to create a new PR or reuse an existing PR for the active release branch.
- Whether the user requested cleanup beyond the automatic GitHub branch deletion allowed by the merge command.

Infer missing inputs from the skills repo checkout and live GitHub state before asking.

## Constraints

### Skill-Specific Rules

- Use this skill only from the skills repo checkout when it is already on the intended local `release/*` branch.
- If the staged branch is not ready, stop because staging is outside this skill's scope.
- Do not edit skill source here. This skill only pushes, opens or updates the GitHub PR, merges, restores `main`, and rebuilds installed skills from `main`.
- Do not delete local task worktrees, source branches, release branches, packages, or artifacts unless the user explicitly requested cleanup.

### Boundaries

- Use this skill only for shipping a staged skills repo branch through GitHub.
- If skill creation, skill update, or local staging work is still needed, stop because source preparation is outside this skill's scope.
- If the task is general non-skill repo shipping, stop and use `$ceratops-gh-ship-change`.

### Workflow

#### 1. Verify staged skills repo branch

- Confirm the skills repo checkout is clean and on the intended local `release/*` branch.
- Confirm the release branch contains the intended staged skill commits.

#### 2. Push and open or update PR

- Push the local release branch to the same-named remote branch unless the user explicitly chose a different branch name.
- Create or update the GitHub PR from the release branch into `main`.
- Keep the PR body concise and let CI provide the required check result.

#### 3. Merge PR

- Use `$ceratops-gh-merge-pr` for PR readiness, merge or auto-merge, and remote PR branch cleanup.
- Verify the live PR endpoint reports the PR merged before restoring `main`.

#### 4. Restore skills repo main and rebuild installed skills

- Run `git fetch --prune origin`, `git switch main`, and `git merge --ff-only origin/main` from the skills repo checkout.
- (D) Run `powershell -ExecutionPolicy Bypass -File .\\scripts\\install-skills.ps1` from `main` so `$CODEX_HOME/skills` is rebuilt from the merged main snapshot.
- Verify the skills repo checkout is clean on `main` and expected installed skill folders have current `.ceratops-runtime-manifest.json` files.

## Done When

### Completion Gate

- Verify PR merge readiness and merge were handled by `$ceratops-gh-merge-pr`.
- Verify the PR is merged or report the exact blocker.
- Verify the skills repo checkout is on `main`, fast-forwarded from `origin/main`, and clean.
- Verify installed skills were rebuilt from `main`.

### Output Contract

Report only:

- PR URL and final merge outcome
- PR readiness and CI result used
- skills repo main restore and install result
- retained local branches, worktrees, or release branches with reasons
- blockers or anything important not verified

### Example Invocation

`Use $ceratops-gh-skill-ship to ship the staged skills repo changes through GitHub, merge the GitHub PR after CI and PR readiness pass, then fetch main and rebuild installed skills from main.`
