# Make Repository Compatible Action

## Goal

Make an existing skills repository satisfy the `ceratops-compatible` source,
validation, installer, and managed-runtime contract without changing its
skills' intended behavior.

## Context

### Inputs To Capture

- Target repository task worktree, source skill inventory, and intended stable
  `runtime_source_id`.
- Existing shared skill rules, metadata, README skill inventory, runtime
  resources, installer, and validation surfaces.
- Whether compatibility is standalone work or a prerequisite for `create` or
  `update`, and whether runtime installation is explicitly requested.

Infer the source identity from stable repository evidence before asking.

### Script Bundle

- (D) Full compatible-repository validation: `python
  scripts/skills-consistency-source-validator.py --repo-root
  <repo-root>
  --mode full` from the installed lifecycle bundle.
- (D) Installer synchronization after the compatibility sources exist: `python
  scripts/runtime/synchronize-installers.py --target-repo-root
  <task-worktree>` from the installed lifecycle bundle.

## Constraints

### Boundaries

- Use this action only when an existing skills repository does not yet satisfy
  the `ceratops-compatible` profile.
- Work only in the target repository's task-specific linked worktree.
- Do not add Ceratops naming, branding, icons, or Ceratops-only contracts to a
  compatible repository unless that repository independently requires them.
- Do not create the requested new skill in this action; return to `create` after
  compatibility passes.
- Do not install runtime copies unless installation is explicitly requested.

### Skill-Specific Rules

- Preserve each existing skill's purpose, trigger, workflow, constraints, and
  output contract.
- Move text into a shared section only when it is genuinely shared; keep
  skill-specific behavior in the source `SKILL.md`.
- Use one stable `runtime_source_id` unique among repositories sharing an
  install root and set `validation_profile` to `ceratops-compatible`.
- Assign every source skill to `core`; declare only existing portable runtime
  payloads and target-owned maintenance commands.
- Keep source skill folders portable and keep generated shared-section blocks
  out of source `SKILL.md` files.

## Workflow

### 1. Inventory the target repository

- Enumerate every source `skills/*/SKILL.md`, metadata file, reference and
  script resource, README skill entry, shared rule candidate, runtime resource,
  and existing installer or manifest.
- Identify source-of-truth files, generated files, repeated shared behavior,
  and any existing naming or layout that the compatible profile must preserve.

### 2. Establish compatible source surfaces

- Create `templates/sections/core.md` from target-owned behavior required by
  every source skill.
- Create `templates/skill-sections.json` with the stable source identity,
  `ceratops-compatible` profile, section paths, per-skill assignments,
  target-owned maintenance workflows, and portable runtime payloads.
- Make every source `SKILL.md` delta-only, add or align
  `skills/<name>/agents/openai.yaml`, and align the README Skills table without
  changing skill behavior.

### 3. Install the repository bootstrap

- Run the installer synchronization helper only after the other compatibility
  surfaces are ready so its required full validation can succeed.
- Retain a same- or higher-version target installer; replace only a missing or
  lower parsed integer `INSTALLER_VERSION`.

### 4. Validate and hand off

- Run full source-repository validation and repair every compatibility finding
  in the task worktree.
- If runtime installation was explicitly requested, run `python
  scripts/install-skills.py --repo-root <repo>` and verify managed manifests;
  otherwise stop at validated source compatibility.
- Resume the owning `create` or `update` action when compatibility was a
  prerequisite.

## Done When

### Completion Gate

- The repository has a stable source identity, `ceratops-compatible` manifest,
  target-owned shared sections, complete per-skill assignments, aligned source
  skills, metadata, README inventory, portable payload declarations, and a
  supported versioned installer.
- Full target-repository validation passes.
- Runtime installation either passed when explicitly requested or remains
  intentionally out of scope.

### Output Contract

Report only:

- target repository and source identity
- compatibility surfaces added or aligned
- validation and requested installation outcome
- unresolved blockers or intentionally retained target-specific behavior
