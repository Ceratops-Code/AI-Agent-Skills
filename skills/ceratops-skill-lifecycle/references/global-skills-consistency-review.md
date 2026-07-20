# Global Skills Consistency Review Action

## Goal

Audit source-neutral consistency across the active Codex skill catalog without
applying Ceratops-specific repository contracts to system, bundled, plugin, or
third-party skills.

## Context

### Inputs To Capture

- The active skills catalog injected into the current Codex run, including each
  skill identity, description, source path, and provider when available.
- Whether the run is report-only or explicitly includes repairs to user-owned
  skill sources.
- Any known installation, plugin, rename, shadowing, missing-resource, or
  trigger-conflict concern.

Use the current active catalog as the inventory source. Do not infer activity
from every versioned folder under the plugin cache.

## Constraints

### Boundaries

- Use this action for consistency across all active user, system, bundled,
  plugin, and third-party skills exposed to the current Codex run.
- Use only source-neutral checks that apply across skill providers.
- Do not require Ceratops H2 structure, `agents/openai.yaml`, shared sections,
  runtime manifests, icons, README rows, or Ceratops action references from
  non-Ceratops skills.
- Do not mutate system, bundled, plugin, cache, or third-party skill sources.
  Report the owning source and repair route instead.
- Use `skills-contract-review` for Ceratops contract upkeep and repository-local
  governance.

### Skill-Specific Rules

- Start from the active catalog already supplied to the run; do not scan the
  full plugin cache or inactive historical versions.
- Run cheap catalog, path, and frontmatter checks before reading full skill
  bodies.
- Deep-read only entries with identity collisions, missing or malformed source,
  unresolved local resources, ambiguous ownership, or plausible trigger and
  responsibility conflicts.
- Treat same-named skills from distinct active providers as a finding only when
  their effective identity, precedence, or trigger ownership is ambiguous.
- Keep report-only as the default. Repair user-owned sources only when the user
  explicitly approves the exact source and change.

### Workflow

#### 1. Inventory active skills

- Record each active catalog identity, description, source path, and provider.
- Group entries by user, system, bundled, plugin, and third-party ownership.
- Report catalog entries whose declared source cannot be resolved or read.

#### 2. Run cheap consistency checks

- Confirm each resolved source has readable `SKILL.md` frontmatter with a name
  and description.
- Compare catalog identity, frontmatter name, directory identity, and provider
  namespace where those fields exist.
- Detect duplicate active identities, duplicate active source paths, missing
  declared local resources, and obvious stale cross-skill references.
- Exclude inactive or historical plugin-cache versions from duplicate findings.

#### 3. Review only justified conflicts

- Deep-read colliding or plausibly overlapping skills to decide whether trigger
  scope, responsibility, provider precedence, or ownership is actually unclear.
- Classify provider-managed defects separately from user-owned source defects.
- Do not turn the review into general skill optimization or upstream standards
  refresh.

#### 4. Close with source-neutral evidence

- Report exact catalog entries, paths, providers, conflicts, and owning repair
  routes for every finding.
- If no findings remain, state the checked catalog coverage and any unresolved
  inventory limit without implying historical cache coverage.

## Done When

### Completion Gate

- Every active catalog entry is inventoried or its inventory blocker is named.
- Cheap checks cover every resolved active skill.
- Every deep review is tied to a concrete collision, broken source, unresolved
  resource, or ownership ambiguity.
- Non-user-owned sources remain unchanged.

### Output Contract

Report only:

- active catalog coverage by provider class
- source-neutral consistency findings and owning repair routes
- intentionally excluded inactive or historical cache state
- unresolved blockers and important unverified items
