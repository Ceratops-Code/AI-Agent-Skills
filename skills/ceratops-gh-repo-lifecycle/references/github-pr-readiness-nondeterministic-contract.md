# GitHub PR Readiness Non-Deterministic Contract

Use this contract when deterministic PR readiness leaves an intent or risk
decision unresolved.

Evidence command:

```powershell
python skills/ceratops-gh-repo-lifecycle/scripts/github-collect-nd-evidence.py --surface pr --pr NUMBER_OR_URL --local-repo-path PATH --json
```

## Checks

| ID | Applies When | Review Question |
| --- | --- | --- |
| `ND.pr.merge-method-fit` | A PR is ready to merge | Confirm the selected merge, squash, or rebase method matches repo policy, release history, branch shape, and user intent. |
| `ND.pr.auto-merge-vs-direct-fit` | Checks are pending or auto-merge is considered | Confirm whether to wait, enable auto-merge, or direct-merge now. |
| `ND.pr.queue-or-admin-bypass-fit` | Merge queue, admin merge, or policy bypass is possible | Confirm bypassing queue or normal protection is intentional and justified by current evidence. |
| `ND.pr.self-merge-fit` | The acting maintainer's own review is the remaining blocker | Confirm repo policy intentionally allows self-merge instead of requiring another reviewer. |
| `ND.pr.workflow-change-risk` | The PR touches workflows, Actions permissions, release automation, or credentials | Confirm the workflow change does not introduce mutable refs, credential expansion, or an unreviewed release path. |
| `ND.pr.flaky-or-unrelated-check-classification` | A check is failing, missing, skipped, or stale but may be unrelated | Confirm the classification is evidence-backed before merging or enabling auto-merge. |
| `ND.pr.release-or-artifact-followup-fit` | Merge may require a tag, release, package, image, or registry update | Confirm whether merge must stay coupled to artifact publishing through the ship workflow. |
| `ND.pr.branch-cleanup-fit` | Branch deletion, safety branch retention, or worktree cleanup is planned | Confirm cleanup preserves reachable work, fork branches, release branches, and reusable integration branches. |
