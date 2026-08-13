# Make Repository Compatible Action

## Goal

Make an existing repository satisfy the `ceratops-compatible` repository and
validation contract without changing any skill's intended behavior. Repositories
with no skills remain valid and omit canonical shared-section and bootstrap work.

## Context

### Inputs To Capture

- Target repository task worktree, optional source skill inventory, and
  intended stable `runtime_source_id`.
- Existing shared skill rules, metadata, README skill inventory, runtime
  resources, installer, deployment definition, and validation surfaces.
- Whether compatibility is standalone work or a prerequisite for `create` or
  `update`, and whether `deploy/deploy.yml` should be omitted.

Infer the source identity from stable repository evidence before asking.

### Script Bundle

- (D) Run the skill-owned compatibility engine from the repository-lifecycle
  bundle's `scripts` folder. The engine operates on `--target-repo-root` and is
  never materialized into the target repository.
- (D) `ceratops_repo_compatibility_engine.compatibility_check.check_repository`
  exposes `check_repository(repo_root) -> {applicable, valid, errors}` and
  performs read-only manifest, deployment, and validation-wiring checks. It
  never runs skill-source validation.
- (D) Compatibility materialization: `python -m
  ceratops_repo_compatibility_engine materialize --target-repo-root
  <task-worktree> [--runtime-source-id <stable-id>]`; it performs the
  compatibility transaction and emits one compact result.
  Add `--no-deploy-contract` only when the caller chooses to leave
  `deploy/deploy.yml` absent or unchanged.
- (D) Bootstrap-only repair: `python -m ceratops_repo_compatibility_engine
  synchronize-bootstrap --target-repo-root <task-worktree>`; it only compares
  parsed installer versions and copies a missing or lower version.
- (D) `ceratops_repo_compatibility_engine.deploy_contract_validation` reads and
  validates deployment contracts for materialization, execution, and health;
  it never creates or modifies them.
- (D) Missing repository-validation surfaces come from
  `references/repository-validation-catalog.json` and the templates under
  `references/templates/`.

## Constraints

### Boundaries

- Use this action only when an existing repository does not yet satisfy the
  `ceratops-compatible` profile.
- Work only in the target repository's task-specific linked worktree.
- Do not add Ceratops naming, branding, icons, or Ceratops-only contracts to a
  compatible repository unless that repository independently requires them.
- Do not create the requested new skill in this action; return to `create` after
  compatibility passes.
- Do not promote or deploy the completed compatibility change here; return to
  the parent skill and select `promote` or `promote-and-deploy` only when
  requested.
- Do not modify an existing repository validator or CI validation workflow
  (`scripts/validate-repository.py`, `.github/workflows/validate.yml`); preserve
  their bytes and mode. If compatibility requires either to change, stop for
  approval.

### Skill-Specific Rules

- Preserve each existing skill's purpose, trigger, workflow, constraints, and
  output contract.
- Move a rule into a shared section when it is repeated, semantically equivalent,
  or harmless as a common default for every assigned skill; keep only true
  exceptions and skill-specific deltas in source `SKILL.md`.
- Use one stable `runtime_source_id` unique among repositories sharing an
  install root and set `validation_profile` to `ceratops-compatible`.
- Assign every source skill to `core`; when none exist, keep the skill map
  empty, add no canonical sections, and skip bootstrap materialization.
  Preserve valid target-owned custom sections and assignments, portable
  runtime payloads, and maintenance commands.
- Block malformed or unsafe existing declarations before mutation. After the
  first write, restore every changed target file after any caught blocker and
  report the failed phase and rollback state.
- Generate a missing validator and CI workflow only from catalogued checks;
  obtain approval before adding a check absent from the catalog.
- Keep source skill folders portable and keep generated shared-section blocks
  out of source `SKILL.md` files.

## Workflow

### 1. Inventory the target repository

- Enumerate every optional source `skills/*/SKILL.md`, metadata file, reference
  and script resource, README skill entry, shared rule candidate, runtime
  resource, and existing installer or manifest.
- Identify source-of-truth files, generated files, repeated shared behavior,
  and any existing naming or layout that the compatible profile must preserve.

### 2. Establish compatible source surfaces

- Run the compatibility materializer so it loads the lifecycle-owned
  `references/templates/skill-sections-template.json`, derives or accepts the
  stable source identity, inventories source skills and multi-action markers,
  writes `skills/skill-sections.json`, and preserves valid target-owned custom
  sections and assignments. Only when source skills exist, copy canonical
  shared sections to `skills/sections/` and remove generated section blocks
  from source skills.
- Unless omitted, materialize `deploy/deploy.yml` from
  `references/templates/deploy-template.yml`, preserve target-owned operations,
  and declare the canonical `bootstrap` operation and default
  `ceratops-skill-lifecycle/deploy` handoff only when skills exist.
- When skills exist, make every source `SKILL.md` delta-only, add or align
  `skills/<name>/agents/openai.yaml`, and align the README Skills table without
  changing skill behavior.

### 3. Materialize repository validation and bootstrap

- Materialize a missing `scripts/validate-repository.py` and
  `.github/workflows/validate.yml` for every repository, including repositories
  with no skills. CI calls the repository-owned validator.
- When skills exist, the compatibility materializer synchronizes the
  first-install-only `scripts/install-skills-bootstrap.py`. Retain a same- or
  higher-version bootstrap and replace only a missing or lower version.
- When no skills exist, do not add a bootstrap script or bootstrap deployment
  operation.

### 4. Validate and hand off

- After every materialization, including zero-skill repositories, call
  `check_repository` inside the rollback boundary and require every applicable
  result to be valid with no errors.
- Commit the validated compatibility change in the task worktree.
- If only local release staging was requested, return to the parent skill and
  select `promote`; if deployment was requested, select `promote-and-deploy`;
  otherwise stop at committed source compatibility.
- Resume the owning `create` or `update` action when compatibility was a
  prerequisite.

## Done When

### Completion Gate

- The repository has a stable source identity, `ceratops-compatible` manifest,
  complete optional per-skill assignments, and an optional live deployment
  definition. Skill-bearing repositories also have target-owned shared
  sections, aligned source skills, metadata, README inventory, portable
  payload declarations, a default deploy handoff, and a supported versioned
  bootstrap.
- Every target has repository validation and CI wiring; every applicable
  `check_repository` result is valid with no errors.
- Any caught blocker after mutation restores the exact prior target files and
  reports completed or failed rollback state.
- Any requested repository-lifecycle handoff completed or its blocker is
  reported.

### Output Contract

Report only:

- target repository and source identity
- compatibility surfaces added or aligned
- validation and requested repository-lifecycle outcome
- unresolved blockers or intentionally retained target-specific behavior
