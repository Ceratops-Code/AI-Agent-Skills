---
name: ceratops-gh-ship-change
description: Ship repository changes through GitHub and any relevant artifact registry with Ceratops defaults, using PR readiness checks before merge decisions.
---

# Ceratops GH Ship Repo Changes

## Goal

Take an existing published repo from local changes to a verified merged result. Publish external artifacts only when the change affects a releasable package, image, module, binary, or other public artifact. Use the PR merge skill for final PR readiness and merge.

## Context

### Inputs To Capture

- Intended change scope, issue or PR reference, target branch, repo owner and name, and merge preference.
- Required local checks, CI checks, security gates, branch protection, release workflow, and package verification commands.
- Whether the run touches GitHub Actions workflows or repo Actions permissions, and whether the repo already enforces SHA pinning.
- Topics, CODEOWNERS, SECURITY instructions, README examples, and local consumer paths affected by the change.

Infer missing inputs from local files and live repo state before asking.

## Constraints

### Boundaries

- Use this skill when the repo already exists and there are actual local changes to complete, merge, and optionally release.
- For the skills repo or another skill-source repo, use this skill only after skill-source changes are committed or intentionally staged for GitHub shipping.
- If the repo is not yet published or lacks a usable remote, stop because first-time publication is outside this skill's scope.
- If the task is only repo validation or stale-state cleanup with no content changes, stop because that work is outside this shipping skill's scope.
- If only PR finalization remains, no content changes are needed, and no release or artifact publish is required after merge, stop this workflow immediately and continue with `$ceratops-gh-merge-pr`, even when this workflow created or updated the PR.

### Workflow

#### 1. Inspect state and scope

- Inspect git status, diff, untracked files, remotes, current branch, upstream, open PRs, tags, releases, CI config, manifests, lockfiles, docs, generated files, and registry metadata.
- Refresh remote refs with `git fetch --prune origin` before relying on remote-tracking branch presence, cleanup status, or branch-reuse decisions.
- Prefer the same local and remote branch name by default. Do not use `local:remote` branch-name remapping unless there is a concrete benefit and the user explicitly wants that tradeoff.
- Identify whether the change is code, docs, config, dependency, release, packaging, security, CI, or generated-artifact work.
- Confirm no secrets, private data, machine-local paths, or internal-only references are being introduced.
- Reuse an existing branch or PR when appropriate instead of creating duplicates.

#### 2. Research only when the next decision needs it

- Default to the narrowest evidence that answers the next shipping decision: local repo files, targeted `gh` or GitHub API calls, and touched-registry evidence before checking docs.
- Check current official docs for GitHub PR, Actions, security, release behavior, and any touched registry or package-manager workflow only when the next task decision remains concretely ambiguous after local state, `gh`, GitHub API, or script output, or when those sources materially conflict.
- Compare at most 1-2 strong reference repos only for a concrete ambiguous docs, security, CI, release, or packaging question.

#### 3. Complete the change

- Finish in-scope code, docs, tests, generated files, and packaging metadata.
- If the run touches workflow files or GitHub Actions settings, pin every non-local action in the changed workflows to a verified full SHA with a same-line version comment and do not introduce new mutable refs.
- Add regression tests or regression checks for meaningful behavior fixes or behavior changes.
- Update README, examples, install or run commands, SECURITY, CONTRIBUTING, changelog, release notes, package metadata, topics, CODEOWNERS, CI, and artifact metadata only when the change makes them stale.

#### 4. Validate locally

- Run the relevant local checks: format, lint, tests, smoke tests, build, packaging, generated-file checks, container build, or security checks.
- Fix in-scope failures instead of stopping at the first error.

#### 5. PR, CI, and merge

- Create or update a branch and commit intentionally.
- Push the branch and create or update a PR with concise change and validation evidence.
- Wait for required CI, code scanning, and branch protection checks, and fix in-scope failures.
- When only PR finalization remains, continue with `$ceratops-gh-merge-pr` for PR readiness, merge or auto-merge, and remote PR branch cleanup.
- After the PR is merged, sync the local default branch, prune stale refs, remove any temporary worktree created or used for the run as soon as its branch is no longer needed, and keep a safety branch or worktree only when needed with an explicit reason.

#### 6. Publish artifacts when relevant

- Publish and verify touched artifacts through the package manager, registry CLI, or registry API that owns the artifact surface.

## Done When

### Completion Gate

- Verify PR readiness and merge were handled by `$ceratops-gh-merge-pr`.
- Verify changed workflow files still use the intended full-SHA action refs when the run touched GitHub Actions workflows or settings.
- Verify local state: default branch, worktree, remotes, refs, generated files, artifacts, temp paths, caches, credential changes, and local consumer paths.
- Verify any temporary branch or worktree created or used for the run was removed unless intentionally retained with an explicit active-workflow reason.

### Output Contract

Report only:

- overall shipping outcome
- released or published artifact details when materially relevant to downstream use
- unresolved blockers or non-blocking debt
- intentionally retained branches, PRs, files, temp paths, or side effects with reasons
- anything important not verified
- exact credential step or paid requirement if blocked

### Example Invocation

`Use $ceratops-gh-ship-change to ship these repo changes through GitHub, publish any relevant artifacts, verify them locally, and clean up state.`
