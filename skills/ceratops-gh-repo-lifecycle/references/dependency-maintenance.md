# Dependency Maintenance Action

## Goal

Handle repository dependencies as an end-to-end maintenance loop. Prefer safe automation for security, patch, and minor updates; stop on ambiguous major upgrades, production risk, unavailable credentials, or paid requirements; and ground queue handling and merge decisions in bundled GitHub helper scripts first.

## Context

### Script Bundle

- (D) Dependency/security posture check: `python scripts/validation/github-validate-repo-artifact-contract.py --repo OWNER/REPO --select repo:dependency --select code:dependency --local-repo-path PATH`
- (D) PR readiness contract check: `python scripts/validation/github-validate-pr-readiness-contract.py --pr NUMBER_OR_URL`

### Inputs To Capture

- Target repo, branch, dependency PRs, package-manager ecosystems, and whether security updates are priority-only, security-only, or part of a full dependency PR queue.
- Release policy, changelog expectations, local verification commands, branch protection, required checks, code scanning, vulnerability alerts, auto-merge policy, and delete-branch policy.
- Whether `github-actions` updates are in scope and whether the repo enforces SHA pinning.

Infer missing inputs from local files and live GitHub state before asking.

## Constraints

### Boundaries

- Use this action when the work is primarily dependency updates, alert cleanup, or dependency-bot PR processing.
- If the repo is not published, lacks a usable remote, needs substantial non-dependency code changes, or only needs PR finalization, return to the router and select the owning action.

### Workflow

#### 1. Inspect queue and risk

- Inspect git state, dependency-bot PRs, dependency alerts, bot config, manifests, lockfiles, CI, security settings, tags, releases, and registry metadata.
- Check GitHub auth, registry auth, and connected tooling before asking for credentials.
- Build an update queue from live dependency-bot PRs, alerts, alert-linked update PRs, and local manifests; classify each update by risk.
- Treat Dependabot or Renovate PRs as first-class queue items even when no security alert is open.
- For each queued PR or alert, capture whether it is security-linked or routine, affected package or action, ecosystem, path, update size, branch freshness, checks, review state, mergeability, and policy fit.

#### 2. Research update evidence

- Use official package metadata, release notes, changelogs, advisories, compatibility notes, migration guides, and package-manager docs before merging meaningful updates.
- Use strong current reference repos only when ecosystem-specific update patterns are unclear and comparison will reduce risk.
- Do not infer that an update is safe from version number alone.

#### 3. Re-check candidates with scripts

- (D) Run the bundled PR-readiness script before enabling auto-merge or merging a dependency PR.
- Include live repo dependency selection only when the queue changes or explicitly verifies GitHub dependency/security posture.
- Include code dependency selection only when explicitly verifying Dependabot config, workflow SHA pinning, manifests, lockfiles, local secret-pattern posture, or other repo-content dependency posture.
- Do not run broader GitHub, code, or artifact contract checks for ordinary dependency PRs whose only moving parts are manifests, lockfiles, tests, CI results, and PR readiness.

#### 4. Process updates recursively

- Prioritize security and low-risk updates unless ordering constraints require otherwise.
- Process already-open routine dependency PRs when in scope and low-risk; classify routine PRs as retained when the task is security-only.
- Inspect the diff, manifest changes, lockfile changes, transitive changes, CI impact, and release impact for each update.
- Refresh lockfiles or generated dependency metadata using the project package manager unless the ecosystem expects manual edits.
- For `github-actions` updates, keep external action refs on full commit SHAs with same-line version comments when the repo enforces or already uses SHA pinning.
- Run targeted tests first, then full required checks before merge.
- If merging directly, use `gh pr merge --admin` with the allowed merge-method flag and `--delete-branch` when cleanup is intended and allowed.
- After each merge, sync the default branch, re-check open dependency-bot PRs and dependency alerts, and continue until no actionable update remains or a real blocker is reached.

#### 5. Publish and cleanup

- Execute the artifact contract when merged dependency updates require a release or artifact publish under repo policy.
- Close or classify stale, superseded, duplicate, or blocked dependency PRs only when the reason is proven.
- Delete merged branches when safe and allowed, sync the local default branch, and prune stale refs.

## Done When

### Completion Gate

- Every dependency PR decision is backed by a fresh `github-validate-pr-readiness-contract.py` run.
- Dependency/security posture is verified with `github-validate-repo-artifact-contract.py --select repo:dependency --select code:dependency --local-repo-path PATH` when queue, alert, label, security-setting, config, workflow ref, manifest, lockfile, or local file posture was part of the run.
- Every dependency-bot PR and dependency alert in the inspected scope is resolved, merged, blocked, out of scope, or intentionally retained with a concrete reason.
- Local state is verified: default branch, worktree, remotes, refs, lockfiles, generated files, temp paths, caches, credentials, and retained branches.

### Output Contract

Report only:

- dependency updates applied
- dependency updates skipped, retained, or blocked with exact reasons
- released or published artifact details when materially relevant
- unresolved blockers or non-blocking debt
- anything important not verified
- exact credential step or paid requirement if blocked
