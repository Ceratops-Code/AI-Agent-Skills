---
name: ceratops-rework-analysis
description: Analyze recent Codex runs for deterministic rework causes that could be prevented or reduced by better prompts, rules, skills, helpers, or validation gates.
---

# Ceratops Rework Analysis

## Goal

Find rework in recent thread runs that was preventable, catchable earlier, or reducible by deterministic producer controls, then recommend the smallest control that would materially reduce recurrence.

## Context

### Inputs To Capture

- Target thread or session. Use the current thread unless the user names a concrete thread title, thread id, or session file.
- Window under review. Use the user's `last N runs`; otherwise use visible recent context or the last five assistant runs.
- Evidence source: visible context, `$CODEX_HOME/session_index.jsonl`, `$CODEX_HOME/sessions/`, or `$CODEX_HOME/archived_sessions/`.
- Whether the task is analysis-only or the user explicitly asked to apply a named control change.

Ask for the missing title, id, or session file only when the target thread cannot be identified.

## Constraints

### Skill-Specific Rules

- Count an issue as deterministic rework only when the failure was knowable from available instructions, local evidence, stable contracts, tool output, or a cheap targeted check before the repeated work happened.
- Exclude ordinary model mistakes unless a concise durable producer control would sharply reduce the same class recurring.
- Treat repeated artifact creation, duplicated investigation, avoidable validation failure, stale cleanup, reversions, user correction, and unnecessary spend as candidate rework.
- Prefer controls in this order: narrow prompt/rule/skill/automation wording, deterministic helper check, preflight guard, validation gate, then docs or examples.
- Do not propose broad best-practice refreshes, large instruction rewrites, or high-maintenance controls unless smaller controls are demonstrably inadequate.
- When the recommendation would edit instructions, skills, automations, or helpers, provide the exact proposed change and wait for explicit approval unless the user already asked to apply it.

### Boundaries

- Use this skill for avoidable rework, repeated artifact iterations, failed output loops, stale cleanup, and producer-failure analysis.
- If the active issue is one unresolved bug, use `$ceratops-fixloop-breaker` or `$ceratops-task-execute-in-stages` first.
- If the user already knows the specific rule to change, use `$ceratops-produce-rules-fix`.

### Workflow

1. Build a compact timeline for each inspected run: goal, touched artifacts, checks, corrections, retries, and final state.
2. Mark each rework episode and the earliest point it could have been prevented or detected.
3. Identify the producer that allowed the invalid state: prompt, rule, skill, automation, helper, validation, workflow habit, or external dependency.
4. Choose the lowest-maintenance control that would have prevented or sharply reduced the episode.
5. Separate confirmed findings from plausible but unverified risks.

## Done When

### Completion Gate

- The inspected window and evidence source are stated.
- Each finding ties to a concrete episode, producer cause, earliest prevention point, recommendation type, and expected impact.
- Ordinary model failures that could be confused with deterministic rework are explicitly excluded.
- Any missing evidence or target-thread blocker is stated.

### Output Contract

Start with one of:

- `No deterministically avoidable rework found in the inspected runs.`
- `Found deterministically avoidable or reducible rework.`
- `Blocked: <specific missing evidence or target>.`

Then report only findings, recommendations, excluded ordinary failures, and important evidence limits.
