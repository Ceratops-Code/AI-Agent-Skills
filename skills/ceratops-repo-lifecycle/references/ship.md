# Ship Action

## Goal

Ship one staged integration branch through GitHub, synchronize local main,
recheck selected local work, execute or explicitly no-op declared remote
release publication, then execute or explicitly no-op local repository
`deploy`, handle its managed-skill handoff, recheck again, and clean only the
selected merged source branches and worktrees.

## Context

### Script Bundle

- (D) From the installed `ceratops-repo-lifecycle` skill root, run complete
  repository ship before manual readiness or implementation inspection:
  `python scripts/ship-repository.py --repo-root PATH --repo OWNER/REPO
  --head-branch release/local --base-branch main --remote-name origin
  --reusable-head`.
  `--repo-root` identifies the target repository; never search that target for
  this helper. The helper owns preflight; after a terminal blocker, inspect
  only the exact blocker-named surface.
- The helper derives the canonical pending-work scope from `--head-branch`.
  When a retained scope exists, the wrapper reuses its recorded exact target
  commit; a caller-supplied `--commit` must match it. An absent scope is a
  cleanup no-op. Each version-2 source persists its branch, exact recorded tip,
  and helper-owned `retained`, `preserved`, or `deleting` state. A missing
  `retained` source remains blocking. Only a missing `deleting` source whose
  recorded commit exists and is an ancestor of the recorded target may be
  atomically retired as completed interrupted helper cleanup. Before normal
  validation, the scope manager atomically converts an exact version-1 record
  to version 2. A missing legacy source is retired; a clean source still
  contained in the legacy target becomes `retained`; a dirty, unavailable, or
  advanced source becomes `preserved`, does not block rollout, and remains
  untouched during cleanup. Other old or malformed formats block.

### Inputs To Capture

- Repository checkout, staged `release/local`, base branch, remote, merge method,
  and PR title/body.
- Whether the head is reusable after merge.

## Constraints

### Boundaries

- Ship only clean staged `release/local`.
- Do not edit source or expand pending-work scope in this action.
- Keep standalone merge behavior under `merge-pr`; its admin choice is
  unchanged.

### Workflow

1. Run the complete ship helper once inside the global OUT-11
   `functions.exec` pattern; keep unchanged gate waits inside that call and
   treat terminal JSON as the complete decision payload. CI blockers must name
   the exact head and failed check plus available run, job, URL, and compact log
   evidence; review blockers must include body, location, thread ID, and top
   comment database ID. After fixing review findings, rerun the complete ship
   helper with `--review-replies-request REQUEST`. Its closed
   `ceratops-review-thread-replies.v1` request binds repository, PR, head,
   thread and top-comment identities to prepared replies; the helper pushes the
   exact head, verifies, posts and resolves every reply, checkpoints the
   handoff, consumes its canonical task-temp request, and continues the same
   gate and ship workflow.
2. Before automatically selecting an incomplete checkpoint to resume, the
   GitHub workflow removes a matching checkpoint only when its phase is exactly
   `prepared`, the local head branch has moved, a fresh fetch proves the commit
   is contained in the remote base branch, and a paginated repository-wide PR
   lookup proves no PR has that exact head. Missing or uncertain evidence
   retains the checkpoint and resumes or blocks. This checkpoint logic receives
   the exact commit already selected by the wrapper.
3. Before the first remote push, the scope manager atomically normalizes an
   exact version-1 record, then the helper checks the canonical version-2 scope.
   During the same preflight it validates every registered selected worktree's
   resolved path. A worktree is cleanup-eligible only when its parent chain
   contains a case-insensitive `worktrees` directory component; otherwise the
   helper returns its branch and exact path in non-blocking
   `preserved_worktrees` while continuing all selected-branch content checks.
   It atomically removes a missing `deleting` source only when its recorded
   commit exists and is an ancestor of the recorded target. A missing
   `retained` source or an unproven `deleting` source remains `pending_work` and
   performs no remote mutation. A `preserved` legacy source is outside
   pending-work blockers and destructive cleanup. An absent or proven-empty
   scope is a cleanup no-op.
4. (D) The delegated GitHub workflow owns deterministic, decision-complete
   PR-gate resolution for the exact head. It reads linked Actions runs with
   argument-array `gh run view --json jobs` calls, matches affected jobs inside
   the helper, and returns bounded run and job evidence without shell-evaluated
   `--jq`.
5. Only after those gates pass, integrated ship delegates the final exact-head
   merge to `merge.merge_verified_pr(admin=True)`. It inherits the shared
   merge action's checkpointed dedicated-endpoint bypass, restoration, read-back,
   and critical recovery semantics; ship contains no independent toggle logic.
6. After merge, the helper synchronizes local main and restores a reusable
   integration branch when selected.
7. Before remote mutation, the wrapper classifies release publication and
   deployment. An absent default `release/release.yml` makes release preflight
   and publication explicit no-ops, and an absent default `deploy/deploy.yml`
   makes `deploy` an explicit no-op; a missing custom contract blocks. Run a
   declared release preflight before the first remote mutation. After
   synchronization, recheck the selected scope, run declared release
   publication or record its no-op, then run declared local deployment or
   record its no-op, and recheck. Before removing a selected worktree or branch
   for a retained source, finalization atomically changes its state to
   `deleting`; an existing `deleting` branch first passes the same cleanliness
   and ancestry checks. Before removing a selected worktree, finalization
   revalidates its exact path and derives its direct parent as the cleanup root
   only when that parent chain contains a case-insensitive `worktrees` directory
   component. Otherwise it leaves the worktree and branch untouched, retires
   their scope record, and returns the exact preserved path. For an eligible
   worktree, it records the exact path, name, cleanup root, and any thread ID
   from `.codex-thread`. Automatic residual cleanup handles only the case where
   Git unregisters that worktree but leaves the recorded directory. The helper
   verifies that the path is unregistered and remains below the recorded root
   before deleting it. When elevated, it may take ownership only of that
   validated path, without a public flag or second confirmation. Before
   retiring the record, it deletes task-temp subdirectories under
   `<repo-parent>/tmp/<repo-name>` only when a name
   exactly matches the recorded worktree name, exactly matches the thread ID,
   or starts with the thread ID followed by `-`; it preserves every other
   name. It removes empty worktree and task-temp parents
   only up to their nearest `worktrees`, `tmp`, or `temp` boundary and never
   deletes the boundary itself. On Windows sharing violation 32,
   after Git unregisters an eligible worktree, the helper preserves and reports
   the exact residual path, retires its cleanup record, and continues
   merged-branch cleanup. Other residual cleanup errors remain blocking.
   Otherwise, the record is removed only after the worktree path and matching
   task-temp directories are absent. After successful branch
   deletion, it atomically removes the source record and deletes the scope after
   the final source is removed.
8. After declared release publication or deployment succeeds, the helper
   checkpoints each result independently against the exact target, operation,
   and resolved contract before the next phase. A retry reuses each completed
   result while later work remains pending and removes both checkpoints only
   after cleanup succeeds. Every terminal blocker after remote mutation returns
   the phases proven complete, the exact remaining phase, and a structured
   `resume_action` containing the owning ship helper's argv and working
   directory; consumed review-reply input is excluded. A publication failure
   blocks deployment and finalization; a deployment failure blocks finalization.
   Terminal success also removes every exact helper-owned atomic-write `.tmp`
   sibling for retired scopes, residual-cleanup records, operation checkpoints,
   and PR checkpoints; it never scans for or removes unrelated temporary files.
   Both operations must remain retry-safe across interruption.
9. After the helper completes, when synchronized main declares managed skills,
   execute the handoff returned in its deployment result against that exact
   checkout. If none was declared, report the managed skills as not deployed
   without changing the completed repository result.

## Done When

### Completion Gate

- PR publication, all gates, exact-head admin merge, main synchronization,
  declared or explicit no-op remote release publication, and declared or
  explicit no-op local repository deployment completed; any returned handoff
  completed, and managed skills without one were reported.
- Every existing cleanup-selected source branch passed pending-work checks; an
  or proven-empty scope completed as a cleanup no-op.
- Only an evidence-proven interrupted `deleting` record was recovered
  automatically; every missing `retained` source remained blocking.
- Dirty, unavailable, or advanced legacy sources were preserved, excluded from
  destructive cleanup, and reported by finalization.
- Only selected clean merged source work was removed.

### Output Contract

Report only:

- PR URL and merge outcome
- synchronized main, release-publication outcome, and local deployment outcome
- finalized or retained selected scope with reasons, exact preserved worktree
  paths, and phase-aware recovery data for terminal post-mutation blockers
