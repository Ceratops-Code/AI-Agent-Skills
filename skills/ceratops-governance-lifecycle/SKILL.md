---
name: ceratops-governance-lifecycle
description: Route Ceratops governance work across prompt optimization, advisory skill optimization, regression-safe instruction updates, and cross-scope governance consistency audits. Use when Codex should rewrite a rough prompt without executing it, recommend exact changes to existing skills without applying them, diagnose and route approved instruction changes, or audit alignment across AGENTS files, automations, directly referenced helpers, and governance owners.
---

# Ceratops Governance Lifecycle

## Goal

Route governance work to the narrowest action reference while keeping prompt,
skill, instruction, and cross-scope audit decisions in one capability surface.

## Context

### Action References

- Optimize a raw prompt without executing it: `references/optimize-prompt.md`
- Propose advisory-only improvements to existing skills:
  `references/optimize-skill.md`
- Design or apply an approved regression-safe instruction change:
  `references/propose-rules-update.md`
- Audit cross-scope governance consistency:
  `references/governance-consistency-audit.md`

### Inputs To Capture

- Action intent and the target prompt, skill set, instruction stack, automation,
  helper contract, policy surface, or governance scope.
- Expected deliverable, strict constraints, current source text, and available
  regression or history evidence.
- Whether the task is advisory-only or authorizes an exact mutation.

Infer missing inputs from current context and local sources before asking.

## Constraints

### Shared Action Rules

- Preserve the target's intended meaning, purpose, constraints, and established
  behavior except where the selected action explicitly permits an authorized
  change.
- Use only the action-scoped work and evidence needed to satisfy the selected
  action's completion gate; do not inspect or change unrelated surfaces.
- Do not mutate an artifact unless the selected action pre-authorizes that exact
  mutation or the user authorizes the exact artifact and change.
- Keep prompt optimization and skill optimization advisory-only: do not execute
  the underlying task or mutate artifacts.
- For skill optimization, rule updates, and governance audits, inspect companion
  artifacts only when they govern the same behavior, evidence, or output
  contract.

### Skill-Specific Rules

- For instruction updates, mutate only the exact artifacts the user authorized
  after the proposal action accepts the candidate.

### Boundaries

- Use this skill for prompt optimization, advisory skill optimization,
  instruction-system change design or approved application, and cross-scope
  governance consistency audits.
- Use `$ceratops-skill-lifecycle` to create a skill or apply skill-source,
  metadata, manifest, helper, validation, or documentation changes.
- Use the owning lifecycle audit for domain-specific repository, code, runtime,
  GitHub, or skill-contract consistency.

### Workflow

#### 1. Classify the action

- Use `optimize-prompt` when the deliverable is a rewritten prompt and the task
  must not be executed.
- Use `optimize-skill` when the deliverable is an exact advisory skill-change
  proposal and files must remain unchanged.
- Use `propose-rules-update` when the task changes or reviews durable rules,
  instructions, automation prompts, skill rules, helper contracts, or their
  interactions.
- Use `governance-consistency-audit` when the task checks alignment across
  AGENTS files, automations, directly referenced helpers, and delegated
  governance owners.

#### 2. Close from action evidence

- Follow only the selected action unless its explicit boundary requires a
  lifecycle handoff.
- Match the final claim and output to the selected action's completion gate.

## Done When

### Completion Gate

- The narrowest action was selected and its completion gate passed or its exact
  blocker was reported.

### Output Contract

Return only the selected action's required output, unresolved blockers, and
important retained or unverified state.
