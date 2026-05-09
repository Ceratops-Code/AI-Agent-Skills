---
name: ceratops-skill-fast-change
description: Apply a simple Ceratops skill change directly on an active release branch, commit it there, and update only the affected runtime skill copy.
---

# Ceratops Skill Fast Change

## Goal

Apply one clearly understood Ceratops skill change without creating a task worktree, broad validation, or broad repo checks, then commit the change on the active release branch and update the specific installed runtime skill.

## Context

### Inputs To Capture

- The exact skill, rule, metadata field, or small file change to apply.
- The source checkout that is already on the intended `release/*` branch.
- Whether the same change should also be copied and committed into any active task worktrees or branches.
- The target runtime root. Use `$CODEX_HOME/skills` unless the user provides another runtime root.

If the change is not exact, low-risk, and dependency-free, stop and use `$ceratops-skill-update` instead.

## Constraints

### Skill-Specific Rules

- Use this skill only when the user explicitly invokes it or explicitly asks for a fast direct skill change.
- Do not create a worktree.
- Do not run broad validation, full validation, GitHub checks, repo health audits, or consistency audits.
- Before editing, verify only that the checkout is on the intended `release/*` branch, the target file exists, and the working tree is clean or the dirty files are exactly the intended change scope.
- Apply only one simple, dependency-free source change such as a single rule update, a narrow wording fix, or one metadata correction.
- After editing, review the changed diff, commit the source change on the release branch, and update only the affected runtime skill copy.
- Prefer `scripts/install-skills.ps1 -Skill <skill-name>` for runtime update when the repo provides that installer; otherwise update only the directly corresponding runtime skill files that can be copied without generation.
- Do not remove stale runtime folders, regenerate all skills, or update unrelated installed skills.
- If the user requests propagation to active worktrees or branches, apply the same patch there only when it merges cleanly and commit each updated branch separately; report any branch that cannot receive the change without manual resolution.
- Stop before destructive cleanup, broad refactors, template changes, helper changes, or changes with unverified dependencies.

### Boundaries

- Use this skill for known-safe Ceratops skill source changes that intentionally bypass the normal worktree and validation workflow.
- If the change touches shared sections, templates, runtime generation, validation logic, contracts, helper scripts, or multiple skills, use `$ceratops-skill-update`.
- If the change creates a new skill, use `$ceratops-skill-create`.

### Workflow

1. Confirm the branch, target skill, exact change, and optional propagation request.
2. Perform only the narrow preflight checks needed to avoid editing the wrong branch or file.
3. Patch the target source file and inspect the diff.
4. Commit the release-branch change.
5. Update only the affected runtime skill copy.
6. Optionally apply and commit the same change in explicitly requested active worktrees or branches.

## Done When

### Completion Gate

- The release branch contains the committed change.
- The affected runtime skill copy was updated or the exact blocker is reported.
- No broad validation or broad checks were run.
- Optional branch/worktree propagation is either completed, intentionally skipped, or blocked with exact branch names.

### Output Contract

Report only:

- release branch and commit
- affected source and runtime skill
- optional propagated branches or blockers
- intentionally skipped checks
