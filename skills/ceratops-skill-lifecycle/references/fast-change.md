# Fast Change Action

## Goal

Apply one exact classified change directly on a clean primary local
`release/*` checkout, update only its affected runtime skills, and commit once.
Prefer this action whenever its complete scope is eligible.

## Context

### Inputs To Capture

- Intended local release checkout and branch.
- Exact unified patch and every selected or removed source skill.
- Classification: `rules-only` or `helper`.
- Existing pytest node IDs covering every changed helper behavior.
- Commit message and optional runtime root.

Infer these inputs from the exact approved change before asking.

### Script Bundle

- (D) Prepare a clean release checkout, when needed, through repository
  lifecycle: `python scripts/promote-repository.py --repo-root PATH
  --main-branch main --release-branch release/local --remote-name origin
  --prepare-release-only`.
- (D) Write one version-1 JSON request and run `python
  scripts/fast-change.py --request <request>` from the skill lifecycle bundle.
  The request contains `version`, `repo_root`, `release_branch`, `patch`,
  `selected_skills`, `removed_skills`, `classification`, `tests`, and
  `commit_message`, plus optional `install_root`.

## Constraints

### Boundaries

- Use this action only for one coherent patch contained in declared existing
  skill-local files.
- Rules-only changes may update non-executable skill rules, actions, references,
  or metadata and run no content validation, readback, or tests.
- Helper changes may preserve the existing dependency, public-interface,
  persistent-state, and side-effect boundaries and must name existing behavior
  tests for every changed behavior.
- Cohesive multi-file and multi-skill requests are eligible when the complete
  scope passes classification before mutation.
- Use `update` for additions, removals, renames, shared sources, manifests,
  templates, deployment, installers, runtime generation, validators, contracts,
  helper-boundary changes, or unresolved affected sets.

### Workflow

1. Confirm the complete patch, selected skills, classification, exact existing
   tests, intended release branch, commit message, and runtime root.
2. If the primary checkout is clean on `main`, use repository lifecycle release
   preparation. If it is already clean on the intended release branch, keep it;
   otherwise stop.
3. Run the fast-change helper once. It mechanically validates branch, clean
   state, request fields, patch paths, ownership, and installer availability
   before mutation.
4. The helper applies the exact patch. Rules-only requests run no validation or
   tests; helper requests run only the declared pytest nodes.
5. The helper invokes the installer once for the exact selected skills, stages
   only patch paths, and commits once.
6. On patch, test, install, staging, or commit failure, the helper reverses only
   its patch. If runtime activation completed before a later failure, it
   reinstalls the restored selected snapshot.
7. If classification returns `decision_required`, preserve the request as the
   `update` change specification and report the exact reason, files, skills,
   and required checks.
8. Later promotion or shipping remains repository lifecycle work; fast-change
   creates no pending-work scope.

## Done When

### Completion Gate

- Classification completed before mutation.
- The committed diff contains only declared eligible paths.
- Every changed helper behavior passed its declared existing test.
- The exact selected runtime batch installed once.
- Compensation completed after any failed mutated run, or its exact failure is
  reported.
- No broad source validation, runtime validation, promotion scope, deployment
  operation, or model-mediated handoff ran.

### Output Contract

Report only:

- release branch and commit
- affected source and runtime skills
- targeted behavior tests and installation outcome
- exact escalation or compensation blocker
- intentionally skipped broad checks
