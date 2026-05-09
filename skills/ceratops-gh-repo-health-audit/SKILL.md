---
name: ceratops-gh-repo-health-audit
description: Audit and repair GitHub repository health with Ceratops defaults, using scripted live checks first for machine-checkable GitHub settings.
---

# Ceratops GH Repo Health Audit

## Goal

Validate that an existing GitHub repo is clean, current, secure, documented, published, and not carrying leftover workflow debris. Apply low-risk reversible fixes directly and report risky, ambiguous, destructive, paid, or credential-bound fixes precisely. Treat the GitHub repo, code repo, and artifact contracts as the first source of truth for machine-checkable health.

## Context

### Script Bundle

- (D) Full GitHub, code, and artifact contract check: `python scripts/validation/github-validate-repo-artifact-contract.py --repo OWNER/REPO --surface all --subset health --local-repo-path PATH`
- (D) Optional org contract check when org posture is in scope: `python scripts/validation/github-validate-org-contract.py --org ORG`
- (D) Add `--json` when another step needs structured findings, and add `--check-id` or a narrower `--subset` when only part of the contract is relevant.

### Inputs To Capture

- Target repo and any expected posture that differs from the GitHub repo, code repo, or artifact contracts.
- Local repo path and local consumers needed to classify stale or risky side effects.

Infer missing inputs from live repo state and local files before asking.

## Constraints

### Boundaries

- Use this skill when the task is primarily validation, stale-state cleanup, or safe repo-health repair and the repo has live GitHub state worth machine-checking.
- Do not use this skill as a routine rubber-stamp closeout pass after normal ship, dependencies-maintenance, or merge flows. Those skills should run only the narrow repo-health checks their own result actually needs.
- If the repo is not yet published, still needs first-time hardening, needs normal PR and release flow, or only needs PR finalization, stop because that work is outside this repo-health audit skill's scope.

### Workflow

#### 1. Inspect local and live state

- Inspect git status, remotes, branches, refs, tags, releases, generated files, artifacts, temp paths, package outputs, and local consumer references.
- Capture only the live GitHub metadata needed to run and interpret the contract check: default branch, visibility, security settings, branch protection or rulesets, and community profile when relevant.
- Inspect local workflow files when they are available so mutable external action refs are classified instead of inferred from repo settings alone.
- Expand to open PRs, releases, tags, branches, Actions runs, moderation detail, or published artifacts only when the script output, repo type, touched files, or the user's request makes them relevant.

#### 2. Run live contract checks first

- (D) Run the full GitHub, code, and artifact contract checker before treating repo health as clean.
- (D) Treat the contract checker output as the source of truth for machine-checkable GitHub settings, repo-content posture, stale queues, local checks, and artifact registry evidence.
- If the checker reports a warning, manual finding, or blind spot, decide whether the gap is acceptable, needs a manual follow-up, or should be fixed now.

#### 3. Research only when the next decision needs it

- Check current official docs only where local files, live contract state, and the shared contracts leave the next fix or decision unresolved.
- Compare at most 1-2 strong current reference repos only for a concrete ambiguous files, metadata, workflow, security, or release question. Do not do broad GitHub health contract maintenance during routine repo audits.
- Use prose-only checks or the web UI only for settings that the bundled script or free APIs cannot currently verify.

#### 4. Audit repo health

- Verify the GitHub repo, code repo, and artifact contracts for the in-scope repo.
- When repo-tracked docs, configs, workflows, or automation prompts are intended for public GitHub, treat user-local absolute filesystem paths as a health gap and replace them with repo-relative paths or portable variables such as `$CODEX_HOME` unless an external runtime explicitly requires a local absolute path.

#### 5. Repair safe gaps

- Apply low-risk reversible fixes directly. Treat a successful mutation command as evidence for that exact setting or file change; rerun the contract checker only for uncertain state, asynchronous effects, or a broader clean-health claim.
- Open or update a PR for repo changes when branch protection or repo policy requires it.
- Do not delete tags, releases, packages, protected branches, backup branches, or external artifacts unless the stale classification is proven and the action is safe or explicitly approved.

#### 6. Validate and close

- Run the local checks needed to prove any repo-file changes are still valid.
- Verify live GitHub and registry state when it was not already proven by the successful command result or when asynchronous external state matters.
- Re-run the relevant contract checks at the end only for unresolved audit scope or broad health claims; otherwise classify remaining findings from command-result evidence, retained drift, blockers, or not-applicable state.

## Done When

### Completion Gate

- Verify the final answer with `scripts/validation/github-validate-repo-artifact-contract.py` only when making a broad current-health claim not already proven by command-result evidence.
- Verify any Actions hardening claim is backed by a fresh local workflow scan when the repo files were available in the run.
- Verify touched live state only when command-result evidence is insufficient for the final claim, state is asynchronous, or a broader audit remains in scope.
- Verify local state for every touched repo, worktree, generated file, artifact, temp path, cache, credential change, local consumer path, shortcut, scheduled task, service, shell profile, and cleanup side effect.

### Output Contract

Report only:

- health gaps fixed
- alerts or findings left open with name or id, blocking status, why they remain open, and the concrete work needed to clear them
- health gaps intentionally retained with exact reasons
- remaining blockers or credential steps
- anything important not verified
- paid requirement with product, reason, and price if encountered

### Example Invocation

`Use $ceratops-gh-repo-health-audit. Run the GitHub health contract checks first, fix safe repo-health gaps, and report only real blockers.`
