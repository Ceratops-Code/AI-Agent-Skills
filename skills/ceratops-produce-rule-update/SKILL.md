---
name: ceratops-produce-rule-update
description: Produce a durable rule or instruction update from a concrete failure, gap, weak draft, or current workflow miss while preserving the original rule intent.
---

# Ceratops Produce Rule Update

## Goal

Produce the smallest durable rule update that prevents the observed failure or closes the stated instruction gap without widening the rule beyond its real reusable class.

## Context

### Inputs To Capture

- The exact current rule or instruction text, when it exists.
- The failure, gap, correction, weak draft, or current workflow miss that the rule must address.
- The artifact that owns the rule: `AGENTS.md`, `SKILL.md`, automation prompt, helper contract, repo docs, or another named control file.
- Any higher-precedence rule that limits the update.

Ask one concise question only when the target rule or failure class cannot be identified from the provided context.

## Constraints

### Skill-Specific Rules

- Start from the exact current rule text when it exists; do not optimize a paraphrase.
- Preserve the original rule's intent, scope, prohibitions, exceptions, and required checks unless the user explicitly asks to change them.
- Prefer one narrow replacement or addition over broad instruction rewrites.
- Draft each added or changed bullet with one primary obligation and an explicit phase when practical.
- Reject wording that is vague, example-driven, duplicative, contradictory, too broad, too narrow, or likely to increase routine rework.
- If the update removes a protection, category, prohibition, exception, or required check, call out whether the removal is intentional, preserved elsewhere, or required to fix the failure class.
- When the correct fix is to split an overloaded rule, provide the split rules and the reason the obligations need separate owners or phases.
- Do not mutate files unless the user explicitly asks to apply the named change.

### Boundaries

- Use this skill for rule, instruction, policy, prompt-line, skill-rule, automation-prompt, and helper-contract wording changes.
- If the user only wants a general prompt rewrite, use `$ceratops-prompt-optimizer`.
- If the user wants a full skill execution workflow review rather than one rule change, use `$ceratops-skill-optimize`.

### Workflow

1. Identify the exact current rule, reusable failure class, and obligations that must survive.
2. Choose the smallest useful operation: delete, narrowly edit, add one rule, or split an overloaded rule.
3. Draft the proposed text in the owning artifact's style.
4. Compare the proposed text against the current rule and identify any removed protections.
5. Keep only the candidate that fixes the failure class with the least durable maintenance cost.

## Done When

### Completion Gate

- The response identifies the target rule or states the missing evidence blocking that identification.
- The proposed update is exact text, not a summary.
- Any removed protection is classified as intentional, preserved elsewhere, or required.
- No file was changed unless the user explicitly asked to apply the change.

### Output Contract

Report only:

- target artifact and current rule anchor
- exact proposed replacement or addition
- removed or preserved protections, if any
- unresolved blocker or missing input, if any
