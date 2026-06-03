# Contracts Review Action

## Goal

Review GitHub org, GitHub repo, PR readiness, repo-code, artifact registry, and
release contract surfaces owned by `ceratops-gh-repo-lifecycle`. Compare
skill-local contract references, checker scripts, current official docs, local
repo evidence, live GitHub evidence, and registry metadata, then report proposed
contract or checker updates for explicit approval before repo changes are
applied.

## Context

### Script Bundle

- (D) GH contract consistency check: `python
  skills/ceratops-gh-repo-lifecycle/scripts/validate-gh-contracts-consistency.py`
- (D) Org contract checker: `python
  skills/ceratops-gh-repo-lifecycle/scripts/github-validate-org-contract.py
  --help`
- (D) GitHub, code, and artifact contract checker: `python
  skills/ceratops-gh-repo-lifecycle/scripts/github-validate-repo-artifact-contract.py
  --help`
- (D) PR readiness contract checker: `python
  skills/ceratops-gh-repo-lifecycle/scripts/github-validate-pr-readiness-contract.py
  --help`
- (D) Non-deterministic evidence collector: `python
  skills/ceratops-gh-repo-lifecycle/scripts/github-collect-nd-evidence.py
  --help`
- (D) Source-doc registry checker: `python
  skills/ceratops-gh-repo-lifecycle/scripts/github-check-source-docs.py
  --help`

### References

- Contract source-doc registry: `references/contract-source-docs.json`
- Org deterministic contract:
  `references/github-org-deterministic-contract.json`
- GitHub repo deterministic contract:
  `references/github-repo-deterministic-contract.json`
- GitHub PR readiness deterministic contract:
  `references/github-pr-readiness-deterministic-contract.json`
- Code repo deterministic contract:
  `references/code-repo-deterministic-contract.json`
- Artifact deterministic contract:
  `references/artifact-deterministic-contract.json`
- Non-deterministic review prompts: `references/*-nondeterministic-contract.md`
- Code comment rubric: `references/code-comment-nondeterministic-contract.md`

### Inputs To Capture

- Whether the run is routine contract upkeep or an explicit user-requested
  contract refresh.
- Which contract surfaces are actually in scope: GitHub org settings, live
  GitHub repo state, repo-content expectations, workflow hardening, release
  posture, artifact types supported by this lifecycle action set, or a
  documented no-artifact posture.
- The official docs, live API evidence, package metadata, registry metadata, or
  reference repositories used for standards comparison and which concrete
  standards question each one informed.
- Which proposed changes require explicit approval and which findings require no
  repo change.

Infer missing inputs from local repo state, live GitHub evidence, and the active
request before asking.

## Constraints

### Boundaries

- Use this action when the task is GitHub, code, PR readiness, artifact,
  registry, release, or org contract review rather than lifecycle execution.
- Do not use this action to audit or repair the health of a specific repository.
  Use live GitHub, registry, official-doc, or reference-repo evidence only when
  needed to decide whether a contract claim is current.
- Do not inspect skill consistency, skill governance, skill-design contracts,
  metadata alignment, shared-section alignment, or runtime payload review here;
  those belong to `$ceratops-skill-lifecycle`
  `skills-consistency-and-contract-review`.
- If the task is normal repo shipping, PR handling, dependency updates,
  repo-health work, or already-prepared skill shipping rather than contract
  upkeep, return to this router and select the lifecycle action that owns the
  work.

### Skill-Specific Rules

- Routine runs must perform a bounded contract review across GitHub org, GitHub
  repo state, repo-content, workflow, security, artifact-publishing, and release
  surfaces already represented in this action's `references/`.
- Review current official docs, live product behavior, official API or registry
  metadata, and at most 2-3 current public third-party GitHub reference
  repositories only for a concrete standards question surfaced by local
  contract, checker, source-registry, live API, or approval-relevant ambiguity
  evidence.
- Use reference repositories only as pattern examples, not as health-audit
  targets, and separate no-extra-cost defaults from paid GitHub Code Security or
  Secret Protection features.
- Treat artifact surfaces as in scope only when
  `references/artifact-deterministic-contract.json` or this lifecycle action set
  claims to cover them.
- Keep durable standards in the skill-local contracts and
  `references/contract-source-docs.json`; do not recreate a separate standards
  checklist file.
- If a recommendation would widen contract scope beyond supported GH lifecycle
  surfaces, change default GitHub policy, change merge or review posture, change
  security posture, add mandatory paid features, or materially alter checker
  behavior, report it as approval-required and do not apply it without explicit
  approval.

## Workflow

### 1. Inspect Local Contract State

- Inspect current repo branch, worktree state, this action's `references/`, the
  contract checker scripts, repo docs that describe contract structure, and
  installed automation prompt when this run came from automation.
- Check GitHub auth, local git auth, and installed tooling before asking for
  credentials.
- Run `validate-gh-contracts-consistency.py` before manual review. If it fails,
  classify each finding as stale local dirt, proposed in-scope change,
  approval-required change, or not applicable.

### 2. Refresh Current Source Evidence

- Read `references/contract-source-docs.json` and the affected contract files at
  the start of the audit and use them as the bounded checklist for the next
  evidence-gathering steps.
- Run `github-check-source-docs.py --json` before ad hoc source-doc URL checks;
  treat fallback-only transport failures as execution-context evidence.
- Use local files, `gh`, GitHub API, `gh` help, package metadata, release
  metadata, and registry endpoints as the first-pass evidence for the GitHub or
  artifact behavior that the contracts encode.
- Check current official GitHub docs for repository-management settings,
  workflow policy, rulesets, Actions, security, release behavior, and
  repository-content expectations wherever the next contract decision depends on
  them.
- Check current official Docker, GHCR, PyPI, npm, or Python packaging docs only
  for artifact surfaces that are actually in scope.

### 3. Audit The Contracts

- Review this action's `references/` and checker scripts only where a contract
  claim depends on them.
- Look for duplicate guidance, contradictory defaults, stale GitHub setting
  names, stale required-file assumptions, stale repository-health expectations,
  stale workflow hardening guidance, stale artifact-publishing guidance,
  deterministic logic trapped in prose, partial follow-through, or logic that
  belongs in a contract rather than prose.
- Review validation-surface drift when validation contracts or guidance are in
  scope: docs, CI steps, linter and type-check configs, dependency pins, and
  helper validation claims must describe the same direct validation surface.
- Keep repo docs aligned when stale: `README.md`, `CONTRIBUTING.md`, and
  `CHANGELOG.md`.

### 4. Prepare Approval Request

- Prepare exact proposed contract or checker updates that align behavior with
  current official GitHub or registry terms.
- Prepare exact proposed file-reference updates when standard repo files, GitHub
  settings, workflow surfaces, or artifact-publish expectations were added,
  removed, or renamed.
- Prepare exact proposed low-risk deduplication or refactoring inside the
  contracts that preserves behavior and clarifies ownership between
  deterministic JSON, non-deterministic review prompts, contract-structure docs,
  and checker scripts.
- Prepare exact proposed source-doc registry updates when the contract needs a
  durable source that would otherwise bloat contract prose.
- Do not apply any proposed change until the user explicitly approves that
  change.

### 5. Align Touched References

- If explicitly approved changes alter this action's `references/`, contract
  checker scripts, `references/contract-source-docs.json`, or repo docs that
  describe contract structure, use targeted readback, stale-reference search,
  and diff review for the touched scope.
- If explicitly approved changes alter copied helper scripts or helper-runtime
  claims, run only the touched helper's own smoke command when that helper
  supports one.
- Verify changed contracts, contract checker scripts, source-doc registry, and
  contract-structure docs point at the current source of truth.

## Done When

### Completion Gate

- Verify every changed in-scope contract artifact has targeted same-surface
  evidence.
- Verify repo changes remain in the worktree unless this contract-review task
  explicitly included another approved local mutation.
- Verify changed contracts, checker scripts, source-doc registry, and
  contract-structure docs remain aligned.

### Output Contract

Report only:

- applied explicitly approved contract or checker updates
- approval-required recommendations, blockers, or non-blocking debt
- intentionally retained leftovers or exceptions with reasons
- anything important not verified
