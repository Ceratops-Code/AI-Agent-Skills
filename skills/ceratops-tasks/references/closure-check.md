# Closure Check Action

## Goal

Give a concise, evidence-based answer about whether required work remains at
the end of a thread, session, or task.

## Context

### Inputs To Capture

- The latest user request and the authorized work scope for this thread.
- Completed actions, directly touched artifacts, and claims already made.
- Touched repos, worktrees, branches, commits, PRs, automation folders,
  generated or runtime artifacts, active goals, failed commands, and warnings.
- Thread-raised proposals, findings, questions, warnings, deferred decisions,
  and follow-ups that may still affect closure.

Infer missing inputs from recent thread context and targeted local state before
asking.

## Constraints

### Skill-Specific Rules

- Advisory by default; do not mutate state unless the user explicitly asks for
  that exact action.
- Scope the check to the current thread's authorized work and directly touched
  artifacts.
- Use fresh same-thread evidence first; run only targeted checks needed to
  answer accurately.
- Do not claim no required work remains unless required work, blockers,
  retained state, stale state, warnings, uncommitted or unpushed changes, and
  unverified claims were checked or explicitly classified.
- Check for thread-raised follow-ups the user may have forgotten; report
  unresolved ones only if still relevant to closure.
- Separate required work from optional cleanup, intentionally retained state,
  and unverified external state.
- If external state matters and was not freshly checked, say so.
- Do not broaden into unrelated repo health, cleanup, or discovery work.

### Boundaries

- Use this action when the user asks whether anything is left to do at the end
  of a thread, session, or task, including "Is there anything left to do?",
  "anything else left here?", "are we done?", or "what remains?"
- If the user asks to continue, fix, ship, promote, or mutate something, select
  the action that owns that requested state change instead.

### Workflow

#### 1. Establish Closure Scope

- Identify the latest user request, completed actions, artifacts actually
  touched, and claims actually made.
- Limit scope to the current thread's authorized work unless the user expands
  it.

#### 2. Identify Evidence Targets

- Identify touched repos, worktrees, branches, commits, PRs, automation folders,
  generated or runtime artifacts, active goals, failed commands, warnings, and
  direct side effects relevant to closure.

#### 3. Gather Targeted Evidence

- Reuse fresh same-thread evidence first.
- Run only targeted checks needed to classify required work, blockers,
  uncommitted or unpushed changes, retained state, stale state, warnings, and
  unverified claims.

#### 4. Scan Relevant Thread Follow-Ups

- Scan task-relevant conversation context for unresolved proposals, findings,
  questions, warnings, or deferred decisions.
- Classify each as required, optional, superseded, or irrelevant.

#### 5. Classify Closure State

- Classify relevant state as required remaining work, blocker, intentionally
  retained, optional cleanup, stale or out-of-scope, unverified, or no longer
  relevant.

#### 6. Answer From Checked Evidence

- Use the strongest closure claim justified by checked evidence.
- Keep the answer concise and omit routine command logs or process narration.

## Done When

### Completion Gate

- The checked closure scope is clear.
- Required remaining work and blockers are not omitted.
- Uncommitted, unpushed, retained, stale, warning, forgotten-follow-up, and
  unverified states are reported or explicitly out of scope.
- Any no-required-work-left claim is limited to evidence actually checked.
- No mutation was performed unless explicitly requested.

### Output Contract

First line must be exactly one of:

- No required work left.
- Required work remains.
- Blocked.
- Unclear from checked evidence.

Then include only relevant concise items:

- required next actions
- blockers
- uncommitted or unpushed changes
- intentionally retained state with reasons
- stale or out-of-scope state
- important unverified claims
- relevant forgotten follow-ups
- optional cleanup

Omit routine command logs and process narration.

### Example Invocation

`Use $ceratops-tasks closure-check to answer whether anything is left to do in
this thread, scoped to the work already authorized and touched here.`
