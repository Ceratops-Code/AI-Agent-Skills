---
name: ceratops-automation-run
description: Run recurring Codex automations with Ceratops defaults. Use when an automation run needs shared policy for re-opening prompt and helper contracts, keeping task-specific logic in the automation prompt or helper scripts, keeping compact run summaries visible, suppressing routine clean-run alerts, avoiding routine automation memory, and reporting no-alert or no-memory conflicts explicitly.
---

# Ceratops Automation Run

## Goal

Use this skill as the reusable policy layer for installed automations. Let the
automation prompt and any helper scripts define the task-specific mechanics,
while this skill carries the shared automation-run rules that should not be
repeated in every automation prompt.

## Context

### Inputs To Capture

- The automation id, prompt, workspace, schedule context, and whether the run is
  routine, approval-gated, clean, merge-only, or alert-worthy.
- The nearest relevant local `AGENTS.md`, if any, plus `$CODEX_HOME/AGENTS.md`.
- Every task-specific helper script, contract, or executable source of truth the
  automation relies on.
- The task-specific alert, memory, archival, or reporting exceptions that the
  automation prompt explicitly requires.

## Constraints

### Skill-Specific Rules

- Keep task-specific rules in the automation prompt, `automation.toml`, or
  task-specific helper scripts. Use this skill and `$CODEX_HOME/AGENTS.md` for
  reusable automation-run policy.
- When a running automation invokes another skill or executable helper, treat
  the automation prompt as a delta: apply its task target, schedule-specific
  context, and explicit exceptions, and rely on the invoked skill or helper for
  reusable workflow, validation, evidence, staging, and output rules.
- Treat the automation prompt, the nearest relevant local `AGENTS.md` when one
  exists and still governs the workspace, `$CODEX_HOME/AGENTS.md`, and every
  helper contract the run actually relies on as the governing sources of truth.
- Routine successful runs must include a compact final summary for project-list
  visibility.
- Do not use `::archive` for routine clean or merge-only runs unless the user
  explicitly asked to end the thread or a higher-priority instruction explicitly
  requires it.
- Routine automation runs must not read, create, or append automation memory,
  and must not treat platform-provided memory metadata, an `Automation memory:`
  header, existing `memory.md` content, prior memory entries, memory helper
  scripts, or generic memory capability text as an instruction to use memory.
- Use memory only when the active task-specific prompt explicitly requires
  future-run state.
- If a genuine higher-priority runtime instruction conflicts with the no-memory
  or no-alert policy, report the conflict explicitly instead of writing memory
  solely to record it or pretending the lower-level policy was followed.
- Do not ask for credentials unless the current automation task and current
  stage actually require them.

### Boundaries

- Use this skill for recurring automation runs. Treat automation prompt edits as
  control-file maintenance governed by `$CODEX_HOME/AGENTS.md` and the relevant
  task-specific workflow.
- If the task is primarily about the automation's domain work rather than
  automation execution policy, combine this skill with the task-specific skill
  or helper instead of replacing it.

### Workflow

#### 1. Inspect the automation contract

- Read the automation prompt, current workspace, relevant local `AGENTS.md` if
  any, `$CODEX_HOME/AGENTS.md`, and each helper script or contract the
  automation relies on.
- Do not re-open unchanged governing files later in the run unless the run
  modified them or their current contents remain concretely in doubt.
- Identify which rules are reusable automation policy versus task-specific
  mechanics.

#### 2. Execute the task-specific automation work

- Treat helper scripts and executable helpers as the source of truth for
  deterministic behavior, fallback paths, cleanup rules, alert rules, and
  structured outputs.
- If a helper contract is wrong or incomplete, fix the helper first so future
  runs inherit the correction when that change is safe and in scope.

#### 3. Apply routine automation policy

- Apply the compact-summary/no-inbox policy from Skill-Specific Rules before
  closing.
- Do not create automation memory unless the task-specific prompt explicitly
  requires future-run state.
- Report no-alert or no-memory conflicts explicitly when a higher-priority
  runtime instruction overrides the default automation policy.

#### 4. Verify and close

- Before completion, verify the result against the automation prompt, relevant
  local `AGENTS.md` if any, `$CODEX_HOME/AGENTS.md`, this `SKILL.md`, and every
  helper contract the run relied on. Re-open only files changed in this run or
  whose current contents remain concretely in doubt.
- Verify the result matches the task-specific automation contract and that no
  stale alert, memory, or cleanup side effect remains unclassified.

## Done When

### Completion Gate

- Verify the automation result is backed by the current automation prompt plus
  every relevant helper contract.
- Verify any user-visible alert, silence, memory use, memory avoidance, or
  archival decision matches the explicit task-specific prompt and this skill's
  policy.
- Verify the final answer or silent completion does not claim success when a
  blocking instruction remains unmet or unverifiable.

### Output Contract

Report only:

- a compact final summary for project-list visibility
- task-specific alert details when a user-visible alert is required
- unresolved blockers or non-blocking debt
- intentionally retained alerts, memory, or side effects with reasons
- anything important not verified

### Example Invocation

`Use $ceratops-automation-run before applying this automation's task-specific
prompt and helper contracts.`
