# Ceratops Codex Skills

Reusable Ceratops skills for Codex and other `SKILL.md`-compatible agents.

## Skills

| Skill | Purpose |
| --- | --- |
| `ceratops-gh-repo-create-and-publish` | Create or production-harden a public GitHub repo and publish the right artifact target when relevant. |
| `ceratops-gh-ship-change` | Ship repo changes through PR, CI, merge, artifact publishing when relevant, and cleanup. |
| `ceratops-gh-repo-dependencies-maintenance` | Maintain Dependabot, Renovate, security, and manual dependency work recursively. |
| `ceratops-gh-repo-health-audit` | Audit and repair GitHub repo health, security posture, stale state, and publication gaps. |
| `ceratops-gh-merge-pr` | Safely merge a GitHub PR, verify checks and protection with live scripted readiness checks, clean up branches, and sync local state. |
| `ceratops-contract-review` | Review the GitHub, code, PR readiness, and artifact health contracts against current standards, then report proposed updates for explicit approval. |
| `ceratops-produce-rule-update` | Produce durable rule or instruction updates from concrete failures or instruction gaps. |
| `ceratops-rule-optimizer` | Optimize durable rule text after a concrete failure, gap, or weak candidate. |
| `ceratops-fixloop-breaker` | Break repeated failed fix loops by requiring a run-by-run failure analysis before more code changes. |
| `ceratops-rework-analysis` | Analyze recent Codex runs for deterministic rework causes and recommend low-maintenance producer controls. |
| `ceratops-prompt-optimizer` | Rewrite rough prompts into clearer structured prompts without changing intent. |
| `ceratops-skill-optimize` | Propose targeted skill updates without applying edits. |
| `ceratops-skill-create` | Create a new Ceratops or compatible skill, using templates, validation, metadata, and runtime preview only when the repo provides them. |
| `ceratops-skill-update` | Update existing Ceratops or compatible skills, using shared sections, generation, validation, helper claims, and docs only when present. |
| `ceratops-skill-fast-change` | Apply a simple known-safe skill change directly on a release branch and update only the affected runtime skill. |
| `ceratops-automation-run` | Run recurring automations with shared Ceratops alert, memory, and completion policy. |
| `ceratops-task-execute-in-stages` | Drive substantial tasks stage by stage, preferring the simplest standard fix and asking before complex paths. |
| `ceratops-code-consistency-audit` | Audit merged refactors for contradictions, docs drift, comment sufficiency, stale follow-through, and merged-only edge cases. |
| `ceratops-thread-resume-manual-stop` | Resume a same-thread task from current local state after a stop, restart, or crash without rebuilding everything from scratch. |
| `ceratops-thread-full-handoff` | Create a copy-paste prompt for moving a whole task into a new thread without re-auditing the whole task. |
| `ceratops-thread-side-task-handoff` | Create a minimal copy-paste prompt for spinning a newly discovered side task into a new thread. |
| `ceratops-codex-skill-stage-release` | Merge ready skill branches into a skill repo `release/*` branch and run only the install or validation steps the repo provides. |
| `ceratops-gh-codex-skill-ship` | Ship staged skills repo changes through GitHub, then restore the skills repo checkout and installed skills to clean `main`. |

## Layout

```text
assets/
  ceratops-logo-500.png
backlog/
  skills-refactor-backlog.md
skills/
  <skill-name>/
    SKILL.md
    agents/openai.yaml
    assets/
      ceratops-logo-500.png
templates/
  skill-sections.json
  sections/
    core.md
    gh-current-state.md
    gh-repo-health-contract.md
    gh-artifact-contract.md
    release-branch-runtime.md
contracts/
  source-docs.json
  code/
    code-repo-deterministic-contract.json
    code-repo-nondeterministic-contract.md
    code-comment-nondeterministic-contract.md
  artifacts/
    artifact-deterministic-contract.json
    artifact-nondeterministic-contract.md
  github/
    github-org-deterministic-contract.json
    github-pr-readiness-deterministic-contract.json
    github-repo-deterministic-contract.json
    github-org-nondeterministic-contract.md
    github-pr-readiness-nondeterministic-contract.md
    github-repo-nondeterministic-contract.md
```

Source `SKILL.md` files are portable, delta-only skill definitions. Runtime `SKILL.md` files are generated during install by expanding the shared section assignments from `templates/skill-sections.json`.
`agents/openai.yaml` is Codex UI metadata and may be ignored by other agents.
Each Ceratops skill declares the runtime-local icon path `./assets/ceratops-logo-500.png`. The repo-root `assets/ceratops-logo-500.png` is the source copied into each skill by `scripts/install-skills.ps1`.
GitHub helper logic lives in copied scripts under `scripts/`, not in an installed Python package.
`contracts/` is the source of truth for deterministic GitHub org/repo checks, repo-content checks, PR readiness checks, external artifact registry checks, non-deterministic review prompts, source-doc tracking, and the local code-comment review rubric. `skills/ceratops-contract-review/` reviews and updates the GitHub, code, PR readiness, and registry contracts when official standards change.

## Scripts

| Script | Caller And Timing |
| --- | --- |
| `scripts/install-skills.ps1` | Single public entrypoint for installing/updating managed skill copies and optionally running section or full skill consistency validation. |
| `scripts/render-runtime-skills.py` | Internal implementation called by the installer to render runtime `SKILL.md` files and copy declared payloads. |
| `scripts/validation/github-validate-pr-readiness-contract.py` | Called before PR merge decisions to validate the live PR readiness contract. |
| `scripts/validation/validate-skills-consistency.py` | Internal implementation called by CI or `install-skills.ps1 -Validate ...` for section/full consistency checks. |
| `scripts/validation/github-validate-org-contract.py` | Called by org setup, org health, and standards review work when org settings need a bundled deterministic audit. |
| `scripts/validation/github-validate-repo-artifact-contract.py` | Called by repo create, repo health, dependency, and standards review work when repo settings, code, or artifact posture needs a deterministic audit. |
| `scripts/validation/github-collect-nd-evidence.py` | Called when non-deterministic org, repo, code, or artifact checks need one bundled evidence payload for human review. |

Release-branch preparation and pending-work cleanup use stage-release-only helpers
inside `skills/ceratops-codex-skill-stage-release/scripts/`. This repo keeps
scripts only where they add reusable safety logic or bundle nontrivial evidence
collection.

## Health Contracts

The health contract structure is split by the surface being checked:

- `contracts/source-docs.json` records official source documents and reference repositories used by the GitHub, repo, and registry contracts.
- `contracts/github/github-org-deterministic-contract.json` defines deterministic organization settings, policy, identity, security, Dependabot, and default-logo/custom-logo checks.
- `contracts/github/github-repo-deterministic-contract.json` defines deterministic live GitHub repository settings, security, branch/ruleset, Actions policy, queues, releases, and stale GitHub state checks.
- `contracts/github/github-pr-readiness-deterministic-contract.json` defines deterministic live PR readiness checks used before merge and auto-merge decisions.
- `contracts/code/code-repo-deterministic-contract.json` defines deterministic repository-content checks for files, workflow text, Dependabot config, CODEOWNERS, local git state, local path references, and secret-pattern scans.
- `contracts/artifacts/artifact-deterministic-contract.json` defines external artifact checks for PyPI, npm, DockerHub or OCI registries, GitHub Container Registry, GitHub releases, docs sites, and other package registries.
- `contracts/*/*-nondeterministic-contract.md` files capture checks that need intent judgment, prose review, manual browser confirmation, or current-doc interpretation after bundled evidence is collected.

Run deterministic checks with bundled selections instead of one command per setting:

```powershell
python .\scripts\validation\github-validate-org-contract.py --org ORG --subset all
python .\scripts\validation\github-validate-repo-artifact-contract.py --repo OWNER/REPO --surface repo --subset settings --local-repo-path .
python .\scripts\validation\github-validate-repo-artifact-contract.py --repo OWNER/REPO --surface code --subset content --local-repo-path .
python .\scripts\validation\github-validate-repo-artifact-contract.py --repo OWNER/REPO --select repo:dependency --select code:dependency --local-repo-path .
python .\scripts\validation\github-validate-repo-artifact-contract.py --repo OWNER/REPO --surface artifact --subset artifact --local-repo-path .
python .\scripts\validation\github-validate-pr-readiness-contract.py --pr NUMBER_OR_URL
```

Collect review evidence for non-deterministic checks with:

```powershell
python .\scripts\validation\github-collect-nd-evidence.py --surface org --org ORG --json
python .\scripts\validation\github-collect-nd-evidence.py --surface repo --repo OWNER/REPO --local-repo-path . --json
python .\scripts\validation\github-collect-nd-evidence.py --surface code --repo OWNER/REPO --local-repo-path . --json
python .\scripts\validation\github-collect-nd-evidence.py --surface artifact --repo OWNER/REPO --local-repo-path . --json
python .\scripts\validation\github-collect-nd-evidence.py --surface pr --pr NUMBER_OR_URL --local-repo-path . --json
```

Contract surfaces select the area being checked. They are read by
`github-validate-repo-artifact-contract.py` and
`github-collect-nd-evidence.py`; skills pass a surface only when they are doing an
explicit audit, drift check, uncertain-state check, or broad closeout claim.

| Surface | Runs When |
| --- | --- |
| `org` | GitHub organization settings, org security policy, org Actions policy, teams, roles, identity, and org-level Dependabot posture need an audit. |
| `repo` | Live GitHub repository settings, Actions policy, security toggles, rulesets, labels, releases, queues, and other GitHub-hosted repo state need an audit. |
| `code` | Repository contents, workflows, Dependabot config, CODEOWNERS, local git state, local path references, or local secret-pattern posture need an audit. |
| `artifact` | External deliverables or registry state such as PyPI, npm, DockerHub, GHCR, release assets, or docs publishing need an audit. |
| `pr` | A live PR merge or auto-merge decision needs fresh readiness evidence. |
| `all` | Full repo health, repo creation, or explicitly broad governance review is in scope. |

When one workflow needs both live GitHub repository state and repository
contents, use repeatable `--select surface:subset` entries in one validator
process. Do not rely on a combined repo-plus-code surface.

Subsets are optional audit filters for explicit contract runs. They narrow
check IDs inside the selected surface. They do not mean regular skill maintenance
should run contract checks after every change.

| Subset | Runs When |
| --- | --- |
| `settings` | Only GitHub repo settings or process settings are in scope. |
| `dependency` | Dependabot, vulnerability alerts, dependency-review, dependency labels, or dependency update posture is in scope. |
| `content` | Repo files and workflow policy are in scope without live GitHub settings or artifacts. |
| `artifact` | Artifact classification, publish workflow, registry metadata, provenance, and consumer evidence are in scope. |
| `create` | Initial repo creation or production hardening is in scope; stale-state-only checks are skipped. |
| `health` | Full health audit is in scope. |
| `all` | No workflow narrowing is applied. |

Common intended combinations:

| Command Surface | Command Subset | Who Runs It |
| --- | --- | --- |
| org validator, implicit org surface | `settings` | `$ceratops-contract-review`; `$ceratops-gh-repo-health-audit` only when org posture is part of the audit. |
| org validator, implicit org surface | `actions` | `$ceratops-contract-review`; `$ceratops-gh-repo-health-audit` only when org Actions posture is part of the audit. |
| org validator, implicit org surface | `dependabot` | `$ceratops-contract-review`; `$ceratops-gh-repo-health-audit` only when org Dependabot posture is part of the audit. |
| org validator, implicit org surface | `security` | `$ceratops-contract-review`; `$ceratops-gh-repo-health-audit` only when org security posture is part of the audit. |
| org validator, implicit org surface | `all` | `$ceratops-contract-review` for governance review; `$ceratops-gh-repo-health-audit` only for explicit broad org health. |
| `repo` | `settings` | `$ceratops-gh-repo-health-audit` and `$ceratops-contract-review` when live repo state is part of the task. |
| `repo` + `code` via `--select repo:dependency --select code:dependency` | `dependency` | `$ceratops-gh-repo-dependencies-maintenance` when both live GitHub dependency/security posture and repo-content dependency posture are in scope; `$ceratops-gh-repo-health-audit` for dependency posture audits. |
| `code` | `content` | `$ceratops-gh-repo-health-audit`, `$ceratops-gh-repo-create-and-publish`, and `$ceratops-contract-review` when repo contents are part of the task. |
| `artifact` | `artifact` | `$ceratops-gh-repo-health-audit`, `$ceratops-gh-repo-create-and-publish`, and `$ceratops-contract-review` when a published artifact is part of the task. |
| `all` | `create` | `$ceratops-gh-repo-create-and-publish`. |
| `all` | `health` | `$ceratops-gh-repo-health-audit`; `$ceratops-contract-review` only for broad contract governance. |
| PR validator, implicit PR surface | none | `$ceratops-gh-merge-pr`, `$ceratops-gh-repo-dependencies-maintenance`, and `$ceratops-gh-codex-skill-ship` before merge or auto-merge decisions. |

A successful mutation command is enough evidence for that exact mutation. Re-run a validator only for drift/audit work, uncertain state, broader closure claims, or checks not already proven by the successful command.

`contracts/code/code-comment-nondeterministic-contract.md` is a non-deterministic local review rubric for comment sufficiency. It avoids repeated live research during code-consistency audits and is not part of routine ongoing-work validation.

## Install For Codex

Codex discovers personal skills from:

```text
$CODEX_HOME/skills/<skill-name>/SKILL.md
```

Run one explicit bootstrap step from the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-skills.ps1
```

That bootstrap does two things explicitly:

- refreshes each skill-local Ceratops icon from the repo-root icon source
- builds managed runtime skill copies under `$CODEX_HOME/skills/`

Installed Ceratops skills should be generated from the skills repo checkout: the local skills repo checkout used as the input path for `scripts/install-skills.ps1`. The active branch only selects which repo snapshot is installed: synced `main` for normal use, or a local `release/*` branch for an active unpublished preview. After changing the installed source snapshot, rerun `scripts/install-skills.ps1` so new, renamed, or deleted managed skill folders match that snapshot.
When shipping a staged batch, reuse the same `release/local` branch name locally and remotely by default. GitHub may delete the remote `release/local` after merge; the next batch simply recreates that same remote branch from the current local `release/local`.

Restart Codex after adding new skill folders if the app does not pick them up automatically.

## Install For Claude Code

Claude Code uses the same core `SKILL.md` folder format. Copy or link a skill folder into:

```text
$HOME/.claude/skills/<skill-name>/SKILL.md
```

Invoke skills directly with `/skill-name` in Claude Code. In Codex, invoke them with `$skill-name`.

## Validate

Run full validation through the public entrypoint and render generated runtime skills into a disposable output folder:

```powershell
$runtimeRoot = Join-Path ([System.IO.Path]::GetTempPath()) "ceratops-runtime-skills"
powershell -ExecutionPolicy Bypass -File .\scripts\install-skills.ps1 -RuntimeRoot $runtimeRoot -Validate full
```

Run `powershell -ExecutionPolicy Bypass -File .\scripts\install-skills.ps1 -SkipInstall -Validate sections` only when shared section source files or `templates/skill-sections.json` assignments changed. The section mode validates that source skills are delta-only; `scripts/render-runtime-skills.py` performs runtime shared-section expansion during install.
`templates/skill-sections.json` records the core same-surface maintenance-check policy for regular work and a separate full-validation command set for governance automation.
The renderer composes each runtime skill's shared block from `templates/skill-sections.json` and `templates/sections/`, and each generated runtime `SKILL.md` block includes section-source comments so the origin of every shared section stays visible in the installed skill copy. The validator checks skill frontmatter, folder/name consistency, section assignments, runtime-renderability, Codex metadata, placeholder leftovers, real README skill rows, cross-skill references, maintenance-workflow targets, contract presence, and high-confidence secret patterns.
Run helper `--help` smoke checks only for touched helper scripts or touched helper claims. Full validation is intended for governance automation or explicit broad verification, not every regular skill update. With working GitHub auth, use `scripts/validation/github-validate-org-contract.py` and `scripts/validation/github-validate-repo-artifact-contract.py` for deterministic GitHub, code, and artifact contract checks.

## Releases

Releases use `vMAJOR.MINOR.PATCH` tags. See `CHANGELOG.md` for release notes.

## Artifact Publishing

This repository publishes skill source files only. It does not publish Docker images, PyPI packages, npm packages, or other runtime artifacts.
