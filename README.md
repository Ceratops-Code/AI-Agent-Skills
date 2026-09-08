# Ceratops Codex Skills

Reusable Ceratops skills for Codex and other agents compatible with `SKILL.md`.

## Skills

| Skill | Purpose |
| --- | --- |
| `design-document-lifecycle` | Create or review an authoritative software design document using a tailored arc42 contract, C4 views, scoped implementation evidence, and mechanical validation. |
| `ceratops-repo-lifecycle` | Route repository lifecycle work across compatibility, local promotion, structured deployment, guarded shipping, GitHub creation, contracts, health, dependencies, and PR merge actions. |
| `ceratops-governance-lifecycle` | Route prompt optimization, advisory skill optimization, regression-safe instruction updates, and cross-scope governance consistency audits across action references. |
| `ceratops-credit-savings-analysis` | Analyze one credit-waste surface or run fixed per-thread analyses for the current, named, or recent project-filtered threads while preserving every confirmed finding. |
| `ceratops-misunderstanding-audit` | Audit N days of misunderstandings or one exchange, preserve exact evidence and repeated clarifications, and propose targeted communication or workflow repairs without applying them. |
| `ceratops-skill-lifecycle` | Route skill-domain work across create, deploy, preferred eligible fast-change, update, skills-contract-review, and skills-consistency-review actions. |
| `ceratops-tool-lifecycle` | Create and package local Python tools, bootstrap the deployment manager, install exact releases, update tools, and inspect versions. |
| `ceratops-automation-run` | Run recurring automations with shared Ceratops alert, memory, and completion policy. |
| `ceratops-task-lifecycle` | Route failed-fix-loop breaks, same-thread task resume, whole-task handoff, and closure checks across action references. |
| `ceratops-code-consistency-audit` | Audit merged refactors for contradictions, docs drift, comment sufficiency, stale follow-through, and merged-only edge cases. |
| `openai-docs-managed` | Retrieve cited official OpenAI documentation through an allowlisted helper with zero routine child-model calls. |

## Layout

The independent [tool deployment manager](tools/ceratops-tool-manager/README.md)
keeps its editable source under `tools/`. Every deployed tool owns
`C:\AI-Agents-Tools\<tool-id>` with its packages, environments, and state;
Python and uv are validated global
prerequisites. Its CLI and local MCP adapters share
one engine. The tool lifecycle skill contains instructions only; the existing
skill installer continues to own `.codex` skill deployment.

```text
skills/
  skill-sections.json
  sections/
    core.md
    multi-action-skill.md
    evidence-analysis.md
    bounded-model-analysis.md
  ceratops-*/
    SKILL.md
    agents/openai.yaml
    assets/
      ceratops-logo-500.png
    scripts/
    references/
      <action-or-contract-reference>
sdlc/
  sdlc.yml
skills/ceratops-repo-lifecycle/references/templates/
  sdlc-template.yml
  install-skills-bootstrap-template.py
  skill-sections-template.json
skills/ceratops-skill-lifecycle/references/templates/
  ceratops-logo-500.png
hooks/
  bounded-source-search.py
  preserve-eol-for-apply-patch-tool.py
  windows-shell-sanity.py
  README.md
```

Source `SKILL.md` files are portable, delta-only skill definitions. Runtime
`SKILL.md` files are generated during install by expanding the shared section
assignments from `skills/skill-sections.json`.
That manifest also declares a stable `runtime_source_id`, unique among source
repos that share an install root, and a
`validation_profile`. Compatible external repos use `ceratops-compatible`;
this repo uses `ceratops`, which adds Ceratops icon, contract,
retired-artifact, and repository-governance checks to the common full checks.
Skill names are independent of the profile and need no `ceratops-` prefix.
`core` is assigned to every skill; `multi-action-skill` is assigned only to
skills that select among multiple action references. `evidence-analysis` is
assigned to skills whose primary output is evidence-backed findings, while
`bounded-model-analysis` is assigned to skills that invoke bounded
analysis-only child models.
The `skills/` tree is authoritative skill source for this repository.
`sdlc/sdlc.yml` is its authoritative structured deployment and release
publication definition.
The repository-compatibility templates under
`skills/ceratops-repo-lifecycle/references/templates/` are reusable skeletons
to copy into other repositories, not live configuration.
`agents/openai.yaml` is Codex UI metadata and may be ignored by other agents.
Each Ceratops skill declares the runtime-local icon path
`./assets/ceratops-logo-500.png`; every source copy matches the canonical
`skills/ceratops-skill-lifecycle/references/templates/ceratops-logo-500.png`.
Reusable skill-runtime helper logic lives in skill-local lifecycle scripts
under `skills/*/scripts/`, not in an installed Python package. User-global
operational hooks that are not owned by one managed skill live under `hooks/`.
Contract sources live inside their owning lifecycle skill.
`skills/ceratops-repo-lifecycle/references/` owns GitHub org, GitHub repo,
repo-code, PR readiness, artifact, release, code-comment, and CodeQL disposition
contracts. `skills/ceratops-skill-lifecycle/references/` owns
skill-design contracts and skill source-doc tracking. The
`skills-contract-review` action refreshes those contracts against registered
best-practice evidence; it does not audit skills or run the source validator.
The `skills-consistency-review` action audits one direct manifest-backed
installed skill, regardless of its name, against the contracts and checks its
coupled metadata, action references, automation consumers, helpers, installer,
generated runtime, source, and docs. Each runtime manifest records schema,
skill, source identity, source path, local source-repository root, and
validation profile. Bootstrap synchronization compares only parsed
`INSTALLER_VERSION` values; ordinary runtime compatibility uses the manifest
schema.
The `global-skills-consistency-review` automation uses the lifecycle runtime
inventory helper to enumerate every direct manifest-backed skill under
`$CODEX_HOME/skills`, then invokes the single-skill action once per valid entry
without repository deduplication.

## Scripts

| Script | Caller And Timing |
| --- | --- |
| `skills/design-document-lifecycle/scripts/validate_design_document.py` | Validates document metadata, mapped sections, fences, local paths, and Mermaid through an existing official CLI; generates the human contract and minimal template from its skill-owned JSON contract. Mermaid checks require the CLI/browser and a caller-selected task temp root. |
| `hooks/bounded-source-search.py` | Runs bounded two-phase ripgrep searches and replaces oversized successful ripgrep hook output with a compact per-file projection. |
| `hooks/preserve-eol-for-apply-patch-tool.py` | Preserves each updated text file's existing encoding and uniform line-ending convention around `apply_patch`. |
| `hooks/windows-shell-sanity.py` | Repository-owned source for the user-global Windows PowerShell preflight; rewrites exact command defects, annotates ordinary failures, and blocks unreliable or policy-prohibited forms. |
| `scripts/install-skills-bootstrap.py` | Self-contained first-install bootstrap; stages and validates one complete selected batch under the install root and never calls lifecycle runtime code. |
| `scripts/bootstrap-tool-manager.py` | First tool-manager installation using validated global Python and uv; invokes the shared deployment engine and never changes Codex settings. |
| `scripts/package-tool-release.py` | Development-only wheel build and exact local release registration from reviewed source, with source dependency lock generation. |
| `scripts/check-tool-manager.py` | Explicit acceptance using real manager releases and a persistent MCP connection across a selected self-update. |
| `scripts/tool_manager_support.py` | Imports the authoritative tool-manager source for repository maintenance without duplicating deployment logic. |
| `scripts/run-tests.py` | Sole test-selection, collection-reconciliation, and pytest-execution owner; validates `tests/test-impact.json`, explains deterministic Git-diff selection, rejects mapping gaps before pytest collection or execution, supports explicit committed-diff, worktree, collection, and `--all` modes, and writes complete failed-pytest streams to a diagnostic file while returning only bounded failure evidence. |
| `scripts/validate-repository.py` | Local validation coordinator; captures first-failure evidence, delegates its default full test phase to `scripts/run-tests.py --all`, and supports CI's separate runner-owned test phase. |
| `skills/ceratops-repo-lifecycle/references/templates/install-skills-bootstrap-template.py` | Authoritative standard-library-only bootstrap copied into compatible skill repositories as `scripts/install-skills-bootstrap.py`. |
| `skills/ceratops-repo-lifecycle/references/repository-validation-catalog.json` | Closed catalog of repository checks that compatibility materialization may select without additional approval. |
| `skills/ceratops-repo-lifecycle/references/templates/validate-repository.py.tmpl` and `validate.yml.tmpl` | Repository-neutral validator and CI templates materialized only when their target files are absent. |
| `skills/ceratops-repo-lifecycle/scripts/ceratops_repo_compatibility_engine/` | Skill-owned package for read-only compatibility checks, SDLC-contract validation, rollback-protected repository materialization, and version-only bootstrap synchronization; it operates on explicit target repositories and is never copied into them. |
| `skills/ceratops-repo-lifecycle/references/templates/skill-sections-template.json` | Repository-neutral template for materializing a target repository's live `skills/skill-sections.json`; never a live manifest. |
| `skills/ceratops-skill-lifecycle/scripts/runtime/install-managed-skills.py` | Classifies explicit, promotion-relative, or all-managed affected sets; owns direct-manifest inventory; and invokes one runtime transaction without source validation. |
| `skills/ceratops-skill-lifecycle/scripts/runtime/managed_runtime_builder.py` | Stages, activates, rolls back, recovers, and cleans one locked selected-skill runtime transaction. |
| `skills/ceratops-skill-lifecycle/scripts/skill-update-workflow.py` | Prepares and verifies declared cohesive skill updates, preserves unrelated dirty state, records exact task-temp ownership plus an active-update retention marker, finalizes owned request, state, evidence, and marker files, and removes the verified task-temp root only when empty after completed caller use. |
| `skills/ceratops-credit-savings-analysis/scripts/credit_analysis/session_evidence_collector.py` | Resolves current, named, indexed, and project-identified sessions and collects one complete prepared traversal per analysis, preserving formatted messages, canonical current-source references, bounded nested-command failure provenance, tool and process telemetry, fingerprints, usage, closure, and classification modes. |
| `skills/ceratops-misunderstanding-audit/scripts/audit.py` and `audit_sources.py` | Read selected local history or exported maintained-reader pages, freeze N-day or single-case scope, separate user wording from annotations, preserve timestamp and lineage evidence, validate semantic-review accounting, and publish a report and ledger with scoped temporary-input cleanup; no model calls or automatic rule edits. |
| `skills/ceratops-credit-savings-analysis/scripts/credit_analysis/execution_outcomes.py` | Shared interpretation of tool-result envelopes and runtime failure headers for collection, model-input preparation, and review routing; printed content stays separate and nonzero process results do not imply semantic failure. |
| `skills/ceratops-credit-savings-analysis/scripts/credit-analysis-workflow.py` and `scripts/credit_analysis/` | Keep one stable CLI over explicitly named single-thread analysis, multi-thread analysis, model-capacity planning, Luna/Sol analysis, prior-analysis runs, session-evidence collection, contract snapshots, and command-line dispatch modules. Each holistic run retains its own immutable contract file so runtime deployment cannot replace that recorded input. |
| `skills/ceratops-credit-savings-analysis/scripts/credit_analysis/report_bookkeeping.py` | Owns result-shape validation, surface ordering, temporary-control links, category consolidation, and reviewer-record preservation. Final results retain complete original confirmed findings, risks, control reviews, and category assessments in controller-generated `source_findings`, `source_risks`, and `source_reviews`, checked against accepted reviewer records. Candidate links identify each finding's destination, which must cover its original calls and evidence; retained source findings do not add to savings or finding totals. Copied category checklists aggregate applicability across reviewed portions without discarding differing assessments. Reports display every distinct risk uncertainty. The controller revalidates saved final output before enforcing limits on new attempts and selects the highest-priority complete audit window that fits the reserved review slot. |
| `skills/ceratops-task-lifecycle/scripts/closure_snapshot.py` | Emits one compact snapshot for explicitly named closure targets and optionally removes exact task-created files validated inside the task temp root. |
| `skills/ceratops-governance-lifecycle/scripts/apply_rules_update.py` | Applies approved rule and TOML text with required rule-history appends or exact ID migrations, supports validated history-only identity repairs, rolls back mixed writes, and cleans only explicitly disposable artifacts after success. |
| `skills/ceratops-governance-lifecycle/scripts/validate_rule_candidate.py` | Safely repairs candidate-only Markdown whitespace, parses complete TOML targets without reflow, preserves shared rule/history checks, proves idempotence, and writes caller-selected evidence. |
| `skills/ceratops-governance-lifecycle/scripts/rule_candidate_source.py` | Owns exact UTF-8 source loading, encoding and line-ending preservation, shared candidate data, and input-integrity checks used by governance validation and application. |
| `skills/ceratops-governance-lifecycle/scripts/proposal-workflow.py` | Validates exact proposal inputs, histories, target policies, and hashes; records task-temp ownership; delegates validated controller transitions; and preserves the exact champion while finalizing owned artifacts. |
| `skills/ceratops-governance-lifecycle/scripts/iteration_controller.py` | Opens structured candidates, invokes mechanical validation before recording, retains the exact validated champion, enforces stopping, and safely finalizes owned artifacts. |
| `skills/ceratops-governance-lifecycle/scripts/rule_graph.py` | Parses canonical AGENTS rules and rejects structural syntax or rule-local explicit-user override escape clauses. |
| `skills/ceratops-repo-lifecycle/scripts/github_contract_engine/` | Package CLI for compact local audit snapshots, contract evaluation, shared GitHub API access, sanitized evidence, and evidence-gated CodeQL disposition. |
| `skills/ceratops-repo-lifecycle/scripts/github_pr_workflow/` | Package CLI for individual PR operations, one-call retry-safe review replies and resolutions, decision-complete gate blockers, single-snapshot terminal Actions outage detection, exact-commit checkpointed shipping, four-proof obsolete-prepared-checkpoint cleanup before automatic resume, scoped pending-work checks, concurrent gates, integrated admin merge, reusable-branch restoration, and terminal cleanup. |
| `skills/ceratops-repo-lifecycle/scripts/promote-repository.py` | Prepares `release/local`; promotes selected branches with no deployment or an explicit ordered operation selection; or composes promotion into exact-head shipping with ordered release and deploy selections, finalization, and cleanup. |
| `skills/ceratops-repo-lifecycle/scripts/manage-pending-work.py` | Records, checks, automatically resumes the retained target commit, and progressively finalizes the exact selected scope; preflight preserves and reports non-cleanup-eligible worktrees, while eligible residual-worktree and identity-matched task-temp cleanup stays within validated named directory boundaries and preserves active skill-update state for post-deployment finalization. |
| `skills/ceratops-repo-lifecycle/scripts/repository_operation.py` | Prepares complete ordered operation sequences before execution and shares exact argv handling, strict parameters, repository path boundaries, compact results, and bounded structured failures. |
| `skills/ceratops-repo-lifecycle/scripts/run-deploy-operation.py` | Prevalidates and executes ordered named local operations from the `deploy` section of `sdlc/sdlc.yml`, returning optional declarative agent handoffs per operation. |
| `skills/ceratops-repo-lifecycle/scripts/run-release-operation.py` | Prevalidates and executes ordered named remote publication operations from the `release` section of `sdlc/sdlc.yml`. |
| `skills/ceratops-repo-lifecycle/scripts/ship-repository.py` | Prevalidates one SDLC contract and ordered phase selections before orchestrating guarded GitHub shipping, main synchronization, per-operation publication and deployment checkpoints, and resumable selected-source cleanup. |
| `skills/ceratops-skill-lifecycle/scripts/skills-consistency-source-validator.py` | Skill-lifecycle-owned source, metadata, runtime-input, contract, and portability validator used only by explicit skill workflows. |
| `skills/ceratops-skill-lifecycle/scripts/fast-change.py` | Classifies exact structured replacements, generates their diff, and owns the eligible direct-release change through declared Markdown lint, exact helper tests, targeted installation, commit, and failure compensation. |

Lifecycle helpers suppress successful subcommand output and print only compact
JSON on success. This repo keeps scripts only where they add reusable safety
logic or bundle nontrivial evidence collection.

New shipping PRs use non-merge commit subjects from the base-to-head range for
their title, shortened to 120 characters, and all those commit messages for
their description. Both direct shipping and promotion with
`--ship-after-promotion` accept independent `--title` and `--body` overrides.
Supplied text, including an empty body, is preserved; existing PR fields change
only when explicitly supplied. A range without change commits requires both
fields. The PR helper owns its temporary UTF-8 body file and removes it after
the GitHub command succeeds or fails.

`fast-change` is the preferred skill-maintenance path whenever one exact
coherent change stays within declared files under existing selected skills,
preserves helper boundaries, and has sufficient targeted checks. It may cover
multiple files and skills. The repository lifecycle helper prepares
`release/local`; one `fast-change.py` request then classifies the complete
scope before mutation and owns exact-match validation, diff generation,
application, repository-declared Markdown lint, exact helper tests when
required, targeted installation, staging, commit, and compensation.

Promotion and deployment are separate repository actions. `promote` assembles
the selected branches into `release/local` without deployment;
`promote-and-deploy` additionally prevalidates and runs explicitly selected
`deploy.operations` in order and executes their returned handoffs in the same
order when the promoted manifest has managed skills. Managed skills without a
declared handoff are reported as not deployed without changing the repository
deployment result.
The runner never converts prose instructions into commands.

`ship` takes either an exact pending-work scope or an explicit disabled-check
mode. When enabled, the same generic scope is checked before the first remote
push, after synchronization before release publication and local deployment,
and again before cleanup because local state can change while CI or operations
run. Pre-push detection returns compact `pending_work` output with
`remote_mutation: false`; later detection reports `remote_mutation: true`
because the merge already occurred. The initial integrated ship request
authorizes the complete workflow. Its final merge uses admin only after
readiness, CI, Codex-review, and exact-head gates pass; standalone merge
behavior remains unchanged.

## Contracts

Each repository owns one lifecycle contract:

- `sdlc/sdlc.yml` keeps the former contract structures unchanged under
  `release` and `deploy`; it declares remote publication operations, artifact
  identity, and local deployment operations and is validated against
  `skills/ceratops-repo-lifecycle/references/schemas/sdlc.yml.schema.json`.
- `skills/ceratops-repo-lifecycle/references/contracts/github-contract-source-docs.json`
  records official source documents and reference repositories used by GitHub,
  repo, PR readiness, code, and artifact contracts.
- `skills/ceratops-repo-lifecycle/references/contracts/github-org-deterministic-contract.json`
  defines deterministic organization settings, policy, identity, security,
  Dependabot, and default-logo/custom-logo checks.
- `skills/ceratops-repo-lifecycle/references/contracts/github-repo-deterministic-contract.json`
  defines deterministic live GitHub repository settings, security,
  branch/ruleset, Actions policy, queues, releases, and stale GitHub state
  checks.
- `skills/ceratops-repo-lifecycle/references/contracts/github-pr-readiness-deterministic-contract.json`
  defines deterministic live PR readiness checks used before merge and
  auto-merge decisions.
- `skills/ceratops-repo-lifecycle/references/contracts/code-repo-deterministic-contract.json`
  defines deterministic repository-content checks for files, workflow text,
  Dependabot config, CODEOWNERS, local git state, local path references, and
  secret-pattern scans.
- `skills/ceratops-repo-lifecycle/references/contracts/artifact-deterministic-contract.json`
  defines external artifact checks for PyPI, npm, DockerHub or OCI registries,
  GitHub Container Registry, GitHub releases, docs sites, and other package
  registries.
- `skills/ceratops-skill-lifecycle/references/contracts/skill-contract-source-docs.json`
  records official skill-standard documents and installed OpenAI skill
  references used by skill-design contracts.
- `skills/ceratops-skill-lifecycle/references/contracts/skill-deterministic-contract.json`
  defines deterministic Ceratops skill checks for source structure, resource
  layout, metadata, shared-section generation, runtime payloads, public docs,
  portability, and contract presence.
- `skills/ceratops-repo-lifecycle/references/contracts/*-nondeterministic-contract.json`
  and
  `skills/ceratops-skill-lifecycle/references/contracts/*-nondeterministic-contract.json`
  files capture checks that need intent judgment, prose review, browser
  confirmation, or current-doc interpretation after bundled evidence is
  collected.
- `skills/ceratops-repo-lifecycle/references/schemas/` contains shared closed
  schemas for state, repository operations, PR-readiness, non-deterministic,
  and source-registry contract families.

Run deterministic checks with bundled selections instead of one command per
setting:

```powershell
Push-Location .\skills\ceratops-repo-lifecycle\scripts
python -m github_contract_engine audit-snapshot --repo-root ..\..\..
python -m github_contract_engine validate org --org ORG --subset all --params-file PATH
python -m github_contract_engine validate repo --repo OWNER/REPO --surface repo --subset settings --local-repo-path PATH
python -m github_contract_engine validate repo --repo OWNER/REPO --surface code --subset content --local-repo-path PATH
python -m github_contract_engine validate repo --repo OWNER/REPO --select repo:dependency --select code:dependency --local-repo-path PATH
python -m github_contract_engine validate repo --repo OWNER/REPO --surface artifact --subset artifact --local-repo-path PATH
python -m github_contract_engine validate repo --repo OWNER/REPO --surface all --subset health --local-repo-path PATH --evidence-file EVIDENCE --summary-json --levels ERROR,WARN,NEEDS_AI_AGENT_REVIEW
python -m github_pr_workflow validate --pr NUMBER_OR_URL --cwd PATH
python -m github_pr_workflow ship --help
python -m github_contract_engine codeql-disposition --help
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
Organization parameters resolve from contract defaults, the `--params-file`
(default `$CODEX_HOME/gh-contract-params.json`), named flags, then repeatable
`--param KEY=VALUE` overrides.

GH lifecycle validators use `ERROR`, `WARN`, and `NEEDS_AI_AGENT_REVIEW` for
actionable findings. `ERROR` and `WARN` are blocking;
`NEEDS_AI_AGENT_REVIEW` is judgment-required evidence that the review owner must
classify before closure. Repo-health summary JSON includes compact stale-state
inventory counts and samples for PRs, branches, tags, releases, and local path
references when present. It also reports the observed community-profile health
percentage and its 100% contract target; inventory alone is not a finding.
Local health collection validates every present `sdlc/sdlc.yml` with the
repository-lifecycle schema and runs the generic compatibility postcondition
checker whenever a manifest, source skill, SDLC definition, or repository
validation surface is present. Ship validates the selected contract's
`release` section before remote mutation. Local health does not run skill-source
validation.

Collect review evidence for non-deterministic checks with:

```powershell
Push-Location .\skills\ceratops-repo-lifecycle\scripts
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
| org validator, implicit org surface | `settings` | `$ceratops-repo-lifecycle` contracts-review for contract governance; health-audit only when org posture is part of a live health audit. |
| org validator, implicit org surface | `actions` | `$ceratops-repo-lifecycle` contracts-review for contract governance; health-audit only when org Actions posture is part of a live health audit. |
| org validator, implicit org surface | `dependabot` | `$ceratops-repo-lifecycle` contracts-review for contract governance; health-audit only when org Dependabot posture is part of a live health audit. |
| org validator, implicit org surface | `security` | `$ceratops-repo-lifecycle` contracts-review for contract governance; health-audit only when org security posture is part of a live health audit. |
| org validator, implicit org surface | `all` | `$ceratops-repo-lifecycle` contracts-review for contract governance; health-audit only for explicit broad org health. |
| `repo` | `settings` | `$ceratops-repo-lifecycle` contracts-review for contract governance; health-audit when live repo state is part of the task. |
| `repo` + `code` via `--select repo:dependency --select code:dependency` | `dependency` | `$ceratops-repo-lifecycle` dependency-maintenance action when both live GitHub dependency/security posture and repo-content dependency posture are in scope; health-audit action for dependency posture audits. |
| `code` | `content` | `$ceratops-repo-lifecycle` contracts-review for contract governance; health-audit or create-or-publish when repo contents are part of the task. |
| `artifact` | `artifact` | `$ceratops-repo-lifecycle` contracts-review for contract governance; health-audit or create-or-publish when a published artifact is part of the task. |
| `all` | `create` | `$ceratops-repo-lifecycle` create-or-publish action. |
| `all` | `health` | `$ceratops-repo-lifecycle` health-audit action; contracts-review only for broad contract governance. |
| PR validator, implicit PR surface | none | `$ceratops-repo-lifecycle` ship, merge-pr, or dependency-maintenance action before merge or auto-merge decisions. |

A successful mutation command is enough evidence for that exact mutation. Re-run
a validator only for drift/audit work, uncertain state, broader closure claims,
or checks not already proven by the successful command.

`skills/ceratops-repo-lifecycle/references/contracts/code-comment-nondeterministic-contract.json`
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

Install the runtime dependency, then use the bootstrap only for the first
installation:

```powershell
python -m pip install -r requirements-runtime.txt
python .\scripts\install-skills-bootstrap.py
```

The bootstrap is self-contained and never calls installed lifecycle code. It
stages the complete selected batch in a uniquely named hidden directory under
the install root, validates it, refuses existing destinations, activates it,
and cleans only bootstrap-owned state. For every later deployment, use
`$ceratops-skill-lifecycle` `deploy`, which invokes the managed runtime
transaction directly.

For another Ceratops-compatible repo, run its versioned repository installer:

```powershell
python <target-repo>\scripts\install-skills-bootstrap.py --repo-root <target-repo>
```

An external repository's copied bootstrap is independent: it uses only the
Python standard library, reads declared skills, resolves shared sections and
payloads, fully stages the requested output under the install root, and refuses
existing destinations. It does not locate or run Ceratops, validate repository
lifecycle policy, negotiate compatibility, or fall back after an error.

For report-only global routing, the runtime installer can write direct managed
manifest entries and malformed-entry blockers without comparing runtime files
to source:

```powershell
python .\skills\ceratops-skill-lifecycle\scripts\runtime\install-managed-skills.py --inventory-output <file>
```

Installed Ceratops skills should be generated from the skills repo checkout: the
local skills repo checkout used as the input path for the runtime installer.
The active branch only selects which repo snapshot is installed: synced `main`
for normal use, or `release/local` for an active unpublished preview.
After changing the installed source snapshot, use the installed lifecycle
skill's `deploy` action to refresh it; never use bootstrap as a reinstall path.
When shipping a staged batch, reuse the same `release/local` branch name locally
and remotely by default. Use `$ceratops-repo-lifecycle` `promote` to assemble
selected reviewed branches without installation, or `promote-and-deploy` to run
an explicit ordered deploy-operation selection and any returned handoffs. Use
`ship` for
the complete
scoped pre-push check, exact-commit PR publication, readiness and review gates,
final merge, main synchronization, optional repository deployment,
returned-handoff handling, late recheck, and selected-source cleanup workflow.

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

Install the declared Python and Node development dependencies, optionally
select a failure-evidence path, then run the same repository validator used by
CI:

```powershell
npm ci
python -m pip install -r requirements-dev.txt
$validationEvidence = Join-Path $env:TEMP "repository-validation.log"
python scripts/validate-repository.py --evidence-file $validationEvidence
```

Without the flag, evidence defaults to
`build/deploy-validation/repository-validation.log`.
Failure evidence remains available for diagnosis until the next successful run,
which removes the selected evidence file and prunes the dedicated default
directory when it is empty.
The validator runs Markdown and YAML lint, Ruff, mypy for Linux and Win32, and
`scripts/run-tests.py --all`. Pull-request CI calls the same runner with exact
base and head commit SHAs. Local uncommitted selection is explicit through
`python scripts/run-tests.py --worktree`, and manifest validation is available
through `python scripts/run-tests.py --validate-manifest`. The validator does
not invoke skill-local validators. Generic compatibility and
health validate lifecycle definitions through the repository-lifecycle
`ceratops_repo_compatibility_engine.sdlc_contract_validation` module. Runtime
rendering is owned only by bootstrap and managed deployment under the selected
install root.

Failed pytest runs write complete stdout and stderr to
`build/test-diagnostics/pytest-failure.json` by default. Use
`--diagnostic-output PATH` to select another file; the terminal JSON contains a
bounded failing-test summary plus the file path, byte count, and SHA-256 hash.
A successful pytest run removes stale evidence at the selected path.

For a structural test migration, capture the pre-migration collection and
reconcile it after moving tests:

```powershell
$collection = Join-Path $env:TEMP "pytest-collection.json"
python scripts/run-tests.py --write-collection $collection
python scripts/run-tests.py --reconcile-collection $collection
```

Reconciliation preserves complete pytest identities, including parameter IDs,
automatically matches unique path moves, reports additive tests, and exits `4`
for missing or ambiguous legacy nodes. Supply a versioned explicit map with
`--node-map PATH` only when multiple current nodes share one legacy identity.
The map format is:

```json
{
  "schema": "ai-agent-skills-pytest-node-map.v1",
  "mappings": {
    "tests/old/test_flow.py::test_case[id]": "tests/new/test_flow.py::test_case[id]"
  }
}
```

Run full skill-source validation explicitly when that source surface is in
scope:

```powershell
python .\skills\ceratops-skill-lifecycle\scripts\skills-consistency-source-validator.py --mode full
```

Targeted installation validates only explicitly selected skills and their
rendering inputs:

```powershell
python .\skills\ceratops-skill-lifecycle\scripts\skills-consistency-source-validator.py --mode skill --skill <skill-name>
```

Run section validation only when shared section source files or
`skills/skill-sections.json` assignments changed:

```powershell
python .\skills\ceratops-skill-lifecycle\scripts\skills-consistency-source-validator.py --mode sections
```

The section mode validates that source skills are delta-only;
`skills/ceratops-skill-lifecycle/scripts/runtime/managed_runtime_builder.py`
performs runtime shared-section expansion during install.
`skills/skill-sections.json` records the source validation commands selected
by each maintenance workflow.
The runtime builder composes each runtime skill's shared block from
`skills/skill-sections.json` and `skills/sections/`, and each generated
runtime `SKILL.md` block includes section-source comments so the origin of every
shared section stays visible in the installed skill copy. Runtime payload
strings preserve their repository-relative installed paths; an exact
`{"source": "...", "target": "..."}` entry maps one shared source file to
an installed-skill-relative target. Single-skill executable sources belong to
that skill, while multi-skill executable sources belong under
`skills/sections/scripts`. Full validation
always checks manifest identity and profile, source skill structure,
shared-section assignments and rendering, payload portability, Codex metadata
and relative icon existence, the README Skills table, cross-skill references,
and high-confidence secret or private-path patterns. The `ceratops` profile
additionally checks the shared Ceratops icon, lifecycle contracts, retired
Ceratops artifacts, and repository-specific governance; the
`ceratops-compatible` profile skips only those Ceratops-specific additions.
Outside the full repository validator, run helper `--help` smoke checks only
for touched helper scripts or touched helper claims. Full source validation is
for explicit broad verification, not every regular skill update. A successful
targeted or all-managed transaction is the post-install runtime evidence;
`skills-consistency-review` reads the selected runtime manifest as structured
identity evidence. With working GitHub auth, run
`python -m github_contract_engine validate org` and
`python -m github_contract_engine validate repo` from
`skills/ceratops-repo-lifecycle/scripts/` for deterministic GitHub, code,
and artifact contract checks.

## Releases

Releases use `vMAJOR.MINOR.PATCH` tags. See `CHANGELOG.md` for release notes.

## Artifact Publishing

This repository publishes source files only. It does not publish Docker images,
PyPI packages, npm packages, or other runtime artifacts.
