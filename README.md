# Ceratops Codex Skills

Reusable Ceratops skills for Codex and other `SKILL.md`-compatible agents.

## Skills

| Skill | Purpose |
| --- | --- |
| `ceratops-gh-repo-lifecycle` | Route GitHub repo lifecycle work across create-or-publish, contracts-review, health-audit, dependency-maintenance, ship-change, and merge-pr actions. |
| `ceratops-propose-rules-update` | Design compact, regression-safe changes across interacting instruction scopes. |
| `ceratops-credit-savings-analysis` | Analyze recent Codex runs for avoidable credit spend and recommend low-maintenance controls. |
| `ceratops-prompt-optimizer` | Rewrite rough prompts into clearer structured prompts without changing intent. |
| `ceratops-skill-optimize` | Propose advisory-only improvements across skill text, action references, metadata, payloads, validators, and docs. |
| `ceratops-skill-lifecycle` | Route skill lifecycle work across create, update, skills-contract-review, global-skills-consistency-review, fast-change, change-promotion, and ship-to-remote actions. |
| `ceratops-automation-run` | Run recurring automations with shared Ceratops alert, memory, and completion policy. |
| `ceratops-task-lifecycle` | Route task execution, ChatGPT chat import, fix-loop break, same-thread resume, handoff, and closure-check work across action references. |
| `ceratops-code-consistency-audit` | Audit merged refactors for contradictions, docs drift, comment sufficiency, stale follow-through, and merged-only edge cases. |

## Layout

```text
assets/
  ceratops-logo-500.png
skills/
  <skill-name>/
    SKILL.md
    agents/openai.yaml
    assets/
      ceratops-logo-500.png
    scripts/
    references/
      <action-or-contract-reference>
templates/
  skill-sections.json
  sections/
    core.md
    multi-action-skill.md
```

Source `SKILL.md` files are portable, delta-only skill definitions. Runtime
`SKILL.md` files are generated during install by expanding the shared section
assignments from `templates/skill-sections.json`.
`core` is assigned to every skill; `multi-action-skill` is assigned only to
skills that select among multiple action references.
`agents/openai.yaml` is Codex UI metadata and may be ignored by other agents.
Each Ceratops skill declares the runtime-local icon path
`./assets/ceratops-logo-500.png`. The repo-root `assets/ceratops-logo-500.png`
is the source copied into each skill by the skill-lifecycle runtime installer.
Reusable helper logic lives in skill-local lifecycle scripts under
`skills/*/scripts/`, not in an installed Python package.
Contract sources live inside their owning lifecycle skill.
`skills/ceratops-gh-repo-lifecycle/references/` owns GitHub org, GitHub repo,
repo-code, PR readiness, artifact, release, and code-comment contracts plus the
`contracts-review` action. `skills/ceratops-skill-lifecycle/references/` owns
skill-design contracts, skill source-doc tracking, and the
`skills-contract-review` action. The source-neutral
`global-skills-consistency-review` action audits the active Codex skill catalog
without making that catalog a Ceratops contract surface.

## Scripts

| Script | Caller And Timing |
| --- | --- |
| `scripts/install-skills.ps1` | Bootstrap entrypoint for initial managed skill installation with direct full source validation. |
| `skills/ceratops-skill-lifecycle/scripts/runtime/install-managed-skills.ps1` | Skill-lifecycle runtime installer for refreshing managed skill copies during local preview, fast change, and ship flows. |
| `skills/ceratops-skill-lifecycle/scripts/runtime/render-runtime-skills.py` | Internal implementation called by the runtime installer to render runtime `SKILL.md` files and copy declared payloads. |
| `skills/ceratops-gh-repo-lifecycle/scripts/validate-gh-contracts-consistency.py` | Validates GH contract schema, assertion operators, observed-state producers, fetch coverage, remediation handlers, subsets, and non-deterministic evidence mappings. |
| `skills/ceratops-gh-repo-lifecycle/scripts/github-validate-pr-readiness-contract.py` | Called before PR merge decisions to validate the live PR readiness contract. |
| `skills/ceratops-gh-repo-lifecycle/scripts/github-codex-review-gate.py` | Called before PR merge decisions to wait for or resolve active Codex review threads. |
| `skills/ceratops-skill-lifecycle/scripts/validation/validate-skills-consistency.py` | Skill-lifecycle validator for section, full, and governance consistency checks. |
| `skills/ceratops-gh-repo-lifecycle/scripts/github-validate-org-deterministic-contract.py` | Called by org setup, org health, and standards review work when org settings need a bundled deterministic audit. |
| `skills/ceratops-gh-repo-lifecycle/scripts/github-validate-repo-artifact-contract.py` | Called by repo create, repo health, dependency, and standards review work when repo settings, code, or artifact posture needs a deterministic audit. |
| `skills/ceratops-gh-repo-lifecycle/scripts/github-collect-nd-evidence.py` | Called when non-deterministic org, repo, code, or artifact checks need one bundled evidence payload for review-owner classification. |
| `skills/ceratops-skill-lifecycle/scripts/stage-skill-release-branch.ps1` | Called by skill change-promotion to prepare `release/local`, merge reviewed branches, validate, clean merged work, and emit compact ready/not-ready JSON. |
| `skills/ceratops-skill-lifecycle/scripts/push-release-branch-and-ensure-pr.ps1` | Called by skill ship-to-remote to push `release/local`, create or reuse its PR, and emit compact PR JSON. |
| `skills/ceratops-gh-repo-lifecycle/scripts/validate-and-merge-pr.ps1` | Called by GH merge-pr to run PR readiness, Codex review gate, merge, live merge verification, and compact merge JSON. |
| `skills/ceratops-gh-repo-lifecycle/scripts/sync-main-after-pr.ps1` | Called after PR merge to fast-forward local `main`, optionally align reusable local branches, and emit compact sync JSON. |

Lifecycle helpers suppress successful subcommand output and print only compact
JSON on success. This repo keeps scripts only where they add reusable safety
logic or bundle nontrivial evidence collection.

## Contracts

The contract structure is split by the owning lifecycle skill:

- `skills/ceratops-gh-repo-lifecycle/references/contract-source-docs.json`
  records official source documents and reference repositories used by GitHub,
  repo, PR readiness, code, and artifact contracts.
- `skills/ceratops-gh-repo-lifecycle/references/contracts/github-org-deterministic-contract.json`
  defines deterministic organization settings, policy, identity, security,
  Dependabot, and default-logo/custom-logo checks.
- `skills/ceratops-gh-repo-lifecycle/references/contracts/github-repo-deterministic-contract.json`
  defines deterministic live GitHub repository settings, security,
  branch/ruleset, Actions policy, queues, releases, and stale GitHub state
  checks.
- `skills/ceratops-gh-repo-lifecycle/references/contracts/github-pr-readiness-deterministic-contract.json`
  defines deterministic live PR readiness checks used before merge and
  auto-merge decisions.
- `skills/ceratops-gh-repo-lifecycle/references/contracts/code-repo-deterministic-contract.json`
  defines deterministic repository-content checks for files, workflow text,
  Dependabot config, CODEOWNERS, local git state, local path references, and
  secret-pattern scans.
- `skills/ceratops-gh-repo-lifecycle/references/contracts/artifact-deterministic-contract.json`
  defines external artifact checks for PyPI, npm, DockerHub or OCI registries,
  GitHub Container Registry, GitHub releases, docs sites, and other package
  registries.
- `skills/ceratops-skill-lifecycle/references/skill-source-docs.json` records
  official skill-standard documents and installed OpenAI skill references used
  by skill-design contracts.
- `skills/ceratops-skill-lifecycle/references/contracts/skill-deterministic-contract.json`
  defines deterministic Ceratops skill checks for source structure, resource
  layout, metadata, shared-section generation, runtime payloads, public docs,
  portability, and contract presence.
- `skills/ceratops-gh-repo-lifecycle/references/contracts/*-nondeterministic-contract.json`
  and
  `skills/ceratops-skill-lifecycle/references/contracts/*-nondeterministic-contract.json`
  files capture checks that need intent judgment, prose review, browser
  confirmation, or current-doc interpretation after bundled evidence is
  collected.

Run deterministic checks with bundled selections instead of one command per
setting:

```powershell
python .\skills\ceratops-gh-repo-lifecycle\scripts\github-validate-org-deterministic-contract.py --org ORG --subset all
python .\skills\ceratops-gh-repo-lifecycle\scripts\github-validate-repo-artifact-contract.py --repo OWNER/REPO --surface repo --subset settings --local-repo-path .
python .\skills\ceratops-gh-repo-lifecycle\scripts\github-validate-repo-artifact-contract.py --repo OWNER/REPO --surface code --subset content --local-repo-path .
python .\skills\ceratops-gh-repo-lifecycle\scripts\github-validate-repo-artifact-contract.py --repo OWNER/REPO --select repo:dependency --select code:dependency --local-repo-path .
python .\skills\ceratops-gh-repo-lifecycle\scripts\github-validate-repo-artifact-contract.py --repo OWNER/REPO --surface artifact --subset artifact --local-repo-path .
python .\skills\ceratops-gh-repo-lifecycle\scripts\github-validate-repo-artifact-contract.py --repo OWNER/REPO --surface all --subset health --local-repo-path . --summary-json --levels ERROR,WARN,NEEDS_AI_AGENT_REVIEW
python .\skills\ceratops-gh-repo-lifecycle\scripts\github-validate-pr-readiness-contract.py --pr NUMBER_OR_URL
python .\skills\ceratops-gh-repo-lifecycle\scripts\validate-gh-contracts-consistency.py
python .\skills\ceratops-skill-lifecycle\scripts\validation\validate-skills-consistency.py --mode full
python .\skills\ceratops-skill-lifecycle\scripts\validation\validate-skills-consistency.py --mode governance
```

The organization and repository/artifact commands are thin entrypoints over the
shared `scripts/github_contract_engine/` state engine. `compose_desired_state.py`
selects and parameterizes the JSON contract assertions;
`collect_observed_states.py` calls reusable collectors once and composes one
observed-states JSON document; `compare_states.py` applies generic operators;
and `format_report.py` renders the result. Collectors produce facts rather than
per-check verdicts. GitHub remediations are separately registered under
`remediations/`; Docker Hub, PyPI, npm, Maven Central, NuGet, crates.io,
RubyGems, and PowerShell Gallery collectors are read-only.

GH lifecycle validators use `ERROR`, `WARN`, and `NEEDS_AI_AGENT_REVIEW` for
actionable findings. `ERROR` and `WARN` are blocking;
`NEEDS_AI_AGENT_REVIEW` is judgment-required evidence that the review owner must
classify before closure. Repo-health summary JSON includes compact stale-state
inventory counts and samples for PRs,
branches, tags, releases, and local path references when present; inventory
alone is not a finding.

Collect review evidence for non-deterministic checks with:

```powershell
python .\skills\ceratops-gh-repo-lifecycle\scripts\github-collect-nd-evidence.py --surface org --org ORG --json
python .\skills\ceratops-gh-repo-lifecycle\scripts\github-collect-nd-evidence.py --surface repo --repo OWNER/REPO --local-repo-path . --json
python .\skills\ceratops-gh-repo-lifecycle\scripts\github-collect-nd-evidence.py --surface code --repo OWNER/REPO --local-repo-path . --json
python .\skills\ceratops-gh-repo-lifecycle\scripts\github-collect-nd-evidence.py --surface artifact --repo OWNER/REPO --local-repo-path . --json
python .\skills\ceratops-gh-repo-lifecycle\scripts\github-collect-nd-evidence.py --surface pr --pr NUMBER_OR_URL --local-repo-path . --json
```

Contract surfaces select the area being checked. GitHub, code, artifact, and PR
surfaces are read by `github-validate-repo-artifact-contract.py`,
`github-validate-pr-readiness-contract.py`, and `github-collect-nd-evidence.py`.
The skill surface is represented by
`skills/ceratops-skill-lifecycle/references/skill-*` and
`skills/ceratops-skill-lifecycle/scripts/validation/validate-skills-consistency.py`.
Skills pass or choose a surface only when they are doing an explicit audit,
drift check, uncertain-state check, or broad closeout claim.

| Surface | Runs When |
| --- | --- |
| `org` | GitHub organization settings, org security policy, org Actions policy, teams, roles, identity, and org-level Dependabot posture need an audit. |
| `repo` | Live GitHub repository settings, Actions policy, security toggles, rulesets, labels, releases, queues, and other GitHub-hosted repo state need an audit. |
| `code` | Repository contents, workflows, Dependabot config, CODEOWNERS, local git state, local path references, or local secret-pattern posture need an audit. |
| `artifact` | External deliverables or registry state such as PyPI, npm, DockerHub, GHCR, release assets, or docs publishing need an audit. |
| `skill` | Ceratops skill source, metadata, shared-section, runtime payload, source-doc, installed-reference, or high-quality skill-design expectations need a contract audit. |
| `pr` | A live PR merge or auto-merge decision needs fresh readiness evidence. |
| `all` | Full repo health, repo creation, or explicitly broad governance review is in scope. |

When one workflow needs both live GitHub repository state and repository
contents, use repeatable `--select surface:subset` entries in one validator
process. Do not rely on a combined repo-plus-code surface.

Subsets are optional audit filters for explicit contract runs. They narrow
check IDs inside the selected surface. They do not mean regular skill
maintenance
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
| org validator, implicit org surface | `settings` | `$ceratops-gh-repo-lifecycle` contracts-review for contract governance; health-audit only when org posture is part of a live health audit. |
| org validator, implicit org surface | `actions` | `$ceratops-gh-repo-lifecycle` contracts-review for contract governance; health-audit only when org Actions posture is part of a live health audit. |
| org validator, implicit org surface | `dependabot` | `$ceratops-gh-repo-lifecycle` contracts-review for contract governance; health-audit only when org Dependabot posture is part of a live health audit. |
| org validator, implicit org surface | `security` | `$ceratops-gh-repo-lifecycle` contracts-review for contract governance; health-audit only when org security posture is part of a live health audit. |
| org validator, implicit org surface | `all` | `$ceratops-gh-repo-lifecycle` contracts-review for contract governance; health-audit only for explicit broad org health. |
| `repo` | `settings` | `$ceratops-gh-repo-lifecycle` contracts-review for contract governance; health-audit when live repo state is part of the task. |
| `repo` + `code` via `--select repo:dependency --select code:dependency` | `dependency` | `$ceratops-gh-repo-lifecycle` dependency-maintenance action when both live GitHub dependency/security posture and repo-content dependency posture are in scope; health-audit action for dependency posture audits. |
| `code` | `content` | `$ceratops-gh-repo-lifecycle` contracts-review for contract governance; health-audit or create-or-publish when repo contents are part of the task. |
| `artifact` | `artifact` | `$ceratops-gh-repo-lifecycle` contracts-review for contract governance; health-audit or create-or-publish when a published artifact is part of the task. |
| `all` | `create` | `$ceratops-gh-repo-lifecycle` create-or-publish action. |
| `all` | `health` | `$ceratops-gh-repo-lifecycle` health-audit action; contracts-review only for broad contract governance. |
| PR validator, implicit PR surface | none | `$ceratops-gh-repo-lifecycle` merge-pr or dependency-maintenance action, and `$ceratops-skill-lifecycle` ship-to-remote action before merge or auto-merge decisions. |

A successful mutation command is enough evidence for that exact mutation. Re-run
a validator only for drift/audit work, uncertain state, broader closure claims,
or checks not already proven by the successful command.

`skills/ceratops-gh-repo-lifecycle/references/contracts/code-comment-nondeterministic-contract.json`
is a non-deterministic local review rubric for comment sufficiency. It avoids
repeated live research during code-consistency audits and is not part of routine
ongoing-work validation.
`skills/ceratops-skill-lifecycle/references/contracts/skill-nondeterministic-contract.json`
is the local review rubric for high-quality skill design. It uses installed
OpenAI skills from `$CODEX_HOME/plugins/cache/` as pattern examples only and
keeps durable Ceratops obligations in the deterministic skill contract, shared
sections, validator, or skill-local source.

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

- runs direct full source validation through the skill-lifecycle validator
- builds managed runtime skill copies under `$CODEX_HOME/skills/`, including
  declared runtime payloads such as the Ceratops icon

Installed Ceratops skills should be generated from the skills repo checkout: the
local skills repo checkout used as the input path for the runtime installer.
The active branch only selects which repo snapshot is installed: synced `main`
for normal use, or a local `release/*` branch for an active unpublished preview.
After changing the installed source snapshot, rerun
`skills/ceratops-skill-lifecycle/scripts/runtime/install-managed-skills.ps1` so
new, renamed, or deleted managed skill folders match that snapshot.
When shipping a staged batch, reuse the same `release/local` branch name locally
and remotely by default. Use `stage-skill-release-branch.ps1` for reviewed local
branch staging, `push-release-branch-and-ensure-pr.ps1` for PR publication,
`$ceratops-gh-repo-lifecycle` merge-pr for merge gates, `sync-main-after-pr.ps1
-AlignBranch release/local` after merge, and
`skills/ceratops-skill-lifecycle/scripts/runtime/install-managed-skills.ps1` for
the final runtime rebuild from `main`. GitHub may delete the remote
`release/local` after merge; the next batch simply recreates that same remote
branch from the current local `release/local`.

Restart Codex after adding new skill folders if the app does not pick them up
automatically.

## Install For Claude Code

Claude Code uses the same core `SKILL.md` folder format. Copy or link a skill
folder into:

```text
$HOME/.claude/skills/<skill-name>/SKILL.md
```

Invoke skills directly with `/skill-name` in Claude Code. In Codex, invoke them
with `$skill-name`.

## Validate

Run full validation through the skill-lifecycle validator:

```powershell
npm ci
npm run lint:markdown
python -m pip install -r requirements-dev.txt
python -m yamllint .
python -m mypy
```

```powershell
python .\skills\ceratops-skill-lifecycle\scripts\validation\validate-skills-consistency.py --mode full
```

Run section validation only when shared section source files or
`templates/skill-sections.json` assignments changed:

```powershell
python .\skills\ceratops-skill-lifecycle\scripts\validation\validate-skills-consistency.py --mode sections
```

The section mode validates that source skills are delta-only;
`skills/ceratops-skill-lifecycle/scripts/runtime/render-runtime-skills.py`
performs runtime shared-section expansion during install.
`templates/skill-sections.json` records the core same-surface maintenance-check
policy for regular work and a separate governance-validation command set for
explicit skill consistency audits.
The renderer composes each runtime skill's shared block from
`templates/skill-sections.json` and `templates/sections/`, and each generated
runtime `SKILL.md` block includes section-source comments so the origin of every
shared section stays visible in the installed skill copy. The validator checks
skill frontmatter, folder/name consistency, section and required-subsection
structure, section assignments, runtime-renderability, Codex metadata,
placeholder leftovers, real README skill rows, cross-skill references,
maintenance-workflow targets, contract presence, skill deterministic
remediation-policy classification, and high-confidence secret patterns.
Use governance validation for explicit Ceratops skill-contract audits:

```powershell
python .\skills\ceratops-skill-lifecycle\scripts\validation\validate-skills-consistency.py --mode governance
```

Run helper `--help` smoke checks only for touched helper scripts or touched
helper claims. Full and governance validation are for explicit broad
verification, not every regular skill update. With working GitHub auth, run
`github-validate-org-deterministic-contract.py` and
`github-validate-repo-artifact-contract.py` from
`skills/ceratops-gh-repo-lifecycle/scripts/` for deterministic GitHub, code,
and artifact contract checks.

## Releases

Releases use `vMAJOR.MINOR.PATCH` tags. See `CHANGELOG.md` for release notes.

## Artifact Publishing

This repository publishes skill source files only. It does not publish Docker
images, PyPI packages, npm packages, or other runtime artifacts.
