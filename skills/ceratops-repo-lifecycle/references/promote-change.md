# Promote Change Action

## Goal

Fast-forward selected committed task branches into `release/local` and validate
the assembled commit. For `promote-and-deploy`, run selected `deploy-local`
entries in order. Composed shipping validates again at its own boundary and
owns selected post-merge publication, deployment and cleanup.

## Context

### Script Bundle

- (D) Invocation contract: bind `<skill-root>` to the directory containing this
  action's parent `SKILL.md`; require
  `<skill-root>/scripts/promote-repository.py` once before the first call.
  Invoke that exact path with the working directory equal to its `--repo-root`
  value; stop if it is absent and never resolve it relative to that repository.
- (D) Promotion helper:
  `python
  "<skill-root>/scripts/promote-repository.py" --repo-root PATH
  --source-branch BRANCH [--source-branch BRANCH...] --main-branch main
  --release-branch release/local --remote-name origin --no-run-operation`.
- (D) Promotion plus deployment:
  `python
  "<skill-root>/scripts/promote-repository.py" --repo-root PATH
  --source-branch BRANCH [--source-branch BRANCH...] --main-branch main
  --release-branch release/local --remote-name origin
  --run-operation ID [--run-operation ID...]`.
- (D) Promotion followed by terminal shipping uses the same command with
  `--ship-after-promotion` as its complete operation choice. Do not add
  `--run-operation` or `--no-run-operation`; shipping alone publishes or
  explicitly no-ops the release, then deploys or explicitly no-ops locally
  after merge.
- (D) Fast-change callers may prepare a clean release checkout without
  promotion or deployment:
  `python
  "<skill-root>/scripts/promote-repository.py" --repo-root PATH
  --main-branch main --release-branch release/local --remote-name origin
  --prepare-release-only`.

### Inputs To Capture

- Repository checkout, selected committed source branches, main branch,
  `release/local`, and remote.
- Whether the selected action is `promote`, `promote-and-deploy`, or composed
  promotion and shipping.
- Optional PR `--title` and `--body` require `--ship-after-promotion` and pass
  unchanged to shipping.
- Ordered complete `deploy-local` locations for `promote-and-deploy`, and
  optional `publish` and `deploy-local` locations for composed shipping.
- Optional ordered `--validation-operation LOCATION` flags select checks.
  SDLC version 3 always retains repository and selected-deliverable validation
  and tests; earlier formats preserve their original selection behavior.

## Constraints

### Boundaries

- Promote only explicitly selected task branches.
- Keep unrelated branches and worktrees outside inspection and cleanup scope.
- Before promotion, automatically rebase a selected clean, unpublished,
  linear-history task branch onto current `release/local`. If rebasing fails,
  abort it, verify the original head and clean worktree were restored, and
  block with the conflicting paths. Apply the parent's local repair/retry rule
  to ordinary check failures; keep unrelated source edits outside this action.

### Workflow

1. Require clean selected worktrees. Through the promotion helper, establish
   Git ancestry with the eligible automatic rebase and run `git diff --check`.
2. For `promote`, run the helper with `--no-run-operation`.
3. For `promote-and-deploy`, repeat `--run-operation LOCATION` in order.
   The helper accepts only `deliverables.<name>.deploy-local.<operation>`,
   prepares the entire selection before commands, runs applicable validation
   and tests once, and executes the prepared operations only while the checked
   commit stays clean and unchanged. Explicit missing locations are errors;
   version-3 tests require declared commands, handoffs, or reasoned no-ops.
4. For composed shipping, use `--ship-after-promotion`, one optional
   `--sdlc-contract PATH`, and repeated `--publish-operation LOCATION` or
   `--deploy-operation LOCATION` for requested post-merge work. Omitted mutation
   selections do nothing. The helper records the exact head and scope, runs
   promotion validation and tests, then invokes shipping with the same inputs.
5. Let the SDLC engine execute registered deterministic skill actions for
   version-3 handoffs. Resolve any returned judgment-required route within the
   selected skill action; dependent mutation remains blocked. Preserve advisory
   routing for older contracts and never claim a route alone completed work.
6. Atomically normalize an exact version-1 pending-work scope to version 2
   before reuse. Retire a missing legacy source, keep a clean source contained
   in the legacy target as `retained`, and mark a dirty, unavailable, or
   advanced source `preserved` so stale cleanup cannot block the new promotion
   or delete evolved work. Treat the normalized version-2 scope as the only
   source scope later passed to ship. Persist each selected source's exact tip
   and helper-owned state. Advance a reusable scope only when its recorded
   target is an ancestor of the new target. Recover a missing source
   automatically only when its `deleting` state and recorded commit ancestry
   prove an interrupted helper deletion; a missing `retained` source blocks.
7. On a shipping blocker, retain the scope, branches, worktrees, and checkpoints
   for resume. Terminal shipping owns finalization and selected-work cleanup;
   it leaves a worktree and branch untouched when the worktree's parent chain
   has no `worktrees` directory component and reports the exact preserved path.

The helper refreshes the remote, fast-forwards main, reuses an existing local
`release/local` without merging main into it, and creates it from main when
missing. When release `HEAD` is not an ancestor, it rebases only an unpublished,
linear selected branch in its existing clean worktree. It refuses published or
nonlinear history. A failed attempt must restore the original branch head and
clean worktree before it reports the failure and conflicting paths. The helper
then runs `git diff --check`, fast-forwards each selected branch, records the
scope and validates the final commit. A failed check returns its YAML location,
checked commit and bounded diagnostics while preserving the scope for repair.
In composed mode, shipping repeats validation before remote mutation; successful
promotion checks never suppress that boundary. Check results cannot authorize a
different or dirty commit. Deployment and publication commands come only from
the repository's declared entries, not from helper-selected script names.
Preparation-only requires a clean `main` checkout and exits immediately after
`release/local` is ready, before source preflight, promotion, scope records,
or deployment.

Use `--result-file PATH` outside the repository to atomically retain the exact
JSON outcome, including operation receipts and phase durations in seconds. The
helper records successful and failed attempts without replaying operations.

After validating every deployment receipt against its producer schema, success
status, requested commit and required fields, finalize the verified saved result
with `--finalize-result --result-file PATH --task-temp-root ROOT
--expected-commit COMMIT --verified-result-sha256 SHA256`. The digest identifies
the exact bytes just validated; it does not replace producer validation. ROOT
must be one task directory under `<repo-parent>/tmp/<repo-name>/`.

Finalization accepts only complete promote-and-deploy results for that commit,
rejects changed files and linked or out-of-scope paths, and deletes only the
named receipt. It preserves failed, incomplete, promotion-only and shipping
results, other task artifacts and pending-work state. Success prints `OK`;
cleanup failure preserves the receipt and reports `replay_required: false`.
Finalization never runs promotion, deployment or publication.

## Done When

### Completion Gate

- The checkout is clean on `release/local`.
- Every selected branch is contained in the reported release commit.
- Every attempted automatic rebase either completed and reported both heads or
  restored the original clean source state before blocking.
- The final assembled commit passed applicable validation and tests before continuation;
  deployment ran during promotion only when requested. In composed mode,
  shipping repeated both gates and ran only the selected post-merge work.
  Advisory routing alone was never reported as completed domain work.
- The exact pending-work scope is retained for standalone promotion or a
  shipping blocker; successful composed shipping finalizes it, cleans selected
  sources, and reports any preserved legacy sources or non-cleanup-eligible
  worktrees left untouched.

### Output Contract

Report only:

- `release/local`, exact head, promoted branches, and automatic rebase results
- ordered operation outcomes and advisory handoffs when selected
- pending-work scope
- blockers or intentionally retained state
