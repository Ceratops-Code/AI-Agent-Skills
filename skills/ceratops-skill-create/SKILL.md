---
name: ceratops-skill-create
description: Create a brand-new Ceratops or compatible skill in a skill repo, using Ceratops templates, validation, metadata, and local preview only when those components exist.
---

# Ceratops Skill Create

## Goal

Create a brand-new skill as a complete repo-integrated addition instead of leaving it as an isolated scaffold. In this Ceratops skills repo, integrate the new skill into the shared section model, runtime payload model, docs, metadata, and local runtime preview flow. In another skill repo, use only the components that repo actually provides and skip missing Ceratops-only templates, validators, installers, or release helpers.

## Context

### Inputs To Capture

- The new skill's purpose, trigger conditions, and likely shared-section needs.
- Whether the new skill needs bundled scripts, references, or helper-runtime changes.
- Which repo surfaces must be updated: `skills/<name>/`, `templates/skill-sections.json`, `templates/sections/`, runtime payload declarations, repo docs, runtime generation or validation scripts, and any helper-runtime claims.
- Which applicable checks from `contracts/skills/skill-deterministic-contract.json` and `contracts/skills/skill-nondeterministic-contract.md` should shape the new skill's source, metadata, references, safety boundaries, workflow, and output contract.
- Which Ceratops-specific surfaces are absent in a non-Ceratops repo and therefore intentionally skipped.
- Whether local runtime availability should be skipped despite the default.

Infer missing inputs from the repo's current structure and the user request before asking.

## Constraints

### Skill-Specific Rules

- Treat new-skill creation as complete only when the new skill folder, metadata, repo docs, and every available repo-owned generation or validation surface are aligned.
- Use `$skill-creator` only as the internal scaffolding step when a new folder or starter metadata is needed. Do not stop after scaffolding.
- In this repo, keep the new source `SKILL.md` delta-only: reuse existing shared sections first, and add a new shared section only when it clearly reduces duplication or drift across multiple skills.
- In this repo, copy the repo-root Ceratops icon from `assets/ceratops-logo-500.png` into the new skill at `assets/ceratops-logo-500.png`, and set both `interface.icon_small` and `interface.icon_large` in `agents/openai.yaml` to `./assets/ceratops-logo-500.png`.
- In this repo, use `contracts/skills/skill-deterministic-contract.json` and `contracts/skills/skill-nondeterministic-contract.md` as the skill-design rubric for new skills. Apply the deterministic contract through the repo's available validation and targeted readback, and apply the non-deterministic contract through reviewer judgment before commit or staging.
- In repos with `templates/skill-sections.json`, use the recorded same-surface maintenance-check policy instead of making the user specify commands; when the manifest is absent, skip that path and rely on targeted readback and diff review.
- Local runtime availability is part of completion by default only when the target repo provides an installer or runtime update path. In this repo, after the new skill validates, make an intentional commit on the worktree branch and continue with `$ceratops-skill-stage-release` unless the user explicitly opts out.
- Do not publish to GitHub unless the user explicitly asked for shipping.

### Boundaries

- Use this skill when the task is creating a brand-new Ceratops skill in this repo, or when the user asks to create a complete skill in another skill repo.
- If the task is generic one-off scaffolding with no repo integration expectations, stop and use `$skill-creator`.
- If the task is updating an existing Ceratops skill, maintaining the shared layer, or shipping already-prepared changes, stop because that work is outside this skill's scope.

### Workflow

#### 1. Design the new skill in repo context

- Inspect the current skill family, repo docs, and any adjacent helper-runtime claims the new skill may touch.
- In this repo, inspect shared sections and manifest assignments, then decide whether the new skill can reuse existing sections or truly needs a new shared section.
- In this repo, inspect `contracts/skills/` and select only the deterministic and non-deterministic skill-design checks that apply to the new skill's purpose, artifacts, tools, references, and side effects.
- In another repo, detect whether shared sections, manifests, validators, installers, metadata files, docs, or runtime payload declarations exist before treating them as required.
- Decide whether raw scaffolding through `$skill-creator` is necessary or whether direct creation is cheaper and clearer.

#### 2. Create the new skill and integrate it

- Scaffold the new skill folder when needed.
- Create or update `SKILL.md`, `agents/openai.yaml`, and any bundled resources, including the skill-local Ceratops icon file and metadata.
- Add the new skill to `templates/skill-sections.json`, assign the right shared sections, and update repo docs only when those surfaces exist in the target repo.
- Before treating the new skill source as ready, review it against the applicable skill-design contract checks for trigger fit, source structure, deterministic placement, reference discipline, safety and state boundaries, output and closure, metadata alignment, and runtime portability.
- Update runtime generation or validation scripts only when those scripts exist and the new skill exposes a real gap in that repo's maintenance model.

#### 3. Run the needed checks

- When a new skill changes shared assignments and `templates/skill-sections.json` exists, run the shared-source check path from that manifest.
- If helper-runtime code or claims changed, run only the touched helper's own smoke command when that helper supports one.
- Re-open the changed files from disk and confirm the source skill, available runtime-generation inputs, manifest assignment, metadata, and docs all align.
- Confirm the applicable skill-design contract checks were satisfied, approved as drift, blocked with a concrete reason, or marked not applicable. Do not run the non-deterministic skill-design review as a routine validator.

#### 4. Make it available locally

- Make an intentional commit on the worktree branch for the new skill once the local repo state is ready.
- In this repo, continue with `$ceratops-skill-stage-release` so the new skill becomes available through the skills repo `release/*` branch and generated local skill copy, unless the user explicitly opted out.
- In another repo, run only that repo's available install, merge, ship, or runtime update path; if none exists, skip local runtime availability and report it as not provided by the repo.
- If staging is blocked, report the blocker instead of presenting the new skill as locally available.

## Done When

### Completion Gate

- Verify the new skill folder, available manifest assignment, runtime-generation inputs, metadata, and repo docs all align.
- Verify the applicable skill-design contract checks were used and their result is reflected in the new skill design or reported as blocked, approved drift, or not applicable.
- Verify the required generation or validation path ran successfully when the target repo provides one.
- In this repo, verify the new skill was committed and staged into the skills repo local preview flow, unless the user explicitly opted out or a blocker prevented it.
- In another repo, verify the furthest available create, update, merge, ship, or runtime step was completed or blocked.

### Output Contract

Report only:

- the new skill created
- any new shared sections or helper updates added with reasons
- unresolved blockers or non-blocking debt
- intentionally retained exceptions with reasons
- anything important not verified

### Example Invocation

`Use $ceratops-skill-create to create a new Ceratops skill for X, integrate it into the repo, run the needed checks, and make it available locally through the skills repo release branch.`
