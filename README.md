# Ceratops Codex Skills

Reusable Ceratops skills for Codex and other agents compatible with `SKILL.md`.

## Skills

| Skill | Purpose |
| --- | --- |
| `codex-desktop-upgrade` | Assess official Codex desktop updates, reconcile patches and route requested qualification through the patcher helpers. |
| `design-document-lifecycle` | Create or review an authoritative software design document using a tailored arc42 contract, C4 views, scoped implementation evidence, and mechanical validation. |
| `ceratops-repo-lifecycle` | Route repository lifecycle work across compatibility, local promotion, structured deployment, guarded shipping, GitHub creation and inspection, PR publication, review follow-up, CI repair, contracts, health, dependencies, and PR merge actions. |
| `ceratops-governance-lifecycle` | Route prompt optimization, advisory skill optimization, regression-safe instruction updates, and cross-scope governance consistency audits across action references. |
| `ceratops-credit-savings-analysis` | Analyze one credit-waste surface or run fixed per-thread analyses for the current, named, or recent project-filtered threads while preserving every confirmed finding. |
| `ceratops-misunderstanding-audit` | Audit N days of misunderstandings or one exchange, preserve exact evidence and repeated clarifications, and propose targeted communication or workflow repairs without applying them. |
| `ceratops-skill-lifecycle` | Route skill-domain work across create, source-validate, deploy, preferred eligible fast-change, update, skills-contract-review, and skills-consistency-review actions. |
| `ceratops-tool-lifecycle` | Create and package local Python tools, bootstrap the deployment manager, install exact releases, update tools, and inspect versions. |
| `ceratops-automation-run` | Run recurring automations with shared Ceratops alert, memory, and completion policy. |
| `ceratops-task-lifecycle` | Route failed-fix-loop breaks, same-thread task resume, whole-task handoff, and closure checks across action references. |
| `ceratops-code-consistency-audit` | Audit merged refactors for contradictions, docs drift, comment sufficiency, stale follow-through, and merged-only edge cases. |
| `openai-docs-managed` | Retrieve cited official OpenAI documentation through an allowlisted helper with zero routine child-model calls. |

## Layout

The independent [tool deployment manager](tools/ceratops_tool_manager/README.md)
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
  sdlc.yml.tmpl
  deploy-skills.py.tmpl
  skill-sections.json.tmpl
skills/ceratops-skill-lifecycle/references/templates/
  ceratops-logo-500.png
hooks/
  bounded-source-search.py
  command-probe.py
  preserve-eol-for-apply-patch-tool.py
  windows-shell-sanity.py
  README.md
```

Source `SKILL.md` and action-reference files are portable, delta-only
definitions. Their installed copies expand the shared section assignments from
`skills/skill-sections.json`. Rendering removes complete
internal author comments, including multiline notes.
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
`sdlc/sdlc.yml` declares repository setup and validation, plus capabilities
of each deliverable. Lifecycle actions decide when those capabilities run.
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
The `source-validate` action owns deterministic source validation through the
existing validator in its skill bundle, with `full`, selected `skill`, and
shared `sections` modes. Deployment requires its passing `full` result for
unchanged source inputs. The separate `skills-consistency-review` action audits
one direct manifest-backed
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
| `scripts/deploy-skills.py` | Independent installation and updates; renders selected skills and overlays their files without validation, retirement, or lifecycle runtime calls. |
| `scripts/deploy-hooks.py` | Independent hook installation and updates; copies the repository hook payloads and merges their registrations while preserving unrelated files and configuration. Does not grant trust or restart Codex. |
| `scripts/deploy-tool-manager.py` | First tool-manager installation, launched in the scripts environment; uses the manager's global Python and uv prerequisites, temporary locked libraries, and packaging and deployment code. Never changes Codex settings. |
| `scripts/testing/run-tests.py` | Sole test-selection, collection-reconciliation, and pytest-execution owner; validates `tests/test-impact.json`, explains deterministic Git-diff selection, rejects mapping gaps before pytest collection or execution, supports explicit committed-diff, worktree, collection, and `--all` modes, adds `--select-only` to check diff/worktree mapping without pytest, and saves failed-pytest streams and structured pre-test failures with captured command output through `--diagnostic-output`; pytest output remains bounded in the console. |
| `scripts/testing/pytest-diagnostics.py` | Extracts bounded failure summaries using exact pytest identities and source-file evidence; ambiguous or missing tracebacks use only that test's summary reason. Full diagnostic files remain owned by the runner. |
| `scripts/validate-repository.py` | Local validation coordinator; checks the running Python against `scripts/pyproject.toml`, captures first-failure evidence, delegates its default full test phase to `scripts/testing/run-tests.py --all`, and supports CI's separate runner-owned test phase. |
| `skills/ceratops-repo-lifecycle/references/templates/deploy-skills.py.tmpl` | Authoritative standalone installer copied into compatible skill repositories as `scripts/deploy-skills.py`; invoke it through uv using the scripts project. |
| `skills/ceratops-repo-lifecycle/references/contracts/repository-validation-contract.json` | Schema-validated repository checks used by compatibility generation and included in repository contract review and validator discovery. |
| `skills/ceratops-repo-lifecycle/references/contracts/ceratops-compatibility-*-contract.json` | Internal structural contract consumed by compatibility generation/checking, plus a behavioral review rubric for environment setup, tests, and lifecycle orchestration; no external source registry. |
| `skills/ceratops-repo-lifecycle/references/templates/validate-repository.py.tmpl` and `validate.yml.tmpl` | Repository-neutral validator and CI templates created only when their target files are absent; new validation setups without JavaScript package-manager files also receive locked Markdown dependencies and default rules from the Markdown templates. Existing tooling, Markdown settings, and exclusive validators are preserved. |
| `skills/ceratops-repo-lifecycle/scripts/ceratops_repo_compatibility_engine/` | Skill-owned package with the shared compatibility-contract loader, read-only compatibility checks, SDLC-contract validation, rollback-protected Ceratops compatibility application, and version-only bootstrap synchronization; it operates on explicit target repositories and is never copied into them. |
| `skills/ceratops-repo-lifecycle/references/templates/skill-sections.json.tmpl` | Repository-neutral template for creating a target repository's live `skills/skill-sections.json`; never a live manifest. |
| `skills/ceratops-skill-lifecycle/scripts/runtime/install-managed-skills.py` | Classifies exact affected sets, owns direct-manifest inventory, and invokes one runtime transaction; emits commit-bound completion evidence and can finalize its saved promotion handoff without replaying deployment. |
| `skills/ceratops-skill-lifecycle/scripts/runtime/managed_runtime_builder.py` | Stages, activates, rolls back, recovers, and cleans one locked selected-skill runtime transaction. |
| `skills/ceratops-skill-lifecycle/scripts/skill-update-workflow.py` | Prepares and verifies declared cohesive skill updates, checks ancillary ownership against the prepared commit so staged and committed deletions remain valid, preserves unrelated dirty state, owns temporary check folders through collection and verification, records exact task-temp ownership plus an active-update retention marker, finalizes owned request, state, evidence, and marker files, and removes the verified task-temp root only when empty after completed caller use. |
| `skills/ceratops-skill-lifecycle/scripts/skill_update_scratch.py` | Supplies subprocess-only temporary-directory settings under the verified task-temp root and removes its unique check folder after success or failure; cleanup errors block verification while preserving check evidence, and recorded residue is retried before new checks. Explicit paths in check arguments remain caller-owned. |
| `skills/ceratops-credit-savings-analysis/scripts/credit_analysis/session_evidence_collector.py` | Resolves current, named, indexed, and project-identified sessions and collects one complete prepared traversal per analysis, preserving formatted messages, canonical current-source references, bounded nested-command failure provenance, tool and process telemetry, fingerprints, usage, closure, and classification modes. |
| `skills/ceratops-misunderstanding-audit/scripts/audit.py` and `audit_sources.py` | Read selected local history or exported maintained-reader pages, freeze N-day or single-case scope, separate user wording from annotations, preserve timestamp and lineage evidence, validate semantic-review accounting, and publish a report and ledger with scoped temporary-input cleanup; no model calls or automatic rule edits. |
| `skills/ceratops-credit-savings-analysis/scripts/credit_analysis/execution_outcomes.py` | Shared interpretation of tool-result envelopes and runtime failure headers for collection, model-input preparation, and review routing; printed content stays separate and nonzero process results do not imply semantic failure. |
| `skills/ceratops-credit-savings-analysis/scripts/credit-analysis-workflow.py` and `scripts/credit_analysis/` | Keep one stable CLI over explicitly named single-thread analysis, multi-thread analysis, model-capacity planning, Luna/Sol analysis, prior-analysis runs, session-evidence collection, contract snapshots, and command-line dispatch modules. Each holistic run retains its own immutable contract file so runtime deployment cannot replace that recorded input. |
| `skills/ceratops-credit-savings-analysis/scripts/credit_analysis/orchestration_execution.py` | Owns the finite concurrent reviewer queue and corrective attempts. One controller validates and durably checkpoints completed siblings while others run; replay uses retained attempts and accepted results. Bounded corrections carry the rejected response and exact validation errors. Corrections preserve coverage, array order, and schema-valid fields; an input that cannot fit intact or a correction that changes protected judgments remains rejected. Retry prompts and schemas stay with the retained attempt evidence. |
| `skills/ceratops-credit-savings-analysis/scripts/credit_analysis/model_response_contract.py` | Owns the shared model-facing schema fragments and Python shape checks for lowercase identifiers and classification/reason forms; evidence references, completeness, and semantic checks remain independent. |
| `skills/ceratops-credit-savings-analysis/scripts/credit_analysis/report_rendering.py` | Renders full-analysis reports as runs tables with UTC start times, combined avoidable counts, separate unassessed counts, exact omission labels, and token percentages. Direct-result delivery uses retained per-call evidence for the same table. Chat guidance comes from the parent skill Output Contract; the caller selects useful findings across the requested audit while complete findings, risks, accounting, and reviewer records stay in machine evidence. |
| `skills/ceratops-credit-savings-analysis/scripts/credit_analysis/report_bookkeeping.py` | Owns result-shape validation, surface ordering, temporary-control links, category consolidation, and reviewer-record preservation. Final results retain complete original confirmed findings, risks, control reviews, and category assessments in controller-generated `source_findings`, `source_risks`, and `source_reviews`, checked against accepted reviewer records. Candidate links identify each finding's destination, which must cover its original calls and evidence; retained source findings do not add to savings or finding totals. Copied category checklists aggregate applicability across reviewed portions without discarding differing assessments. Every distinct risk uncertainty remains in machine evidence. The controller revalidates saved final output before enforcing limits on new attempts and selects the highest-priority complete audit window that fits the reserved review slot. |
| `skills/ceratops-task-lifecycle/scripts/closure_snapshot.py` | Emits one compact snapshot for explicitly named closure targets, inspects temp-root metadata without traversal unless `--count-temp-files` is requested, and optionally removes exact task-created files validated inside the task temp root. |
| `skills/ceratops-governance-lifecycle/scripts/apply_rules_update.py` | Applies approved rule and TOML text with required rule-history appends or exact ID migrations, supports validated history-only identity repairs, rolls back mixed writes, and cleans only explicitly disposable artifacts after success. |
| `skills/ceratops-governance-lifecycle/scripts/validate_rule_candidate.py` | Preflights untouched Markdown before proposal preparation, safely repairs candidate-only whitespace, parses complete TOML targets without reflow, preserves shared rule/history checks, proves idempotence, and writes caller-selected evidence. |
| `skills/ceratops-governance-lifecycle/scripts/rule_candidate_source.py` | Owns exact UTF-8 source loading, encoding and line-ending preservation, shared candidate data, and input-integrity checks used by governance validation and application. |
| `skills/ceratops-governance-lifecycle/scripts/proposal-workflow.py` | Validates exact proposal inputs, histories, target policies, and hashes; rejects untouched formatting errors before opening artifacts; records task-temp ownership; delegates validated controller transitions; and preserves the exact champion while finalizing owned artifacts. |
| `skills/ceratops-governance-lifecycle/scripts/iteration_controller.py` | Opens structured candidates, invokes mechanical validation before recording, retains the exact validated champion, enforces stopping, and safely finalizes owned artifacts. |
| `skills/ceratops-governance-lifecycle/scripts/rule_graph.py` | Parses canonical AGENTS rules and rejects structural syntax or rule-local explicit-user override escape clauses. |
| `skills/ceratops-repo-lifecycle/scripts/github_contract_engine/` | Package CLI for compact local audit snapshots, contract evaluation, shared GitHub API access, sanitized evidence, and evidence-gated CodeQL disposition. |
| `skills/ceratops-repo-lifecycle/scripts/github_pr_workflow/` | Package CLI for individual PR operations, opt-in scoped branch/stage/commit preparation and checked draft or fork PR publication in `ensure_pr.py`, bounded standalone review and CI inspectors with caller-owned evidence files, shared readiness-owned CI diagnostics, one-call retry-safe review replies and resolutions, decision-complete gate blockers, single-snapshot terminal Actions outage detection, exact-commit checkpointed shipping, four-proof obsolete-prepared-checkpoint cleanup before automatic resume, scoped pending-work checks, concurrent gates, integrated admin merge, reusable-branch restoration, and terminal cleanup. |
| `skills/ceratops-repo-lifecycle/scripts/promote-repository.py` | Prepares `release/local`; promotes selected branches with no deployment or an explicit ordered operation selection; or composes promotion into exact-head shipping with ordered release and deploy selections, finalization, and cleanup; checks live publication before rebasing only task commits while preserving shared history; records outcomes and finalizes bound deployment evidence within the task temp root without replay. |
| `skills/ceratops-repo-lifecycle/scripts/manage-pending-work.py` | Records, checks, automatically resumes the retained target commit, and progressively finalizes the exact selected scope; preflight preserves and reports non-cleanup-eligible worktrees, while eligible residual-worktree and identity-matched task-temp cleanup stays within validated named directory boundaries and preserves active skill-update state for post-deployment finalization. |
| `skills/ceratops-repo-lifecycle/action.yml` | GitHub composite action that runs declared validation and tests using the skill-owned SDLC engine; CI defers skill handoffs and retains failure evidence. |
| `skills/ceratops-repo-lifecycle/scripts/repository_operation.py` | Single capability runner: resolves complete YAML locations, prevalidates ordered argv/parameters/cwd, runs declared validation before deployment or publication, and retains bounded structured step results separately from command completion, with bounded failures and advisory handoffs. |
| `skills/ceratops-repo-lifecycle/scripts/ship-repository.py` | Prevalidates one SDLC contract and ordered phase selections, runs declared CI test selection against freshly fetched base and exact staged head commits before push, and orchestrates guarded GitHub shipping, main synchronization, per-operation publication and deployment checkpoints, and resumable selected-source cleanup. |
| `skills/ceratops-repo-lifecycle/scripts/rename-repository-path.py` | Plans or applies tracked file renames and exact filename references; accepts explicit or Git-detected rename pairs, updates relative Markdown links, blocks ambiguous references, preserves the index and text bytes outside replacements, and compensates caught file errors. |
| `skills/ceratops-skill-lifecycle/scripts/skills-consistency-source-validator.py` | Existing source, metadata, runtime-input, contract, and portability validator invoked by source-validate and explicit skill workflows. |
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

Promotion validates the assembled `release/local` commit.
`promote-and-deploy` additionally runs explicitly selected `deploy-local`
entries after that single validation and test pass. Shipping requires both
results before remote changes and repeats both on the synchronized commit before
pending publication or deployment. Successful earlier checks do not suppress
a later lifecycle
boundary. The agent repairs ordinary failures in the selected task worktree,
commits and retries; a failed check never permits later mutation.

Operations are identified by their YAML location, such as
`repository.bootstrap.runtime` or
`deliverables.skills.deploy-local.ceratops-managed`.
There are no extra IDs, defaults or full flows in the contract. Prerequisites
are setup metadata; only explicitly declared bootstrap commands install
dependencies. Version-3 handoffs name a skill/action. For skill callers, the
engine resolves the installed skill's `references/action-executors.json` and
runs its declared argv or ordered steps; unresolved routes block dependent work.
CI uses `--ci`, never dispatches skills, and reports deferred handoffs separately.
Earlier SDLC versions retain advisory handoffs.
Ceratops skill handoffs use the operation name `ceratops-managed`, including
skill and tool deployment. Skill source validation stays under the generic
`validate` category: `deliverables.skills.validate.ceratops-managed` hands off
to `ceratops-skill-lifecycle/source-validate`; its skill-owned binding invokes
the validator. Managed deployment binds source validation followed by the
transactional installer. The compatible-repository producer
adds these skill operations only for source skills in current-format contracts;
the generic template declares repository validation and an explicit test no-op.

`ship` derives its optional pending-work scope from the staged branch. When
present, the same generic scope is checked before the first remote
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

- Applying current compatibility creates `sdlc/sdlc.yml` version 3.
  `repository` owns prerequisites, bootstrap, validation and shared tests;
  every deliverable declares its own tests plus any validation, deployment,
  publication and artifact identities. Each operation declares commands,
  a skill handoff, or a nonempty `no-op` reason. Validation and tests are
  separate gates; explicit selections cannot omit applicable version-3 gates.
  The same engine still executes version 1 and 2 without automatic migration.
  Version 1 uses `deploy.operations.NAME` and `release.operations.NAME`.
  Applying current compatibility upgrades version 2; version 1 needs explicit
  operation-ownership mapping before application. Installer release numbers
  alone do not determine SDLC compatibility.
- Operation `status: completed` records command completion. A successful step
  whose entire stdout is a JSON object with nonempty string `schema` and
  `status` fields is retained unchanged in `step_results` as
  `{"step": POSITION, "result": OBJECT}`. `POSITION` is the declared version-1
  step ID or the one-based version-2/3 step position. Domain success still
  requires the producer's schema, status and evidence checks; `OK` is not
  translated to `deployed`. Capture does not validate that domain schema.
  Stdout above 65,536 UTF-8 bytes yields
  `{"step": POSITION, "result_omitted": "stdout_limit"}` without content.
  Logs, mixed output, non-object JSON, malformed JSON, duplicate members and
  non-finite numbers or container depth above 64 are suppressed; successful
  stderr is never forwarded.
  Earlier captured results survive later step failure or commit drift.
  Promotion returns them and shipping persists them in existing operation
  checkpoints for resume. Missing results, including older saved operation
  metadata, do not authorize replaying a completed mutation to recover output.
- On command failure, diagnostics include a concise error excerpt and preserve
  bounded structured errors from each output stream. Excerpts extract error
  details before shortening the output and retain reported diagnostic-file
  locations. CI log retrieval may fall back to the raw log of the completed
  job; it never reruns the failed command.
- `skills/ceratops-repo-lifecycle/references/contracts/github-contract-source-docs.json`
  records official source documents and reference repositories used by GitHub,
  repo, PR readiness, code, artifact, and repository-validation contracts. Its
  `repository_validation` scope includes tool documentation and discovery
  indexes; contract review also performs bounded web searches for missing tools.
- `skills/ceratops-repo-lifecycle/references/contracts/ceratops-compatibility-deterministic-contract.json`
  owns compatibility destination/template mappings, required-file conditions,
  accepted manifest profiles, CI arguments, and managed-skill routing defaults.
  Its closed schema and loader validate the internal companion review contract
  and SDLC defaults before target mutation. Contract review checks both documents;
  compatibility application and health review apply the companion requirements
  from local declarations and execution results, without an external registry.
  It also owns the isolated uv runtime, Python-test discovery and required
  runner, SDLC version and CI execution boundary. Structural success alone
  does not prove test coverage or custom-validator separation.
- `skills/ceratops-repo-lifecycle/references/contracts/repository-validation-contract.json`
  owns the conditional checks used to generate missing repository validators
  and CI workflows. Its closed schema and loader validate all entries and
  evidence scopes before selection. It contains validation behavior only;
  tests and dependency versions belong to repository declarations.
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
Local health validates each present `sdlc/sdlc.yml` against its version's schema
and checks generic repository compatibility. Supported older formats produce
advisory migration proposals with the repository, current and recommended
versions, and reason. The existing Global Repo Health Consistency automation
receives these through its health findings; proposals neither block execution
nor migrate files. Ship validates selected publication operations before remote
mutation. Local health runs SDLC validation and tests, including registered
deterministic skill actions when declared. It retains direct validator
execution for repositories without a validation-capable SDLC.

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
| org validator, implicit org surface | `settings` | `$ceratops-repo-lifecycle` repo-contracts-review for contract governance; health-audit only when org posture is part of a live health audit. |
| org validator, implicit org surface | `actions` | `$ceratops-repo-lifecycle` repo-contracts-review for contract governance; health-audit only when org Actions posture is part of a live health audit. |
| org validator, implicit org surface | `dependabot` | `$ceratops-repo-lifecycle` repo-contracts-review for contract governance; health-audit only when org Dependabot posture is part of a live health audit. |
| org validator, implicit org surface | `security` | `$ceratops-repo-lifecycle` repo-contracts-review for contract governance; health-audit only when org security posture is part of a live health audit. |
| org validator, implicit org surface | `all` | `$ceratops-repo-lifecycle` repo-contracts-review for contract governance; health-audit only for explicit broad org health. |
| `repo` | `settings` | `$ceratops-repo-lifecycle` repo-contracts-review for contract governance; health-audit when live repo state is part of the task. |
| `repo` + `code` via `--select repo:dependency --select code:dependency` | `dependency` | `$ceratops-repo-lifecycle` dependency-maintenance action when both live GitHub dependency/security posture and repo-content dependency posture are in scope; health-audit action for dependency posture audits. |
| `code` | `content` | `$ceratops-repo-lifecycle` repo-contracts-review for contract governance; health-audit or create-or-publish when repo contents are part of the task. |
| `artifact` | `artifact` | `$ceratops-repo-lifecycle` repo-contracts-review for contract governance; health-audit or create-or-publish when a published artifact is part of the task. |
| `all` | `create` | `$ceratops-repo-lifecycle` create-or-publish action. |
| `all` | `health` | `$ceratops-repo-lifecycle` health-audit action; repo-contracts-review only for broad contract governance. |
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

## Reusable Repository Tooling

Compatibility templates create `scripts/pyproject.toml`, `scripts/uv.lock`
and an ignored `scripts/.venv` with a Python matching `requires-python`. This separate
uv project owns tooling dependencies. `pyproject.toml` and `uv.lock` suffice
for that environment; no parallel requirements file is needed. Existing
application manifests retain their owners and locations. Dependabot gets
a `uv` entry for `/scripts` without removing other entries.

The same project template supplies Ruff lint rules and mypy checking defaults.
Generated validators select those settings explicitly unless the repository
provides root tool configuration. Existing settings remain authoritative;
compatibility adds only absent tool tables.

Initial application resolves the lock and syncs the environment. Later runs
use the lock; missing dependencies are installed by uv before Python starts,
while stale locks fail instead of changing dependency decisions during checks.

SDLC execution and schemas stay in the repository-lifecycle skill. Target
repositories receive no engine copy or SDLC launcher. CI sets up uv and calls
`Ceratops-Code/AI-Agent-Skills/skills/ceratops-repo-lifecycle@<commit>` with
`repo-root` and `evidence-file` inputs. GitHub obtains the action; no Codex skills
installation is needed on the runner. The action uses its own locked Python
project, while target scripts use their repository's project.

Compatibility preserves an existing action pin. For new CI it resolves a
published revision before writing files; `--ci-action-revision <commit>` selects
an explicit revision for offline planning or a chosen release. That revision
must contain the published action before CI can run. Dependabot maintains
GitHub Actions pins as well as the scripts project.

Skill callers invoke their bundled engine directly:

```powershell
uv run --no-project --python 3.14 python "$env:CODEX_HOME/skills/ceratops-repo-lifecycle/scripts/run-skill.py" scripts/repository_operation.py --repo-root <repo> --validate
```

`--validate` runs validation and tests as separate operations. `--tests` selects
only tests; `--return-handoffs` exposes unresolved routes to a skill caller.
New repository validators never select test runners. Conventional Python tests
or pytest configuration generate `scripts/run-tests.py` from its template when
absent. That runner uses the scripts project, owns its temporary pytest
directories, and can be customized. Invoke Python entrypoints with
`uv run --locked <path-to-script.py>`; uv discovers their project from the
script location and prepares its environment before execution. Use an
absolute script path when calling from outside the repository. Module
commands select the project with `--project scripts`. Repository scripts
contain no environment bootstrap or package-installation logic. Existing
test implementations and non-Python test commands remain repository-owned.

This source repository uses `scripts/pyproject.toml` and `scripts/uv.lock` for
its maintenance scripts and Python tests. The root `pyproject.toml` holds Ruff
and mypy settings. Its existing SDLC format and test-selection behavior remain
repository-owned; this environment migration does not apply every compatibility
template to the source repository.

## Shared Skill Python Environment

All managed skills receive `scripts/run-skill.py` and a small
`scripts/python-runtime/pyproject.toml` and `uv.lock` pair through the section
manifest. The source declarations live under `skills/sections/python`.
Dependabot maintains this project's lock independently of repository tooling.
Compatibility setup copies these starter inputs into skill-bearing targets;
their owners declare any additional dependencies their skills need.

Run an installed Python helper through its launcher, preserving its arguments:

```text
uv run --no-project --python 3.14 python <skill-root>/scripts/run-skill.py scripts/<helper>.py
```

The launcher also accepts `-m MODULE`. The first uv command selects the
dependency-free bootstrap interpreter. The launcher then invokes uv with the
bundled project's locked dependencies and required Python version. It preserves
the caller's working directory and the helper's output and exit status.
Nested plain Python commands inherit that environment. Repository uv commands
select their own projects; the launcher does not forward its setup override.

The shared environment resides at `$CODEX_HOME/runtimes/ceratops/.venv`.
When `CODEX_HOME` is unset, the launcher uses `~/.codex`. uv reads declarations
from the installed skill and synchronizes that fixed environment before helper
execution. Different installed locks update the same active dependency set;
managed skills should therefore be deployed with consistent declarations.
The fixed `runtime.lock` file serializes setup across installed bundles;
helper execution releases that lock so skills can call one another.
Deployment copies declarations, never a `.venv`. Missing packages are repaired;
stale locks block execution. The environment remains reusable after success or
failure. Existing external tools retain their installer-owned environments.

## Install For Codex

Codex discovers personal skills from:

```text
$CODEX_HOME/skills/<skill-name>/SKILL.md
```

Install uv and a global Python matching `scripts/pyproject.toml`. The shared
bootstrap selects that Python and creates `scripts/.venv` with the committed
lock; it does not install packages globally or download another interpreter.

```powershell
python .\scripts\deploy-skills.py
```

The deployed skills' separate project includes timezone data for date-based
helpers on Windows. The standalone installer uses the scripts environment and
never calls installed lifecycle code. It
renders the selected batch in a hidden staging directory and copies its files
over existing installations without source or staged-content validation.
Destination-only files and unselected or retired skills remain untouched.
Input parsing and path-safety checks remain necessary for copying. Copy errors
can leave partial updates; staging and locks created by this run are cleaned.
For validated deployment with managed retirement and rollback, use
`$ceratops-skill-lifecycle` `deploy`.

For another Ceratops-compatible repo, run its versioned repository installer:

```powershell
python <target-repo>\scripts\deploy-skills.py --repo-root <target-repo>
```

An external repository's copied bootstrap is independent: it uses only the
Python standard library, reads declared skills, resolves shared sections and
payloads, and overlays the requested output under the install root. It retains
destination-only files and other skills. It does not locate or run Ceratops,
validate skill or repository content, negotiate compatibility, or fall back
after an error.

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
skill's `deploy` action for managed updates or the independent installer for
an explicit overlay without validation or retirement.
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

## Rename Files And References

From the installed `ceratops-repo-lifecycle` skill directory, preview a rename:

```powershell
python scripts/rename-repository-path.py --repo-root PATH --rename scripts/old.py scripts/new.py
```

Add `--apply` to change files. Repeat `--rename OLD NEW` for independent pairs.
Use `--from-git` for staged renames, or add `--base BASE --head HEAD` for committed
renames. Git's similarity detection can miss a heavily rewritten file; supply
the explicit pair in that case. The helper creates no permanent rename catalog
and leaves staging and committing to the caller.

The plan lists exact reference edits and unresolved filenames. It updates
repository-relative path tokens, including backslash forms, and local Markdown
links, preserving quotation marks and line endings. Moving a Markdown document
also adjusts its links to tracked local files. Ambiguous bare names, computed
paths and non-UTF-8 references block application. Resolve them with an explicit
`--reference OLD NEW` replacement, or preserve an entire historical reference
file with `--exclude FILE`. This does not perform language-symbol refactoring.
Only tracked regular files and already-moved destinations are included; links,
case-only renames, overlapping pairs and existing destinations are rejected.
Case-only renames need an explicitly staged intermediate filename.
An existing worktree's edited content is preserved outside the planned changes.

Use `--report PATH` for a new report outside the repository; the caller owns its
retention and cleanup. Without a report, preview prints the plan and a successful
apply prints `OK`. Caught file errors restore original bytes and paths and remove
only newly created empty directories. After process termination, inspect Git's
working-tree diff before retrying; no crash-recovery journal is maintained.

## Validate

Install the declared Python and Node development dependencies, optionally
select a failure-evidence path, then run the same repository validator used by
CI:

```powershell
npm ci
$validationEvidence = Join-Path $env:TEMP "repository-validation.log"
uv run --locked scripts/validate-repository.py --evidence-file $validationEvidence
```

CI runs `uv sync --project scripts --locked`; local commands use
`uv run --locked <script.py>`. In both cases uv selects Python from
`scripts/pyproject.toml` and synchronizes its locked dependencies before
execution. The validator checks the selected interpreter against the project's
requirement before repository checks; mypy uses that interpreter. Root Ruff and
mypy settings configure the checks independently of dependency installation.

Without the flag, evidence defaults to
`build/deploy-validation/repository-validation.log`.
Failure evidence remains available for diagnosis until the next successful run,
which removes the selected evidence file and prunes the dedicated default
directory when it is empty.
The validator runs Markdown and YAML lint, Ruff, mypy for Linux and Win32, and
`scripts/testing/run-tests.py --all`. Pull-request CI calls the same runner
with exact base and head commit SHAs. Local uncommitted selection is explicit
through `uv run --locked scripts/testing/run-tests.py --worktree`.
Add `--select-only` to either diff or worktree mode to validate the same mapping
without collecting or running pytest; success reports `selection-valid` and
pytest `not-run`, including when no tests are selected. Failures retain the
normal diagnostics.
Shipping runs optional `repository.test-selection` entries from `sdlc/sdlc.yml`
before pushing, independently of `repository.validate`. Each entry declares
`parameters: [base, head]` and executable steps using whole-argument `{base}`
and `{head}` placeholders. The helper supplies the freshly fetched remote base
and exact staged head commits. Entries without both arguments, failed checks,
fetch failures and changed source state block the push. Other lifecycle actions
keep their existing validation discovery. A base branch that advances after
this check is still evaluated by GitHub CI.
Manifest validation
is available through
`uv run --locked scripts/testing/run-tests.py --validate-manifest`.
The validator does not invoke skill-local validators. Generic compatibility and
health validate lifecycle definitions through the repository-lifecycle
`ceratops_repo_compatibility_engine.sdlc_contract_validation` module. Runtime
rendering is owned only by bootstrap and managed deployment under the selected
install root.

Each pytest subprocess gets temporary-directory defaults in its own disposable
directory beneath `PYTEST_DEBUG_TEMPROOT` when set, otherwise the system
temporary directory. The runner removes it when the subprocess exits and
keeps failure diagnostics at the selected output path. On Windows it enables
Git long-path handling for the child process and repositories initialized
from a private copy of Git's selected template, preserving the template's
other files and configuration.

Failed pytest runs write complete stdout and stderr to
`build/test-diagnostics/pytest-failure.json` by default. Use
`--diagnostic-output PATH` to select another file; the terminal JSON contains a
bounded failing-test summary plus the file path, byte count, and SHA-256 hash.
A successful pytest run removes stale evidence at the selected path.

For a structural test migration, capture the pre-migration collection and
reconcile it after moving tests:

```powershell
$collection = Join-Path $env:TEMP "pytest-collection.json"
uv run --locked scripts/testing/run-tests.py --write-collection $collection
uv run --locked scripts/testing/run-tests.py --reconcile-collection $collection
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

Use `ceratops-skill-lifecycle/source-validate` for deterministic source
validation. Its bundle owns the helper invocation and requires an explicit
source repository. During source maintenance, the equivalent full-mode command
from the source checkout is:

```powershell
python .\skills\ceratops-skill-lifecycle\scripts\skills-consistency-source-validator.py --mode full
```

To explicitly validate selected skill sources and their rendering inputs,
run the source validator separately from installation:

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
shared section stays visible in the installed skill copy.

The optional `actions` object maps skill names to direct action-reference paths
and ordered section-ID lists, independently of existing `skills` assignments:

```json
{
  "actions": {
    "ceratops-repo-lifecycle": {
      "references/repo-contracts-review.md": ["contract-review"]
    }
  }
}
```

Each target must exist, have an H1 of `# <Action Name> Action`, and appear once
in its parent's `### Action References` index. Installation inserts one shared
block immediately after that H1; unassigned actions remain unchanged. Unknown
skills or sections, unsafe or unrouted paths, malformed or empty assignments,
repeated sections (including source aliases), inherited skill-level sections,
and generated markers in source actions are rejected. An absent or empty
`actions` object preserves existing skill-only manifests. The reusable template
starts with an empty action map.

`skills/sections/contract-review.md` is assigned only to
`ceratops-repo-lifecycle: repo-contracts-review` and
`ceratops-skill-lifecycle: skills-contract-review`. Routing and instruction
inspection identifies these as the contract-standards review actions.
`skills-consistency-review` and design-document `review` check compliance;
credit-savings helper-contract analysis reviews execution costs. Those actions
do not receive the section. Core rules remain in `core.md`; domain-specific
requirements, including repository validator discovery, remain in their action
references. Scripts, checkers, contracts, and evidence registries retain their
owning skill paths and remain available to other actions.

The managed renderer and standalone bootstrap produce identical action content;
the bootstrap and its template remain independent of installed lifecycle code.
The compatibility checker uses its own bundled bootstrap parser and preserves
action assignments during materialization. Source validation checks action
assignments in skill, sections, and full modes. Changes to an action assignment
or its section source select its skill in both the old and new manifest; they
do not select unrelated skills.

Runtime payload strings preserve their repository-relative installed paths; an exact
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
