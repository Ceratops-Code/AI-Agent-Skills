---
name: ceratops-skill-lifecycle
description: Route Ceratops or compatible skill lifecycle work to action references for create, make-repo-compatible, fast-change, update, skills-contract-review, and skills-consistency-review work. Use when Codex should create a skill, make a skills repository Ceratops-compatible, apply an eligible direct-release skill change with targeted installation, update skill source or shared governance surfaces, refresh Ceratops skill-design contracts, or audit one manifest-backed installed skill and its coupled source.
---

# Ceratops Skill Lifecycle

## Goal

Route skill lifecycle work to the narrowest action reference, then follow that
reference as the execution contract. Keep one live skill lifecycle capability
surface for standards refresh, repository consistency, creation, and mutation.

## Context

### Action References

- Create a new skill: `references/create.md`
- Make an existing skills repository Ceratops-compatible:
  `references/make-repo-compatible.md`
- Apply an eligible direct-release skill change: `references/fast-change.md`
- Update an existing skill or shared maintenance surface: `references/update.md`
- Refresh Ceratops skill-design contracts from current standards evidence:
  `references/skills-contract-review.md`
- Audit one manifest-backed installed skill and its coupled source:
  `references/skills-consistency-review.md`

### Inputs To Capture

- Target skill, installed runtime manifest, repo, branch, and action intent.
- Which repo-owned surfaces are in scope: source skill folders,
  `agents/openai.yaml`, `skills/sections/`, `skills/skill-sections.json`,
  reusable templates, runtime payload declarations, validators, contracts,
  helper scripts, docs, or runtime generation.
- Whether `skills/skill-sections.json` declares a stable
  `runtime_source_id` and either the `ceratops` or `ceratops-compatible`
  validation profile.
- Whether the complete intended scope qualifies for `fast-change`.
- Whether the task should stop at committed task-worktree changes or hand off
  to `$ceratops-repo-lifecycle`.

Infer missing inputs from the current repo state before asking.

## Constraints

### Skill-Specific Rules

- Use the action references as the source of truth for skill-source edits,
  validation, and output contracts.
- Keep skill creation, repository compatibility, fast change, update, contract
  review, and repository consistency review inside this multi-action skill and
  its `references/` files; do not introduce alias skills or old-name shims.
- For skill-source mutation in this repo, treat source skill text, metadata,
  shared sections, `skills/skill-sections.json`, runtime payloads,
  validators, contracts, helper scripts, and docs as one coupled maintenance
  surface when they exist.
- Treat another repo as Ceratops-compatible only when its section manifest
  declares `runtime_source_id`, `validation_profile: ceratops-compatible`,
  shared sections, and per-skill assignments. Skill names need not use a
  Ceratops prefix.
- Use the installed Ceratops lifecycle runtime to install or deploy
  AI-Agent-Skills, executing a temporary runtime snapshot outside the managed
  destination; if unavailable or unsuccessful, run the checkout's independent
  installer once. Compatible-repository installers remain self-contained and
  Ceratops-independent, only resolving declarations and rendering or copying
  skills.
- Use `fast-change` directly on verified primary `release/local` whenever
  its action contract and one-request orchestrator accept the complete intended
  scope. The orchestrator owns patch, repository-declared Markdown lint, exact
  helper tests, targeted installation, commit, and compensation. Use a task
  worktree for `update` and for `create` outside this repo; new Ceratops skills
  continue through repository lifecycle `promote-and-deploy`.

### Boundaries

- Use this skill for creating skills, eligible direct-release changes, updating
  existing skills, skill repository compatibility, consistency audits, and
  skill-design contract upkeep.
- If the task is advisory-only skill optimization, use
  `$ceratops-governance-lifecycle` action `optimize-skill`.
- If the task is Ceratops skill-contract standards upkeep, use
  `references/skills-contract-review.md`.
- If the task is manifest-backed installed-skill consistency and contract
  compliance, use
  `references/skills-consistency-review.md`.
- If the task is repository promotion, deployment, shipping, or another Git or
  GitHub lifecycle operation, use `$ceratops-repo-lifecycle`.

### Workflow

#### 1. Classify the action

- Use `create` when a brand-new skill must be added and integrated with
  available repo governance surfaces.
- Use `make-repo-compatible` when a target skills repository lacks the manifest,
  shared-section, metadata, documentation, installer, or validation surfaces
  required by the `ceratops-compatible` profile.
- Use `fast-change` whenever the request is exact and its complete selected
  skill-local scope satisfies `references/fast-change.md`.
- Use `update` when an existing skill, shared section, manifest, runtime
  generation, validator, contract, helper interface, or other coupled surface
  falls outside fast-change.
- Use `skills-contract-review` only to refresh the skill-design contracts
  against current registered best-practice evidence.
- Use `skills-consistency-review` to audit one manifest-backed installed skill
  against those contracts and its coupled source, automation, installer, and
  runtime surfaces.

#### 2. Close from action evidence

- Match final claims to the exact source diff, validator output, or runtime state
  actually verified.
- Report retained runtime copies, automation prompts, or external side effects
  only when the selected action requires them.

## Done When

### Completion Gate

- Source, runtime, and validation claims are limited to the checks and state
  actually verified.

### Output Contract

Report only:

- selected action and final outcome
- updated skill, standards, contract, or shared maintenance surfaces
- unresolved blockers or non-blocking debt
- intentionally retained runtime copies, automation prompts, or external side
  effects with reasons
- anything important not verified

### Example Invocation

`Use $ceratops-skill-lifecycle for this exact skill change. Prefer fast-change
when its complete scope passes readiness; otherwise use update in a task
worktree.`
