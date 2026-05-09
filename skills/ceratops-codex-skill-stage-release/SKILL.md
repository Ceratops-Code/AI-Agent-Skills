---
name: ceratops-codex-skill-stage-release
description: Stage committed Ceratops or compatible skill changes into a skill repo checkout's local `release/*` branch, using install and validation steps only when the repo provides them.
---

# Ceratops Codex Skill Stage Release

## Goal

Stage committed skill branches into the skill repo checkout's local release branch so Codex can use one coherent unpublished repo snapshot. In this repo, update the installed runtime and run validation. In another skill repo, merge and run only the install, validation, cleanup, or runtime steps that repo actually provides.

## Context

### Defaults

- Source repo: active skill repo checkout root
- Installed Ceratops skill path: `$CODEX_HOME/skills/<skill-name>`
- Default release branch: `release/local`
- (D) Skill install/update entrypoint: `powershell -ExecutionPolicy Bypass -File .\\scripts\\install-skills.ps1`

### Script Bundle

- (D) Skill-local merged-work cleanup and pending local work check: `scripts/check-pending-release-work.ps1 -CleanMerged` from the installed skill folder, or `skills/ceratops-codex-skill-stage-release/scripts/check-pending-release-work.ps1 -CleanMerged` from a source checkout, when that helper exists.

### Inputs To Capture

- The committed task branches that are ready to join the local batch.
- The skill repo checkout path and intended local `release/*` branch.
- Whether the release branch should append more branches or be rebuilt manually before staging.
- Any other local worktree or branch with staged, unstaged, untracked, or committed work not included in the intended release branch.
- Local validation expectations for the staged batch.
- Which install, validation, cleanup, and runtime update helpers are absent in a non-Ceratops repo and therefore intentionally skipped.

Infer missing inputs from local repo state before asking.

## Constraints

### Skill-Specific Rules

- Stage only committed task-worktree branches. Do not use this skill as a substitute for intentional commits on the source branches.
- During staging, after merging ready task branches into the local `release/*` branch, remove clean task worktrees and local task branches that are already merged into that `release/*` branch. Use the cleanup helper when the repo provides one; otherwise remove them directly with safe scoped `git worktree remove` and `git branch -d` operations. Do not remove the release branch, dirty worktrees, protected branches, or worktrees outside the repo's expected `..\worktrees\<project>\` root.
- Before reporting a staged release branch as ready to publish, check remaining local worktrees and local branches for staged, unstaged, untracked, or committed work that is not included in the release branch.
- If another local branch or worktree has work not included in the release branch, stop before shipping and ask whether to commit and stage it into the same release, intentionally retain it for later, or clean it up; do not decide silently.
- After a squash-merged ship, recreate or rebase long-lived task branches from updated `main` before staging more work. Do not re-merge a branch whose earlier contents already landed on `main` via squash.

### Boundaries

- Use this skill when the goal is coherent local preview or local batching of unpublished skill changes in a skill repo checkout.
- If the task is creating a brand-new Ceratops skill and not yet staging it, stop and use `$ceratops-skill-create`.
- If the task is updating existing Ceratops skill contents and not yet staging them, stop and use `$ceratops-skill-update`.
- If the skills repo release branch is already staged or the task is general repo shipping, stop because there is no staging work left for this skill.

### Workflow

#### 1. Inspect source and skills repo state

- Inspect the source worktree branches, skill repo checkout branch, installed managed skill-copy state when applicable, and any duplicated installed copies when that runtime exists.
- Inspect remaining local worktrees and local branches before ship handoff so non-staged work is not silently left behind.
- Confirm each branch to stage is intentionally committed and available to the shared repo.
- Refresh remote refs with `git fetch --prune origin` before judging whether `origin/release/*` still exists or whether a prior staged branch or PR was already cleaned up.
- After merging ready task branches into `release/*`, remove clean local branches and worktrees already merged into the staged release branch instead of retaining them across batches. Use the skill-local helper with `-CleanMerged` when it exists; otherwise use safe scoped direct git cleanup.
- Assume the next ship will reuse the same `release/*` branch name remotely unless the user explicitly chose a different branch-naming scheme.
- If a branch already shipped through a squash merge, recreate or rebase it on current `main` before staging new work from it.
- Decide whether the release branch can be reused or whether manual release-branch cleanup is needed before staging.

#### 2. Stage the skills repo release branch

- From the skill repo checkout, refresh and fast-forward the default base branch when it exists locally; in this repo use `main`: `git fetch --prune origin`, `git switch main`, `git merge --ff-only origin/main`.
- Switch to the local release branch if it already exists; otherwise create it from `main`.
- Fast-forward the existing release branch to `main` before merging new task branches.
- Before merging each requested committed task branch into the active local `release/*` branch, run a blocking local code review against the current release branch state; any finding blocks staging until fixed and re-reviewed clean.
- (D) Use this PowerShell command from the skill repo checkout for that review diff: `git diff (git merge-base HEAD BRANCH) BRANCH`, where `HEAD` is the active local `release/*` branch and `BRANCH` is the task branch being staged.
- Merge each reviewed committed task branch into the local `release/*` branch with `git merge --no-edit BRANCH`.
- If the skill repo checkout is dirty before staging, stop and resolve that state instead of merging into it blindly.

Exact PowerShell command sequence for the default `release/local` branch:

```powershell
git fetch --prune origin
git switch main
git merge --ff-only origin/main
if (git show-ref --verify --quiet refs/heads/release/local) {
    git switch release/local
    git merge --ff-only main
} else {
    git switch -c release/local main
}
git diff (git merge-base HEAD BRANCH) BRANCH
# Run the blocking local code review on this diff and fix every finding before continuing.
git merge --no-edit BRANCH
if (Test-Path -LiteralPath .\skills\ceratops-codex-skill-stage-release\scripts\check-pending-release-work.ps1) {
    powershell -ExecutionPolicy Bypass -File .\skills\ceratops-codex-skill-stage-release\scripts\check-pending-release-work.ps1 -SkillsRepoRoot . -CleanMerged
} else {
    # Remove clean merged task worktrees and branches with safe scoped git cleanup.
}
```

#### 3. Install and validate staged state

- (D) Run `powershell -ExecutionPolicy Bypass -File .\\scripts\\install-skills.ps1 -Validate full` from the skill repo checkout when that installer and validation path exist.
- Confirm each installed Ceratops skill copy has `.ceratops-runtime-manifest.json` and was regenerated by the installer when the repo uses managed runtime copies.
- If `scripts/install-skills.ps1` is absent but source `skills/<skill-name>` folders exist, copy each affected skill folder directly to `$CODEX_HOME/skills/<skill-name>` for the runtime update; skip only unavailable validation and report it.
- (D) When the PR-readiness validator or installer changed and the relevant script exists, run `python scripts/validation/github-validate-pr-readiness-contract.py --help`.

#### 4. Report the staged state

- Run the skill-local pending local work check before reporting the batch as ready to publish when the helper exists. Use `-CleanMerged` for the post-merge cleanup pass; omit it for the final read-only pending-work pass unless another cleanup was explicitly requested. If the current directory is not the skill repo checkout, pass `-SkillsRepoRoot PATH`.
- If the pending-work check reports any other dirty worktree, untracked work, staged work, unstaged work, or branch commits outside the release branch, stop before shipping and ask the user whether to include, retain, or clean up that work.
- Report the active local `release/*` branch, the staged task branches, and any blockers that still prevent shipping.
- Leave the skill repo checkout on the staged release branch only when the batch is intentionally active.

## Done When

### Completion Gate

- Verify the skill repo checkout is on the intended local `release/*` branch.
- Verify every branch merged into the staged `release/*` branch had a clean blocking local code review against the then-current local release branch.
- Verify each requested task branch was staged; clean source worktrees and source branches already merged into the staged `release/*` branch were removed, and unmerged or dirty source worktrees and branches remain unless the user separately requested cleanup.
- Verify the pending local work check passed before ship handoff when the helper exists, or every reported non-staged branch or worktree is covered by an explicit user choice, retention reason, or blocker.
- Verify the installed skill copies are managed runtime outputs and include fresh runtime manifests when the repo uses managed runtime copies.
- Verify the local validation batch passed or the blocking failures were reported when the repo provides validation.
- When a repo lacks install, runtime, or validation helpers, verify the merge state and report the skipped unavailable steps instead of treating them as blockers.

### Output Contract

Report only:

- the active local release branch and staged task branches
- unresolved blockers or non-blocking debt
- intentionally retained skills repo state, branches, or worktrees with reasons
- anything important not verified

### Example Invocation

`Use $ceratops-codex-skill-stage-release to merge the ready skill branches into the local skill repo release branch, switch the skill repo checkout there, and run the staged batch checks the repo provides.`
