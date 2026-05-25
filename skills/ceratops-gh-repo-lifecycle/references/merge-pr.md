# Merge PR Action

## Goal

Merge one GitHub PR only after proving PR-specific merge gates are satisfied. This action owns final readiness, merge or auto-merge, and cleanup; it does not own dependency campaigns, artifact publishing, first publication, broad repo health, or content repair except narrow active Codex review-thread fixes detected before merge.

## Context

### Script Bundle

- (D) Validate and merge helper: `skills/ceratops-gh-repo-lifecycle/scripts/validate-and-merge-pr.ps1 -Pr NUMBER_OR_URL [-Admin] [-DeleteBranch] [-MergeMethod merge|squash|rebase]` from a source checkout, or `scripts/validate-and-merge-pr.ps1` from the installed skill folder.
- (D) Post-merge sync helper: `skills/ceratops-gh-repo-lifecycle/scripts/sync-main-after-pr.ps1 -RepoRoot PATH -MainBranch main -RemoteName origin [-AlignBranch BRANCH]` from a source checkout, or `scripts/sync-main-after-pr.ps1` from the installed skill folder.
- (D) PR readiness contract check: `python scripts/validation/github-validate-pr-readiness-contract.py --pr NUMBER_OR_URL --allow-admin-review-bypass` for direct admin merges.
- (D) Codex review gate: `python scripts/validation/github-codex-review-gate.py wait --pr NUMBER_OR_URL --wait-seconds 260 --interval-seconds 10 --json`
- (D) Codex thread resolver: `python scripts/validation/github-codex-review-gate.py resolve --thread-id THREAD_ID --json`
- Direct merge command: `gh pr merge --admin NUMBER_OR_URL_OR_BRANCH [--merge|--squash|--rebase] [--delete-branch]`
- (D) Branch deletion policy check for reusable release or integration head branches: `gh repo view OWNER/REPO --json deleteBranchOnMerge`

### Inputs To Capture

- PR URL, number, branch, or local branch that identifies the PR.
- Repo owner and name, default branch, merge method preference, and whether auto-merge or immediate merge is expected.
- Required checks, review policy, conversation-resolution policy, merge queue, branch deletion policy, Codex review policy, and whether the branch is from a fork.
- Release policy, artifact-publish expectation, and whether merging creates an immediate publish obligation.

Infer missing inputs from `gh`, git remotes, current branch, and live repo data before asking.

## Constraints

### Boundaries

- Use this action when the PR content is already ready and the remaining work is to verify gates, merge, and clean up.
- If the PR queue is part of a broader dependency campaign, return to the router and select `dependency-maintenance`.
- If the PR needs code, docs, CI, packaging, artifact publishing, repo creation, or first-time hardening work first, return to the router and select the owning action, except for narrow active Codex review-thread fixes detected here.

### Workflow

#### 1. Inspect local state and auth

- Inspect local git status, current branch, remotes, upstream, default branch, and whether the local branch maps to a PR.
- Check GitHub auth through `gh`, git credentials, env vars, and connected GitHub tooling before asking for login.

#### 2. Run live PR checks first

- (D) Prefer `validate-and-merge-pr.ps1` for ready direct merges; it runs `github-validate-pr-readiness-contract.py`, waits on `github-codex-review-gate.py`, merges with `gh`, verifies the live PR state, and emits compact JSON.
- (D) When not using the helper, run `python scripts/validation/github-validate-pr-readiness-contract.py` before merge or auto-merge decisions and run `python scripts/validation/github-codex-review-gate.py wait --pr NUMBER_OR_URL --wait-seconds 260 --interval-seconds 10 --json`; it must return zero active threads before merge.
- If active Codex threads appear, fix only narrow authorized issues, push, resolve fixed thread IDs, then rerun the Codex gate and PR readiness check.
- Stop instead of merging on ambiguous, risky, out-of-scope, stale, or unverified Codex threads.
- Re-run checks after any action that could change readiness unless the successful command result proves the exact state.

#### 3. Inspect merge-decision exceptions

- Inspect live PR base, head, conversation-resolution state, branch protection result, merge queue state, and workflow-ref changes only when readiness output, repo policy, or the user request makes them relevant.
- Ignore labels, assignees, deployments, broader repo-health surfaces, or code-scanning follow-up unless they materially gate the merge or the user explicitly asked for them.

#### 4. Prepare, merge, and verify

- Confirm the PR is not draft unless the user wants it kept draft.
- Confirm required checks, conversations, Codex review gate, and strict status-check freshness are satisfied; `REVIEW_REQUIRED` does not block explicitly requested direct admin merges, but requested changes still block.
- If workflow refs or Actions permissions changed, confirm no mutable external action refs violate the repo policy.
- Use `validate-and-merge-pr.ps1` for the deterministic direct merge path when available; otherwise use `gh pr merge --admin` for direct merges, adding the PR selector, allowed merge-method flag, and `--delete-branch` when cleanup is intended and allowed.
- For remote-only PR merges, run `gh pr merge <number> --repo OWNER/REPO` from an existing non-repo directory such as `$CODEX_HOME`.
- Use `gh pr merge --auto` only when the user explicitly wants GitHub to defer final merge until remaining requirements finish.
- Verify merge or queued auto-merge from the live PR endpoint rather than trusting only command exit code.

#### 5. Clean up

- Delete the remote head branch only for disposable branches.
- For reusable release or integration branches, verify local and remote head refs still exist at the expected post-merge commit and restore them if GitHub auto-deleted the remote head.
- (D) Use `sync-main-after-pr.ps1` for local default-branch sync when a local checkout is in scope; pass `-AlignBranch` only for reusable local branches that should move to the synced main commit.
- Prune stale refs safely and keep a clearly named safety branch only when needed.

## Done When

### Completion Gate

- A fresh pre-merge PR readiness check and fresh Codex review gate backed the merge decision.
- Post-merge state was verified separately from the live PR endpoint.
- Local repo state, branch, remotes, refs, worktree cleanliness, and retained safety branches were verified.

### Output Contract

Report only:

- final merge outcome
- unresolved blockers or non-blocking debt
- intentionally retained branch or side effect with reason
- anything important not verified
- exact credential step if blocked
