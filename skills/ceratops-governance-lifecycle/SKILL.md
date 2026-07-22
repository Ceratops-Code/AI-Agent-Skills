---
name: ceratops-governance-lifecycle
description: Route Ceratops governance authoring work across prompt optimization, advisory skill optimization, and regression-safe instruction updates. Use when Codex should rewrite a rough prompt without executing it, recommend exact changes to existing skills without applying them, or diagnose, propose, and route approved changes to rules, skill instructions, automation prompts, helper contracts, policy lines, or interacting instruction scopes.
---

# Ceratops Governance Lifecycle

## Goal

Route governance authoring work to the narrowest action reference while keeping
prompt, skill, and instruction decisions in one capability surface.

## Context

### Action References

- Optimize a raw prompt without executing it: `references/optimize-prompt.md`
- Propose advisory-only improvements to existing skills:
  `references/optimize-skill.md`
- Design or apply an approved regression-safe instruction change:
  `references/propose-rules-update.md`

### Inputs To Capture

- Action intent and the target prompt, skill set, instruction stack, automation,
  helper contract, or policy surface.
- Expected deliverable, strict constraints, current source text, and available
  regression or history evidence.
- Whether the task is advisory-only or authorizes an exact mutation.

Infer missing inputs from current context and local sources before asking.

## Constraints

### Skill-Specific Rules

- Use the selected action reference as the source of truth for inputs,
  constraints, helpers, workflow, completion, and output.
- Keep prompt optimization and skill optimization non-mutating.
- For instruction updates, mutate only the exact artifacts the user authorized
  after the proposal action accepts the candidate.
- Route approved skill-source mutations through `$ceratops-skill-lifecycle`.
- Keep cross-action handoffs inside this lifecycle skill.
- Preserve each action's distinct intent boundary: prompt meaning, skill
  purpose, or recorded governance behavior.

### Boundaries

- Use this skill for prompt optimization, advisory skill optimization, and
  instruction-system change design or approved application.
- Use `$ceratops-skill-lifecycle` to create a skill or apply skill-source,
  metadata, manifest, helper, validation, or documentation changes.
- Use the owning audit skill for repository, code, runtime, or governance
  consistency audits.

### Workflow

#### 1. Classify the action

- Use `optimize-prompt` when the deliverable is a rewritten prompt and the task
  must not be executed.
- Use `optimize-skill` when the deliverable is an exact advisory skill-change
  proposal and files must remain unchanged.
- Use `propose-rules-update` when the task changes or reviews durable rules,
  instructions, automation prompts, skill rules, helper contracts, or their
  interactions.

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
