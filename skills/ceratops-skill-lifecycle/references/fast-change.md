# Fast Change Action

## Goal

Apply an exact compatible change directly on the primary local release branch,
commit it, and update only the affected runtime skills. Prefer this action
whenever its complete scope is eligible; it is not limited to one file or one
skill.

## Context

### Inputs To Capture

- Complete intended target paths and selected existing skills.
- Exact coherent change, affected executable behavior, and targeted checks.
- Primary skills checkout, intended local `release/*` branch, and runtime root.
- Any explicitly requested propagation into retained task branches.

Infer these inputs from the current task and repository before asking.

### Script Bundle

- (D) From a clean `main` checkout, prepare the release branch:
  `python scripts/promote-repository.py --repo-root PATH --main-branch main
  --release-branch release/local --remote-name origin
  --prepare-release-only` from the repository lifecycle bundle.
- (D) Validate the complete direct-release scope:
  `python scripts/validate-fast-change-readiness.py --repo-root PATH
  --release-branch release/local --skill NAME [--skill NAME...]
  --target PATH [--target PATH...]` from the skill lifecycle bundle.

## Constraints

### Boundaries

- Use this action whenever one exact coherent change is fully contained in
  existing selected skill folders and targeted installation can validate every
  affected skill.
- Multiple files and multiple skills are eligible when all are required by the
  same coherent change and every target is declared before editing.
- Executable helper changes qualify only when they preserve the existing public
  interface, dependencies, persistent state, and side-effect scope and have a
  safe targeted behavior check.
- Use `update` when any affected path is shared, generated, repository-control,
  manifest, template, deployment, installer, runtime-generation, validator, or
  contract state; when a helper boundary changes; or when targeted checks
  cannot establish safety.
- Do not use this action to create, rename, or delete a skill.

### Workflow

1. Confirm the complete target, selected skills, intended release branch,
   coherent change, and targeted checks.
2. If the primary checkout is clean on `main`, run repository lifecycle release
   preparation. If it is already clean on the intended release branch, keep it;
   otherwise stop.
3. Run the readiness helper with every selected skill and intended target.
4. Patch only the declared targets. Require the complete diff to remain inside
   that scope. Reopen changed non-executable text; for executable helpers, run
   only the identified targeted checks.
5. Commit the release-branch change.
6. Run `python scripts/install-skills.py --repo-root PATH --skill NAME`, repeating
   `--skill` for every selected skill. Targeted installation validates only
   those skills and removes no stale runtime folders.
7. Propagate and commit the same change into retained task branches only when
   explicitly requested and cleanly applicable.
8. If the release is later shipped, hand off to repository lifecycle with
   `--no-pending-work-check`; direct fast-change creates no promotion scope or
   selected source worktree.

## Done When

### Completion Gate

- The primary checkout is clean on the intended local release branch and
  contains the committed change.
- The committed diff contains only declared eligible targets.
- Every affected runtime skill passed targeted installation.
- No repository-wide validation or deployment operation ran.
- No promotion scope was created.
- Requested propagation completed or its exact blocker is reported.

### Output Contract

Report only:

- release branch and commit
- affected source and runtime skills
- targeted checks and installation outcome
- propagated branches or blockers
- intentionally skipped broad checks
