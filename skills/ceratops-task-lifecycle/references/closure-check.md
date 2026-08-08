# Closure Check Action

## Goal

At the end of a thread, session, or task, give a concise, evidence-based answer
about whether required work remains and include the credit-savings analysis
result.

## Context

### Inputs To Capture

- Closure mode: full-thread, or `incremental closure` beginning after the
  previous completed closure; the authorized work scope; and any unresolved or
  intentionally retained state at the boundary.
- Completed actions, directly touched artifacts, and claims already made.
- Touched repos, worktrees, branches, commits, PRs, automation folders,
  generated or runtime artifacts, active goals, failed commands, and warnings.
- Thread-raised proposals, findings, questions, warnings, deferred decisions,
  and follow-ups that may still affect closure.

Infer missing inputs from the selected window, carried boundary state, and
targeted local state before asking.

## Constraints

### Skill-Specific Rules

- Closure invocation authorizes credit-controller state, retained machine
  evidence, and transient artifacts only inside the verified task temp root.
  Finalization must remove only controller-owned transients; report retained
  evidence for later owning-task cleanup. Remain advisory and ask before any
  other mutation.
- For an `incremental closure`, scope new work and credit analysis to completed
  runs after the previous completed closure and carry forward only unresolved
  or intentionally retained boundary state; otherwise scope from the beginning
  of the thread.
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
  [--temp-root PATH] [--cleanup-temp PATH]`; it snapshots only named targets,
  removes only exact temporary artifacts that its safety contract validates
  under `--temp-root`, and emits compact cleanup evidence.
- Pass `--cleanup-temp` only for an exact artifact that selected-thread evidence
  proves this task created; otherwise omit it and report the cleanup.
- Do not rerun facts reported by the snapshot. Query goal state only when
  same-thread evidence shows a goal was created or active, and run additional
  diagnostics only for snapshot state that remains unresolved.

#### 4. Scan Relevant Thread Follow-Ups

- Scan task-relevant conversation context for unresolved proposals, findings,
  questions, warnings, or deferred decisions.
- Classify each as required, optional, superseded, or irrelevant.

#### 5. Include Credit-Saving Analysis

- Invoke `$ceratops-credit-savings-analysis` for the current thread and
  selected closure window using `full-analysis`. Prepare the controller once,
  use its shared evidence bundle for every fixed surface and internal
  synthesis, finalize it, and include every confirmed finding or the exact
  blocker under `Credit savings`.

#### 6. Classify Closure State

- Classify relevant state as required remaining work, blocker, intentionally
  retained, optional cleanup, stale or out-of-scope, unverified, or no longer
  relevant.

#### 7. Answer From Checked Evidence

- Keep the answer concise and omit routine command logs, process narration, and
  ignored or generated validation artifacts unless they failed, are stale in
  scope, affect correctness, or the user explicitly requested their cleanup.

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
- The credit analysis finalized the exact selected window through all fixed
  surfaces and internal synthesis. An unfinalized, surface-limited, or
  incompletely classified result is a blocker.
- No mutation occurred except creation and helper-validated cleanup of
  task-required temporary artifacts inside the verified task temp root, unless
  the user explicitly requested another exact action.

### Output Contract

Return only relevant concise bullets:

- checked scope, labeled `Incremental closure` when that mode applies, only when
  it limits the answer
- required next actions
- blockers
- uncommitted or unpushed changes
- intentionally retained state with reasons
- stale or out-of-scope state
- important unverified claims
- relevant forgotten follow-ups
- optional cleanup that was unsafe or unauthorized to perform
- `Credit savings`: the required `$ceratops-credit-savings-analysis` result

If no listed item applies, return only `- No unresolved items.`

Omit routine command logs, process narration, and ignored or generated
validation artifacts unless they failed, are stale in scope, affect
correctness, or the user explicitly requested their cleanup.

### Example Invocation

```text
Use $ceratops-task-lifecycle closure-check to answer whether anything is left to
do from the beginning of this thread, scoped to the work already authorized and
touched here.
```
