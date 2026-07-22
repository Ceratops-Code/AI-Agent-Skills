# Ensure PR Action

## Goal

Push one clean prepared local branch and ensure one open GitHub pull request
targets the intended base branch at the pushed local head.

## Context

### Script Bundle

- (D) Run `python -m github_pr_workflow ensure-pr --repo-root <repo>
  --head-branch <branch> --base-branch <branch> --remote-name <remote>` from the
  GH lifecycle skill's `scripts` directory.

### Inputs To Capture

- Repository root, prepared head branch, base branch, remote, and optional PR
  title or body.

Infer missing inputs from the prepared checkout before asking.

## Constraints

### Boundaries

- Use this action only when local change preparation and validation are already
  complete and the remaining operation is push plus PR create or update.
- Return to the calling lifecycle for readiness, merge, post-merge sync,
  release, installation, or artifact work.
- Do not commit, modify source, merge, delete branches, or publish artifacts.

## Workflow

1. Confirm the checkout is clean, on the requested head branch, and ahead of
   the base branch.
2. Run the deterministic helper; it pushes the same-named remote branch,
   creates or updates one open PR, waits for GitHub to expose the pushed head,
   and returns compact PR JSON.
3. Return the PR result to the calling lifecycle.

## Done When

### Completion Gate

- The open PR head equals local `HEAD`, or the exact blocker is reported.

### Output Contract

Report only:

- PR number, URL, head, state, draft state, and compact check summary
- blockers or anything important not verified
