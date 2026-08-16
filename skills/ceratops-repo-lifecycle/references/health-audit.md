# Health Audit Action

## Goal

Validate that an existing GitHub repo is clean, current, secure, documented,
published, and not carrying leftover workflow debris. Apply low-risk reversible
fixes directly and report risky, ambiguous, destructive, paid, or
credential-bound fixes precisely.

## Context

### Script Bundle

- (D) Full GitHub, code, and artifact contract check, run from the lifecycle
  skill's `scripts` folder: `python -m github_contract_engine validate repo
  --repo OWNER/REPO --surface all --subset health --local-repo-path PATH
  --evidence-file EVIDENCE`
- (D) Optional org contract check when org posture is in scope, run from the
  same folder: `python -m github_contract_engine validate org
  --org ORG [--params-file PATH] [--billing-email EMAIL]
  [--owner-login LOGIN]`
- (D) Add `--summary-json --levels ERROR,WARN,NEEDS_AI_AGENT_REVIEW`, `--json`,
  `--check-id`, or a narrower `--subset` when another step needs structured or
  scoped findings.
- (D) Prefer `--summary-json` for agent-readable repo-health output; use
  `--json` only when a parser needs the full report.
- (D) Local health records
  `ceratops_repo_compatibility_engine.compatibility_check.check_repository(repo_root)`
  unchanged. It also runs a present `scripts/validate-repository.py` once with
  `--evidence-file` outside the target; a missing validator or CI validation
  workflow is a finding. External-only health runs no local validator.
- (D) When the local repository declares `artifacts` in
  `release/release.yml`, the repo checker validates that release contract and
  uses its artifact identities automatically. Caller-supplied
  `artifact_contracts` remain only for repositories without local declarations.
- (D) Organization parameters resolve in this order: contract defaults,
  `--params-file`, named flags, then `--param`. The parameter file defaults to
  `$CODEX_HOME/gh-contract-params.json`.

### Inputs To Capture

- Target repo and any expected posture that differs from the GitHub repo, code
  repo, or artifact contracts.
- Local repo path, repository-owned release and artifact identity, and local
  consumers needed to classify stale or risky side effects.

## Constraints

### Boundaries

- Use this action when the task is primarily validation, stale-state cleanup, or
  safe repo-health repair and the repo has live GitHub state worth
  machine-checking.
- Do not use this action as a routine rubber-stamp closeout pass after normal
  ship, dependency-maintenance, or merge flows.
- If the repo is not yet published, needs first hardening, needs normal PR and
  release flow, or only needs PR finalization, return to the parent skill and select
  the owning action.

### Workflow

#### 1. Inspect local and live state

- Inspect git status, remotes, branches, refs, tags, releases, generated files,
  artifacts, temp paths, package outputs, and local consumer references.
- Capture only live GitHub metadata needed to run and interpret the contract
  check.
- Inspect local workflow files when available so mutable external action refs
  are classified from file evidence.
- Inspect validation configs, dependency pins, CI wiring, and local validation
  guidance when repository contents are part of the health surface.
- Inspect generic manifest structure, deployment schema, and repository
  validation wiring through `ceratops_repo_compatibility_engine` when local
  contents are present. Skill-source validation remains outside repo health.
- Expand to open PRs, releases, tags, branches, Actions runs, moderation detail,
  or published artifacts only when script output, repo type, touched files, or
  the user request makes them relevant.

#### 2. Run contract checks first

- (D) Run the full GitHub, code, and artifact contract checker before treating
  repo health as clean.
- (D) Treat checker output as the source of truth for machine-checkable GitHub
  settings, repo-content posture, stale queues, local checks, and artifact
  registry evidence.
- Report the returned community-profile health percentage against its contract
  target for every audited repository, including repositories with no other
  finding.
- Treat stale-state inventory counts as evidence, not findings; only
  policy-matching stale candidates should produce `NEEDS_AI_AGENT_REVIEW`.
- If the checker reports `WARN`, `NEEDS_AI_AGENT_REVIEW`, or a blind spot,
  classify it from available repo evidence first; escalate only intent that
  cannot be inferred from repo evidence, and do not close while review items remain
  unclassified.

#### 3. Research only where needed

- Check current official docs only where local files, live contract state, and
  shared contracts leave the next fix or decision unresolved.
- Compare at most one or two strong reference repos only for a concrete
  ambiguous file, metadata, workflow, security, or release question.

#### 4. Repair safe gaps

- Apply low-risk reversible fixes directly.
- Treat a successful mutation command as evidence for that exact setting or file
  change; rerun the checker only for uncertain state, asynchronous effects, or a
  broader clean-health claim.
- Open or update a PR for repo changes when branch protection or repo policy
  requires it.
- Do not delete tags, releases, packages, protected branches, backup branches,
  or external artifacts unless stale classification is proven and the action is
  safe or explicitly approved.

#### 5. Validate and close

- For local health, run the repository validator once after the last content
  change and before a broad health claim; do not rerun its checks. External-only
  health runs no local validator.
- Verify live GitHub and registry state when not already proven by
  command-result evidence or when asynchronous external state matters.
- Re-run relevant contract checks only for unresolved audit scope or broad
  health claims.

## Done When

### Completion Gate

- Any broad current-health claim is backed by
  `python -m github_contract_engine validate repo` or equivalent command-result
  evidence.
- Every applicable `check_repository` result is valid with no errors; every
  local health run's repository validator also passes.
- Actions hardening claims are backed by a fresh local workflow scan when repo
  files were available.
- Local state is verified for every touched repo, worktree, generated file,
  artifact, temp path, cache, credential change, local consumer path, shortcut,
  scheduled task, service, shell profile, and cleanup side effect.

### Output Contract

Report only:

- observed community-profile health percentage and contract target
- health gaps fixed
- alerts or findings left open with name or id, blocking status, reason, and
  concrete work needed
- health gaps intentionally retained with exact reasons
- remaining health blockers
- paid requirement with product, reason, and price if encountered
