---
name: ceratops-task-pause
description: Stop an active same-thread execution at the next safe agent boundary and emit a compact checkpoint for manual resume without pause-induced reads or validation. Use only when the user explicitly invokes this skill during ongoing work.
---

# Ceratops Task Pause

## Goal

Pause current execution with the smallest sufficient same-thread checkpoint.

## Context

### Inputs To Capture

- The last fully completed atomic action.
- The first not-yet-started action.
- Any known running, background, or partially completed state.

Infer these inputs only from already-loaded same-thread context.

## Constraints

### Skill-Specific Rules

- After invocation, do not start another task action or tool call.
- Do not reread context or state, validate, clean up, update the plan, or create
  a persistent checkpoint artifact.
- Do not cancel, wait for, or modify background work; record it in
  `active_state`.
- Treat the checkpoint as an execution boundary, not task completion.
- Do not waive checks or closure work already required by the paused task.

### Boundaries

- Use only by explicit invocation during active work in the current thread.
- This skill does not interrupt a tool or command mid-call; it stops at the
  first agent boundary where the invocation can be processed.
- Use task-lifecycle handoff actions for cross-thread continuation.
- Use task-lifecycle recovery behavior when no valid checkpoint exists.

## Workflow

### 1. Freeze Execution

- Use current same-thread context to identify the exact completed boundary and
  next action.
- Start no additional work.

### 2. Emit The Checkpoint

- Set `active_state` to `none` when no unresolved running, background, or
  partial action is known.
- Return only the checkpoint defined below.

## Done When

### Completion Gate

- No post-invocation task action was started.
- The checkpoint identifies one completed boundary, one next action, and known
  active state.

### Output Contract

```text
PAUSE_CHECKPOINT
last_completed: <last fully completed atomic action>
next_action: <first action not yet started>
active_state: <none or known unresolved state>
resume: $ceratops-task-lifecycle manual-resume
```
