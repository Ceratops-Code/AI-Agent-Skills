# GitHub Repo Non-Deterministic Checks

This file complements `github-repo-deterministic-contract.json`. The JSON
contains machine-checkable GitHub repository settings, policy, security,
Actions, queue, and stale-state checks. This file contains review checks that
require intent judgment, current-doc interpretation, paid/free classification,
or browser confirmation of GitHub screens.

## Evidence Bundle

Use one bundled evidence command instead of running one command per check:

```powershell
python skills/ceratops-gh-repo-lifecycle/scripts/github-collect-nd-evidence.py --surface repo --repo OWNER/REPO --local-repo-path PATH --json
```

The report maps each ND check ID to evidence keys and includes bundled GitHub
endpoint data, detected repo types, deterministic GitHub finding counts, and
failed or plan-limited endpoint evidence. When repository-content quality or
workflow-file intent is also in scope, collect a separate `--surface code`
evidence bundle.

## Review Result Values

- `pass`: reviewer found the intent satisfied and recorded evidence.
- `fail`: reviewer found a concrete mismatch.
- `approved_drift`: mismatch is allowed by the contract's approved drift
  profile.
- `blocked`: review needs unavailable permission, paid feature, missing product
  decision, or browser confirmation.
- `not_applicable`: repository state or source line does not apply.

## Non-Deterministic Check Definitions

| ID | Applies when | Review required |
| --- | --- | --- |
| `ND.github.repo-public-contract-accuracy` | Non-archived repos, especially public repos | Confirm repository description, topics, homepage, visibility, feature flags, support route, and visible GitHub surfaces are accurate and not misleading. |
| `ND.github.release-posture-fit` | Repos with releases, tags, protected release process, or public release claims | Confirm GitHub releases, tags, draft/prerelease state, release-note source, rollback expectations, and user-facing release text match the real project. |
| `ND.github.merge-branch-policy-fit` | Non-archived, non-fork repos | Confirm required checks match real CI, required review count is appropriate, bypass/admin exceptions are deliberately approved, and private-plan branch protection gaps are classified rather than hidden. |
| `ND.github.actions-policy-fit` | Repos with Actions enabled or workflows present | Confirm allowed Actions policy, workflow-token defaults, SHA-pinning enforcement, artifact/log retention, fork PR approval, private-fork behavior, and latest default-branch run posture fit the repo. |
| `ND.github.security-reporting-and-paid-surface-fit` | Security settings, public repos, private repos with paid-feature responses | Confirm security reporting, paid security controls, alerts, code-security configurations, and churn-prone controls are classified correctly and not enabled without explicit approval. |
| `ND.github.dependabot-queue-fit` | Dependabot alerts or open Dependabot PRs exist | Confirm open alert and PR queues are active work, intentionally retained, approved drift, stale, or blocked before merging or closing. |
| `ND.github.stale-state-intent-classification` | Open PRs, extra branches, tags, releases, security alerts, code-scanning alerts, or process findings are present | Confirm each item is active, intentionally retained, approved drift, stale, or blocked before removal or repair. |
| `ND.github.sources-current-doc-recheck` | Exact feature availability, paid/free status, or API behavior matters and local/API evidence is ambiguous | Recheck official GitHub documentation or `gh` help before deciding drift. |
| `ND.reference-repo.comparator-only` | A reference repository is consulted | Record the exact standards question answered by the reference repo and do not audit or repair that reference repo. |
