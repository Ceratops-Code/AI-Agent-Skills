# Ship Action

## Goal

Ship one staged integration branch through GitHub, synchronize local main,
recheck selected local work, execute or explicitly no-op repository `deploy`,
handle its managed-skill handoff, recheck again, and clean only the selected
merged source branches and worktrees.

## Context

### Script Bundle

- (D) Complete repository ship:
  `python scripts/ship-repository.py --repo-root PATH --repo OWNER/REPO
  --head-branch release/local --base-branch main --remote-name origin
  --reusable-head`.
- The helper derives the canonical pending-work scope from `--head-branch`.
  When a retained scope exists, the wrapper reuses its recorded exact target
  commit; a caller-supplied `--commit` must match it. An absent scope is a
  cleanup no-op. Entries for missing source branches are atomically removed
  from an existing scope before shipping continues.

### Inputs To Capture

- Repository checkout, staged `release/local`, base branch, remote, merge method,
  and PR title/body.
- Whether the head is reusable after merge.

Infer missing values from the checkout, scope file, and live PR before asking.

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
   comment database ID. After fixing review findings, invoke `python -m
   github_pr_workflow address --request REQUEST` once from the helper directory.
   Its closed `ceratops-review-thread-replies.v1` request binds repository, PR,
   head, thread and top-comment identities to prepared replies; the helper
   verifies them, posts and resolves every reply, and emits only `OK` on success.
2. Before automatically selecting an incomplete checkpoint to resume, the
   GitHub workflow removes a matching checkpoint only when its phase is exactly
   `prepared`, the local head branch has moved, a fresh fetch proves the commit
   is contained in the remote base branch, and a paginated repository-wide PR
   lookup proves no PR has that exact head. Missing or uncertain evidence
   retains the checkpoint and resumes or blocks. This checkpoint logic receives
   the exact commit already selected by the wrapper.
3. Before the first remote push, the helper checks the canonical scope when it
   exists. It atomically removes entries for missing source branches and deletes
   the scope if none remain. An absent or emptied scope is a cleanup no-op;
   remaining `pending_work` performs no remote mutation.
4. The delegated GitHub workflow ensures the PR, waits for readiness, CI, and
   Codex review, immediately rereads every gate, and verifies the exact head.
   Explicitly pending checks use the configured CI wait. An unrecognized or
   incomplete check state, or required checks not yet attached, receives one
   immediate reread and at most a 60-second grace. Persistent uncertainty
   blocks with the exact check-state fields and head, the normalized `gh pr
   checks` result, and linked Actions-run state when available. An empty rollup
   is accepted only when applicable branch protection and rulesets require no
   status checks.
5. Only after those gates pass, integrated ship delegates the final exact-head
   merge to `merge.merge_verified_pr(admin=True)`. It inherits the shared
   merge action's checkpointed dedicated-endpoint bypass, restoration, read-back,
   and critical recovery semantics; ship contains no independent toggle logic.
6. After merge, the helper synchronizes local main and restores a reusable
   integration branch when selected.
7. Before remote mutation, the wrapper classifies deployment. An absent default
   `deploy/deploy.yml` makes `deploy` an explicit no-op; a missing custom
   contract blocks. After synchronization it rechecks the selected scope, runs
   a declared operation or records the no-op, and rechecks. Before removing a
   selected worktree, finalization records its exact path. Automatic residual
   cleanup handles only the case where Git unregisters the worktree but leaves
   that recorded directory. The helper verifies that the path is unregistered
   and remains below the canonical worktree root before deleting it. When the
   helper runs elevated, the same cleanup may take ownership only of that
   validated path, without a public flag or second confirmation. The helper
   removes the residual-cleanup record only after verifying the path is absent,
   then removes the merged selected branch.
8. After a declared `deploy` succeeds, the helper checkpoints its result
   against the exact target, operation, and resolved contract before
   finalization. A retry reuses that result while cleanup remains pending and
   removes the checkpoint after cleanup succeeds. Deployment operations must
   remain retry-safe across interruption.
9. After the helper completes, when synchronized main declares managed skills,
   execute the handoff returned in its deployment result against that exact
   checkout. If none was declared, report the managed skills as not deployed
   without changing the completed repository result.

## Done When

### Completion Gate

- PR publication, all gates, exact-head admin merge, main synchronization, and
  declared or explicit no-op repository deployment completed; any returned
  handoff completed, and managed skills without one were reported.
- Every remaining selected source branch passed pending-work checks; an absent
  or emptied scope completed as a cleanup no-op.
- Only selected clean merged source work was removed.

### Output Contract

Report only:

- PR URL and merge outcome
- synchronized main and deployment outcome
- finalized or retained selected scope with reasons
- blockers or anything important not verified
