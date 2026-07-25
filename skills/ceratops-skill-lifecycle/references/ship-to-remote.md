# Ship To Remote Action

## Goal

Ship an already-staged Ceratops skill batch from the skills repo checkout's
active `release/*` branch, then restore the skills repo checkout and installed
skills to synced `main`.

## Context

### Defaults

- Default release branch: `release/local`
- (D) Repository installer: `python scripts/install-skills.py`, which uses the
  supported installed lifecycle bundle.
- Installed managed skill path: `$CODEX_HOME/skills/<skill-name>`

### GitHub Lifecycle Handoffs

- PR publication, gates, merge, synchronization, and reusable release-branch
  restoration: use `$ceratops-gh-repo-lifecycle` with the `ship-change` action.
- (D) Run its helper from
  `skills/ceratops-gh-repo-lifecycle/scripts` in a source checkout or `scripts`
  in the installed GH lifecycle skill folder:
  `python -m github_pr_workflow ship --repo-root <repo>
  --head-branch release/local --base-branch main --remote-name origin
  --reusable-head`.

### Inputs To Capture

- Skills repo checkout path, active release branch, target `main` branch, PR
  title/body expectation, and merge method.
- Whether to create a new PR or reuse an existing PR for the active release
  branch.
- Whether the user requested cleanup beyond automatic GitHub branch deletion
  allowed by merge.

Infer missing inputs from the skills repo checkout and live GitHub state before
asking.

## Constraints

### Boundaries

- Use this action only for shipping a staged skills repo branch through GitHub.
- If skill creation, skill update, or local staging work is still needed, return
  to the parent skill and select the owning action.
- If the task is general non-skill repo shipping, use
  `$ceratops-gh-repo-lifecycle` with the `ship-change` action.
- Do not edit skill source here. This action only pushes, opens or updates the
  GitHub PR, merges, restores `main`, and rebuilds installed skills from `main`.
- Delete only approved clean task worktrees and source branches named by the
  exact promotion record, and only after terminal successful shipping. Do not
  delete unrelated worktrees, branches, release branches, packages, or
  artifacts.

### Workflow

#### 1. Verify staged branch

- Confirm the skills repo checkout is clean and on the intended local
  `release/*` branch.
- Confirm the release branch contains the intended staged skill commits.

#### 2. Ship the staged branch

- Use `$ceratops-gh-repo-lifecycle` with the `ship-change` action and its
  deterministic helper. It owns clean release-branch publication, exact-commit
  checkpoints, concurrent CI/readiness and Codex review gates, exact-head
  merge, live verification, main synchronization, and safe reusable
  `release/local` restoration.
- Resume with the same full commit after interruption; incomplete work uses its
  checkpoint, while completed work is reconstructed from the exact merged PR.
  Do not fall back to separate ensure, merge, or sync commands.
- When `ship` returns `authorization_required`, preserve its result as the
  complete handoff, request approval for its exact `next_argv`, and run that
  vector in `next_cwd` directly after approval without rediscovery calls.

#### 3. Clean promoted task sources

- After `ship` returns `shipped` or `already_shipped`, run
  `scripts/check-pending-release-work.ps1 -SkillsRepoRoot <repo>
  -ReleaseBranch release/local -PromotionCommit <ship.commit>
  -CleanMergedBranches` from the selected lifecycle bundle when promotion
  reported retained approved sources.
- The helper must consume only that exact promotion record, remove only its
  clean merged worktrees and branches, and delete the record. Retain the record
  and stop if shipping is incomplete or cleanup finds dirty or unmerged work.

#### 4. Rebuild installed skills

- (D) Run `python scripts/install-skills.py --repo-root <repo>` after restoring
  `main`, so this source repository's managed skills are rebuilt from the
  merged main snapshot and same-source stale runtime folders are removed.
- Keep installation in this skill lifecycle action; do not move it into the
  GitHub ship helper.
- Verify the skills repo checkout is clean on `main` and expected installed
  skill folders have current `.runtime-manifest.json` files.

## Done When

### Completion Gate

- PR publication, gates, exact-head merge, main synchronization, and reusable
  release-branch restoration were handled by `$ceratops-gh-repo-lifecycle`
  with the `ship-change` action.
- The PR is merged or the exact blocker is reported.
- The skills repo checkout is on `main`, fast-forwarded from `origin/main`, and
  clean.
- Approved clean task worktrees and branches from the shipped promotion record
  were removed; any blocked retained source is reported.
- Installed skills were rebuilt from `main`.

### Output Contract

Report only:

- PR URL and final merge outcome
- PR readiness and CI result used
- skills repo main restore and install result
- retained local branches, worktrees, or release branches with reasons
- blockers or anything important not verified
