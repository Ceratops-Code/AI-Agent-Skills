---
name: ceratops-skills-consistency-audit
description: Audit Ceratops skill-source consistency, governance-only validation, lifecycle router/action-reference alignment, retired-name drift, runtime payload mapping, metadata alignment, and shared-section cleanup residue. Use after skill consolidation, rename waves, manifest changes, validation changes, or broad skill-source refactors.
---

# Ceratops Skills Consistency Audit

## Goal

Run an explicit Ceratops skills consistency audit for the skills repo. Use the governance validation mode for deterministic drift, then review the remaining non-deterministic checks that need judgment.

## Context

### Defaults

- Source repo: active Ceratops skills repo checkout root
- (D) Governance validation: `powershell -ExecutionPolicy Bypass -File .\scripts\install-skills.ps1 -SkipInstall -Validate governance`
- (D) Direct validator: `python scripts/validation/validate-skills-consistency.py --mode governance`

### Inputs To Capture

- Whether the user wants report-only audit output or approved fixes.
- Whether installed runtime skill copies are expected to reflect the current checkout.
- Any recent rename, router/action-reference consolidation, shared-section, contract, validation, README, runtime payload, or automation cleanup change that should be checked.

Infer missing inputs from the repo state before asking.

## Constraints

### Skill-Specific Rules

- Use this skill only for explicit Ceratops skills consistency audits, governance validation, or follow-up repair of skill-source drift.
- Do not run this during routine skill text edits unless the user asked for broad validation, governance checks, or rename/source-of-truth drift investigation.
- Treat `--mode governance` as the deterministic owner for machine-checkable skill consistency drift.
- Keep duplicate contract text, shared-section fit, router/action-reference fit, retired-name drift, broad GH action boundary prose, artifact-scope prose, Dependabot/admin-merge prose, and rule-shape quality as non-deterministic checks unless the validator reports an objective finding.
- Do not add backward-compatibility aliases, old-name shims, pointer artifacts, one-time migration detectors, or stale-term audit checks.
- Do not mutate installed skills during report-only audits. If runtime repair is approved, use the repo installer from the skills repo checkout.

### Boundaries

- Use `$ceratops-skill-lifecycle` with the `update` action for ordinary skill edits.
- Use `$ceratops-skill-lifecycle` with the `create` action for creating a new skill.
- Use `$ceratops-skill-lifecycle` with the `change-promotion` action when committed skill changes need local preview staging.
- Use the broader governance automation for cross-scope AGENTS, automation, model, credit, worktree, inbox, memory, and prompt/helper consistency.

### Workflow

#### 1. Run deterministic checks

- Run the governance validation command from the skills repo checkout.
- If it fails, report the exact findings first and do not continue into broad manual review until those deterministic failures are understood.

#### 2. Review non-deterministic checks when justified

- Review duplicate contract text that may belong in `templates/sections/`.
- Review shared-section fit for missing, duplicated, over-broad, too narrow, or skill-specific shared text.
- Review router/action-reference consistency: router action list, reference file presence, action boundaries, metadata prompt wording, README rows, runtime payload mapping, and validator expectations.
- Review retired-name drift in active triggers, metadata, manifests, validators, automations, docs, and cross-skill references; allow only clearly historical changelog mentions.
- Review shared-section cleanup: only `core` should remain shared unless another section has more than one real consuming skill after consolidation.
- Review GH action boundary prose, artifact-scope wording, Dependabot/admin-merge guidance, and skill-rule shape only when the task asks for those areas or the deterministic check points there.
- When changed files include `contracts/skills/*`, `contracts/source-docs.json`, `scripts/validation/validate-skills-consistency.py`, or source skills, review changed-surface alignment between source docs, deterministic contracts, non-deterministic contracts, validator behavior, README contract docs, and actual source-skill structure.
- For any new deterministic skill-structure requirement, inventory all source skills for that required section, subsection, resource, or metadata field before reporting the structure clean.

#### 3. Apply fixes only when approved

- For source fixes, use the narrowest skill-maintenance workflow that matches the change.
- For installed runtime fixes, regenerate through `scripts/install-skills.ps1` from the skills repo checkout.
- For automation cleanup, use `$ceratops-propose-rules-update` before editing automation prompt text or helpers.

#### 4. Close with scoped evidence

- Re-run `--mode governance` after any in-scope repair.
- If source skills changed and local runtime availability is required, stage through `$ceratops-skill-lifecycle` with the `change-promotion` action.

## Done When

### Completion Gate

- Deterministic governance validation either passes or every finding is reported with the owning file and smallest credible repair.
- Candidate-only review items are marked reviewed, not applicable, intentionally deferred, or blocked.
- Any approved source, runtime, or automation repair was verified by the narrowest relevant command.

### Output Contract

Report only:

- governance validation outcome
- deterministic findings and smallest repairs
- non-deterministic check results when checked
- source, runtime, or automation changes made
- unresolved blockers, intentionally deferred candidates, and important unverified items

### Example Invocation

`Use $ceratops-skills-consistency-audit to run governance skill consistency validation, review the remaining non-deterministic skill-drift checks, and report the smallest repairs.`
