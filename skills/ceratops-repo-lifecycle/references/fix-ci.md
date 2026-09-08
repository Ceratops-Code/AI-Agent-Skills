# Fix CI Action

## Goal

Diagnose selected failing PR checks and implement requested GitHub Actions
repairs without requiring a full ship workflow.

## Context

### Inputs To Capture

- PR URL or number and base repository, or the current branch PR.
- Target checkout, optional exact check names, and a new evidence file.
- Whether the user requested diagnosis or implementation, and whether remote
  publication or workflow reruns are in scope.

### Script Bundle

- Bind `<skill-root>` to the folder containing the parent `SKILL.md`.
  Invoke its installed script from the target checkout or another caller-owned
  directory, never from the replaceable skill or scripts directory.
- Inspect CI:
  `python "<skill-root>/scripts/github_pr_workflow/__main__.py"
  inspect-ci --cwd PATH --evidence-file FILE
  [--pr NUMBER_OR_URL] [--repo OWNER/REPO] [--check NAME]`.
  Repeat `--check` to select exact names; omission inspects all attached checks.
- `readiness.py` owns check and log evidence shared with ship. The report
  schema is `ceratops-pr-ci-evidence.v1`: identity and head SHA, selected
  names, observed checks, all selected failures, Actions run/job metadata,
  bounded failure excerpts, log availability, and query diagnostics.
- Stdout contains status, identity, counts, diagnostics, and the evidence path.
  Exit zero means the selected checks passed; every other status exits one.
  Distinguish `failed`, `pending`, `no_checks`, `unknown`, `blocked`,
  `stale`, and command `error`; absent or unreadable checks are never green.
- Evidence files are exclusively created and caller-owned. Keep reports for
  blocked work or requested delivery; remove task-temporary reports at
  successful closure under the active task-temp cleanup rules.

## Constraints

### Boundaries

- Diagnosis does not authorize code repair. A clear fix request authorizes the
  narrow evidenced repair under active repository rules; do not add another
  blanket approval gate. Ask when a material behavior tradeoff or broader scope
  needs a decision.
- Inspect Actions through `gh`, not assumed connector log capabilities.
  Third-party checks are report-only URLs unless a separate investigation is
  requested; never fetch an arbitrary check URL with GitHub credentials.
- Do not bypass checks, disable workflows, rerun jobs, push, or merge merely
  because CI failed. Existing publication, readiness, and shipping gates remain
  owned by their lifecycle actions.

### Workflow

#### 1. Collect and interpret evidence

- Use the inspector for checks and logs; use connected tools for relevant PR
  metadata and patch context. The base PR repository owns Actions queries.
- The helper accepts valid check JSON for failed or pending CLI exit codes,
  fetches run metadata once per run, and collects every selected failed check.
  Completed jobs in running workflows use the job-log endpoint; unfinished jobs
  remain pending. Missing jobs, unavailable logs, and external checks stay
  explicit instead of triggering blind retries.
- Attribute the failure using the check, failing job or step, excerpt, and
  relevant diff. An empty excerpt is not evidence of success. Run head SHAs
  may differ for synthetic merge or target-branch workflows; use the event and
  workflow context before attributing a mismatch to stale CI.
- The final PR-head read must match the inspected head. A `stale` report
  requires fresh inspection before repair conclusions or publication decisions.
  Diagnose auth, permission, rate-limit, transport, and unsupported CLI fields
  separately; do not silently omit evidence or widen permissions.
- If the failure is unrelated to the selected diff, say so before proposing a
  source change. Do not infer flakiness from one failing run.

#### 2. Apply requested repair

- Explain the evidenced cause and smallest repair. For diagnosis-only work,
  stop at the proposal; for authorized repair, use the owning source workflow
  and task worktree, reproduce where practical, fix the cause, and run focused
  local tests.
- If push or rerun is authorized, use the owning lifecycle operation and
  re-inspect relevant checks for the resulting PR head. Otherwise report local
  verification separately from remote CI that remains unverified.
- When invoked from ship, return the repair and CI evidence to its existing
  resume flow; do not bypass its other gates or replace its checkpoint state.

## Done When

### Completion Gate

- The selected failures have evidence-backed diagnoses or explicit evidence
  blockers. Requested repairs have relevant local verification, and any claim
  about remote success is tied to the verified PR head and selected check scope.

### Output Contract

Report failing checks and their run URLs, cause or evidence gaps, verified
repairs, and only unresolved or intentionally unverified state.
