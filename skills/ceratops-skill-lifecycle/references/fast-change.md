# Fast Change Action

## Goal

Apply one clearly understood Ceratops skill change directly on an intended local
release branch without a task worktree, broad validation, or broad repo checks,
then commit the change and update only the affected runtime skill copy.

## Context

### Inputs To Capture

- Exact skill, rule, metadata field, or small file change to apply.
- Source checkout that is already on the intended `release/*` branch, or is
  clean on `main` and can be switched to the intended local `release/*` branch
  through the repo's release-branch helper.
- Whether the same change should also be copied and committed into any active
  task worktrees or branches.
- Target installed skills directory. Use `$CODEX_HOME/skills` unless the user
  provides another target.

If the change is not exact, low-risk, and dependency-free, return to the router
and select `update`.

### Script Bundle

- (D) Fast-change preflight:
  `skills/ceratops-skill-lifecycle/scripts/fast-change-preflight.ps1
  -SkillsRepoRoot <repo> -ReleaseBranch release/local -SkillName <skill-name>
  -TargetPath <target-file>` from a source checkout, or
  `scripts/fast-change-preflight.ps1 -SkillsRepoRoot <repo> -ReleaseBranch
  release/local -SkillName <skill-name> -TargetPath <target-file>` from the
  installed skill folder.

## Constraints

### Boundaries

- Use this action only when the user explicitly asks for a fast direct skill
  change.
- If the change touches shared sections, templates, runtime generation,
  validation logic, contracts, helper scripts, or multiple skills, select
  `update`.
- If the change creates a new skill, select `create`.

### Workflow

1. Confirm branch, target skill, exact change, and optional propagation request.
2. If the checkout is clean on `main`, prepare and switch to the intended local
   `release/*` branch with the repo's release-branch helper; if no helper
   exists, stop instead of hand-rolling release branch setup.
3. (D) Run fast-change preflight for the intended branch, clean worktree, target
   file, and targeted install command evidence; stop on helper failure.
4. Patch the target source file and inspect the diff.
5. Commit the release-branch change.
6. Update only the affected runtime skill copy through
   `scripts/install-skills.ps1 -Skill <skill-name>` when available; otherwise
   child-copy that skill folder and read back a changed sentinel.
7. Optionally apply and commit the same change in explicitly requested active
   worktrees or branches when it merges cleanly.

## Done When

### Completion Gate

- The checkout is on the intended local `release/*` branch and contains the
  committed change.
- The affected runtime skill copy was updated or the exact blocker is reported.
- No broad validation or broad checks were run.
- Optional branch or worktree propagation is completed, intentionally skipped,
  or blocked with exact branch names.

### Output Contract

Report only:

- release branch and commit
- affected source and runtime skill
- optional propagated branches or blockers
- intentionally skipped checks
