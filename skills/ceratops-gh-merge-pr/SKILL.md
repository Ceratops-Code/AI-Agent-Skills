---
name: ceratops-gh-merge-pr
description: Merge a GitHub pull request safely with Ceratops defaults, starting with a live scripted readiness check and ending with verified cleanup.
---

# Ceratops GH Merge PR

## Goal

Merge one GitHub PR only after proving the PR-specific merge gates are satisfied. This is the narrow finalization workflow for PR completion; it does not take ownership of code changes, dependency campaigns, artifact publishing, first-time publication, or broad repo health. Start with the bundled live PR check instead of relying on prose summaries or stale screenshots.

## Context

### Script Bundle

- (D) PR readiness contract check: `python scripts/validation/github-validate-pr-readiness-contract.py --pr NUMBER_OR_URL`
- Direct merge command: `gh pr merge --admin NUMBER_OR_URL_OR_BRANCH [--merge|--squash|--rebase] [--delete-branch]`

### Inputs To Capture

- PR URL, number, branch, or local branch that identifies the PR.
- Repo owner and name, default branch, merge method preference, and whether auto-merge or immediate merge is expected.
- Release policy, artifact-publish expectation, and whether merging this PR creates an immediate publish obligation.
- Required checks, review policy, conversation-resolution policy, merge queue, admin enforcement, branch deletion policy, and whether the branch is from a fork.
- Whether the PR changes workflow refs or GitHub Actions permissions.
- Local branch and worktree state that might be affected by syncing or cleanup.

Infer missing inputs from `gh`, git remotes, the current branch, and live repo data before asking.

## Constraints

### Boundaries

- Use this skill when the PR content is already ready and the remaining work is to verify gates, merge, and clean up.
- If the PR queue is part of a broader dependency-maintenance campaign, stop and use `$ceratops-gh-repo-dependencies-maintenance`.
- If the PR needs code, docs, CI, packaging, artifact publishing, repo creation, or first-time hardening work first, stop because that work is outside this skill's scope.

### Workflow

#### 1. Inspect local state and auth

- Inspect local git status, current branch, remotes, upstream, default branch, and whether the local branch maps to a PR.
- Check GitHub auth through `gh`, git credentials, env vars, and connected GitHub tooling before asking for login.

#### 2. Run the live PR check first

- (D) Run `python scripts/validation/github-validate-pr-readiness-contract.py` before merge or auto-merge decisions.
- (D) Treat the script output as the first source of truth for draft state, mergeability, blocking review decisions, visible status-check failures, and pending status checks.
- Re-run the script after an action that could change readiness when the successful command result does not already prove the exact state, or when CI, merge queue, review, or conversation state is asynchronous.

#### 3. Inspect only merge-decision exceptions

- Inspect live PR base, head, conversation-resolution state, branch protection result, merge queue state, and workflow-ref changes only when the readiness check, current repo policy, or the user's request makes them relevant.
- Ignore labels, assignees, deployments, broader repo-health surfaces, or detailed code-scanning follow-up unless they materially gate the merge or the user explicitly asked for them.

#### 4. Research current rules when needed

- Check current official GitHub docs or `gh` help only when merge queue, auto-merge, branch protection, required status checks, review behavior, or cleanup semantics remain concretely ambiguous after the readiness check and targeted live state, or when those sources materially conflict.
- Prefer live GitHub API or CLI state over memory.

#### 5. Prepare the PR

- Confirm the PR is not draft unless the user explicitly wants to keep it draft.
- Confirm required checks are green or pending in a state suitable for auto-merge.
- Confirm required reviews are satisfied and no blocking review remains.
- Confirm required conversations are resolved.
- Confirm the PR is up to date when strict status checks require it.
- Confirm the PR can be completed by merge and cleanup alone. If completion also requires release, artifact publishing, or further repo changes, stop because that work is outside this skill's scope.
- If the PR changes workflow refs or GitHub Actions permissions, confirm it does not introduce mutable external action refs that violate the repo's SHA-pinning policy. If it does, stop because content repair is outside this skill's scope.

#### 6. Merge or enable auto-merge

- Use `gh pr merge --admin` for every direct merge this skill performs. Add the PR selector, the repo's allowed merge-method flag, and `--delete-branch` when cleanup is intended and allowed.
- Use `gh pr merge --auto` only when the user explicitly wants GitHub to defer the final merge until remaining requirements finish; otherwise close the PR now with `gh pr merge --admin`.
- If the repo would otherwise route the PR through a merge queue, treat `gh pr merge --admin` as an intentional queue bypass and use it only after the fresh readiness check and live PR state show the bypass is justified.
- If the readiness check is green on checks and mergeability and the only remaining blocker is the acting maintainer's own required review, and the repo intentionally allows that maintainer to self-merge, use `gh pr merge --admin` instead of fabricating approval or waiting for a second account.
- Use the repo's allowed and preferred merge method.
- Verify the merge or queued auto-merge from the live PR endpoint instead of trusting only the command exit code.

#### 7. Clean up and verify

- Delete the remote head branch only when the PR is merged, deletion is allowed, and the branch is not a reusable release or integration branch.
- After the merge, verify the live PR endpoint shows the PR as merged instead of reusing the pre-merge readiness script on a now-closed PR.
- Sync the local default branch to the remote default branch without destructive resets.
- Prune stale refs safely.
- Keep a clearly named safety branch only when needed to preserve reachable work after a squash or rebase merge.

## Done When

### Completion Gate

- Verify the final merge decision was backed by a fresh pre-merge `python scripts/validation/github-validate-pr-readiness-contract.py` run, then verify the post-merge PR state separately from the live PR endpoint.
- Verify live PR state, checks, reviews, conversations, and branch protection before merge decisions; after a successful merge or branch command, reread only asynchronous queue state or broader claims not proven by that command.
- Verify local repo state, branch, remotes, refs, worktree cleanliness, and retained safety branches.

### Output Contract

Report only:

- final merge outcome
- unresolved blockers or non-blocking debt
- intentionally retained branch or side effect with reason
- anything important not verified
- exact credential step if blocked

### Example Invocation

`Use $ceratops-gh-merge-pr for PR #12. Run the bundled live PR check first, merge it when gates are satisfied, delete the branch, and sync local main.`
