# Skills Consistency And Contract Review Action

## Goal

Audit skill-source consistency, skill governance, runtime payload mapping,
shared-section alignment, metadata alignment, and skill-design contract upkeep
inside the skill lifecycle surface. Keep skill contracts, skill-standard source
docs, and the skill consistency validator owned by `ceratops-skill-lifecycle`.

## Context

### Script Bundle

- (D) Skill consistency validator: `python
  skills/ceratops-skill-lifecycle/scripts/validation/validate-skills-consistency.py
  --mode governance`
- (D) Markdown lint when source skill Markdown is in scope: `npm run
  lint:markdown`
- (D) Python type check when skill helper or validator scripts are in scope:
  `python -m mypy`

### References

- Skill source-doc registry: `references/skill-source-docs.json`
- Skill deterministic contract: `references/skill-deterministic-contract.json`
- Skill non-deterministic contract:
  `references/skill-nondeterministic-contract.md`
- Shared-section manifest: `templates/skill-sections.json`
- Skill consistency validator:
  `scripts/validation/validate-skills-consistency.py`

### Inputs To Capture

- Whether the user wants report-only audit output or approved fixes.
- Whether installed runtime skill copies are expected to reflect the current
  checkout.
- Any recent rename, router/action-reference consolidation, shared-section,
  skill contract, validation, README, runtime payload, or automation cleanup
  change that should be checked.

Infer missing inputs from the repo state before asking.

## Constraints

### Boundaries

- Use this action only for explicit skill consistency audits or skill-design
  contract upkeep.
- Do not run this action for ordinary small skill updates; use `update.md` and
  its targeted checks unless the update changes the skill contract, validator,
  runtime payload map, shared-section model, metadata routing, or another
  governance surface.
- Do not inspect GitHub org, GitHub repo, PR readiness, repo-code, artifact,
  registry, or release contracts here; those belong to
  `$ceratops-gh-repo-lifecycle` `contracts-review`.
- Do not mutate installed skills during report-only audits. If runtime repair is
  approved, regenerate through the skill-lifecycle runtime installer from the
  skills repo checkout.

### Skill-Specific Rules

- Treat `--mode governance` as the deterministic owner for machine-checkable
  skill consistency drift.
- Keep duplicate contract text, shared-section fit, router/action-reference fit,
  retired-name drift, broad GH action boundary prose, artifact-scope prose,
  Dependabot/admin-merge prose, and rule-shape quality as non-deterministic
  checks unless the validator reports an objective finding.
- Do not add backward-compatibility aliases, old-name shims, pointer artifacts,
  one-time migration detectors, or stale-term audit checks.
- Keep skill standards in this action's skill-local `references/` files and
  validator; do not recreate a repo-root shared contract payload.

## Workflow

### 1. Run Deterministic Checks

- Run the governance validation command from the skills repo checkout.
- Run Markdown lint and mypy for explicit broad skill governance, or when
  touched skill Markdown, helper scripts, validators, or validation configs put
  those surfaces in scope.
- If it fails, report the exact findings first and do not continue into broad
  manual review until those deterministic failures are understood.

### 2. Review Non-Deterministic Checks When Justified

- Review duplicate contract text that may belong in `templates/sections/`.
- Review shared-section fit for missing, duplicated, over-broad, too narrow, or
  skill-specific shared text.
- Review router/action-reference consistency: router action list, reference file
  presence, action boundaries, metadata prompt wording, README rows, runtime
  payload mapping, and validator expectations.
- Review retired-name drift in active triggers, metadata, manifests, validators,
  automations, docs, and cross-skill references; allow only clearly historical
  changelog mentions.
- Review shared-section cleanup: only `core` should remain shared unless another
  section has more than one real consuming skill after consolidation.
- When changed files include `references/skill-*`,
  `references/skill-source-docs.json`, `scripts/validation/validate-skills-consistency.py`,
  `templates/skill-sections.json`, or source skills, review changed-surface
  alignment between source docs, deterministic contracts, non-deterministic
  contracts, validator behavior, README contract docs, and actual source-skill
  structure.
- For any new deterministic skill-structure requirement, inventory all source
  skills for that required section, subsection, resource, or metadata field
  before reporting the structure clean.

### 3. Apply Fixes Only When Approved

- For source fixes, use the narrowest skill-maintenance workflow that matches
  the change.
- For installed runtime fixes, regenerate through the skill-lifecycle runtime
  installer from the skills repo checkout only when runtime mutation is
  explicitly in scope.
- For automation cleanup, use `$ceratops-propose-rules-update` before editing
  automation prompt text or helpers.

### 4. Close With Scoped Evidence

- Re-run `--mode governance` after any in-scope repair.
- If source skills changed and local runtime availability is required, stage
  through `change-promotion.md`.

## Done When

### Completion Gate

- Deterministic governance validation either passes or every finding is reported
  with the owning file and smallest credible repair.
- Every non-deterministic check category listed in Workflow step 2 is reviewed,
  not applicable, intentionally deferred, or blocked before reporting a clean
  pass.
- Any approved source, runtime, or automation repair was verified by the
  narrowest relevant command.

### Output Contract

Report only:

- governance validation outcome
- deterministic findings and smallest repairs
- non-deterministic check results for every Workflow step 2 category, including
  not applicable, deferred, or blocked categories
- source, runtime, or automation changes made
- unresolved blockers, intentionally deferred candidates, and important
  unverified items
