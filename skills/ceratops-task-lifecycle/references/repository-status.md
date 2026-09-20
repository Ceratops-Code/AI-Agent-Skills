# Repository Status Action

## Goal

Show the requested repository's branch and worktree state in one fixed Markdown
table, including promotion, shipping, active-task, salvage, and implementation
evidence.

## Inputs

- Requested repository path or saved project.
- Release branch, base branch, and remote when they differ from
  `release/local`, `main`, and `origin`.

## Rules

- Inspect repository state without changing branches, worktrees, or tasks.
- Refresh remote refs when current shipping status is required and the remote
  is available; label unavailable evidence instead of guessing.
- Emit one row for every registered worktree, then one row for every remaining
  local or non-symbolic remote branch not represented by a worktree. Use `-`
  for a detached worktree or a branch without a worktree.
- `Is promoted?` is `Yes` only when the row's commit is contained in the local
  release branch. `Is shipped?` is `Yes` only when it is contained in the
  remote-tracking base branch. Report `Unavailable` when the required ref is
  missing or stale and cannot be refreshed.
- Resolve active task titles from available Codex task or session evidence. Do
  not infer a task solely from a branch or folder name; report `None` or
  `Unverified` when appropriate.
- Fill the promotion-worth column with `Yes`, `No`, or `Unverified` only when
  promotion and shipping are both `No` and there is no active task; otherwise
  use `-`. Base the decision on unique commits, patch equivalence, and the
  current diff, with a short reason.
- Summarize implementation from commit subjects and the changed paths or diff.
- Render the table directly as Markdown. Do not put it in a code fence or
  replace it with prose.

## Output Contract

Preserve this header text and column order:

| Branch | Worktree | Is promoted? | Is shipped? | It's active thread name, if has any | If all the answers are "no" - does it have any changes worth promoting? | What does it implement, in short |
| --- | --- | --- | --- | --- | --- | --- |
| `<branch or ->` | `<worktree or ->` | `<Yes, No, or Unavailable>` | `<Yes, No, or Unavailable>` | `<task title, None, or Unverified>` | `<Yes/No/Unverified with reason, or ->` | `<short implementation summary>` |

## Done When

- Every in-scope worktree and branch appears exactly once.
- Every status and recommendation is backed by current evidence or explicitly
  marked unavailable or unverified.
- The response contains the fixed table as a rendered Markdown table.
