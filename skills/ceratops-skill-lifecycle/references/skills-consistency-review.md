# Skills Consistency Review Action

## Goal

Audit one direct manifest-backed installed skill, regardless of its name, as a
coupled source, contract-compliance, metadata, action-reference,
automation-consumer, helper, installer, generated-runtime, and
installed-runtime surface.

## Context

### Script Bundle

- (D) Source consistency validator: `python
  scripts/skills-consistency-source-validator.py --repo-root <repo-root>
  --mode skill --skill <skill-name>` from the lifecycle bundle.
- (D) Managed runtime validator: `python
  scripts/runtime/skills-consistency-runtime-validator.py --skill
  <skill-name>` from the installed lifecycle bundle; it derives the source
  repository from the selected direct runtime manifest.
- (D) Global inventory helper: `python
  scripts/runtime/skills-consistency-runtime-validator.py --inventory` emits
  compact JSON for every direct manifest-backed installed skill and malformed
  direct-manifest blocker without auditing any skill.
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

- Target direct installed skill directory and its `.runtime-manifest.json`;
  derive the skill name, source repository root, `runtime_source_id`, and
  `validation_profile`.
- Whether the review is report-only or includes approved source repairs.
- Direct installed runtime root, normally `$CODEX_HOME/skills`.
- Existing task worktree for any approved installer or source repair.
- Installed automation prompts or repo-owned automation templates that invoke a
  skill or action from the target skill.

Infer missing inputs from the repository and installed manifests before asking.

### Global Automation Caller

- The `global-skills-consistency-review` automation runs the global inventory
  helper and invokes this action once per valid inventory entry.
- The automation may aggregate results, but it must not deduplicate skills that
  share a source repository or make this action perform global discovery.
- Report an unreadable direct runtime manifest as a blocker for that installed
  skill without routing it through another skill's review.
- Keep standards refresh out of the global consistency run unless it is
  separately and explicitly requested through `skills-contract-review`.

## Constraints

### Boundaries

- Use this action for one direct installed skill containing a supported runtime
  manifest and its attributable source and automation consumers. Eligibility
  depends on the manifest schema and validation profile, never on a Ceratops
  name prefix.
- Do not discover or audit sibling installed skills. Global fan-out belongs
  only to the automation caller.
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

- Treat the selected runtime manifest's skill, `runtime_source_id`,
  `validation_profile`, source path, source repository root, matching manifest
  assignment, and installer as its identity and ownership surface.
- Run deterministic validation before AI semantic contract validation.
- Run deterministic source checks through
  `skills-consistency-source-validator.py --mode skill --skill <skill-name>`
  and installed-runtime checks through
  `skills-consistency-runtime-validator.py --skill <skill-name>`.
- Validate every applicable non-deterministic contract check through
  evidence-backed AI validation.
- Let the runtime validator read the selected direct manifest before validating
  its identity, installer version, and complete managed file tree.
- Compare installers only by parsed integer `INSTALLER_VERSION`; retain
  same- or higher-version differences and synchronize missing or lower versions
  only through an approved task worktree.
- Accept only a direct installed-skill directory containing
  `.runtime-manifest.json`; do not descend into `.system`, plugin caches,
  bundled providers, unmanaged folders, or sibling skills.
- Deep-read only coupled surfaces needed to evaluate a contract check,
  identity collision, unresolved resource, stale reference, trigger conflict,
  helper contract, or source/runtime mismatch.
- Record each non-deterministic check as `pass`, `fail`, `approved_drift`,
  `blocked`, or `not_applicable` for the selected source skill.

## Workflow

### 1. Resolve the selected skill surface

- Read the selected direct runtime manifest and resolve its source repository,
  source skill, section-manifest assignment, action references, metadata,
  runtime payloads, relevant helpers and callers, installer, validator, and
  public documentation.
- Find repo-owned automation templates and installed automation prompts that
  explicitly invoke the selected skill or its actions.
- Build an identity map for the selected skill through metadata, action lists,
  docs, runtime payloads, its installed manifest, and automation consumers.

### 2. Run deterministic contract checks

- Resolve the validator from the target source checkout when present, otherwise
  from the installed lifecycle bundle.
- Run `--mode skill --skill <skill-name> --repo-root <repo-root>` so common and
  profile-specific source checks execute only for the selected skill.
- Map every validator finding to its deterministic contract check ID and owning
  source repair. Do not treat a passing validator as evidence for any
  non-deterministic check.
- Run declared Markdown lint or Python type checks only when their governed
  files are in the review scope.

### 3. Validate installer and runtime coherence

- Run the managed runtime validator once with `--skill <skill-name>`.
- Reject a malformed selected manifest; compare manifest schema, skill,
  `runtime_source_id`, `source_path`, `source_repository_root`,
  `validation_profile`, and `installer_version` with source ownership.
- Detect unresolved source or local resources, a missing or stale installed
  skill, stale shared-section output, frontmatter drift, source/runtime
  ownership conflicts, and stale cross-skill references attributable to the
  selected skill.
- When an installer is missing or lower-version and repair is approved, run the
  synchronization helper in the task worktree and require successful full
  target-repository validation before continuing.

### 4. Validate non-deterministic contract compliance

- Validate the selected source skill against every applicable check in
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
- Account for every deterministic and non-deterministic contract check for the
  selected skill before completion.

## Done When

### Completion Gate

- The selected source skill is inventoried and evaluated against every
  applicable deterministic and non-deterministic contract check.
- Targeted source validation passes or every finding has an owning file and
  smallest credible repair.
- The selected runtime manifest is read before validation, and every managed
  file for that installed skill is checked or its blocker is named.
- Skill text, action routing, metadata, automation consumers, helpers,
  installers, runtime payloads, installed runtime, docs, and validator claims
  agree or every mismatch is classified.
- Every approved repair is verified through the narrowest owning check.

### Output Contract

Report only:

- target skill, installed path, source repository, profile, and managed count
- deterministic contract and validation outcome
- non-deterministic contract results by failed, blocked, approved-drift, or
  not-applicable check; omit passing detail
- installer, runtime, semantic, and ownership findings with source repair
  routes
- exact installed paths and source identities for runtime findings
- changes made, unresolved blockers, retained external state, and important
  unverified items
