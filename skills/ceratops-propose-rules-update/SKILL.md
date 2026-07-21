---
name: ceratops-propose-rules-update
description: Diagnose instruction-system failures and design compact, regression-safe rule, workflow, or helper changes. Use when asked to add, change, reconcile, or review AGENTS.md rules, skill instructions, automation prompts, helper contracts, policy lines, or interactions between global and local instructions.
---

# Ceratops Propose Rules Update

## Goal

Produce the smallest safe behavioral correction, not the smallest text patch.
Every confirmed failure must change the controlling instruction surface or its
deterministic enforcement.

Read [references/rule-design.md](references/rule-design.md) before drafting.

## Constraints

### Boundaries

Use this skill for instruction-system changes. Route general prompt rewrites to
`$ceratops-prompt-optimizer`; answer diagnosis-only requests without forcing a
rule change.

## Workflow

1. Reconstruct the failed decision from current evidence. Identify the active
   instruction stack, chosen behavior, and required behavior without assuming a
   relevant rule, single cause, or owning artifact exists.
2. Inspect exact current text from every involved source. For global and local
   instructions, determine scope and precedence before evaluating interaction.
3. Resolve structured history before drafting. For global rules, check
   `$CODEX_HOME/AGENTS.history.json`; for local rules, check
   `AGENTS.history.json` beside their `AGENTS.md`. From this skill directory,
   run `python scripts/rule_history.py lookup --history <history> --rules
   <rules> ID...`, repeating both options for an interacting instruction stack.
   Query relation targets when adding a rule. If the applicable history does
   not exist, use targeted source history and state that recorded behavioral
   history was unavailable.
4. Compare a local correction with a structural or non-rule correction. Select
   by prevention of the failure, regression safety, behavioral scope, and
   complexity; textual minimality does not win automatically.
5. Draft under the rule-design contract. Resolve interacting guidance inside
   the candidate and identify every intentional behavior change.
6. Replay the current failure and relevant recorded history. Reject a candidate
   that leaves the failed decision possible or regresses a recorded outcome.
7. Report the selected correction, material alternative, regression result,
   and uncertainty. Mutate only the exact authorized artifacts.

## Applying an approved change

Append history in each changed rule scope, naming changed rules and direct
relation neighbors. Record causal and regression evidence with validation. Run
the source's rule checker when one exists; its history binding must reject
unrecorded rule changes.

## Iterative optimization

Use `scripts/iteration_controller.py` when repeated optimization is requested or
one-pass comparison remains materially uncertain. The controller owns numbering,
artifact hashes, and stopping state; it does not judge semantic quality.

For each issued iteration, produce one candidate and one assessment. Compare it
with the original, champion, and regression evidence, then submit `improved` or
`no-improvement`. Improvement resets the streak. Stop when the controller
reports 200 iterations or ten consecutive non-improvements. Never claim state
the controller did not report.

## Completion gate

A proposal is complete only when it prevents the current recorded failure,
preserves earlier recorded behavior unless intentionally superseded, and is
better than the current state and material alternative. Otherwise change the
intervention or report the unresolved decision point.

## Output

### Output Contract

Report only the selected exact change, its decision and regression evidence,
and unresolved impact.
