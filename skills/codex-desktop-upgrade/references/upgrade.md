# Upgrade Action

## Goal

Assess a selected official desktop release against the patched build, reconcile
affected patches, qualify every supported feature, and route explicitly
requested adoption through the existing patcher helpers.

## Context

The inputs are the active patcher source checkout, app-code catalog, selected
runtime state file, target release or snapshot, and requested phase. The
patcher owns package discovery, imports, code comparison, assessment records,
candidate construction, qualification, adoption, and cleanup. Its
`docs/runtime-records.md` describes the current command and evidence contracts.

## Constraints

### Boundaries

- For advisory requests, inspect existing metadata and recommend the next step.
  Run imports and assessments only within an execution request.
- Keep reconciliation in patcher source. Generated app code is comparison data;
  candidate builds consume archived original bytes.
- Release, deployment, publication, and application restart require their
  explicitly requested operations through the existing owners.

## Workflow

1. Resolve the supplied checkout, catalog, and state file. Check the current
   `AssessUpgrade` command contract and official release notes and settings
   before inspecting changed runtime code.
2. Run `scripts/New-CodexPatchedRuntime.ps1 -Operation AssessUpgrade` from the
   selected source checkout with `CodeRoot`, `StatePath`, and a task-owned
   `ResultPath`. Use PowerShell 7 as required by the repository. Omit
   `SnapshotId` only to import the registered official package; otherwise pass
   the exact intended snapshot.
3. Read the returned assessment and bounded comparison results. Treat changed
   paths and owner matches as investigation hints. Review each requested patch
   against its required behavior and record its decision, reason, and evidence
   in the returned review file. Retire a patch only when behavior evidence
   establishes its replacement on the target version.
4. Repeat `AssessUpgrade` with the returned `TargetSnapshotId` to validate and
   retain the review. `NeedsReview` preserves unresolved decisions; `Reviewed`
   means decisions were supplied. Neither establishes compatibility. Changed
   bindings require a fresh review; do not transfer old decisions blindly.
5. For requested upgrade or reconciliation work, fix the owning patcher code
   and run its existing tests. Build from the assessed snapshot with an explicit
   patch set using `BuildCode` after committing clean source. Run all applicable
   repository, browser, and actual-Codex tests through their existing owners,
   using the isolated app runner for tests inside Codex. Account for every
   supported feature and resolve coverage gaps. Retain unresolved results and
   prior deferred checks as blockers; reuse earlier passes only when the owning
   helper verifies their applicability to the candidate.
6. For requested adoption, use the returned candidate evidence handoff and
   existing qualification and repository lifecycle commands. Stop at the
   authorized phase and report unresolved requirements or command failures.

## Done When

### Completion Gate

The authorized phase has its exact helper receipt and every requested patch has
a supported decision or an explicit unresolved disposition. Reconciliation is
complete only when all applicable tests pass for the exact candidate and every
supported feature is covered. Assessment completion alone does not establish
compatibility, qualification, or runtime adoption.

### Output Contract

Report imported versions, patch decisions, validation state, and unresolved
evidence in chat. Distinguish completed assessment, committed reconciliation,
qualified candidate, and adopted runtime.
