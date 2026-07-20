# Global Skills Consistency Review Action

## Goal

Audit consistency across installed skills managed from the user's source
repositories.

## Context

### Inputs To Capture

- The direct runtime skills root, normally `$CODEX_HOME/skills`.
- Whether the run is report-only or explicitly includes repairs to an owning
  source repository.
- Any known installation, rename, missing-resource, or trigger-conflict concern.

## Constraints

### Boundaries

- Inventory only direct child directories of the runtime skills root that
  contain `.runtime-manifest.json`.
- Do not inventory `.system`, plugin caches, bundled skills, catalog entries, or
  any directory without `.runtime-manifest.json`.
- Use the manifest's `runtime_source_id` and `source_path` as the ownership and
  repair route. Do not infer repository ownership from a skill name.
- Keep report-only as the default. Repair a source repository or installed copy
  only when the user explicitly approves that exact change.
- Use `skills-contract-review` for Ceratops contract upkeep and
  repository-local governance.

### Skill-Specific Rules

- Reject an unreadable or malformed manifest; do not silently treat its folder
  as managed.
- Run manifest, path, and frontmatter checks before reading full skill bodies.
- Deep-read only skills with identity collisions, unresolved local resources,
  ambiguous ownership, or plausible trigger and responsibility conflicts.
- Do not turn the review into general skill optimization or upstream standards
  refresh.

### Workflow

#### 1. Inventory managed installed skills

- Enumerate direct child directories of the runtime skills root.
- Keep only directories containing `.runtime-manifest.json`.
- Record directory identity plus the manifest's `schema`, `skill`,
  `runtime_source_id`, and `source_path`.
- Report manifests whose declared source identity or source path is missing,
  malformed, or unresolved.

#### 2. Run cheap consistency checks

- Confirm each managed folder has readable `SKILL.md` frontmatter with a name
  and description.
- Compare directory identity, frontmatter name, and manifest skill identity.
- Detect duplicate managed identities, duplicate declared source paths, missing
  declared local resources, and obvious stale cross-skill references.

#### 3. Review only justified conflicts

- Deep-read colliding or plausibly overlapping managed skills to decide whether
  trigger scope, responsibility, or ownership is unclear.
- Group defects by `runtime_source_id` and identify the owning source repair.

#### 4. Close with source evidence

- Report exact installed paths, source identities, conflicts, and owning repair
  routes for every finding.
- If no findings remain, state the number of manifest-bearing installed skills
  checked and any unresolved source-path limit.

## Done When

### Completion Gate

- Every direct manifest-bearing installed skill is inventoried or its inventory
  blocker is named.
- Cheap checks cover every readable managed installed skill.
- Every deep review is tied to a concrete collision, broken source, unresolved
  resource, or ownership ambiguity.
- Unmanaged installed folders and external provider caches remain unchanged.

### Output Contract

Report only:

- managed installed skill count grouped by `runtime_source_id`
- consistency findings and owning source repair routes
- unresolved blockers and important unverified items
