---
name: ceratops-codex-skill-stage-release
description: Stage committed Ceratops skill changes into the skills repo checkout's local `release/*` branch for coherent local preview. Use when Codex should merge ready task-worktree branches into a release branch created from `main`, switch the skills repo checkout to that branch, update the local skill install, and run the local validation batch before GitHub shipping.
---

# Ceratops Codex Skill Stage Release

## Goal

Stage committed skill branches into the skills repo checkout's local release branch so Codex can use one coherent unpublished repo snapshot.

## Context

### Defaults

- Source repo: active skills repo checkout root
- Installed Ceratops skill path: `$CODEX_HOME/skills/<skill-name>`
- Default release branch: `release/local`
- Skill install/update entrypoint: `powershell -ExecutionPolicy Bypass -File .\\scripts\\install-skills.ps1`

### Script Bundle

- Skill-local merged-work cleanup and pending local work check: `scripts/check-pending-release-work.ps1 -CleanMerged` from the installed skill folder, or `skills/ceratops-codex-skill-stage-release/scripts/check-pending-release-work.ps1 -CleanMerged` from a source checkout.

### Inputs To Capture

- The committed task branches that are ready to join the local batch.
- The skills repo checkout path and intended local `release/*` branch.
- Whether the release branch should append more branches or be rebuilt manually before staging.
- Any other local worktree or branch with staged, unstaged, untracked, or committed work not included in the intended release branch.
- Local validation expectations for the staged batch.

Infer missing inputs from local repo state before asking.

## Constraints

### Skill-Specific Rules

- Stage only committed task-worktree branches. Do not use this skill as a substitute for intentional commits on the source branches.
- During staging, remove clean task worktrees and local task branches that are already merged into synced `main`, and remove a local `release/*` branch that is already merged into synced `main` before recreating or reusing the release branch. Do not remove dirty worktrees, branches requested for the current staged batch, protected branches, or worktrees outside the repo's expected `..\worktrees\<project>\` root.
- Before reporting a staged release branch as ready to publish, check remaining local worktrees and local branches for staged, unstaged, untracked, or committed work that is not included in the release branch.
- If another local branch or worktree has work not included in the release branch, stop before shipping and ask whether to commit and stage it into the same release, intentionally retain it for later, or clean it up; do not decide silently.
- After a squash-merged ship, recreate or rebase long-lived task branches from updated `main` before staging more work. Do not re-merge a branch whose earlier contents already landed on `main` via squash.

### Boundaries

- Use this skill when the goal is coherent local preview or local batching of unpublished skill changes in the skills repo checkout.
- If the task is creating a brand-new Ceratops skill and not yet staging it, stop and use `$ceratops-skill-create`.
- If the task is updating existing Ceratops skill contents and not yet staging them, stop and use `$ceratops-skill-update`.
- If the skills repo release branch is already staged or the task is general repo shipping, stop because there is no staging work left for this skill.

### Workflow

#### 1. Inspect source and skills repo state

- Inspect the source worktree branches, skills repo checkout branch, installed managed skill-copy state, and any duplicated installed copies.
- Inspect remaining local worktrees and local branches before ship handoff so non-staged work is not silently left behind.
- Confirm each branch to stage is intentionally committed and available to the shared repo.
- Refresh remote refs with `git fetch --prune origin` before judging whether `origin/release/*` still exists or whether a prior staged branch or PR was already cleaned up.
- After refreshing `main`, run the skill-local helper with `-CleanMerged` before creating or reusing `release/*` so local branches and worktrees already merged into `main` are removed instead of being retained across batches.
- Assume the next ship will reuse the same `release/*` branch name remotely unless the user explicitly chose a different branch-naming scheme.
- If a branch already shipped through a squash merge, recreate or rebase it on current `main` before staging new work from it.
- Decide whether the release branch can be reused or whether manual release-branch cleanup is needed before staging.

#### 2. Stage the skills repo release branch

- From the skills repo checkout, refresh and fast-forward main: `git fetch --prune origin`, `git switch main`, `git merge --ff-only origin/main`.
- Switch to the local release branch if it already exists; otherwise create it from `main`.
- Fast-forward the existing release branch to `main` before merging new task branches.
- Merge each requested committed task branch into the local `release/*` branch with `git merge --no-edit BRANCH`.
- If the skills repo checkout is dirty before staging, stop and resolve that state instead of merging into it blindly.

Exact PowerShell command sequence for the default `release/local` branch:

```powershell
git fetch --prune origin
git switch main
git merge --ff-only origin/main
powershell -ExecutionPolicy Bypass -File .\skills\ceratops-codex-skill-stage-release\scripts\check-pending-release-work.ps1 -SkillsRepoRoot . -CleanMerged -StagedBranches BRANCH
if (git show-ref --verify --quiet refs/heads/release/local) {
    git switch release/local
    git merge --ff-only main
} else {
    git switch -c release/local main
}
git merge --no-edit BRANCH
```

#### 3. Install and validate staged state

- Run `powershell -ExecutionPolicy Bypass -File .\\scripts\\install-skills.ps1 -Validate full` from the skills repo checkout.
- Confirm each installed Ceratops skill copy has `.ceratops-runtime-manifest.json` and was regenerated by the installer.
- (D) When the PR-readiness validator or installer changed, run `python scripts/validation/github-validate-pr-readiness-contract.py --help`.

#### 4. Report the staged state

- Run the skill-local pending local work check before reporting the batch as ready to publish. Use `-CleanMerged` for the pre-staging cleanup pass; omit it for the final read-only pending-work pass unless another cleanup was explicitly requested. If the current directory is not the skills repo checkout, pass `-SkillsRepoRoot PATH`.
- If the pending-work check reports any other dirty worktree, untracked work, staged work, unstaged work, or branch commits outside the release branch, stop before shipping and ask the user whether to include, retain, or clean up that work.
- Report the active local `release/*` branch, the staged task branches, and any blockers that still prevent shipping.
- Leave the skills repo checkout on the staged release branch only when the batch is intentionally active.

## Done When

### Completion Gate

- Verify the skills repo checkout is on the intended local `release/*` branch.
- Verify each requested task branch was staged; clean source worktrees and source branches already merged into synced `main` were removed by the cleanup pass, and unmerged or dirty source worktrees and branches remain unless the user separately requested cleanup.
- Verify the pending local work check passed before ship handoff, or every reported non-staged branch or worktree is covered by an explicit user choice, retention reason, or blocker.
- Verify the installed skill copies are managed runtime outputs and include fresh runtime manifests.
- Verify the local validation batch passed or the blocking failures were reported.

### Output Contract

Report only:

- the active local release branch and staged task branches
- unresolved blockers or non-blocking debt
- intentionally retained skills repo state, branches, or worktrees with reasons
- anything important not verified

### Example Invocation

`Use $ceratops-codex-skill-stage-release to merge the ready skill branches into the local skills repo release branch, switch the skills repo checkout there, and validate the staged batch.`
