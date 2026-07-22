# Skills Consistency Review Action

## Goal

Audit one Ceratops or Ceratops-compatible skills repository as a coupled
source, contract-compliance, metadata, action-reference, automation-consumer,
helper, installer, generated-runtime, and installed-runtime surface.

## Context

### Script Bundle

- (D) Source consistency validator: `python
  scripts/skills-consistency-source-validator.py --repo-root <repo-root>
  --mode full` from the lifecycle bundle.
- (D) Managed runtime validator: `python
  scripts/runtime/skills-consistency-runtime-validator.py --repo-root
  <repo-root>` from the installed lifecycle bundle when the repository is
  expected to be installed.
- (D) Installer synchronization when repair is authorized: `python
  scripts/runtime/synchronize-installers.py --target-repo-root
  <task-worktree>` from the installed lifecycle bundle.
- (D) Markdown lint when the repository declares it and skill Markdown is in
  scope: `npm run lint:markdown`.
- (D) Python type check when the repository declares it and skill helpers or
  validators are in scope: `python -m mypy`.

### References

- Skill deterministic contract:
  `references/contracts/skill-deterministic-contract.json`
- Skill non-deterministic contract:
  `references/contracts/skill-nondeterministic-contract.json`
- Compatible-repository section manifest: `templates/skill-sections.json`

### Inputs To Capture

- Target repository root and its `runtime_source_id` and
  `validation_profile`.
- Whether the review is report-only or includes approved source repairs.
- Direct installed runtime root, normally `$CODEX_HOME/skills`, and whether the
  repository is expected to be installed there.
- Existing task worktree for any approved installer or source repair.
- Installed automation prompts or repo-owned automation templates that invoke a
  skill or action from the target repository.

Infer missing inputs from the repository and installed manifests before asking.

### Global Automation Caller

- The `global-skills-consistency-review` automation owns required-repository
  discovery and invokes this action once per repository.
- The automation may aggregate results and must deduplicate unattributable
  malformed-manifest blockers repeated across repository runs, but it must not
  replace or narrow this action's repository checks.
- Keep standards refresh out of the global consistency run unless it is
  separately and explicitly requested through `skills-contract-review`.

## Constraints

### Boundaries

- Use this action for one source repository and its attributable installed
  runtime and automation consumers. Unreadable direct runtime manifests may be
  reported as unattributable routing blockers during a global run.
- Use `skills-contract-review` only when the standards contracts themselves
  require a best-practice refresh.
- Exclude GitHub organization, repository, code, PR, artifact, registry, and
  release contracts; route those to `$ceratops-gh-repo-lifecycle`
  `contracts-review`.
- Keep report-only as the default. Apply source, installer, runtime, or
  automation changes only when the user approved that exact scope.
- Update source repositories only through task worktrees and regenerate runtime
  copies only through the owning repository installer.
- Do not turn repository consistency review into general skill optimization;
  use `$ceratops-governance-lifecycle` action `optimize-skill` for advisory
  improvement beyond contract or coupled-surface defects.

### Skill-Specific Rules

- Treat the target repository's `runtime_source_id`, `validation_profile`,
  manifest assignments, source skill directories, and installer as its
  identity and ownership surface.
- Run deterministic validation before AI semantic contract validation.
- Run deterministic source checks through
  `skills-consistency-source-validator.py` and installed-runtime checks through
  `skills-consistency-runtime-validator.py`.
- Validate every applicable non-deterministic contract check through
  evidence-backed AI validation.
- Let the runtime validator discover attributable manifests before validating
  their identities, installer versions, and complete managed file trees.
- Compare installers only by parsed integer `INSTALLER_VERSION`; retain
  same- or higher-version differences and synchronize missing or lower versions
  only through an approved task worktree.
- Inventory only direct installed-skill directories containing
  `.runtime-manifest.json`; do not descend into `.system`, plugin caches,
  bundled providers, or unmanaged folders.
- Deep-read only coupled surfaces needed to evaluate a contract check,
  identity collision, unresolved resource, stale reference, trigger conflict,
  helper contract, or source/runtime mismatch.
- Record each non-deterministic check as `pass`, `fail`, `approved_drift`,
  `blocked`, or `not_applicable` for every validated source skill.

## Workflow

### 1. Inventory the repository surface

- Read the section manifest and enumerate every source skill, action reference,
  metadata file, runtime payload declaration, relevant helper and caller,
  installer, validator, and public document.
- Find repo-owned automation templates and installed automation prompts that
  explicitly invoke the repository's skills or actions.
- Build an identity map from source skill names through metadata, action lists,
  docs, runtime payloads, installed manifests, and automation consumers.

### 2. Run deterministic contract checks

- Resolve the validator from the target source checkout when present,
  otherwise from the installed lifecycle bundle.
- Run `--mode full --repo-root <repo-root>` so common and profile-specific
  source checks execute together.
- Map every validator finding to its deterministic contract check ID and owning
  source repair. Do not treat a passing validator as evidence for any
  non-deterministic check.
- Run declared Markdown lint or Python type checks only when their governed
  files are in the review scope.

### 3. Validate installer and runtime coherence

- When the repository is expected to be installed, run the managed runtime
  validator once; otherwise classify installed-runtime validation as not
  applicable.
- Reject malformed attributable manifests; compare manifest schema, skill,
  `runtime_source_id`, `source_path`, `source_repository_root`,
  `validation_profile`, and `installer_version` with source ownership.
- Detect duplicate identities or source paths, unresolved source or local
  resources, missing or stale installed skills, stale shared-section output,
  frontmatter drift, source/runtime ownership conflicts, and stale cross-skill
  references.
- When an installer is missing or lower-version and repair is approved, run the
  synchronization helper in the task worktree and require successful full
  target-repository validation before continuing.

### 4. Validate non-deterministic contract compliance

- Validate every source skill against every applicable check in
  `skill-nondeterministic-contract.json`.
- Check semantic agreement across trigger descriptions, metadata prompts,
  parent skill routing, action references, inputs, boundaries, workflow,
  helper contracts, runtime payloads, automation consumers, completion gates,
  output contracts, and public docs.
- Check shared-section fit, duplicated or conflicting ownership, retired-name
  drift, deterministic behavior left in prose, excessive routine work, and
  missing safety or closure evidence under the corresponding contract checks.
- Use registered best-practice sources only when contract application is
  ambiguous; do not refresh the contracts during this action.

### 5. Apply only approved repairs

- Route source fixes through the lifecycle `update` action and the current task
  worktree.
- Update every producer and consumer together for an approved rename or
  ownership change; leave no aliases, old-name shims, or pointer artifacts.
- Regenerate installed runtime or update installed automation prompts only when
  those external mutations are explicitly in scope.

### 6. Close from current evidence

- Re-run the failed deterministic, lint, type, installer, or runtime checks
  after an approved repair.
- Revalidate only affected non-deterministic checks and coupled semantic
  surfaces.
- Account for every deterministic and non-deterministic contract check and
  every repository skill before completion.

## Done When

### Completion Gate

- Every source skill is inventoried and evaluated against every applicable
  deterministic and non-deterministic contract check.
- Full source validation passes or every finding has an owning file and smallest
  credible repair.
- Runtime discovery precedes validation internally, and every attributable
  installed manifest and managed file is checked or its blocker is named.
- Skill text, action routing, metadata, automation consumers, helpers,
  installers, runtime payloads, installed runtime, docs, and validator claims
  agree or every mismatch is classified.
- Every approved repair is verified through the narrowest owning check.

### Output Contract

Report only:

- target repository, profile, source-skill count, and installed managed count
- deterministic contract and validation outcome
- non-deterministic contract results by failed, blocked, approved-drift, or
  not-applicable check; omit passing detail
- installer, runtime, semantic, and ownership findings with source repair
  routes
- exact installed paths and source identities for runtime findings
- changes made, unresolved blockers, retained external state, and important
  unverified items
