# Fast Change Action

## Goal

Apply one clearly understood Ceratops skill change directly on an active release branch without a task worktree, broad validation, or broad repo checks, then commit the change and update only the affected runtime skill copy.

## Context

### Inputs To Capture

- Exact skill, rule, metadata field, or small file change to apply.
- Source checkout that is already on the intended `release/*` branch.
- Whether the same change should also be copied and committed into any active task worktrees or branches.
- Target installed skills directory. Use `$CODEX_HOME/skills` unless the user provides another target.

If the change is not exact, low-risk, and dependency-free, return to the router and select `update`.

## Constraints

### Boundaries

- Use this action only when the user explicitly asks for a fast direct skill change.
- If the change touches shared sections, templates, runtime generation, validation logic, contracts, helper scripts, or multiple skills, select `update`.
- If the change creates a new skill, select `create`.

### Workflow

1. Confirm branch, target skill, exact change, and optional propagation request.
2. Verify only that the checkout is on the intended `release/*` branch, the target file exists, and the worktree is clean or dirty only in the intended scope.
3. Patch the target source file and inspect the diff.
4. Commit the release-branch change.
5. Update only the affected runtime skill copy through `scripts/install-skills.ps1 -Skill <skill-name>` when available; otherwise child-copy that skill folder and read back a changed sentinel.
6. Optionally apply and commit the same change in explicitly requested active worktrees or branches when it merges cleanly.

## Done When

### Completion Gate

- The release branch contains the committed change.
- The affected runtime skill copy was updated or the exact blocker is reported.
- No broad validation or broad checks were run.
- Optional branch or worktree propagation is completed, intentionally skipped, or blocked with exact branch names.

### Output Contract

Report only:

- release branch and commit
- affected source and runtime skill
- optional propagated branches or blockers
- intentionally skipped checks
