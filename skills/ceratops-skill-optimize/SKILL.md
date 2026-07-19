---
name: ceratops-skill-optimize
description: Propose advisory-only improvements for existing Codex or Ceratops skills, including router SKILL.md text, action references, triggers, metadata, runtime payload declarations, validators, docs, workflow constraints, output contracts, and done criteria. Use when Codex should recommend exact skill changes without applying them.
---

# Ceratops Skill Optimizer

## Goal

Propose the smallest clear skill update that improves an existing skill's
structure, trigger behavior, workflow, constraints, output contract, or done
criteria without changing its intended purpose unless the user explicitly
requests that behavior change.

## Context

### Inputs To Capture

- Current skill text or the concrete target skill path.
- The skill's purpose, trigger conditions, expected user request, workflow,
  constraints, output contract, and completion criteria.
- Companion artifacts that govern the same behavior, such as router `SKILL.md`,
  action reference files, `agents/openai.yaml`, bundled resources, helper
  references, docs, manifests, runtime payload declarations, or validators.
- Whether the requested change is structural, behavioral, trigger-only,
  output-only, validation-only, or wording-only.

Ask one concise question and stop if no skill text, file path, or concrete
target is available.

## Constraints

### Skill-Specific Rules

- Do not apply edits or mutate files.
- Preserve the skill's existing intent unless the user explicitly asks to change
  behavior.
- Prefer targeted proposals over whole-skill rewrites.
- Put trigger information in YAML frontmatter descriptions rather than only in
  the body.
- Keep `SKILL.md` focused on execution rules that are useful after the skill has
  already triggered.
- Include a role only when it changes how Codex should judge tradeoffs, inspect
  inputs, choose tools, or decide completion.
- Inspect companion artifacts only when they exist and govern trigger behavior,
  runtime packaging, helper usage, validation, docs, or user-visible output for
  the target skill.
- For router skills, inspect the router `SKILL.md` and action reference files;
  inspect metadata, runtime payload declarations, validators, and docs only when
  they govern the action surface.
- When companion artifacts govern the same behavior, include the aligned
  companion update or state why it is intentionally retained.
- Remove or merge duplicate responsibilities and avoid overlong, brittle, vague,
  contradictory, or purely stylistic changes.
- Prefer deterministic scripts or helpers for repeatable procedural behavior
  only when text instructions are insufficient.
- Do not add auxiliary documentation, README files, examples, or unrelated
  resources unless they are required to prevent misinterpretation.
- A proposed update must preserve intent, improve execution clarity or trigger
  accuracy, have a clear owner, avoid duplicated instructions, be enforceable,
  define completion, and avoid unjustified recurring maintenance cost.

### Boundaries

- Use this skill for advisory skill optimization and exact proposed skill text
  changes.
- If the user asks to apply changes to Ceratops skills, use
  `$ceratops-skill-lifecycle` with the `update` action.
- If the user asks to create a new skill, use `$ceratops-skill-lifecycle` with
  the `create` action.
- If the requested change is one durable rule, use
  `$ceratops-propose-rules-update`.

### Workflow

1. Inspect the target skill text, action references when present, and companion
   metadata.
2. Before proposing a structural helper or validator change, map its owner,
   responsibilities, callers, entrypoints, and bootstrap paths.
3. Identify current purpose, trigger surface, workflow, constraints, output
   contract, and done criteria.
4. Decide whether Goal / Context / Constraints / Done When structure would
   improve execution.
5. Find concrete issues: missing trigger context, unclear ownership, duplicated
   rules, weak completion criteria, stale labels, metadata drift, excessive
   output, or unverifiable instructions.
6. Propose the narrowest update that fixes the issue across router text, action
   references, metadata, runtime payloads, validators, and docs when those
   surfaces govern the same behavior.
7. Include exact proposed replacement or addition and the smallest current
   anchor needed to locate it.

## Done When

### Completion Gate

- The response states whether an update is recommended.
- Every proposed change includes exact new text and target location.
- Behavior changes, recurring cost increases, blockers, and missing inputs are
  explicit.
- No files were edited.

### Output Contract

Return only:

- recommendation status
- target section or insertion point
- exact proposed replacement or addition
- minimal current anchor when needed
- behavior changes, if any
- blockers or missing inputs, if any
