# Closure Check Action

## Goal

Give a concise, evidence-based answer about whether required work remains at
the end of a thread, session, or task.

## Context

### Inputs To Capture

- The complete same-thread work history from the beginning of the thread and
  the authorized work scope.
- Completed actions, directly touched artifacts, and claims already made.
- Touched repos, worktrees, branches, commits, PRs, automation folders,
  generated or runtime artifacts, active goals, failed commands, and warnings.
- Thread-raised proposals, findings, questions, warnings, deferred decisions,
  and follow-ups that may still affect closure.

Infer missing inputs from complete same-thread context and targeted local state
before asking.

## Constraints

### Skill-Specific Rules

- Advisory by default; do not mutate state unless the user explicitly asks for
  that exact action.
- Scope the check from the beginning of the thread across the current thread's
  authorized work and every directly touched artifact.
- When closure follows a mutating or multi-entity task, classify touched,
  discovered, or plausibly affected artifacts, external entities, and side
  effects as active, intentionally retained, stale-in-scope, stale-out-of-scope,
  blocker, or unverified; do not fix stale-in-scope items during closure-check
  unless explicitly asked.
- Use same-thread context and existing action evidence first; inspect files or
  run commands only when needed to support or limit the closure claim.
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

- From the beginning of the thread, identify all completed actions, artifacts
  actually touched, retained state, deferred follow-ups, and claims actually
  made.
- Treat every same-thread touched artifact, retained state, deferred follow-up,
  and claim as part of the closure scope.

#### 2. Identify Evidence Targets

- From same-thread context, identify touched or claimed state relevant to
  closure, including local, external, generated, runtime, warning, and follow-up
  state only when present.
- Use the selected or recently completed action's Done When and Output Contract
  as closure evidence targets; do not re-run full action validation unless those
  gates were not checked, became stale, or are needed for the closure claim.

#### 3. Gather Targeted Evidence

- Reuse fresh same-thread evidence first.
- Run only targeted checks needed to classify required work, blockers,
  retained state, stale state, warnings, unverified claims, and touched git
  repos' branch, cleanliness, staged/unstaged/untracked state, and unpushed
  commits.

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
  unverified states from any same-thread touched artifact are reported.
- Any no-required-work-left claim is limited to evidence actually checked.
- No mutation was performed unless explicitly requested.

### Output Contract

First line must be exactly one of:

- No required work left.
- Required work remains.
- Blocked.
- Unclear from checked evidence.

Then include only relevant concise items:

- checked scope, only when it limits the answer
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

`Use $ceratops-task-lifecycle closure-check to answer whether anything is left to do from
the beginning of this thread, scoped to the work already authorized and touched
here.`
