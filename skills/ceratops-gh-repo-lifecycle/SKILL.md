---
name: ceratops-gh-repo-lifecycle
description: Route Ceratops GitHub repository lifecycle work to action references for create-or-publish, health-audit, dependency-maintenance, ship-change, and merge-pr work. Use when Codex should create or harden a repo, audit or repair repo health, process dependency PRs or alerts, ship local changes through GitHub, or finalize a ready PR.
---

# Ceratops GH Repo Lifecycle

## Goal

Route GitHub repository lifecycle work to the narrowest action reference, then follow that reference as the execution contract. Keep one live GitHub repo capability surface instead of separate skill identities for adjacent repo creation, health, dependency, shipping, and merge actions.

## Context

### Action References

- Create or publish a repo: `references/create-or-publish.md`
- Audit or repair repo health: `references/health-audit.md`
- Maintain dependency PRs or alerts: `references/dependency-maintenance.md`
- Ship local repo changes through GitHub: `references/ship-change.md`
- Finalize an already-ready PR: `references/merge-pr.md`

### Inputs To Capture

- Target repo, local checkout, PR, branch, artifact, dependency queue, or creation request that identifies the action.
- Whether the work is first publication, existing repo health, dependency maintenance, local change shipping, or PR finalization.
- Required live GitHub, local repo, CI, artifact, and credential context named by the selected action reference.

Infer missing inputs from local git state, `gh`, remotes, manifests, and live repo data before asking.

## Constraints

### Skill-Specific Rules

- Load only the selected action reference unless the current action explicitly hands off to another action.
- Use the action references as the source of truth for scripts, readiness gates, cleanup rules, and output contracts.
- Keep repo creation, repo health, dependency, shipping, and merge behavior inside this router and its `references/` files; do not introduce alias skills or old-name shims.
- For PR finalization reached from a broader shipping or dependency action, continue with `references/merge-pr.md` instead of duplicating merge gates.
- Run broad repo or artifact health checks only when the selected action requires them or a concrete uncertainty makes them relevant.

### Boundaries

- Use this skill for GitHub repo creation or publication, existing repo health, dependency maintenance, local repo change shipping, and PR merge or auto-merge decisions.
- If the task is skill creation, skill mutation, local skill release promotion, or staged skill remote shipping, stop and use `$ceratops-skill-lifecycle`.
- If the task is contract review rather than lifecycle execution, use the contract review workflow.
- If the task is general GitHub triage with no Ceratops lifecycle action, use the relevant generic GitHub capability.

### Workflow

#### 1. Classify the action

- Use `create-or-publish` when the repo does not yet exist publicly, needs first-time hardening, or needs first artifact publication.
- Use `health-audit` when the repo exists and the main goal is validation, stale-state cleanup, or safe health repair.
- Use `dependency-maintenance` when the main goal is dependency-bot PRs, dependency alerts, security updates, or dependency queue handling.
- Use `ship-change` when the repo already exists and local changes need to be completed, validated, PR'd, merged, and optionally released.
- Use `merge-pr` when the PR content is already ready and only PR-specific readiness, merge, and cleanup remain.

#### 2. Execute the selected action

- Read the matching file under `references/`.
- Follow that action's script bundle, boundaries, workflow, completion gate, and output contract.
- If the selected action discovers that another action owns the remaining work, switch to that action reference and report the handoff reason only when it changes the user's next step.

#### 3. Close from action evidence

- Match final claims to the exact action checks and live state that were run.
- Report retained branches, worktrees, PRs, artifacts, credentials, or external side effects only when the selected action requires them.

## Done When

### Completion Gate

- The selected action reference was followed or the task was explicitly blocked before action execution.
- Any cross-action handoff used another reference in this router rather than a standalone skill identity.
- GitHub, repo, artifact, and local-state claims are limited to the checks and live data actually verified.

### Output Contract

Report only:

- selected action and final outcome
- unresolved blockers or non-blocking debt
- intentionally retained branches, PRs, artifacts, worktrees, or external side effects with reasons
- anything important not verified

### Example Invocation

`Use $ceratops-gh-repo-lifecycle to ship these local repo changes through GitHub, then finalize the PR once readiness gates pass.`
