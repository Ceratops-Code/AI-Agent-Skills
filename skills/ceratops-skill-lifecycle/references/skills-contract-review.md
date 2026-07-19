# Skills Contract Review Action

## Goal

Review Ceratops skill-design contracts and the coupled source, metadata,
shared-section, runtime-payload, validator, and documentation surfaces in the
active skills repository. Keep Ceratops skill standards, source-doc tracking,
and deterministic governance checks owned by `ceratops-skill-lifecycle`.

## Context

### Script Bundle

- (D) Ceratops skill governance validator: `python
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

- Whether the user wants report-only contract review or approved fixes.
- Whether installed Ceratops runtime copies should reflect the current checkout.
- Recent contract, shared-section, metadata, runtime-payload, validator, README,
  action-reference, or automation changes that need coupled review.

Infer missing inputs from the repository state before asking.

## Constraints

### Boundaries

- Use this action only for Ceratops skill-contract review and coupled
  repository-governance consistency.
- Do not use this action for consistency across the active Codex skill catalog;
  use `global-skills-consistency-review`.
- Do not inspect GitHub org, GitHub repo, PR readiness, repo-code, artifact,
  registry, or release contracts; those belong to
  `$ceratops-gh-repo-lifecycle` `contracts-review`.
- Do not mutate installed skills during report-only reviews. If runtime repair
  is approved, regenerate through the skill-lifecycle runtime installer from
  the skills repository checkout.

### Skill-Specific Rules

- Treat `--mode governance` as the deterministic owner for machine-checkable
  Ceratops skill-contract and repository consistency drift.
- Keep duplicate contract text, shared-section fit, multi-action-skill fit,
  retired-name drift, and rule-shape quality as non-deterministic checks unless
  the validator reports an objective finding.
- Do not add backward-compatibility aliases, old-name shims, pointer artifacts,
  one-time migration detectors, or stale-term audit checks.
- Keep Ceratops skill standards in this action's skill-local `references/` files
  and validator; do not recreate a repository-root contract payload.

### Workflow

#### 1. Run deterministic checks

- Run the governance validation command from the skills repository checkout.
- Run Markdown lint and mypy for explicit broad contract review, or when the
  touched Markdown, helper scripts, validators, or configs require them.
- If a deterministic check fails, report the exact findings before broad manual
  review.

#### 2. Review contract consistency

- Review duplicate contract text that may belong in `templates/sections/`.
- Review shared-section fit for missing, duplicated, over-broad, too narrow, or
  skill-specific shared text.
- Review multi-action/action-reference consistency across action lists,
  reference files, boundaries, metadata prompts, README rows, runtime payloads,
  and validator expectations.
- Review retired-name drift in active triggers, metadata, manifests, validators,
  automations, docs, and cross-skill references.
- Keep only shared sections with more than one real consuming skill.
- When contract files, source docs, validators, manifests, or source skills
  changed, review alignment between those surfaces, README contract docs, and
  actual source-skill structure.
- Inventory all Ceratops source skills before accepting a new deterministic
  structure requirement.

#### 3. Apply only approved fixes

- Use the narrowest skill-maintenance workflow that owns each source fix.
- Regenerate installed runtime copies only when runtime mutation is explicitly
  in scope.
- Use `$ceratops-propose-rules-update` before editing automation prompts or
  helper contracts.

#### 4. Close with scoped evidence

- Re-run `--mode governance` after any in-scope repair.
- If source skills changed and local runtime availability is required, stage
  through `change-promotion`.

## Done When

### Completion Gate

- Governance validation passes or every deterministic finding is reported with
  its owning file and smallest credible repair.
- Every manual review category is passed, not applicable, intentionally
  deferred, or blocked.
- Every approved source, runtime, or automation repair is verified by the
  narrowest relevant command.

### Output Contract

Report only:

- governance validation outcome
- deterministic findings and smallest repairs
- manual contract-review results, including deferred or blocked categories
- source, runtime, or automation changes made
- unresolved blockers, intentionally deferred candidates, and important
  unverified items
