---
name: ceratops-propose-rules-update
description: Propose focused rule-update recommendations after a concrete agent failure or miss caused or allowed by existing or missing instructions. Use when the user invokes $Ceratops-Propose-Rules-Update or $ceratops-propose-rules-update to diagnose instruction causes and propose exact updates to AGENTS.md rules, SKILL.md rules, automation prompts, helper contracts, policy lines, or prompt rules.
---

# Ceratops Propose Rules Update

## Goal

Act as a skill and instruction engineer. Propose exact update recommendations
for rules, instructions, prompts, skills, automations, and helper contracts
after a concrete failure, miss, or user request to govern behavior.

## Context

### Inputs To Capture

- The concrete failure or miss and the observed incorrect behavior.
- The reusable failure class the update must prevent.
- The exact current rule or contract line from every involved source, when it
  exists.
- All governing sources involved in the failed thread, including global
  `AGENTS.md`, local `AGENTS.md`, invoked skills, automations, prompts, helper
  contracts, and control files.
- The likely owner artifact for each proposed update.
- Whether the user wants only proposed text or also wants the named change
  applied.

Ask one concise question and stop only when the failure class, involved sources,
or owning artifact cannot be identified from the provided context and local
evidence.

## Constraints

### Skill-Specific Rules

- Before drafting, identify the failure or miss, reusable failure class,
  involved sources, and the current text or helper contract that allowed, failed
  to prevent, or should own the fix.
- Start from exact current rule or contract text; do not optimize a paraphrase.
- Answer before proposing text: what change would have prevented the miss, where
  that change belongs, how it avoids recurrence, and whether existing text
  conflicts with the fix.
- Put special weight on contradictions and source-of-truth drift across involved
  instruction sources; name the conflict, likely authoritative source, and
  smallest repair.
- Preserve existing intent, scope, prohibitions, exceptions, required checks,
  triggers, and constraints unless removal is explicitly required to fix the
  identified failure class.
- Propose the smallest change set that fixes the identified failure class
  without broadening unrelated behavior.
- Draft each added or changed bullet with one primary obligation and an explicit
  phase when practical.
- Keep proposed rule or contract text as short as possible while preserving
  enforceability and required protections; state the positive invariant, and add
  prohibitions only for plausible failure modes or preserved protections.
- Use machine-oriented wording and avoid example lists unless needed to
  disambiguate behavior.
- Before output, reject any proposed rule change that adds examples, category
  lists, mechanisms, or explanatory clauses unless they are required to prevent
  the identified failure class without changing unrelated behavior.
- Reject wording that is vague, duplicative, contradictory, too broad, too
  narrow, too long, example-driven, or likely to increase routine rework.
- If deterministic, testable behavior can prevent or detect the failure class
  more reliably than prompt text, recommend the narrowest script or
  executable-helper contract instead of, or alongside, rule text.
- If the update removes a protection, category, prohibition, exception, trigger,
  constraint, or required check, classify the removal as intentional, preserved
  elsewhere, or required to fix the failure class.
- Do not mutate files unless the user explicitly asks to apply the named change.

### Boundaries

- Use this skill for rule, instruction, policy, prompt-line, skill-rule,
  automation-prompt, and helper-contract update recommendations caused by a
  concrete failure or miss.
- If the user only wants a general prompt rewrite, use
  `$ceratops-prompt-optimizer`.
- If the user asks only for current-state diagnosis, answer the diagnosis
  instead of forcing a rule rewrite.

### Workflow

1. Identify the concrete failure or miss, observed incorrect behavior, and
   reusable failure class.
2. Inspect the current text and helper contracts from all involved governing
   sources before proposing changes.
3. Identify the current text or helper contract that allowed, failed to prevent,
   or should own the fix.
4. Answer what change would have prevented the miss, where it belongs, how it
   avoids recurrence, and whether existing text conflicts with the fix.
5. Draft the exact changed, removed, and resulting rule or contract lines,
   including any deterministic helper contract when prompt text is not the right
   control.
6. Before completion, verify the proposal against the involved sources and
   reject duplicate, contradictory, protection-dropping, overbroad, or
   non-minimal wording.

## Done When

### Completion Gate

- The response identifies the failure or miss, reusable failure class, involved
  sources, and target artifact, or states the missing evidence blocking that
  identification.
- The proposal includes every full current rule or contract line it changes or
  removes, and every full resulting rule or contract line it adds or keeps after
  the change.
- The proposal fixes only the identified failure class and does not broaden
  unrelated behavior.
- Any removed protection is classified as intentional, preserved elsewhere, or
  required.
- Any contradiction or source-of-truth drift found in involved sources is named
  with the smallest proposed repair.
- No file was changed unless the user explicitly asked to apply the named
  change.

### Output Contract

Report only:

- changed files, or `none` when proposing only
- failure or miss
- reusable failure class
- involved sources and target artifact
- full current rules or contract lines changed or removed
- full resulting rules or contract lines added or kept
- retained behavior from prior rules or retired rule-update workflow
- intentionally retired behavior
- removed or preserved protections
- unresolved contradiction, blocker, or retained risk
- whether the change could materially increase recurring or avoidable credit
  usage
