# Skills Refactor Backlog

Status: partially implemented; retained for future governance candidates.

Goal: keep routine skill updates cheap and scoped, while moving broad
consistency validation into scheduled governance automation or explicitly
requested full validation.

## 1. Routine Skill-Update Policy

- Regular skill-local text, metadata, and docs edits should use targeted
  readback, stale-reference search, and diff review.
- Shared section or manifest edits should run only the shared-source check path.
- Helper changes should run only the touched helper smoke check.
- Runtime-generation changes should run only the runtime-generation smoke check
  unless a generated runtime preview is explicitly requested.
- Full validation should be reserved for governance automation,
  validation-script changes, explicit broad verification, or a concrete
  cross-surface uncertainty.

## 2. Weekly Governance Candidates

### 2.1. Contract Ownership Validator

Implement as a governance validation mode, not as a routine skill-update gate.

Inputs:

- `contracts/github/github-repo-deterministic-contract.json`
- `contracts/code/code-repo-deterministic-contract.json`
- `contracts/artifacts/artifact-deterministic-contract.json`
- `scripts/validation/github-validate-repo-artifact-contract.py`

Checks:

- GitHub repo contract IDs stay on live GitHub settings, security, Actions,
  rulesets, queues, labels, and stale GitHub state.
- Code repo contract IDs stay on repo contents, local files, workflows,
  Dependabot config, CODEOWNERS, local git state, local path references, and
  local secret-pattern scans.
- Artifact contract IDs stay on external packages, images, registry metadata,
  provenance, trusted publishing, release assets, and consumer verification.
- Checker implementation has no dead comparison branches for IDs no contract
  owns.

Run when:

- weekly governance automation runs
- a repo/code/artifact contract file changes
- the contract checker changes
- a split-ownership regression is suspected

### 2.2. Skill Scope Validator

Implement as a selective governance scan, not a mandatory per-edit check.

Inputs:

- `skills/ceratops-gh-repo-lifecycle/SKILL.md`
- `skills/ceratops-gh-repo-lifecycle/references/*.md`
- `templates/skill-sections.json`

Checks:

- `merge-pr` action does not use full repo or artifact contract checks for
  normal merge-only work.
- `dependency-maintenance` action uses dependency-scoped repo and code
  selections and does not run artifact checks unless a release or publish is
  actually in scope.
- `ship-change` action keeps narrow GitHub, code, and artifact contract
  selections instead of defaulting to full health checks.
- `create-or-publish` and `health-audit` actions may use full checks because
  their purpose is broad setup or broad audit.
- Contract-review workflow reviews contracts and source docs, but does not run
  per-repo health as if it were auditing a target repo.

Run when:

- weekly governance automation runs
- a GH lifecycle router command example, action reference, or completion gate
  changes
- lifecycle routing rules change

### 2.3. ND Evidence Coverage Validator

Implement as a selective governance scan, not a mandatory per-edit check.

Inputs:

- `contracts/github/*-nondeterministic-contract.md`
- `contracts/code/*-nondeterministic-contract.md`
- `contracts/artifacts/*-nondeterministic-contract.md`
- `scripts/validation/github-collect-nd-evidence.py`

Checks:

- Every `ND.*` ID in a nondeterministic check file has a matching evidence
  mapping.
- Every evidence mapping points to an existing evidence key or documented
  external/manual source.
- Obsolete mappings without a corresponding nondeterministic check are reported.

Run when:

- weekly governance automation runs
- a nondeterministic check file changes
- `scripts/validation/github-collect-nd-evidence.py` changes

### 2.4. Runtime Payload Consistency

Prefer prevention through deterministic copy rules over frequent validation.

Implementation direction:

- Keep GH skills that can need contract evidence carrying `contracts/` and the
  relevant helper scripts as manifest payloads.
- Keep code-consistency audit carrying only the code comment rubric it needs.
- If a validator is added, run it in weekly governance or when
  `templates/skill-sections.json` changes, not for every skill text edit.

Run when:

- weekly governance automation runs
- runtime payload manifest changes
- install/build scripts change

### 2.5. Code Comment Sufficiency

Do not implement as a deterministic checker now.

Implementation direction:

- Treat `contracts/code/code-comment-nondeterministic-contract.md` as a
  nondeterministic review rubric.
- Use it during `ceratops-code-consistency-audit`.
- Do not run it during ordinary implementation, shipping, or skill update work
  unless the task is explicitly a consistency audit or comment sufficiency
  review.

### 2.6. Handoff Section Regression

Do not implement a validator.

Current action is enough:

- stale shared section removed
- stale manifest assignment removed
- handoff skills carry their own first-step refresh behavior directly

## 3. Side-Task Handoff Prompt

Use this prompt if the governance validators should be implemented later:

```text
Implement the remaining selective Ceratops skill governance validation in the skills repo. Keep routine skill updates minimal. Add or refine governance-only or change-triggered checks for contract ownership, lifecycle router action scope usage, nondeterministic evidence coverage, and runtime payload consistency. Do not add a handoff-section regression validator or deterministic code-comment checker. Treat contracts/code/code-comment-nondeterministic-contract.md as a nondeterministic rubric used by ceratops-code-consistency-audit only. Start from backlog/skills-refactor-backlog.md and update scripts, templates/skill-sections.json, README.md, and relevant skills only where the backlog says a validator should exist.
```
