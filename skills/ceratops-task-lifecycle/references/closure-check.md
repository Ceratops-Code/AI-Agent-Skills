# Closure Check Action

## Goal

At the end of a thread, session, or task, prioritize discovering forgotten
open loops and task leftovers, then give a concise, evidence-based answer about
what still needs attention.

## Context

### Inputs To Capture

- Closure mode: full-thread, or `incremental closure` beginning after the
  previous completed closure; the authorized work scope; and any unresolved or
  intentionally retained state at the boundary.
- Completed actions, directly touched artifacts, and claims already made.
- Touched repos, worktrees, branches, commits, PRs, automation folders,
  generated or runtime artifacts, active goals, failed commands, and warnings.
- User requests, preferences, corrections, questions, and desired behavior, plus
  assistant proposals, questions, warnings, and next steps that may remain open.

## Constraints

### Skill-Specific Rules

- Remain advisory and ask before any mutation outside the exact task-temp
  cleanup authorized below.
- For an `incremental closure`, scope new work to completed runs after the
  previous completed closure and carry forward only unresolved or intentionally
  retained boundary state; otherwise scope from the beginning of the thread.
- When closure follows a mutating or multi-entity task, classify touched,
  discovered, or plausibly affected artifacts, external entities, and side
  effects as active, intentionally retained, stale-in-scope, stale-out-of-scope,
  blocker, or unverified; do not fix stale-in-scope items during closure-check
  unless explicitly asked.
- Spend most of the closure review on semantic discovery of forgotten requests,
  proposals, unanswered questions, and undecided options.
- Reuse fresh same-thread evidence and deterministic action results. Run a check
  only when evidence is absent, stale, contradictory, or needed to classify a
  plausible leftover.
- Do not infer closure from related or partial implementation, an advisory
  answer, or silence. A direction to defer execution does not abandon the
  underlying option or decision.
- After semantic discovery, sweep only touched scopes and the verified task temp
  root for plausible task-created residue.
- Reconcile every material failed command, gate, retry, interruption, and manual
  recovery in the selected closure window. Classify its cause as target-system,
  workflow/helper, agent/tool-use, or external interruption; name the earliest
  deterministic prevention or detection owner. Treat an instruction that did
  not enforce the behavior in the run as an enforcement gap, not prevention.
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

#### 2. Find Forgotten User Open Loops

- Make a semantic pass over the selected conversation for user requests,
  preferences, corrections, questions, or desired behavior that was deferred,
  partly addressed, or left without a decision.
- Compare each candidate with later context. Treat it as closed only when later
  context establishes completion of the exact behavior, cancellation,
  supersession, an explicit user decision to leave it unresolved, or
  irrelevance.
- Do not treat a request for advice or a direction to defer execution as a
  decision to abandon the underlying option.

#### 3. Find Forgotten Assistant Open Loops

- Make a separate semantic pass for assistant proposals, alternatives,
  unanswered questions, warnings, or suggested next steps that still materially
  affect the user's stated desired state.
- Report an item only when later context provides no completion, rejection,
  supersession, explicit user decision, or reason it became irrelevant.
- Before state checks, ask internally: "Besides the items already found, what
  else was asked, proposed, or left undecided?" Reconcile every additional
  item against both passes.

#### 4. Sweep Narrow Task Leftovers

- Use the selected or recently completed action's Done When and Output Contract,
  together with fresh same-thread deterministic results, as disposition
  evidence. Do not rerun action validation for properties that evidence proves.
- Inspect only touched scopes and the verified task temp root when evidence is
  missing, stale, contradictory, or leaves plausible task-created residue
  unclassified. Cover temporary artifacts and unresolved Git, worktree,
  generated, runtime, controller, goal, warning, or external state only when the
  selected window makes that state plausible.
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

#### 5. Classify Closure State

- Classify relevant state as required remaining work, blocker, intentionally
  retained, optional cleanup, stale or out-of-scope, unverified, or no longer
  relevant.

#### 6. Answer From Checked Evidence

- Keep the answer concise and omit routine command logs, process narration, and
  ignored or generated validation artifacts unless they failed, are stale in
  scope, affect correctness, or the user explicitly requested their cleanup.

## Done When

### Completion Gate

- The checked closure scope is clear.
- Both origin-separated semantic passes and the final internal open-loop
  question are complete.
- Every material failure in the closure window is classified with its earliest
  deterministic prevention or detection owner.
- Every still-relevant user-origin open loop and material assistant-origin open
  loop without a later terminal disposition is reported. Related or partial
  implementation, advisory answers that leave a choice open, silence, and
  execution-only deferrals are not terminal dispositions.
- Uncommitted, unpushed, retained, stale, warning, plausible task-temp, and
  unverified states from the selected window and carried boundary state are
  classified and reported when unresolved. Fresh deterministic evidence was not
  redundantly revalidated.
- A response that reports no unresolved items is supported by checked evidence.
- No mutation occurred outside the exact task-temp cleanup authorized above.

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
- relevant unresolved requests, proposals, questions, warnings, or decisions
- material failures, their cause class, and their earliest deterministic
  prevention or detection owner
- optional cleanup that was unsafe or unauthorized to perform

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
