# Update Action

## Goal

Maintain existing skills as one consistency surface instead of patching
individual skill files in isolation. Decide first whether the source of truth is
skill-local text, a shared section, the section manifest, runtime payloads,
runtime generation logic, validation logic, helper-runtime claims, contracts, or
repo docs, then update the narrowest correct source that exists.

## Context

### Inputs To Capture

- Existing skills or shared files in scope: `skills/*`, `templates/sections/`,
  `templates/skill-sections.json`,
  `skills/ceratops-skill-lifecycle/scripts/templates/install-skills-template.py`,
  `scripts/install-skills.py`,
  `skills/ceratops-skill-lifecycle/scripts/runtime/render-runtime-skills.py`,
  installer resolution, synchronization, and global-review helpers,
  `skills/ceratops-skill-lifecycle/scripts/validation/validate-skills-consistency.py`,
  skill-local `references/`, helper-runtime files, and repo docs.
- Whether the change belongs in skill-local text, shared sections, manifests,
  runtime generation, validation, helper-runtime code or claims, contracts, or
  docs.
- Target repo `runtime_source_id` and `validation_profile`; the `ceratops`
  profile adds Ceratops icon, contract, retired-artifact, and repository
  governance checks while `ceratops-compatible` uses the common full checks.
- Whether the task should stop at local repo changes or also continue to local
  promotion.

Infer missing inputs from current repo state before asking.

## Constraints

### Boundaries

- Use this action to update existing Ceratops skills, compatible skills in
  another repo, or the shared skill-maintenance layer itself.
- If the task creates a brand-new skill, return to the parent skill and select
  `create`.
- If the task is Ceratops skill-contract upkeep, return to the parent skill and
  select `skills-contract-review`.
- If the task is consistency review across manifest-managed installed skills,
  return to the parent skill and select `global-skills-consistency-review`.
- If the task only promotes already-prepared committed changes, select
  `change-promotion`.

### Workflow

#### 1. Inspect the maintenance surface

- Inspect targeted skills, available shared section files, section manifest,
  runtime generation and validation scripts, touched helper-runtime files or
  claims, and repo docs that describe current structure.
- Start with targeted `rg` or path inventory and small line-window reads;
  broaden to full-file reads only for governing control files, ownership
  decisions, or unresolved context.
- Identify source-of-truth files versus generated output.
- Require a compatible section manifest before using the shared validator or
  installer. Do not infer compatibility from skill-name prefixes or from the
  presence of the lifecycle source skill.
- Classify the requested change as skill-local, shared, structural,
  validation-only, helper-runtime-adjacent, or docs-only.

#### 2. Decide ownership before editing

- Prefer shared sections and the manifest for shared behavior, and keep
  per-skill source text limited to true deltas.
- Add a new shared section only when it reduces meaningful duplication,
  clarifies ownership, or prevents conflicting drift across multiple skills.
- Keep trivial one-off text inline unless duplication is already causing drift
  or ownership confusion.

#### 3. Apply updates at the real source

- Update skills, shared sections, manifest, runtime payloads, runtime generation
  or validation scripts, helper-runtime files or claims, contracts, and repo
  docs only where ownership requires it.
- When addressing review feedback, patch the referenced artifact first. Touch
  adjacent skills, action references, contracts, or docs only when targeted
  evidence proves the same source-of-truth defect applies there; otherwise
  report them as separate candidates requiring approval.
- Before renaming a skill or named skill surface, build one old-to-new reference
  map and update folder name, frontmatter `name`, README rows, manifest
  assignments, runtime payload keys, cross-skill references,
  `agents/openai.yaml`, helper comments and prompts, validators, and docs.
- Do not leave alias folders, old-name shims, or pointer artifacts.
- When removing, merging, or narrowing sections, update every affected
  assignment and keep runtime generated section source comments readable.
- If runtime generation or validation flow no longer matches the section model,
  fix the scripts instead of working around them in skill text.

#### 4. Run needed checks

- If shared section files or `templates/skill-sections.json` changed, run the
  manifest's shared-source check path.
- Do not run validation solely because skill-local text, metadata, or docs
  changed; use targeted readback, stale-reference search, and diff review unless
  a broader check is stale.
- If helper-runtime code or claims changed, run only the touched helper's smoke
  command when supported.
- If runtime generation code changed, run the repo's runtime-generation check
  path when provided.
- Install a compatible repo through its `python scripts/install-skills.py
  --repo-root <repo>` entrypoint. It must use the supported installed lifecycle
  bundle, with target-checkout fallback allowed only for the initial Ceratops
  installation, and every install must run full target-repository validation.
- Reserve governance validation for scheduled governance automation, explicit
  broad validation, validation-script changes, or concrete cross-surface
  uncertainty.
- Re-open changed files and confirm source skills, manifest assignments, runtime
  payloads, docs, contracts, and metadata still align.

## Done When

### Completion Gate

- Every changed skill and shared file still points at the intended source of
  truth.
- Runtime shared-section generation is updated through shared sources, manifest,
  and renderer when those surfaces exist and changed.
- Manifest, renderer, validation script, repo docs, and touched metadata remain
  aligned when present.
- Ceratops skill-local icons match the repo-root icon and metadata icon paths
  are runtime-local.
- Removed, merged, or renamed sections leave no stale assignment or stale
  runtime payload.

### Output Contract

Report only:

- skills or shared maintenance surfaces updated
- new, removed, merged, or narrowed shared sections with reasons
- unresolved blockers or non-blocking debt
- intentionally retained inconsistencies or follow-up items with reasons
- anything important not verified
