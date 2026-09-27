# Ceratops repository lifecycle design draft

## Scope and status

This unfinished draft records repository validation, Python environments,
SDLC, and deployment decisions. The release-unit, receipt, bundle-transaction,
and update-correction sections additionally describe their scoped implementation
and behavior tests. Other sections remain discussion-derived, not a complete
implementation audit or a new governing contract. The README owns general
methodology and output-lifetime policy; this draft records implementation detail.

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
`run-actionlint.py.tmpl`, `run-tests.py.tmpl`, `deploy-skills.py.tmpl`,
`sdlc.yml.tmpl`, and `skill-sections.json.tmpl`. Compatible repositories receive
the pinned actionlint runner, while repositories with Python tests receive the
required test runner. Python test detection is deterministic where possible;
test bodies and their implementation remain repository-specific.

| Environment | Declarations | Execution and ownership |
| --- | --- | --- |
| Repository Python scripts and tests | `scripts/pyproject.toml` and `scripts/uv.lock` | uv selects the required Python and prepares ignored `scripts/.venv`; repository entrypoints use this project. |
| Installed Ceratops skill helpers | Source-only declarations under `skills/sections/python` | Deployment prepares a versioned venv under `$CODEX_HOME/runtimes/ceratops/versions/`; each installed skill manifest pins its interpreter. After manifest activation, the owner retains the selected version plus two predecessors, deferring cleanup for manifest-pinned or running interpreters. Direct uv commands run helpers. |
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

Supported SDLC v4 and v5 place tests in explicit actions. A deliverable may declare
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

The shared SDLC loader also owns the opt-in v5 release-unit reader. Units group
artifact-producing deliverables for a shared release; package prerequisites
remain separate dependencies whose release-unit owners are resolved without
merging membership. The schema and semantic validator reject ambiguous owners,
unresolved dependencies, cycles, unsafe paths, and missing build declarations.
The reader returns metadata only. Automatic unit builds and receipt-based
publication or deployment are later lifecycle integrations; the compatibility
producer and the live repository configuration remain v4.

`sdlc_results.py` owns explicit build-receipt verification alongside bounded
operation-result capture. The existing operation-result schema adds a v2 build
record with the complete release selection, exact output and dependency files,
supporting files, and artifact-bound test evidence. Callers supply the expected
selection independently; the verifier checks records, reference consistency,
path boundaries, byte sizes, and SHA-256 values without building, installing,
or changing test statuses. Verification is a point-in-time integrity check, not
proof of test success, provenance, immutability, or permission to deploy.
Capture remains free of artifact reads, and installer integration is deferred.

The final direction removes generated repository `sdlc.py`, a local copy of the
operation engine, and `scripts/runtime`. Those proposed extra layers were
rejected. Installed skill bindings remain in the skills; target repositories
receive configuration and their own entrypoints.

CI runs declared executable checks and tests and reports skill handoffs as
deferred. It does not dispatch skills. A skill-driven workflow can execute
those handoffs. AI-Agent-Skills uses its local composite action; other
repositories can use a pinned published action.

This repository currently declares SDLC v4 and a repository-wide test action;
the shared loader no longer supports v1–3. Its runner supports individual
test paths or node IDs and optional automatic selection: all tests locally and
on pushes, with impact selection from the exact pull-request base/head in CI.
That impact-selection implementation is repository-specific, not a requirement
imposed on every compatible repository.

## Portable result records

[`docs/result_records.py.tmpl`](result_records.py.tmpl) is the reference
implementation for repository-owned validation, test, and build records. It is
a documentation asset, not an installed runtime payload or an automatically
copied compatibility file. A repository adopts it by copying and adapting it
as `scripts/result_records.py` when that repository owns persistent result
records.

The template keeps current validation and test JSON under tracked
`.test-results/`, raw screenshots and logs under ignored
`.test-results/evidence/`, tracked build metadata and approvals under
`.build/builds/`, and package bytes under ignored `.build/artifacts/`. Records
bind to source bytes, the latest commit that changed non-result files, execution
context, and exact artifact bytes. An immutable source tag is the build version;
its resolved commit is traceability metadata. Evidence retention is bounded to
the current run and at most two predecessors.

Repository validators and test runners remain the behavior owners. Targeted
reruns replace affected results, preserve only still-applicable passing results,
and recalculate the aggregate outcome. Delivery verifies applicable validation
and test outcomes plus exact artifact identity without rerunning tests. Existing
repositories that contain `result_records.py` should be reviewed individually
against this reference and migrated where behavior differs, while preserving
repository-specific schemas, groups, environments, and behavior tests; the
template must not be copied blindly over a working implementation.
`tests/repository_lifecycle/test_compatibility.py` exercises the template's
source and artifact binding, bounded evidence, compact failure output, and
result-only commit stability.

## Exact-artifact bundle transaction

Steps 1a and 1b provide metadata and verification; 1c makes skill-update
corrections resumable; 1d supplies internal artifact storage.
`repository_operation.build_bundle` coordinates adapters, tests and publication.
`sdlc_results.verify_release_unit_build` remains the read-only integrity owner;
it neither stores bundles nor decides whether required tests passed.

The caller provides all six selection fields (repository, commit, unit, channel,
version, target), resolved locked inputs, required test IDs and two adapter
callbacks. Selection is validated before output creation. Its canonical JSON
SHA-256 is the build key. Git's absolute common directory identifies the shared
store, so different worktrees use the same key and location. No separate index,
caller-selected diagnostic path or wildcard selection is involved.

The transaction uses the following sequence:

1. Acquire one native repository-store lock using pinned `filelock`, with a
   bounded wait and no soft-lock fallback. Keep that single lock file to avoid
   waiter races. While holding it, remove every recognizable abandoned staging
   directory and interrupted diagnostic write left by earlier instances, then
   apply completed-bundle retention.
2. If the final directory exists, verify its receipt and every file, require
   the exact required passed test set, and compare canonical recorded inputs.
   Reuse the exact receipt path; corruption or changed inputs never cause a
   replacement build under that identity.
3. Otherwise create `.staging/<key>/bundle` and a separate `work` directory.
   The build adapter gets both locations and returns explicit output descriptors,
   not supplied hashes. The transaction measures artifacts and dependency files
   before testing. Scratch source copies and environments belong only in `work`.
4. Give the test adapter the measured artifact inventory and require every
   declared test result to pass, provide evidence and identify its tested hashes.
   Every built artifact must be referenced. Measure supporting evidence, add
   `supporting-files/build-inputs.json`, and create the v2 receipt. Verify all
   files again, including unchanged pre-test artifact hashes; refuse unlisted
   files before publishing.
5. Rename the complete bundle directory to `builds/<key>` on the same
   filesystem, apply retention again, return its exact `receipt.json` path and
   clean remaining private work. A retained directory is never overwritten.
   Later consumers must still verify saved bytes; this is not a signature or
   authenticity guarantee.

Callbacks must finish their child processes before returning. Their required
test implementation and resolved dependency/toolchain inputs belong in the
caller-supplied locked inputs. The store checks that these inputs agree on reuse;
it does not discover missing dependencies or infer test coverage from source.
Real package/skill adapters and installed-artifact tests arrive in later steps.
The existing SDLC commands and installers are unchanged.

The README's generated-output table is the retention policy. Completed bundles
are grouped by repository, release unit, channel and target. Transaction startup
and successful publication retain the newest three per group, ordered by
completion-directory modification time and then build key, and remove older
helper-owned directories. Failed work creates no completed receipt. Its error,
required tests and bounded evidence excerpts atomically replace the one
`.diagnostics/<group-key>.json` report; success removes that report. Read-only
scratch files are cleaned without changing linked or unrecognized targets.
Cleanup errors remain failures with diagnostics. On a killed process, the kernel
releases the repository lock; the next transaction cleans all recognizable
orphaned staging before reuse or building. This is call-triggered recovery, not
a background sweeper or a power-loss durability guarantee.

Existing `tests/repository_lifecycle/test_sdlc_handoffs.py` exercises exact reuse,
input conflicts, failed/missing tests, changed artifacts, corruption, concurrent
callers, worktree sharing, bounded retention, killed-owner recovery and cleanup
failure. The store keeps one reusable lock, at most three completed bundles per
release group and one current diagnostic per group. No public Build command is
introduced.

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

`skill-update-workflow.py` retains its original Git baseline and explicit
allowed file list throughout normal corrections. `amend` expands approved
scope before any check or after passed/failed verification without replacing
that baseline. Added paths are compared against the original commit or initial
dirty snapshot, not their state at amendment time. Passed evidence becomes
pending on amendment; changed inputs after each success start another numbered
verification generation with no arbitrary one-correction limit. Original
branch, descendant-commit, ownership and unrelated-change checks still apply.
Tests remain in the repository runner, not this helper. Finalization is the
explicit end-of-work cleanup trigger, never an intermediate correction step.

`supersede` remains a subcommand of `skill-update-workflow.py` for an explicitly
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
schemas. The bundle section supplies scoped concurrency and recovery details,
not a system-wide audit. The proposed health-audit rename remains unresolved.

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
    {"path": "docs/result_records.py.tmpl", "role": "Reference implementation for portable validation, test, and build records"},
    {"path": "skills/skill-sections.json", "role": "Live shared section and payload assignments"},
    {"path": "skills/ceratops-repo-lifecycle/scripts/repository_operation.py", "role": "Operation execution and internal build transaction"},
    {"path": "skills/ceratops-repo-lifecycle/scripts/sdlc_results.py", "role": "Read-only build receipt verification"},
    {"path": "skills/ceratops-skill-lifecycle/scripts/skill-update-workflow.py", "role": "Skill update baseline, corrections and finalization"}
  ],
  "update_triggers": [
    "A recorded ownership, contract, environment, routing, or cleanup decision changes",
    "The portable result-record contract or reference implementation changes",
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
    "verification": {"heading": "Verification, limits, and unresolved points", "status": "unverified", "reason": "Foundation and correction behavior has scoped tests; no complete implementation audit was performed."},
    "governance": {"heading": "Verification, limits, and unresolved points", "status": "unverified", "reason": "A full design owner and maintenance process were not assigned in the thread."}
  }
}
```
