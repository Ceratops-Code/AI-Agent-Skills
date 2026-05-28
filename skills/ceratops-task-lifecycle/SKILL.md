---
name: ceratops-task-lifecycle
description: Route Ceratops task execution, same-thread resume, new-thread handoff, and closure checks. Use closure-check when the user asks whether anything remains, whether we are done, or what remains.
---

# Ceratops Task Lifecycle

## Goal

Route task execution, interrupted-thread resume, thread handoff, and closure
check work to the narrowest action reference. Keep one task-workflow skill
instead of separate skill identities for staged execution, same-thread resume,
whole-task handoff, side-task handoff, and closure assessment.

## Context

### Action References

- Execute a substantial task in stages: `references/execute-in-stages.md`
- Resume an interrupted current-thread task: `references/manual-resume.md`
- Create a whole-task new-thread handoff: `references/full-handoff.md`
- Create a side-task new-thread handoff: `references/side-task-handoff.md`
- Check whether required work remains: `references/closure-check.md`

### Inputs To Capture

- Target task, current thread state, desired completion state, and any
  user-stated action.
- Whether the work is staged execution, same-thread resume, whole-task handoff,
  side-task handoff, or closure check.
- Current local or external entities that constrain the selected action.

Infer missing inputs from recent thread context and local state before asking.

## Constraints

### Skill-Specific Rules

- Load only the selected action reference unless the current action explicitly
  hands off to another action.
- Use the selected action reference as the source of truth for workflow,
  evidence refresh, completion gate, and output contract.
- Keep staged task execution, same-thread resume, whole-task handoff, side-task
  handoff, and closure check inside this router and its `references/` files; do
  not introduce alias skills or old-name shims.
- If action identity is ambiguous, choose the action that matches the user's
  immediate requested output or next state.

### Boundaries

- Use `execute-in-stages` for substantial tasks with multiple justified stages
  or multiple plausible solution paths.
- Use `manual-resume` only when the work stays in the current thread and should
  resume from current local state after a manual stop, pause, restart, or crash.
- Use `full-handoff` only when the user wants to move the whole task into a
  different thread.
- Use `side-task-handoff` only when the user wants to spin off a newly
  discovered sub-issue into a different thread.
- Use `closure-check` when the user asks whether anything is left to do at the
  end of a thread, session, or task.

### Workflow

#### 1. Classify The Action

- Select `execute-in-stages` when the task should be handled end to end with
  diagnosis, simplest credible fix, justified stage progression, and closure.
- Select `manual-resume` when the task was interrupted in this thread and should
  continue from current state without replaying completed work.
- Select `full-handoff` when the output should be one paste-ready prompt for
  moving the entire task into a new thread.
- Select `side-task-handoff` when the output should be one paste-ready prompt
  for a side task while the main task stays separate.
- Select `closure-check` when the output should be a concise evidence-based
  answer about required work, blockers, retained state, unverified claims, and
  reasonable next actions.

#### 2. Execute The Selected Action

- Read the matching file under `references/`.
- Follow that action's inputs, constraints, workflow, completion gate, and
  output contract.
- If the selected action discovers another action owns the remaining work,
  switch to that action reference and report the handoff reason only when it
  changes the user's next step.

#### 3. Close From Action Evidence

- Match final claims to the exact current state, prompt content, local checks,
  or external evidence actually verified.
- Report only the retained state, blockers, unresolved debt, or unverified items
  required by the selected action.

## Done When

### Completion Gate

- The selected action reference was followed or the task was explicitly blocked
  before action execution.
- Any cross-action handoff used another reference in this router rather than a
  standalone skill identity.
- Completion, resume, handoff, and closure claims are limited to evidence
  actually checked or fresh same-task evidence that still applies.

### Output Contract

Report only:

- selected action and final outcome, unless the selected action requires a
  prompt-only output
- unresolved blockers or non-blocking debt
- intentionally retained items with reasons
- anything important not verified

### Example Invocation

`Use $ceratops-task-lifecycle execute-in-stages to handle this substantial task end to
end, trying the simplest standard fix first and asking before any complex path.`
