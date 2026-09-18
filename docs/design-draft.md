# Ceratops repository lifecycle design draft

## Scope and status

This draft records the decisions made in the discussion about repository
validation, Python environments, SDLC v3, and deployment helpers. It uses only
that discussion. It is not a complete design, an implementation audit, or a new
governing contract. The linked files identify the owners discussed in the
thread; they were not investigated to extend this draft's scope.

The intended users are agents and CI working on Ceratops-compatible
repositories, including repositories other than AI-Agent-Skills and
repositories containing languages other than Python. Repository configuration
declares what to check, test, and deploy; installed skills own shared lifecycle
procedures. Repository-specific tests and dependencies remain with the repo.

## Ownership and contracts

| Surface | Responsibility recorded in the thread |
| --- | --- |
| `repository-validation-contract.json` and its schema | Define validation behavior and when validators apply, without named repositories, package prerequisites, or package-version pins. |
| Ceratops compatibility deterministic contract and schema | Define mechanically checkable compatibility requirements and the reusable files needed to satisfy them. Executable fields require a runtime or validator consumer. |
| Ceratops compatibility nondeterministic contract | Guide review of whether the repository's choices satisfy the internal Ceratops intent. External evidence is not invented for this internal concept. |
| Repository dependency declarations and lockfiles | Own the packages and versions needed to execute repository commands successfully. |
| Repository `sdlc/sdlc.yml` | Declare operations, tests, and skill/action handoffs for this repository and its deliverables. |
| Installed lifecycle skills | Own reusable execution, validation gates, deployment routing, and their domain helpers. |
| Repository test runner and tests | Own repository-specific test execution and implementation. |

The validation catalog became a contract because its entries govern generated
validation behavior. Its name is now `repository-validation-contract.json`.
Removing package requirements from that contract does not remove dependency
management: repositories declare dependencies, uv prepares their environment,
and the checks must actually succeed. A package-presence or version heuristic
is insufficient evidence that a repository's checks work.

Validator configuration detection must recognize supported configuration
locations. The pytest correction added its omitted TOML and INI forms and
matching unittest exclusions, so a pytest repository is not misclassified.
This is detection of which validation/test tooling the repository uses, not a
requirement to run its tests inside repository validation.

Contract maintenance combines documentation evidence with bounded web searches
for validators missing from the contract, across languages. Reviewing only
already-listed validators cannot discover a newly introduced validator.
Domain review actions retain their own contracts, scripts, evidence sources,
and checkers; common review guidance is shared through action sections.

## Compatibility setup and Python environments

`apply-ceratops-compatibility` is the action/helper name chosen instead of
"materialization." Its reusable templates provide compatible repository
surfaces while preserving repository-owned choices. Template changes belong
with their generators and consumers so other repositories receive the same
behavior.

The recorded template set includes `validate-repository.py.tmpl`,
`run-tests.py.tmpl`, `deploy-skills.py.tmpl`, `sdlc.yml.tmpl`, and
`skill-sections.json.tmpl`. Python test detection is deterministic where
possible; repositories with Python tests receive the required runner from a
template. Test bodies and their implementation remain repository-specific.

| Environment | Declarations | Execution and ownership |
| --- | --- | --- |
| Repository Python scripts and tests | `scripts/pyproject.toml` and `scripts/uv.lock` | uv selects the required Python and prepares ignored `scripts/.venv`; repository entrypoints use this project. |
| Installed Ceratops skill helpers | Source-only declarations under `skills/sections/python` | Deployment prepares a versioned venv under `$CODEX_HOME/runtimes/ceratops/versions/`; each installed skill manifest pins its interpreter. Direct uv commands run helpers, and old versions remain available to running helpers. |
| Installed external tools | The selected tool's declarations and installer | The tool manager owns the installed tool environment, separately from the shared skill environment. |

One environment does not need both requirements files and a pyproject dependency
list. The thread selected pyproject plus its lockfile and removal of the root
requirements files. In AI-Agent-Skills, `scripts/pyproject.toml` owns both
Python tooling dependencies and Ruff and mypy settings. Node tooling manifests
and Markdown/YAML lint settings also live under `scripts`; generated diagnostic
files live under the ignored `.build` directory.
Dependabot must address the directories containing the dependency projects,
including `/scripts` and the separate shared skill project.

Repository examples use `uv run --locked scripts/<entrypoint>.py`; source
helpers outside `scripts` use `uv run --project scripts --locked python ...`.
The caller and uv prepare the environment. Individual scripts do not contain
the removed `python_environment.py` self-installing bootstrap. A direct
`python script.py` invocation still uses the explicitly selected interpreter;
it does not automatically turn into a uv invocation.

Earlier discussion allowed test environment overrides. The later decision
places tests and other repository scripts under the same scripts project.

## Operations, tests, and CI

SDLC here means the repository's lifecycle configuration in `sdlc/sdlc.yml`.
An operation is an entry such as a deliverable's validation or local deployment
command. A handoff names an installed skill and action that owns the next step.

Version 3 gives every deliverable a `tests` section. A deliverable may declare
a no-op with a reason, including coverage by repository-wide tests. Different
deliverables can name different test entrypoints. The repository validator
does not execute tests; promotion, shipping, and CI require both applicable
validation and test results before dependent work proceeds.

The reusable operation procedure belongs to the repository-lifecycle skill's
`repository_operation.py`: read the selected repository's YAML, select the
applicable operations, run commands and gates, and resolve skill-owned
executable bindings. This avoids each lifecycle helper implementing its own
interpretation of those declarations. It does not move repository tests into
the skill.

The final direction removes generated repository `sdlc.py`, a local copy of the
operation engine, and `scripts/runtime`. Those proposed extra layers were
rejected. Installed skill bindings remain in the skills; target repositories
receive configuration and their own entrypoints.

CI runs declared executable checks and tests and reports skill handoffs as
deferred. It does not dispatch skills. A skill-driven workflow can execute
those handoffs. AI-Agent-Skills uses its local composite action; other
repositories can use a pinned published action.

For this repository, the thread reported migration to SDLC v3, repository-wide
tests, and explicit deliverable test no-ops. Its runner supports individual
test paths or node IDs and optional automatic selection: all tests locally and
on pushes, with impact selection from the exact pull-request base/head in CI.
That impact-selection implementation is repository-specific, not a requirement
imposed on every compatible repository.

## Promotion, installation, and update recovery

Promotion takes task work into the local release batch. Its deployment steps
come from the selected repository's YAML; the promotion helper must not
hardcode dependencies on the skill-lifecycle implementation. Skill-driven
execution resolves the named installed skill/action and waits for each command
to finish successfully before dependent mutations.

Automatic rebasing considers the task-only commit range. Inherited
`origin/main` tracking is not proof that the task branch is published, and
merges already shared with main are not task merge commits. The safeguards
retain refusal for actual published work that would be rewritten, ambiguous
ancestry, merges within the task changes, and failed Git queries. A failed
rebase must restore the original clean state.

Deployment completion must be verifiable against the selected commit,
installed skills, destination, outcome, and cleanup debt. Promotion finalization
removes only its owned temporary record after validating completion. It
preserves failed, incomplete, mismatched, or changed records. Cleanup must
never rerun deployment. A bare `OK` detached from the recorded operation does
not prove that an arbitrary saved record is eligible for removal.

Tool deployment can route to `ceratops-tool-lifecycle/install`. Its installed
binding invokes the installed manager with `--source` set to the selected
repository. That checkout supplies the tool name and version. "SDLC install"
was shorthand in an earlier answer, not a separate command.

`supersede` is a subcommand of `skill-update-workflow.py` for an explicitly
revised update request after failed verification. It creates a successor
request/state while retaining the original source baseline and failed records.
It may expand the declared scope but cannot hide unrelated changes. Only after
the successor passes and is finalized may unchanged inherited disposable
records be removed. It does not deploy skills.

## Shared sections and generated skill copies

The live `skills/skill-sections.json` manifest maps shared content to skills
and specific actions. Shared sources remain under `skills/sections`; the
reusable manifest template is separate from the live manifest. Shared file
ownership also lets source validation select the affected skills.

Contract-review actions share common review guidance through that mechanism.
Their domain-specific dependencies remain in the owning skills because other
actions use them. The repository action reference is `repo-contracts-review.md`;
the skill action is `skills-contract-review.md`.

Generating runtime skill copies means rendering shared sections and payloads
into installed skill directories. It does not mean generating another SDLC
engine in the target repository. Managed deployment and the standalone
installer must preserve the same action content.

## Verification, limits, and unresolved points

The thread reported targeted promotion, installation, transaction, runner, and
update-workflow tests, followed by passing repository checks. That is historical
implementation evidence, not a new verification of every statement in this
draft. Documentation checks cannot prove the lifecycle is correct end to end.

The discussion emphasized tests for successful completion and preservation of
refusal, publication, recovery, and cleanup safeguards. Template behavior must
also be checked so fixes are available to other repositories. Routine
deterministic phases should finish in helpers with progress reporting, leaving
model intervention for decisions and skill work that actually require it.

The thread does not settle a complete architecture, security model, concurrency
design, performance targets, every public interface, or all persistent record
schemas. It also leaves the proposed health-audit rename unresolved. No
additional research or design decisions are supplied here.

This draft has no individually assigned design owner. A later full design
would need an owner and implementation review. Changes to the recorded contract
boundaries, environment locations, operation routing, or cleanup semantics are
reasons to revisit it; the existing contracts remain authoritative.

## Draft coverage metadata

This metadata makes the draft's coverage and gaps checkable. A documented topic
means the thread's decision is recorded, not that the whole system was audited.

```design-document
{
  "contract_version": 1,
  "document": "docs/design-draft.md",
  "owners": ["Unassigned in the thread; confirm for a full design"],
  "source_of_truth": [
    {"path": "README.md", "role": "Repository usage documentation"},
    {"path": "sdlc/sdlc.yml", "role": "This repository's operation declarations"},
    {"path": "skills/ceratops-repo-lifecycle/references/contracts/repository-validation-contract.json", "role": "Reusable validation behavior"},
    {"path": "skills/ceratops-repo-lifecycle/references/contracts/ceratops-compatibility-deterministic-contract.json", "role": "Mechanically checked compatibility requirements"},
    {"path": "skills/ceratops-repo-lifecycle/references/contracts/ceratops-compatibility-nondeterministic-contract.json", "role": "Internal compatibility review"},
    {"path": "skills/skill-sections.json", "role": "Live shared section and payload assignments"}
  ],
  "update_triggers": [
    "A recorded ownership, contract, environment, routing, or cleanup decision changes",
    "A full design is explicitly commissioned beyond the thread-only draft"
  ],
  "coverage": {
    "purpose": {"heading": "Scope and status", "status": "documented"},
    "constraints": {"heading": "Ownership and contracts", "status": "documented"},
    "context": {"heading": "Scope and status", "status": "unverified", "reason": "The thread identifies participants but not a complete system context."},
    "strategy": {"heading": "Ownership and contracts", "status": "documented"},
    "building_blocks": {"heading": "Compatibility setup and Python environments", "status": "unverified", "reason": "Only the components discussed in the thread are recorded."},
    "runtime": {"heading": "Operations, tests, and CI", "status": "unverified", "reason": "Recorded flows have not been reviewed as a complete runtime design."},
    "deployment": {"heading": "Promotion, installation, and update recovery", "status": "unverified", "reason": "The thread does not define every deployment target or operational detail."},
    "data": {"heading": "Promotion, installation, and update recovery", "status": "unverified", "reason": "State ownership is discussed, but complete record schemas are outside this draft."},
    "interfaces": {"heading": "Operations, tests, and CI", "status": "unverified", "reason": "Examples and boundaries are recorded without a full interface inventory."},
    "protection": {"heading": "Promotion, installation, and update recovery", "status": "unverified", "reason": "Publication and cleanup safeguards do not constitute a complete security model."},
    "decisions": {"heading": "Compatibility setup and Python environments", "status": "documented"},
    "quality": {"heading": "Verification, limits, and unresolved points", "status": "unverified", "reason": "The thread has no complete measurable quality requirements."},
    "risks": {"heading": "Verification, limits, and unresolved points", "status": "unverified", "reason": "Only risks and unresolved questions raised in the thread are included."},
    "glossary": {"heading": "Operations, tests, and CI", "status": "documented"},
    "verification": {"heading": "Verification, limits, and unresolved points", "status": "unverified", "reason": "Historical test reports are retained; no new implementation audit was performed."},
    "governance": {"heading": "Verification, limits, and unresolved points", "status": "unverified", "reason": "A full design owner and maintenance process were not assigned in the thread."}
  }
}
```
