# Closure Check Action

## Goal

At the end of a thread, session, or task, give a concise, evidence-based answer
about whether required work remains and include the credit-savings analysis
result.

## Context

### Inputs To Capture

- The user-stated closure boundary, or the beginning of the thread when none
  is stated; the authorized work scope; and any unresolved or intentionally
  retained state at the boundary.
- Completed actions, directly touched artifacts, and claims already made.
- Touched repos, worktrees, branches, commits, PRs, automation folders,
  generated or runtime artifacts, active goals, failed commands, and warnings.
- Thread-raised proposals, findings, questions, warnings, deferred decisions,
  and follow-ups that may still affect closure.

Infer missing inputs from the selected window, carried boundary state, and
targeted local state before asking.

## Constraints

### Skill-Specific Rules

- Advisory by default; do not mutate state unless the user explicitly asks for
  that exact action.
- When the user states a closure boundary, scope new work and credit analysis
  to that window and carry forward only unresolved or intentionally retained
  boundary state; otherwise scope from the beginning of the thread.
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

- From the selected closure window, identify completed actions, artifacts
  actually touched, retained state, deferred follow-ups, and claims actually
  made.
- Include pre-window state only when it was unresolved or intentionally
  retained at the selected boundary.

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
- (D) For each touched local Git repository that needs refreshed closure
  evidence, run `python scripts/closure_snapshot.py --repo PATH
  [--fetch-remote NAME] [--release-branch BRANCH
  --release-upstream REF] [--task-worktree PATH --task-branch BRANCH]
  [--temp-root PATH]`; it checks only the named targets and emits one compact
  non-destructive snapshot.
- Do not rerun facts reported by the snapshot. Query goal state only when
  same-thread evidence shows a goal was created or active, and run additional
  diagnostics only for snapshot state that remains unresolved.

#### 4. Scan Relevant Thread Follow-Ups

- Scan task-relevant conversation context for unresolved proposals, findings,
  questions, warnings, or deferred decisions.
- Classify each as required, optional, superseded, or irrelevant.

#### 5. Include Credit-Saving Analysis

- Invoke `$ceratops-credit-savings-analysis` for the current thread, reuse fresh
  closure evidence, and include its required result under `Credit savings`.
- Obtain model-call inventory in one `model-call-ledger.py --closure
  [--last-runs N]` invocation. For a prior-closure boundary, set `N` to the
  completed runs strictly after that closure; exclude the boundary and active
  runs. Omit `--last-runs` only when the user states no boundary, use the
  current thread ID when available or its exact session path otherwise, and
  create no temporary ledger.
- (D) Before reporting, run the same helper once more for the same source and
  window with `--classifications PATH`; use its validated category totals,
  then remove the caller-owned classification file.
- Treat the ledger as evidence, not analysis. A zero-finding result is invalid
  unless selected session rows support dismissal of every visible candidate
  signal and every required result category; report an analysis blocker when
  that semantic review is incomplete.

#### 6. Classify Closure State

- Classify relevant state as required remaining work, blocker, intentionally
  retained, optional cleanup, stale or out-of-scope, unverified, or no longer
  relevant.

#### 7. Answer From Checked Evidence

- Keep the answer concise and omit routine command logs or process narration.

## Done When

### Completion Gate

- The checked closure scope is clear.
- Required remaining work and blockers are not omitted.
- Uncommitted, unpushed, retained, stale, warning, forgotten-follow-up, and
  unverified states from the selected window and carried boundary state are
  reported.
- A response that reports no unresolved items is supported by checked evidence.
- A completed `$ceratops-credit-savings-analysis` result or its blocker is
  included under `Credit savings`; ledger evidence alone does not satisfy this
  gate.
- The credit analysis used category totals validated by the existing ledger
  helper; an unvalidated classification is a blocker.
- No mutation was performed unless explicitly requested.

### Output Contract

Return only relevant concise bullets:

- checked scope, only when it limits the answer
- required next actions
- blockers
- uncommitted or unpushed changes
- intentionally retained state with reasons
- stale or out-of-scope state
- important unverified claims
- relevant forgotten follow-ups
- optional cleanup
- `Credit savings`: the required `$ceratops-credit-savings-analysis` result

If no listed item applies, return only `- No unresolved items.`

Omit routine command logs and process narration.

### Example Invocation

```text
Use $ceratops-task-lifecycle closure-check to answer whether anything is left to
do from the beginning of this thread, scoped to the work already authorized and
touched here.
```
