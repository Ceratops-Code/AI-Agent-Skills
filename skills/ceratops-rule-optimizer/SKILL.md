---
name: ceratops-rule-optimizer
description: Optimize a provided rule or instruction after a failure, gap, or weaker first attempt. Use when the user explicitly invokes $Ceratops-Rule-Optimizer or $ceratops-rule-optimizer to refine rule text, instruction text, policy lines, prompt rules, AGENTS.md rules, SKILL.md instructions, or automation guidance.
---

# Ceratops Rule Optimizer

## Goal

Produce the best durable rule update for the specific original rule and failure context provided by the user or current thread. Prefer concise machine-oriented rule text that prevents the observed failure without becoming too broad, brittle, example-driven, duplicative, or contradictory.

## Context

### Inputs To Capture

- The exact original rule or instruction being changed.
- The concrete failure, gap, use case, or weaker first attempt the update must address.
- Any current governing file or instruction source if the user asks for a file-backed update.
- Whether the user wants only proposed text or also wants the change applied.

Ask one concise question and stop if no adequate failure, gap, use case, or candidate weakness can be identified.

## Constraints

### Skill-Specific Rules

- Before drafting, name the exact governing rule being changed and reject candidates that change a different rule.
- Start from the original rule.
- Run only candidate passes that you record as reportable pass summaries; do not report unrecorded internal reasoning as passes.
- Each candidate must solve the original failure or use case, every concrete shortcoming found in earlier candidates, and every concrete shortcoming in any provided first attempt.
- Each candidate must be durable, specific enough to enforce, broad enough to reuse, concise, non-duplicative, and non-contradictory.
- Reject candidates that are too general, too specific, too vague, too long, too list-heavy, example-driven, or likely to be misinterpreted.
- Accept a candidate only when it is better than the original rule, any provided first attempt, and every previously accepted candidate.
- Stop early after 20 consecutive rejected candidates and use the best accepted candidate so far; otherwise continue until 200 passes.
- Split, add, replace, or remove rules only when that produces a better durable instruction.
- Prefer shorter rules when they preserve the needed protection.

### Boundaries

- Use this skill only for optimizing one or more durable instruction lines from a concrete rule failure, gap, or weak candidate.
- If the task is broad instruction maintenance with file edits, use `$ceratops-produce-rule-update` or the relevant skill-maintenance workflow instead.
- If the user asks only for a current-state diagnosis, answer the diagnosis instead of forcing a rule rewrite.

## Done When

### Completion Gate

- The response identifies the original rule or states the missing input blocker.
- The final proposed rule text is provided exactly.
- Every reported pass summary corresponds to an actually completed and recorded candidate pass.
- The final candidate preserves the original rule intent while addressing the concrete failure, gap, or weaker first attempt.

### Output Contract

Report only:

- the governing rule being changed
- pass summaries, one line per recorded pass
- final proposed rule text
- unresolved blockers or retained risk
