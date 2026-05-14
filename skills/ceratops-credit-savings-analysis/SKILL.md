---
name: ceratops-credit-savings-analysis
description: Analyze recent Codex runs for avoidable credit spend, including deterministic rework, and recommend small prompt, rule, skill, helper, workflow, or validation controls.
---

# Ceratops Credit Savings Analysis

## Goal

Find avoidable credit spend in recent thread runs, including rework and non-rework inefficiencies, then recommend the smallest control that would materially reduce recurrence.

## Context

### Inputs To Capture

- Target thread or session. Use the current thread unless the user names a concrete thread title, thread id, or session file.
- Window under review. Use the user's `last N runs`; otherwise use visible recent context or the last five assistant runs.
- Evidence source: visible context, `$CODEX_HOME/session_index.jsonl`, `$CODEX_HOME/sessions/`, or `$CODEX_HOME/archived_sessions/`.
- Whether the task is analysis-only or the user explicitly asked to apply a named control change.

Ask for the missing title, id, or session file only when the target thread cannot be identified.

## Constraints

### Skill-Specific Rules

- Count spend as avoidable only when it was preventable or reducible from available instructions, local evidence, stable contracts, tool output, or a cheap targeted check.
- Exclude ordinary model mistakes unless a concise durable producer control would sharply reduce the same class recurring.
- Treat rework and other avoidable spend as candidate credit waste, including repeated artifact creation, duplicated investigation, overbroad evidence gathering, stale freshness checks, non-minimal tool or script output, oversized validation, inefficient tool choice, avoidable waits, excessive context loading, stale cleanup, reversions, user correction, and unnecessary spend.
- Use credit-waste signals as prompts for analysis, not mandatory checks; inspect only categories visible in the selected evidence window.
- Prefer controls in this order: narrow prompt/rule/skill/automation wording, deterministic helper check, preflight guard, validation gate, then docs or examples.
- Do not propose broad best-practice refreshes, large instruction rewrites, or high-maintenance controls unless smaller controls are demonstrably inadequate.
- When the recommendation would edit instructions, skills, automations, or helpers, provide the exact proposed change and wait for explicit approval unless the user already asked to apply it.

### Boundaries

- Use this skill for avoidable credit spend, including rework, repeated artifact iterations, failed output loops, stale cleanup, oversized validation, inefficient evidence gathering, and producer-failure analysis.
- If the active issue is one unresolved bug, use `$ceratops-fixloop-breaker` or `$ceratops-task-execute-in-stages` first.
- If the user already knows the specific rule to change, use `$ceratops-propose-rules-update`.

### Workflow

1. Build a compact timeline for each inspected run: goal, touched artifacts, checks, corrections, retries, and final state.
2. Mark each avoidable spend episode and the earliest point it could have been prevented or detected.
3. Identify the producer or workflow choice that allowed the spend: prompt, rule, skill, automation, helper, validation, tool choice, workflow habit, or external dependency.
4. Choose the lowest-maintenance control that would have prevented or sharply reduced the spend.
5. Separate confirmed findings from plausible but unverified risks.

## Done When

### Completion Gate

- The inspected window and evidence source are stated.
- Each finding ties to a concrete episode, cause, earliest prevention point, recommendation type, and expected impact.
- Ordinary model failures that could be confused with avoidable credit spend are explicitly excluded.
- Any missing evidence or target-thread blocker is stated.

### Output Contract

Start with one of:

- `No avoidable credit spend found in the inspected runs.`
- `Found avoidable or reducible credit spend.`
- `Blocked: <specific missing evidence or target>.`

Then report only findings, recommendations, excluded ordinary failures, and important evidence limits.
