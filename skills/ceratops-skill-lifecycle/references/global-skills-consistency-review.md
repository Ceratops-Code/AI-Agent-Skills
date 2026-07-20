# Global Skills Consistency Review Action

## Goal

Audit consistency across installed skills managed from the user's source
repositories, synchronize outdated compatible-repository installers through
task worktrees when repair is authorized, then review managed skill coherence.

## Context

### Inputs To Capture

- The direct runtime skills root, normally `$CODEX_HOME/skills`.
- Whether the run is report-only or explicitly includes repairs to an owning
  source repository.
- Existing task worktrees for source repositories whose installers may need an
  approved update.
- Any known installation, rename, missing-resource, or trigger-conflict concern.

## Constraints

### Boundaries

- Inventory only direct child directories of the runtime skills root that
  contain `.runtime-manifest.json`.
- Do not inventory `.system`, plugin caches, bundled skills, catalog entries, or
  any directory without `.runtime-manifest.json`.
- Use `runtime_source_id`, `source_repository_root`, and `source_path` as the
  ownership and repair route. Do not infer repository ownership from a skill
  name.
- Keep report-only as the default. Repair a source repository or installed copy
  only when the user explicitly approves that exact change.
- Update source installers only through task worktrees. Do not mutate the source
  checkout recorded in an installed manifest.
- Use `skills-contract-review` for Ceratops contract upkeep and
  repository-local governance.

### Skill-Specific Rules

- Reject an unreadable or malformed manifest; do not silently treat its folder
  as managed.
- Run installer inventory and version comparison before managed-skill checks.
- Compare installers only by their parsed integer `INSTALLER_VERSION`; do not
  compare file contents.
- Run manifest, path, and frontmatter checks before reading full skill bodies.
- Deep-read only skills with identity collisions, unresolved local resources,
  ambiguous ownership, or plausible trigger and responsibility conflicts.
- Do not turn the review into general skill optimization or upstream standards
  refresh.

### Helper Contracts

- (D) Run `python scripts/runtime/review-managed-skills.py --mode inventory`
  from the installed `ceratops-skill-lifecycle` bundle to group manifests and
  compare installed and source installer versions with the authoritative
  template.
- (D) When repair is authorized and an installer version is missing or lower,
  run `python scripts/runtime/synchronize-installers.py --target-repo-root
  <task-worktree>` from the installed lifecycle bundle. The helper updates only
  `scripts/install-skills.py`, retains same- or higher-version differences, and
  runs full target-repository validation afterward.
- (D) After installer repair and validation, run `python
  scripts/runtime/review-managed-skills.py --mode consistency` from the
  installed lifecycle bundle.

## Workflow

### 1. Inventory managed installed skills

- Enumerate direct child directories of the runtime skills root.
- Keep only directories containing `.runtime-manifest.json`.
- Record directory identity plus `schema`, `skill`, `runtime_source_id`,
  `source_path`, `source_repository_root`, `validation_profile`, and
  `installer_version`.
- Group manifests by `runtime_source_id` and `source_repository_root`.
- Report manifests whose declared source identity, source root, source path, or
  installer version is missing, malformed, or unresolved.

### 2. Align installer versions when authorized

- Compare each group's installed and source installer versions with the
  authoritative template's `INSTALLER_VERSION`.
- When a source installer version is missing or lower, identify its task
  worktree and run the synchronization helper only after exact repair approval.
- Do not replace a same- or higher-version installer because its contents differ
  from the template.
- Require successful full target-repository validation after every installer
  synchronization before continuing.

### 3. Run cheap managed-skill checks

- Confirm each managed folder has readable `SKILL.md` frontmatter with a name
  and description.
- Compare directory identity, frontmatter name, and manifest skill identity.
- Detect duplicate managed identities, duplicate declared source paths, missing
  declared local resources, and obvious stale cross-skill references.

### 4. Review only justified conflicts

- Deep-read colliding or plausibly overlapping managed skills to decide whether
  trigger scope, responsibility, or ownership is unclear.
- Group defects by source repository and identify the owning source repair.

### 5. Close with source evidence

- Report exact installed paths, source identities, conflicts, and owning repair
  routes for every finding.
- If no findings remain, state the number of manifest-bearing installed skills
  checked and any unresolved source-path limit.

## Done When

### Completion Gate

- Every direct manifest-bearing installed skill is inventoried or its inventory
  blocker is named.
- Installer versions were compared before managed-skill consistency checks.
- Every authorized installer update occurred through a task worktree and passed
  full target-repository validation.
- Cheap checks cover every readable managed installed skill.
- Every deep review is tied to a concrete collision, broken source, unresolved
  resource, or ownership ambiguity.
- Unmanaged installed folders and external provider caches remain unchanged.

### Output Contract

Report only:

- managed installed skill count grouped by `runtime_source_id`
- installer-version findings and task-worktree repair routes
- consistency findings and owning source repair routes
- unresolved blockers and important unverified items
