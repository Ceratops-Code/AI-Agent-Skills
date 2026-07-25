# Manual Resume Action

## Goal

Resume a same-thread task from current local state after a manual pause,
cancellation, restart, or crash.

## Context

### Inputs To Capture

- The current task goal and completion standard from the recent thread.
- The latest `PAUSE_CHECKPOINT`, when present.
- Its `state_scope` and opaque `state_token`.
- Any user statement about what changed since the stop.
- The last clearly completed stage and the next likely stage.
- The local repos, files, artifacts, PRs, images, or automations that were in
  scope.

Infer missing inputs from the recent thread and local state before asking.

## Constraints

### Skill-Specific Rules

- Treat recent thread context plus current local state as the primary sources of
  truth, even after a restart, unless local evidence forces a broader rebuild.
- Treat the latest same-thread `PAUSE_CHECKPOINT` with `active_state: none`,
  `state_scope: local_git`, and a valid helper token as sufficient resume state
  when the user reports no intervening external change.
- On that checkpoint fast path, run only
  `python "$env:CODEX_HOME\skills\ceratops-task-lifecycle\scripts\pause_state.py"
  verify <state_token>`. If it returns `UNCHANGED`, execute `next_action`
  immediately without rereading the thread, inspecting files manually,
  recomputing the plan, rerunning checks, or restating the checkpoint.
- Fall back to recovery only when the checkpoint is absent or malformed,
  `active_state` is not `none`, state validation is unavailable or changed, the
  user reports an external change, or an active instruction requires fresh
  evidence for the next action.
- Assume nothing external changed unless the user says it did or local evidence
  suggests otherwise.
- Do not restart the whole task from zero if the next justified stage can be
  identified cheaply.
- Re-check only entities that were touched, plausibly affected, or needed for
  the next stage or final verification.
- If the next viable option is complex, invasive, nonstandard, or
  high-maintenance, stop and ask before taking it.
- Do not ask for credentials unless the resumed task actually requires them.
- Do not add checks because execution was paused; retain checks already required
  by the original task.

### Boundaries

- Use this action only when the work stays in the current thread and Codex
  should resume from current local state after a manual stop, pause, restart, or
  crash.

### Workflow

#### 1. Re-Anchor The Task

- If the checkpoint fast path applies, run its single helper verification. On
  `UNCHANGED`, skip the rest of this step and Step 2 and execute `next_action`.
- Read only the recent thread tail needed to recover the goal, the latest
  confirmed state, and any unfinished stage.
- Restate the next justified stage internally before acting.

#### 2. Refresh Narrow Local State

- If helper verification returns `CHANGED`, inspect only the reported worktree
  or worktrees before continuing.
- Inspect only the touched or plausibly affected local state: git status,
  changed files, generated outputs, temp paths, local installs, or runtime
  state.
- Refresh remote or external state only if the task depends on it or it may have
  changed while stopped.

#### 3. Continue From The Next Justified Stage

- Resume at the next unfinished stage rather than replaying already-completed
  work.
- Reuse prior verified results unless your own actions, elapsed time, or
  external changes make them stale.
- Fix newly discovered low-risk in-scope issues immediately.

#### 4. Finish With Risk-Based Closure

- Before completion, run the narrowest justified closure pass for the task.
- Remove low-risk stale items that are no longer needed.
- Report only unresolved blockers, unresolved non-blocking debt, intentionally
  retained items, and anything important not verified.

## Done When

### Completion Gate

- Verify the resumed task reached the next justified stable state or the
  requested completion state.
- Verify any re-checked local or remote entities are still consistent with the
  final answer.

### Output Contract

Report only:

- the resumed stage or completed outcome
- any detected divergence from the earlier assumed state
- unresolved blockers or non-blocking debt
- intentionally retained items with reasons
- anything important not verified

### Example Invocation

`Use $ceratops-task-lifecycle manual-resume to resume this interrupted task in the
current thread from current local state after a stop, restart, or crash. Nothing
changed externally.`
