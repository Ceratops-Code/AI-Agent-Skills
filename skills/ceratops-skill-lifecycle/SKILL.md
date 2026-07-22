---
name: ceratops-skill-lifecycle
description: Route Ceratops or compatible skill lifecycle work to action references for create, make-repo-compatible, update, skills-contract-review, skills-consistency-review, fast-change, change-promotion, and ship-to-remote work. Use when Codex should create a skill, make a skills repository Ceratops-compatible, update skill source or shared governance surfaces, refresh Ceratops skill-design contracts, audit one skills repository and its coupled runtime consumers, apply an explicit fast release-branch change, promote committed skill changes into a local release/runtime preview, or ship a staged skills batch through GitHub.
---

# Ceratops Skill Lifecycle

## Goal

Route skill lifecycle work to the narrowest action reference, then follow that
reference as the execution contract. Keep one live skill lifecycle capability
surface for standards refresh, repository consistency, creation, mutation,
local promotion, and remote shipping.

## Context

### Action References

- Create a new skill: `references/create.md`
- Make an existing skills repository Ceratops-compatible:
  `references/make-repo-compatible.md`
- Update an existing skill or shared maintenance surface: `references/update.md`
- Refresh Ceratops skill-design contracts from current standards evidence:
  `references/skills-contract-review.md`
- Audit one skills repository and its coupled runtime consumers:
  `references/skills-consistency-review.md`
- Apply an explicit fast release-branch change: `references/fast-change.md`
- Promote committed skill changes into a local release branch and runtime
  preview: `references/change-promotion.md`
- Ship a staged skills repo branch through GitHub and rebuild runtime from main:
  `references/ship-to-remote.md`

### Inputs To Capture

- Target skill, repo, branch, release branch, installed runtime expectation,
  action intent, and any explicitly requested staging or shipping step.
- Which repo-owned surfaces are in scope: source skill folders,
  `agents/openai.yaml`, `templates/`, runtime payload declarations, validators,
  contracts, helper scripts, docs, or runtime generation.
- Whether `templates/skill-sections.json` declares a stable
  `runtime_source_id` and either the `ceratops` or `ceratops-compatible`
  validation profile.
- Whether the task should stop at local task-worktree changes or continue to
  local promotion or remote shipping.

Infer missing inputs from the current repo state before asking.

## Constraints

### Skill-Specific Rules

- Use the action references as the source of truth for source edits, staging,
  runtime update, cleanup, validation, and output contracts.
- Keep skill creation, repository compatibility, update, contract review,
  repository consistency review, fast change, change promotion, and remote
  shipping inside this multi-action skill and its `references/` files; do not
  introduce alias skills or old-name shims.
- For skill-source mutation in this repo, treat source skill text, metadata,
  shared sections, `templates/skill-sections.json`, runtime payloads,
  validators, contracts, helper scripts, and docs as one coupled maintenance
  surface when they exist.
- Treat another repo as Ceratops-compatible only when its section manifest
  declares `runtime_source_id`, `validation_profile: ceratops-compatible`,
  shared sections, and per-skill assignments. Skill names need not use a
  Ceratops prefix.
- Treat `scripts/templates/install-skills-template.py` as the authoritative
  installer source. Copy only `scripts/install-skills.py` into compatible
  repositories, and compare installers only by their parsed integer
  `INSTALLER_VERSION`.
- Stop in the task worktree by default for update actions and for create actions
  outside this repo. In this repo, new Ceratops skill creation continues through
  change-promotion and install verification unless the user opts out.
- Treat `ship-to-remote` as an action identity, not a separate skill folder.

### Boundaries

- Use this skill for creating skills, updating existing skills, skill
  repository compatibility, consistency audits, skill-design contract upkeep,
  fast direct release-branch changes, promoting committed skill branches into a
  local release branch, and shipping staged skills repo changes through GitHub.
- If the task is advisory-only skill optimization, use
  `$ceratops-governance-lifecycle` action `optimize-skill`.
- If the task is Ceratops skill-contract standards upkeep, use
  `references/skills-contract-review.md`.
- If the task is repository skill consistency and contract compliance, use
  `references/skills-consistency-review.md`.
- If the task is a general GitHub repo lifecycle operation, use
  `$ceratops-gh-repo-lifecycle`.

### Workflow

#### 1. Classify the action

- Use `create` when a brand-new skill must be added and integrated with
  available repo governance surfaces.
- Use `make-repo-compatible` when a target skills repository lacks the manifest,
  shared-section, metadata, documentation, installer, or validation surfaces
  required by the `ceratops-compatible` profile.
- Use `update` when an existing skill, shared section, manifest, runtime
  generation, validator, contract, helper, or doc surface must change.
- Use `skills-contract-review` only to refresh the skill-design contracts
  against current registered best-practice evidence.
- Use `skills-consistency-review` to audit one skills repository against those
  contracts and its coupled source, automation, installer, and runtime surfaces.
- Use `fast-change` only when the user explicitly asks for a known-safe direct
  release-branch edit and targeted runtime update.
- Use `change-promotion` when committed task-worktree branches are ready to
  merge into the skills repo checkout's local `release/*` branch and runtime
  preview.
- Use `ship-to-remote` when the skills repo checkout already has a staged
  `release/*` branch ready to push, PR, merge, restore to `main`, and reinstall
  from `main`.

#### 2. Close from action evidence

- Match final claims to the exact source diff, validator output, runtime state,
  release branch state, or live GitHub state actually verified.
- Report retained worktrees, branches, runtime copies, automation prompts, or
  external side effects only when the selected action requires them.

## Done When

### Completion Gate

- Source, runtime, validation, branch, and shipping claims are limited to the
  checks and state actually verified.

### Output Contract

Report only:

- selected action and final outcome
- updated skill, standards, contract, or shared maintenance surfaces
- unresolved blockers or non-blocking debt
- intentionally retained branches, worktrees, runtime copies, automation
  prompts, or external side effects with reasons
- anything important not verified

### Example Invocation

`Use $ceratops-skill-lifecycle to update these Ceratops skills in a task
worktree and stop before runtime promotion.`
