# Pause Action

## Goal

Stop current same-thread execution at the next safe agent boundary and emit the
smallest sufficient checkpoint for a minimally verified manual resume.

## Inputs

- The task goal and completion standard already present in the current thread.
- The last fully completed atomic action.
- The first not-yet-started action.
- Any known running, background, or partially completed state.
- The local Git worktree or worktrees whose state must remain unchanged.

Infer these inputs only from already-loaded same-thread context.

## Constraints

- After invocation, do not start another task action. The only permitted tool
  call is the checkpoint helper used to capture local Git state.
- Do not reread context, inspect files manually, clean up, update the plan, or
  create a persistent checkpoint artifact.
- Do not cancel, wait for, or modify background work; record it in
  `active_state`.
- Treat the checkpoint as an execution boundary, not task completion.
- Do not waive checks or closure work already required by the paused task.
- Do not claim unchanged external, ignored, non-Git, or submodule state.
- Stop only at an agent boundary: after the current tool call or atomic action
  returns, before starting another action.
- Do not claim byte-exact continuation of in-process model or tool execution.
- If a foreground tool call is still running, wait only until it returns control
  or record it as active if the runtime already exposed a stable background
  handle.
- If a tool call was interrupted or its result is unknown, record that
  uncertainty; do not infer success or rollback.

## Helper Contract

- (D) From the installed `ceratops-task-lifecycle` skill folder, run
  `python scripts/pause_state.py capture --repo <worktree>` once, repeating
  `--repo` in the same call for each in-scope local Git worktree.
- (D) Use the returned token without decoding it. If the helper returns
  `UNAVAILABLE`, set `state_scope` and `state_token` to `unavailable`.

## Workflow

### 1. Freeze At The Boundary

- Finish only the atomic action already in flight.
- Start no follow-up tool call, inspection, validation, cleanup, plan update, or
  next stage.
- Identify the last completed atomic action and the first action not started.
- Record any known running, background, partial, or uncertain tool state.

### 2. Capture Local Git State

- Invoke the helper once for all in-scope local Git worktrees.
- Set `active_state` to `none` when no unresolved running, background, or
  partial action is known.

### 3. Emit The Checkpoint

- Return only the checkpoint defined below.
- End the turn immediately after the checkpoint.

## Completion Gate

- No post-invocation task action was started.
- The checkpoint identifies one completed boundary, one next action, and known
  active state.
- The checkpoint includes one helper-produced token for every in-scope local
  Git worktree or explicitly reports that validation is unavailable.

## Output Contract

```text
PAUSE_CHECKPOINT
goal: <one-line task goal>
last_completed: <last fully completed atomic action>
next_action: <first action not yet started>
active_state: <none or known unresolved state>
state_scope: <local_git or unavailable>
state_token: <helper token or unavailable>
resume: $ceratops-task-lifecycle manual-resume
```
