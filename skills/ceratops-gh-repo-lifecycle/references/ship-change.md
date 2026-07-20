# Ship Change Action

## Goal

Take an existing published repo from local changes to a verified merged result.
Publish external artifacts only when the change affects a releasable package,
image, module, binary, or other public artifact. Use the `merge-pr` action for
final PR readiness and merge.

## Context

### Inputs To Capture

- Intended change scope, issue or PR reference, target branch, repo owner and
  name, and merge preference.
- Required local checks, CI checks, security gates, branch protection, release
  workflow, and package verification commands.
- Whether the run touches GitHub Actions workflows or repo Actions permissions,
  and the repo's current SHA-pinning posture.
- Topics, CODEOWNERS, SECURITY instructions, README examples, and local consumer
  paths affected by the change.

Infer missing inputs from local files and live repo state before asking.

## Constraints

### Boundaries

- Use this action when the repo already exists and local changes need
  completion, merge, and optional release.
- For the skills repo or another skill-source repo, use the skill lifecycle
  `ship-to-remote` action when the staged release branch is being shipped.
- If the repo is not published or lacks a usable remote, return to the parent skill
  and select `create-or-publish`.
- If the task is only repo validation or stale-state cleanup with no content
  changes, select `health-audit`.
- If only PR finalization remains and no release or artifact publish is required
  after merge, continue with `merge-pr`.

### Workflow

#### 1. Inspect state and scope

- Inspect git status, diff, untracked files, remotes, current branch, upstream,
  open PRs, tags, releases, CI config, manifests, lockfiles, docs, generated
  files, and registry metadata.
- Refresh remote refs with `git fetch --prune origin` before relying on
  remote-tracking branch presence, cleanup status, or branch-reuse decisions.
- Prefer the same local and remote branch name by default.
- Identify whether the change is code, docs, config, dependency, release,
  packaging, security, CI, or generated-artifact work.
- Confirm no secrets, private data, machine-local paths, or internal-only
  references are being introduced.
- Reuse an existing branch or PR when appropriate instead of creating
  duplicates.

#### 2. Research only where needed

- Use local repo files, targeted `gh` or GitHub API calls, and touched-registry
  evidence before checking docs.
- Check current official docs for GitHub PR, Actions, security, release
  behavior, and touched registry or package-manager workflow only when local
  state, `gh`, GitHub API, or script output leaves the next decision ambiguous.
- Compare at most one or two strong reference repos only for a concrete
  ambiguous docs, security, CI, release, or packaging question.

#### 3. Complete the change

- Finish in-scope code, docs, tests, generated files, and packaging metadata.
- If the run touches workflow files or GitHub Actions settings, pin every
  non-local action in changed workflows to a verified full SHA with a same-line
  version comment.
- Add regression tests or checks for meaningful behavior fixes or behavior
  changes.
- Update README, examples, install or run commands, SECURITY, CONTRIBUTING,
  changelog, release notes, package metadata, topics, CODEOWNERS, CI, and
  artifact metadata only when stale.

#### 4. Validate locally

- Run relevant local checks: format, lint, tests, smoke tests, build, packaging,
  generated-file checks, container build, or security checks.
- Fix in-scope failures instead of stopping at the first error.

#### 5. PR, CI, merge, and publish

- Create or update a branch and commit intentionally.
- Push the branch and create or update a PR with concise change and validation
  evidence.
- Wait for required CI, code scanning, and branch protection checks, and fix
  in-scope failures.
- When only PR finalization remains, continue with `merge-pr`.
- After merge, run `python -m github_pr_workflow sync --repo-root PATH` from the
  lifecycle skill's `scripts` folder to sync the local default branch, then
  prune stale refs, remove temporary worktrees as soon as their branches are no
  longer needed, and keep a safety branch or worktree only with an explicit
  reason.
- Publish and verify touched artifacts through the package manager, registry
  CLI, or registry API that owns the artifact surface.

## Done When

### Completion Gate

- PR readiness and merge were handled through `merge-pr`.
- Changed workflow files use full-SHA action refs when the run touched GitHub
  Actions workflows or settings.
- Local state is verified: default branch, worktree, remotes, refs, generated
  files, artifacts, temp paths, caches, credential changes, and local consumer
  paths.
- Any temporary branch or worktree created or used for the run was removed
  unless intentionally retained with an active-workflow reason.

### Output Contract

Report only:

- overall shipping outcome
- released or published artifact details when materially relevant
- unresolved blockers or non-blocking debt
- intentionally retained branches, PRs, files, temp paths, or side effects with
  reasons
- anything important not verified
- exact credential step or paid requirement if blocked
