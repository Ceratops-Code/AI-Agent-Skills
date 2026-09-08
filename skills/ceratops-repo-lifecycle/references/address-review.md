# Address Review Action

## Goal

Inspect PR feedback and implement only the requested actionable fixes without
requiring a complete ship or merge workflow.

## Context

### Inputs To Capture

- PR URL or number and base repository, or the current branch PR.
- Whether the request is inspection-only, selected fixes, or all unresolved
  actionable feedback; publication, replies, and resolution have separate scope.
- The target checkout and a new caller-selected evidence file.

### Script Bundle

- Bind `<skill-root>` to the folder containing the parent `SKILL.md`.
  Invoke its installed script from the target checkout or another caller-owned
  directory, never from the replaceable skill or scripts directory.
- Inspect thread-aware feedback:
  `python "<skill-root>/scripts/github_pr_workflow/__main__.py"
  inspect-review --cwd PATH --evidence-file FILE
  [--pr NUMBER_OR_URL] [--repo OWNER/REPO]`.
- Apply an authorized prepared reply-and-resolution request:
  `python "<skill-root>/scripts/github_pr_workflow/__main__.py"
  address --request REQUEST --cwd PATH`.
- `codex_review.py` owns these operations. The inspector writes
  `ceratops-pr-review-evidence.v1` with repository, PR, URL, head SHA, complete
  conversation comments, submitted reviews, and paginated inline threads with
  replies, anchors, resolved state, and outdated state. Stdout contains only
  identity, counts, and the evidence path; errors exit nonzero.
- Evidence files are caller-owned and exclusively created. Read only relevant
  records from the report; retain a user deliverable or blocked-work evidence.
  Remove task-temporary reports and prepared requests at successful task
  closure under the active task-temp cleanup rules.

## Constraints

### Boundaries

- Inspect-only requests do not authorize source changes. A request to fix all
  feedback selects all unresolved actionable feedback, not approvals,
  informational comments, or already-resolved items.
- Do not push, reply, resolve, or submit a review without explicit authorization
  or an active workflow's pre-approval. Draft explanations when only local
  repair was requested; do not force a code change for an explanatory issue.
- Keep source changes in the owning repository workflow and task worktree.
  Skill changes remain owned by `$ceratops-skill-lifecycle`.
- Existing ship review gates remain authoritative. When called from ship,
  return evidence and prepared replies to ship's existing checkpoint/resume
  flow; standalone review handling never authorizes merge.

### Workflow

#### 1. Inspect the selected feedback

- Resolve the PR and inspect metadata or patch context through connected tools
  when useful. For thread state, use `inspect-review`; flat comments alone
  cannot establish resolution, outdated state, or inline anchors.
- Group actionable feedback by file or behavior and identify exact thread or
  review IDs. Outdated does not mean resolved or no longer actionable.
- If selection is missing, present the actionable items and ask which to fix.
  Surface conflicting or ambiguous changes before editing; do not accept a
  proposed regression merely because it appears in a review.

#### 2. Repair and verify

- Trace each selected change to its feedback and run the narrow relevant tests.
  Keep unrelated findings separate from the authorized repair.
- Reinspect affected feedback after a head change; never use stale IDs or an
  earlier head as proof that current feedback has been addressed.
- For authorized reply-and-resolution, prepare exactly
  `schema: ceratops-review-thread-replies.v1`, `repo`, positive integer
  `pr`, current `head_oid`, and `replies`. Each reply contains
  `thread_id`, `top_comment_database_id`, and the prepared `reply` text.
  The existing `address` helper validates all identities before writes,
  avoids duplicate own replies on retry, and resolves only those exact threads.
  Use the appropriate existing item operation for reply-only or review
  submission requests; `address` always includes resolution.
- Diagnose permission, authentication, rate-limit, and network failures from
  their evidence rather than automatically asking for reauthentication.

## Done When

### Completion Gate

- Every selected item is fixed and verified, answered within granted scope, or
  explicitly blocked or intentionally left open. No local fix is presented as
  a posted reply, resolved thread, pushed commit, or merged PR.

### Output Contract

Report addressed items, relevant verification, and remaining items with reasons.
Distinguish local fixes from GitHub writes and identify retained evidence.
