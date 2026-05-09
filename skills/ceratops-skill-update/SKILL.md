---
name: ceratops-skill-update
description: Update existing Ceratops or compatible skills while using shared sections, manifests, runtime generation, validation, helper claims, contracts, and docs only when the target repo provides them.
---

# Ceratops Skill Update

## Goal

Maintain existing skills as one consistency surface instead of patching individual skill files in isolation. Decide first whether the source of truth is a skill-local delta, a shared section, the section manifest, runtime payloads, runtime generation logic, validation logic, helper-runtime claims, contracts, or repo docs, then update the narrowest correct source that exists in the target repo.

## Context

### Inputs To Capture

- Which existing skills or shared files are in scope: `skills/*`, `templates/sections/`, `templates/skill-sections.json`, `scripts/render-runtime-skills.py`, `scripts/validation/validate-skills-consistency.py`, `contracts/`, helper-runtime files, and repo docs.
- Whether the requested change belongs in skill-local text, a shared section, the section manifest, runtime generation logic, validation logic, helper-runtime code or claims, or repo docs.
- Which Ceratops-specific surfaces are absent in a non-Ceratops repo and therefore intentionally skipped.
- Whether the task should stop at local repo changes or also stage them into the active local `release/*` batch.

Infer missing inputs from the current repo state before asking.

## Constraints

### Skill-Specific Rules

- Treat `templates/sections/`, `templates/skill-sections.json`, `scripts/render-runtime-skills.py`, `scripts/validation/validate-skills-consistency.py`, `contracts/`, related repo docs, and any touched helper-runtime claims as one coupled maintenance surface when they exist in the target repo.
- Decide the broadest correct source of truth before editing anything. Prefer shared sections and the section manifest for shared behavior, and keep per-skill source text limited to true deltas.
- Do not put generated shared-section blocks in source `skills/*/SKILL.md` when the repo uses generated runtime sections; update `templates/sections/`, `templates/skill-sections.json`, or `scripts/render-runtime-skills.py` when those surfaces exist and runtime generation needs to change.
- Add a new shared section only when it reduces meaningful duplication, clarifies ownership, or prevents conflicting drift across multiple skills. Prefer deleting, merging, or narrowing sections when that is cleaner.
- Treat this skill as the default Ceratops entrypoint for modifying existing skills.
- Update `agents/openai.yaml` when trigger behavior or the user-facing prompt becomes stale.
- In this repo, ensure every Ceratops skill keeps `assets/ceratops-logo-500.png` copied from the repo-root `assets/ceratops-logo-500.png`, and sets both `interface.icon_small` and `interface.icon_large` in `agents/openai.yaml` to `./assets/ceratops-logo-500.png` when skill metadata, installer, or validation surfaces are updated.
- Update helper scripts or helper-runtime claims when the target repo has them and the section model, runtime generation markers, validation rules, contract payloads, or skill claims require it.
- Stop in the worktree by default. Do not stage or ship the resulting repo changes unless the user explicitly asked for staging, runtime-preview sync, or GitHub shipping.
- Use the same-surface maintenance-check policy recorded in `templates/skill-sections.json` when it exists; when it is absent, skip template validation and use targeted readback, stale-reference search, and diff review. Do not run full validation during regular skill updates unless validation, runtime generation, shared section assignments, or explicit broad verification is actually in scope.

### Boundaries

- Use this skill when the task is to update existing Ceratops skills, compatible skills in another repo, or the shared skill-maintenance layer itself.
- If the task is creating a brand-new Ceratops skill, stop because new-skill creation is outside this skill's scope.
- If the task is only staging already-prepared skill changes, stop and use `$ceratops-codex-skill-stage-release`.

### Workflow

#### 1. Inspect the current maintenance surface

- Inspect the targeted skills, available shared section files, section manifest, runtime generation and validation scripts, touched helper-runtime files or claims, and repo docs that describe the current structure.
- Start maintenance inspection with targeted `rg` or path inventory and small line-window reads; broaden to full-file reads only for governing control files, ownership decisions, or unresolved context.
- Identify which parts are source of truth versus generated output.
- Identify absent Ceratops repo components before treating template, validation, installation, or contract steps as required.
- Classify the requested change as skill-local, shared, structural, validation-only, helper-runtime-adjacent, or docs-only.

#### 2. Decide ownership before editing

- Decide whether the change belongs in a per-skill delta, an existing shared section, the section manifest, runtime generation logic, validation logic, helper-runtime code or claims, or repo docs, limited to sources that exist in the target repo.
- Prefer the smallest change that keeps future maintenance consistent.
- If a proposed new section would only hold trivial text or one repeated line, keep it inline unless the duplication is already causing drift or ownership confusion.

#### 3. Apply the updates at the real source of truth

- Update existing skills, shared sections, the section manifest, runtime payloads, runtime generation or validation scripts, helper-runtime files or claims, contracts, and repo docs only where the chosen ownership requires it and the target repo provides that surface.
- Before renaming or moving shared contracts, scripts, templates, or payload folders, build one old-to-new reference map and update docs, skills, manifests, validators, and checkers from that map before running validation.
- When removing, merging, or narrowing sections, update every affected assignment and keep runtime generated section source comments readable in installed `SKILL.md` files.
- If the repo's current runtime generation or validation flow exists but no longer matches the section model, fix the scripts instead of working around them in skill text.

#### 4. Run the needed checks

- If shared section source files or `templates/skill-sections.json` assignments changed and the manifest exists, run the shared-source check path from `templates/skill-sections.json`.
- Do not run validation solely because skill-local text, `agents/openai.yaml`, or repo docs changed; use targeted readback, stale-reference search, and diff review unless a broader check is made stale.
- If helper-runtime code or claims changed, run only the touched helper's own smoke command when that helper supports one.
- If runtime generation code changed and the repo provides a runtime-generation check path, run it.
- Reserve `governance_full_validation` for scheduled governance automation, explicit broad validation, validation-script changes, or a concrete cross-surface uncertainty.
- Re-open the changed files from disk and confirm source skills, manifest assignments, runtime payloads, docs, contracts, and metadata still align for the touched scope.

#### 5. Report or hand off

- Stop at validated local repo changes unless the user explicitly asked for local preview staging.
- If local preview staging was requested, continue with `$ceratops-codex-skill-stage-release`.

## Done When

### Completion Gate

- Verify every changed skill and available shared file still points at the intended source of truth.
- Verify runtime shared-section generation is updated through shared sources, the manifest, and the renderer when those surfaces exist and shared sources changed.
- Verify the section manifest, runtime renderer, validation script, repo docs, and touched `agents/openai.yaml` files remain aligned when present.
- In this repo, verify all Ceratops skill-local icon copies match the repo-root icon source and all `agents/openai.yaml` icon paths are runtime-local.
- Verify any removed, merged, or renamed section leaves no stale assignment or stale runtime payload behind.

### Output Contract

Report only:

- skills or shared maintenance surfaces updated
- new, removed, merged, or narrowed shared sections with reasons
- unresolved blockers or non-blocking debt
- intentionally retained inconsistencies or follow-up items with reasons
- anything important not verified

### Example Invocation

`Use $ceratops-skill-update to update the Ceratops skills, choose the right source of truth automatically, run the needed checks, and keep the repo consistent.`
