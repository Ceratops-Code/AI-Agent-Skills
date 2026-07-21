# Ceratops Codex Skills

Reusable Ceratops skills for Codex and other `SKILL.md`-compatible agents.

## Skills

| Skill | Purpose |
| --- | --- |
| `ceratops-gh-repo-lifecycle` | Route GitHub repo lifecycle work across create-or-publish, contracts-review, health-audit, dependency-maintenance, ensure-pr, ship-change, and merge-pr actions. |
| `ceratops-propose-rules-update` | Propose focused rule-update recommendations after a concrete instruction failure, miss, or missing-rule gap. |
| `ceratops-credit-savings-analysis` | Analyze recent Codex runs for avoidable credit spend and recommend low-maintenance controls. |
| `ceratops-prompt-optimizer` | Rewrite rough prompts into clearer structured prompts without changing intent. |
| `ceratops-skill-optimize` | Propose advisory-only improvements for one skill by default or an explicitly requested skill set. |
| `ceratops-skill-lifecycle` | Route skill lifecycle work across create, make-repo-compatible, update, skills-contract-review, skills-consistency-review, fast-change, change-promotion, and ship-to-remote actions. |
| `ceratops-automation-run` | Run recurring automations with shared Ceratops alert, memory, and completion policy. |
| `ceratops-task-lifecycle` | Route task execution, fix-loop break, same-thread resume, handoff, and closure-check work across action references. |
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
That manifest also declares a stable `runtime_source_id`, unique among source
repos that share an install root, and a
`validation_profile`. Compatible external repos use `ceratops-compatible`;
this repo uses `ceratops`, which adds Ceratops icon, contract,
retired-artifact, and repository-governance checks to the common full checks.
Skill names are independent of the profile and need no `ceratops-` prefix.
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
skill-design contracts and skill source-doc tracking. The
`skills-contract-review` action refreshes those contracts against registered
best-practice evidence; it does not audit skills or run the repository
validator. The `skills-consistency-review` action audits one skills repository
against the contracts and checks its coupled metadata, action references,
automation consumers, helpers, installer, generated runtime, installed managed
skills, and docs. Each runtime manifest records schema, skill, source identity,
source path, local source-repository root, validation profile, and installer
version. Repository consistency review compares only parsed
`INSTALLER_VERSION` values before installed-skill checks.
The `global-skills-consistency-review` automation discovers required source
repositories and invokes the repo-scoped action once for each repository.

## Scripts

| Script | Caller And Timing |
| --- | --- |
| `scripts/install-skills.py` | Versioned repository bootstrap that delegates validation and installation to the supported lifecycle bundle. |
| `skills/ceratops-skill-lifecycle/scripts/templates/install-skills-template.py` | Authoritative installer copied into compatible repositories as `scripts/install-skills.py`; consistency compares only `INSTALLER_VERSION`. |
| `skills/ceratops-skill-lifecycle/scripts/runtime/install-managed-skills.py` | Installed source-scoped runtime installer; full installs run full source validation and same-source stale cleanup, while targeted installs validate only selected skills and remove no stale folders. |
| `skills/ceratops-skill-lifecycle/scripts/runtime/resolve-lifecycle-bundle.py` | Installed-first resolver with target-checkout fallback only for the initial Ceratops installation. |
| `skills/ceratops-skill-lifecycle/scripts/runtime/synchronize-installers.py` | Copies the authoritative installer into an approved task worktree only when its parsed version is missing or lower, then runs full validation. |
| `skills/ceratops-skill-lifecycle/scripts/runtime/skills-consistency-runtime-validator.py` | Discovers one repository's installed managed runtime, validates identity and installer versions, and compares every managed file with canonical builder output. |
| `skills/ceratops-skill-lifecycle/scripts/runtime/managed_runtime_builder.py` | Canonical managed-runtime builder used for installation and expected-tree generation. |
| `skills/ceratops-gh-repo-lifecycle/scripts/github_contract_engine/` | Package CLI for contract schemas, consistency, source documents, org/repo validation, shared severity levels, and non-deterministic evidence. |
| `skills/ceratops-gh-repo-lifecycle/scripts/github_pr_workflow/` | Package CLI for prepared-branch PR publication, PR readiness, Codex review wait/resolution, merge orchestration, live merge verification, and post-merge local sync. |
| `skills/ceratops-skill-lifecycle/scripts/skills-consistency-source-validator.py` | Source validator for selected-skill, section, and full repository checks. |
| `skills/ceratops-skill-lifecycle/scripts/promote-skill-branches-to-release-and-install.ps1` | Called by skill change-promotion to prepare `release/local`, merge reviewed branches, validate, install, clean merged work, and emit compact ready/not-ready JSON. |

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
- `skills/ceratops-gh-repo-lifecycle/references/schemas/` contains shared closed
  schemas for state, PR-readiness, non-deterministic, and source-registry
  contract families.

Run deterministic checks with bundled selections instead of one command per
setting:

```powershell
Push-Location .\skills\ceratops-gh-repo-lifecycle\scripts
python -m github_contract_engine validate org --org ORG --subset all
python -m github_contract_engine validate repo --repo OWNER/REPO --surface repo --subset settings --local-repo-path PATH
python -m github_contract_engine validate repo --repo OWNER/REPO --surface code --subset content --local-repo-path PATH
python -m github_contract_engine validate repo --repo OWNER/REPO --select repo:dependency --select code:dependency --local-repo-path PATH
python -m github_contract_engine validate repo --repo OWNER/REPO --surface artifact --subset artifact --local-repo-path PATH
python -m github_contract_engine validate repo --repo OWNER/REPO --surface all --subset health --local-repo-path PATH --summary-json --levels ERROR,WARN,NEEDS_AI_AGENT_REVIEW
python -m github_pr_workflow validate --pr NUMBER_OR_URL --cwd PATH
python -m github_contract_engine validate consistency
Pop-Location
python .\skills\ceratops-skill-lifecycle\scripts\skills-consistency-source-validator.py --mode full
```

The organization and repository/artifact commands are package operations over
the shared `scripts/github_contract_engine/` state engine. `compose_desired_state.py`
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
Push-Location .\skills\ceratops-gh-repo-lifecycle\scripts
python -m github_contract_engine collect --surface org --org ORG --json
python -m github_contract_engine collect --surface repo --repo OWNER/REPO --local-repo-path PATH --json
python -m github_contract_engine collect --surface code --repo OWNER/REPO --local-repo-path PATH --json
python -m github_contract_engine collect --surface artifact --repo OWNER/REPO --local-repo-path PATH --json
python -m github_contract_engine collect --surface pr --pr NUMBER_OR_URL --local-repo-path PATH --json
Pop-Location
```

Contract surfaces select the area being checked. GitHub, code, artifact, and PR
surfaces are read by `github_contract_engine` and `github_pr_workflow` package
commands.
The skill surface is represented by
`skills/ceratops-skill-lifecycle/references/skill-*` and
`skills/ceratops-skill-lifecycle/scripts/skills-consistency-source-validator.py`.
Skills pass or choose a surface only when they are doing an explicit audit,
drift check, uncertain-state check, or broad closeout claim.

| Surface | Runs When |
| --- | --- |
| `org` | GitHub organization settings, org security policy, org Actions policy, teams, roles, identity, and org-level Dependabot posture need an audit. |
| `repo` | Live GitHub repository settings, Actions policy, security toggles, rulesets, labels, releases, queues, and other GitHub-hosted repo state need an audit. |
| `code` | Repository contents, workflows, Dependabot config, CODEOWNERS, local git state, local path references, or local secret-pattern posture need an audit. |
| `artifact` | External deliverables or registry state such as PyPI, npm, DockerHub, GHCR, release assets, or docs publishing need an audit. |
| `skill` | Skill-design standards need contract refresh, or a skills repository and its metadata, actions, helpers, runtime, docs, and automation consumers need contract-compliance review. |
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

Install the lifecycle runtime dependency and run the bootstrap from the repo
root:

```powershell
python -m pip install -r requirements-runtime.txt
python .\scripts\install-skills.py
```

For a full install, that bootstrap does two things explicitly:

- runs direct full source validation through the skill-lifecycle validator
- builds managed runtime skill copies under `$CODEX_HOME/skills/`, including
  declared runtime payloads such as the Ceratops icon

For another Ceratops-compatible repo, run its versioned repository installer:

```powershell
python <target-repo>\scripts\install-skills.py --repo-root <target-repo>
```

The repository bootstrap prefers the supported installed lifecycle bundle and
uses the target checkout's bundle only for the initial Ceratops installation.
An install without `--skill` runs full source validation, refreshes all source
skills, and removes only stale folders with the same `runtime_source_id`. An
explicit `--skill` validates and installs only the selected skills and performs
no stale cleanup. Runtime manifests record source ownership, local
source-repository root, validation profile, and installer version.

Installed Ceratops skills should be generated from the skills repo checkout: the
local skills repo checkout used as the input path for the runtime installer.
The active branch only selects which repo snapshot is installed: synced `main`
for normal use, or a local `release/*` branch for an active unpublished preview.
After changing the installed source snapshot, rerun `python
scripts/install-skills.py --repo-root <repo>` so new, renamed, or deleted
same-source managed skill folders match that snapshot.
When shipping a staged batch, reuse the same `release/local` branch name locally
and remotely by default. Use
`promote-skill-branches-to-release-and-install.ps1` for reviewed local
branch staging, `$ceratops-gh-repo-lifecycle` ensure-pr for PR publication,
`$ceratops-gh-repo-lifecycle` merge-pr for merge gates,
`python -m github_pr_workflow sync --repo-root <repo> --align-branch
release/local` after merge, and
`python scripts/install-skills.py --repo-root <repo>` for the final runtime
rebuild from `main`. GitHub may delete the remote
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
python .\skills\ceratops-skill-lifecycle\scripts\skills-consistency-source-validator.py --mode full
```

Targeted installation validates only explicitly selected skills and their
rendering inputs:

```powershell
python .\skills\ceratops-skill-lifecycle\scripts\skills-consistency-source-validator.py --mode skill --skill <skill-name>
```

Run section validation only when shared section source files or
`templates/skill-sections.json` assignments changed:

```powershell
python .\skills\ceratops-skill-lifecycle\scripts\skills-consistency-source-validator.py --mode sections
```

The section mode validates that source skills are delta-only;
`skills/ceratops-skill-lifecycle/scripts/runtime/managed_runtime_builder.py`
performs runtime shared-section expansion during install.
`templates/skill-sections.json` records the source validation commands selected
by each maintenance workflow.
The runtime builder composes each runtime skill's shared block from
`templates/skill-sections.json` and `templates/sections/`, and each generated
runtime `SKILL.md` block includes section-source comments so the origin of every
shared section stays visible in the installed skill copy. Full validation
always checks manifest identity and profile, source skill structure,
shared-section assignments and rendering, payload portability, Codex metadata
and relative icon existence, the README Skills table, cross-skill references,
and high-confidence secret or private-path patterns. The `ceratops` profile
additionally checks the shared Ceratops icon, lifecycle contracts, retired
Ceratops artifacts, and repository-specific governance; the
`ceratops-compatible` profile skips only those Ceratops-specific additions.
Run helper `--help` smoke checks only for touched helper scripts or touched
helper claims. Full source validation is for explicit broad verification, not
every regular skill update. Installed runtime is validated separately by
`skills-consistency-runtime-validator.py` during `skills-consistency-review`.
With working
GitHub auth, run
`python -m github_contract_engine validate org` and
`python -m github_contract_engine validate repo` from
`skills/ceratops-gh-repo-lifecycle/scripts/` for deterministic GitHub, code,
and artifact contract checks.

## Releases

Releases use `vMAJOR.MINOR.PATCH` tags. See `CHANGELOG.md` for release notes.

## Artifact Publishing

This repository publishes skill source files only. It does not publish Docker
images, PyPI packages, npm packages, or other runtime artifacts.
