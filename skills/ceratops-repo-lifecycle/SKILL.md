---
name: ceratops-repo-lifecycle
description: Route Ceratops repository lifecycle work to action references for repository creation, compatibility, contracts, health, dependencies, local promotion, deterministic deployment, GitHub shipping, and PR merge. Use when Codex should create or harden a repository, make it Ceratops-compatible, review its contracts, disposition CodeQL, maintain dependencies, promote selected task branches into a local release branch with or without deployment, ship a staged branch through guarded GitHub merge and post-merge deployment, or finalize an already-ready PR.
---

# Ceratops Repository Lifecycle

## Goal

Route repository compatibility, local Git, GitHub, and deployment lifecycle
work to the narrowest action reference. Keep repository state transitions in
one skill while each repository owns its executable deployment behavior in
`deploy/deploy.yml`.

## Context

### Action References

- Create or publish a repository: `references/create-or-publish.md`
- Make an existing repository Ceratops-compatible:
  `references/make-repo-compatible.md`
- Review GitHub, code, PR, artifact, registry, and release contracts:
  `references/contracts-review.md`
- Validate or apply a CodeQL alert disposition:
  `references/codeql-disposition.md`
- Audit or repair repository health: `references/health-audit.md`
- Maintain dependency PRs or alerts: `references/dependency-maintenance.md`
- Promote selected branches with or without deployment:
  `references/promote-change.md`
- Ship, synchronize, deploy, and finalize selected work: `references/ship.md`
- Finalize an already-ready PR: `references/merge-pr.md`

### Inputs To Capture

- Target repository, checkout, task worktree, branch, selected source branches,
  PR, artifact, dependency queue, compatibility gap, or creation request that
  identifies the action.
- Whether promotion should stop after assembling `release/local`, run its
  optional `deploy` operation before shipping, or continue directly into
  terminal shipping with deployment only after merge.
- Required live GitHub, local repository, CI, artifact, credential, and
  deployment context named by the selected action reference.

Infer missing inputs from local Git state, the deployment contract, `gh`,
remotes, manifests, and live repository data before asking.

## Constraints

### Skill-Specific Rules

- Use action references as the source of truth for deterministic helpers,
  readiness gates, cleanup, and output contracts.
- Keep local promotion, GitHub publication, guarded merge, synchronization,
  deployment routing, repository compatibility, and selected-source cleanup in
  this skill; do not create alias skills or old-name shims.
- Execute only named structured operations from `deploy/deploy.yml` through
  the operation runner. Do not interpret prose as deployment commands.
- Use `references/merge-pr.md` for standalone PR finalization. Integrated ship
  must preserve every readiness, CI, Codex-review, and exact-head gate before
  its final admin merge.
- Inspect only branches and worktrees named by the selected pending-work scope.

### Boundaries

- Use this skill for repository creation, compatibility, local Git promotion,
  GitHub lifecycle work, deterministic deployment, dependency maintenance,
  CodeQL disposition, and PR merge decisions.
- Use `$ceratops-skill-lifecycle` for skill-domain creation, mutation, managed
  deployment, contract review, or consistency review; accept its promotion or
  shipping handoff and return the managed-skill phase.
- Use `references/contracts-review.md` for contract review rather than
  lifecycle execution.
- Use a generic GitHub capability only when no Ceratops repository action fits
  or the selected reference explicitly requires it.

### Workflow

#### 1. Classify the action

- Use `create-or-publish`, `make-repo-compatible`, `contracts-review`,
  `codeql-disposition`, `health-audit`, or `dependency-maintenance` for their
  named repository surfaces.
- Use `promote` when selected committed branches should join a local
  `release/local` branch without deployment.
- Use `promote-and-deploy` when the same promotion should run optional
  repository deployment, execute a returned handoff, and report managed skills
  when no handoff is declared.
- Use composed promotion and shipping when selected committed branches should
  enter the complete ship workflow immediately after promotion; only shipping
  may deploy in this mode.
- Use `ship` for the complete staged-branch PR, gate, merge, main sync,
  optional repository deployment, returned handoff handling, late recheck, and
  selected-source cleanup workflow.
- Use `merge-pr` only when standalone PR finalization is the whole task.

#### 2. Close from action evidence

- Match final claims to the exact action checks and state actually verified.
- Report retained branches, worktrees, scopes, PRs, artifacts, or external side
  effects only when the selected action requires them.

## Done When

### Completion Gate

- Repository, deployment, GitHub, artifact, and local-state claims are limited
  to the checks and live data actually verified.

### Output Contract

Report only:

- selected action and final outcome
- unresolved blockers or non-blocking debt
- intentionally retained branches, scopes, PRs, artifacts, worktrees, or
  external side effects with reasons
- anything important not verified

### Example Invocation

`Use $ceratops-repo-lifecycle to promote these task branches into release/local
without deployment.`
