# Changelog

## Unreleased

- Moved Ceratops skills to a copy-based runtime install model: source skills stay delta-only, `scripts/render-runtime-skills.py` renders shared sections, and `scripts/install-skills.ps1` copies managed runtime skill folders plus declared payloads.
- Split health policy into deterministic and non-deterministic contracts for GitHub org settings, live GitHub repo settings, repo contents, code comments, and external artifact registries.
- Renamed contract checker scripts under `scripts/validation/` and renamed the skill standards workflow to `ceratops-contract-review`.
- Retired the separate standards baseline file; durable source tracking now lives in `contracts/source-docs.json`, deterministic JSON contracts, and non-deterministic contract review prompts.
- Reduced routine skill maintenance validation to same-surface checks, with full validation reserved for CI, governance automation, explicit broad verification, validation-script changes, or real cross-surface uncertainty.
- Replaced thin release-branch wrapper scripts with direct Git commands in the stage and ship skills, while keeping the pending-release-work script for read-only multi-worktree and branch evidence.
- Clarified that successful mutation commands are enough evidence for the exact setting or file they changed; contract validators are for drift, audit, uncertain state, and broad current-health claims.
- Updated `AGENTS.md`, README, contributing guidance, shared sections, runtime payload declarations, and skill metadata to match the new install, contract, and validation behavior.
- Expanded no-extra-cost GitHub, Dependabot, artifact-registry, trusted publishing, provenance, and paid-feature classification coverage across the contracts.
- Added `ceratops-automation-run`, split handoff skills, `ceratops-code-consistency-audit`, `ceratops-skill-create`, `ceratops-skill-update`, local runtime staging, and GitHub skill shipping workflows for recurring Codex operations.

## 0.1.2 - 2026-04-19

- Required all Ceratops GitHub workflow skills to report each retained security, code-scanning, maturity, or process alert with name or id, blocking status, defer reason, and concrete clearance work.
- Expanded `ceratops-gh-repo-health-audit` to perform an explicit end-to-end alert audit and forbid collapsing retained alerts into a generic healthy result.

## 0.1.1 - 2026-04-18

- Tightened publication checks across the publish, ship, audit, and merge skills.
- Added explicit retained-state reporting for Scorecard maturity gaps in publish, ship, and audit flows.
- Compressed repeated skill policy text into a synced shared core block.
- Added explicit skill boundaries and handoff rules between publish, ship, audit, dependencies-maintenance, and merge flows.
- Added `templates/common-core.md` and `scripts/sync-skill-core.py` so shared policy text stays consistent across skills.
- Updated validation and CI to enforce common-core sync.
- Narrowed `ceratops-code` ownership preference to explicit Ceratops context instead of acting as a universal default.

## 0.1.0 - 2026-04-18

- Initial public release of five Ceratops GitHub workflow skills.
- Added Codex metadata for each skill.
- Added repository validation, GitHub Actions CI, CodeQL workflow, Dependabot config, security policy, contribution docs, issue forms, pull request template, and CODEOWNERS.
