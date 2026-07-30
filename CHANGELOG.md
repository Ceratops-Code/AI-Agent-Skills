# Changelog

## Unreleased

- Added deterministic repository shipping with a scoped pending-work check
  before the first remote push, retained post-sync and post-deploy rechecks,
  concurrent CI and Codex-review gates, exact-head post-gate admin merge, local
  synchronization, structured post-merge deployment, and selected-source
  cleanup. Standalone PR merge behavior is unchanged.
- Added evidence-gated CodeQL disposition that requires sentinel source-to-sink
  sanitizer proof and explicit authorization before alert dismissal.
- Moved Ceratops skills to a copy-based runtime install model: source skills
  stay delta-only, the lifecycle renderer expands shared sections, and the
  versioned `scripts/install-skills.py` bootstrap installs managed runtime skill
  folders plus declared payloads.
- Renamed the repository owner to `ceratops-repo-lifecycle` and consolidated
  local Git promotion, structured deployment, guarded GitHub shipping, and PR
  lifecycle work there. Skill creation and mutation remain in
  `ceratops-skill-lifecycle`.
- Added separate `promote`, `promote-and-deploy`, `run-operation`, and `ship`
  actions backed by `promote-repository.py`, `manage-pending-work.py`,
  `run-deploy-operation.py`, and `ship-repository.py`.
- Moved the live section manifest and sources to
  `skills/skill-sections.json` and `skills/sections/`, added the live
  `deploy/deploy.yml` contract, and limited `templates/` to reusable section
  manifest and deployment-contract skeletons.
- Split health policy into deterministic and non-deterministic contracts for
  GitHub org settings, live GitHub repo settings, repo contents, code comments,
  and external artifact registries.
- Split contract review by lifecycle owner: GitHub, code, repo, PR, org, and
  artifact contracts now live under `ceratops-repo-lifecycle` as
  `contracts-review`; skill consistency, governance, and skill-design contracts
  now live under `ceratops-skill-lifecycle` as
  `skills-consistency-review`.
- Retired the standalone `ceratops-contract-review` and
  `ceratops-skills-consistency-audit` skill folders, moving their contracts,
  validators, and source-doc registries into the owning lifecycle skills.
- Reduced routine skill maintenance validation to same-surface checks, with full
  validation reserved for CI, governance automation, explicit broad
  verification, validation-script changes, or real cross-surface uncertainty.
- Replaced the skill-specific release wrappers with deterministic generic
  repository lifecycle helpers and exact selected-branch/worktree scope.
- Clarified that successful mutation commands are enough evidence for the exact
  setting or file they changed; contract validators are for drift, audit,
  uncertain state, and broad current-health claims.
- Updated `AGENTS.md`, README, contributing guidance, shared sections, runtime
  payload declarations, and skill metadata to match the new install, contract,
  and validation behavior.
- Expanded no-extra-cost GitHub, Dependabot, artifact-registry, trusted
  publishing, provenance, and paid-feature classification coverage across the
  contracts.
- Added `ceratops-automation-run`, split handoff skills,
  `ceratops-code-consistency-audit`, consolidated skill lifecycle actions, local
  runtime staging, and skill remote shipping workflows for recurring Codex
  operations.

## 0.1.2 - 2026-04-19

- Required all Ceratops GitHub workflow skills to report each retained security,
  code-scanning, maturity, or process alert with name or id, blocking status,
  defer reason, and concrete clearance work.
- Expanded `ceratops-gh-repo-health-audit` to perform an explicit end-to-end
  alert audit and forbid collapsing retained alerts into a generic healthy
  result.

## 0.1.1 - 2026-04-18

- Tightened publication checks across the publish, ship, audit, and merge
  skills.
- Added explicit retained-state reporting for Scorecard maturity gaps in
  publish, ship, and audit flows.
- Compressed repeated skill policy text into a synced shared core block.
- Added explicit skill boundaries and handoff rules between publish, ship,
  audit, dependencies-maintenance, and merge flows.
- Added `templates/common-core.md` and `scripts/sync-skill-core.py` so shared
  policy text stays consistent across skills.
- Updated validation and CI to enforce common-core sync.
- Narrowed `ceratops-code` ownership preference to explicit Ceratops context
  instead of acting as a universal default.

## 0.1.0 - 2026-04-18

- Initial public release of five Ceratops GitHub workflow skills.
- Added Codex metadata for each skill.
- Added repository validation, GitHub Actions CI, CodeQL workflow, Dependabot
  config, security policy, contribution docs, issue forms, pull request
  template, and CODEOWNERS.
