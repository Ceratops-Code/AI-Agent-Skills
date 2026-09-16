# Ceratops Credit Savings Analysis

This is the authoritative architecture and maintenance reference for the
`ceratops-credit-savings-analysis` skill. The operational instructions remain
in [SKILL.md](SKILL.md) and its action references. The versioned contract and
Python controller remain authoritative for executable behavior; this document
explains how those parts work together and must be updated when they change.

```design-document
{
  "contract_version": 1,
  "document": "skills/ceratops-credit-savings-analysis/README.md",
  "owners": [
    "Maintainers of ceratops-credit-savings-analysis"
  ],
  "source_of_truth": [
    {
      "path": "skills/ceratops-credit-savings-analysis/scripts/credit-analysis-contract.json",
      "role": "Versioned executable policy, model, limit, action, and schema registry"
    },
    {
      "path": "skills/ceratops-credit-savings-analysis/scripts/credit_analysis/luna_sol_analysis.py",
      "role": "Current single-thread planning, model-result validation, reconciliation, and final assembly"
    },
    {
      "path": "skills/ceratops-credit-savings-analysis/scripts/credit_analysis/orchestration_execution.py",
      "role": "Current attempt execution, correction, retry, omission, concurrency, and resume behavior"
    },
    {
      "path": "skills/ceratops-credit-savings-analysis/scripts/credit_analysis/multi_thread_analysis.py",
      "role": "Recent-thread selection, per-thread batch state, aggregation, and finalization behavior"
    },
    {
      "path": "skills/ceratops-credit-savings-analysis/SKILL.md",
      "role": "Public action routing, shared invariants, classification policy, and output contract"
    },
    {
      "path": "skills/ceratops-credit-savings-analysis/references/full-analysis.md",
      "role": "Full-analysis workflow and completion contract"
    }
  ],
  "update_triggers": [
    "A public action, command, request, state, result, or schema contract changes",
    "Source selection, completed-run handling, model routing, capacity, retry, recovery, or final assembly changes",
    "A model, concurrency limit, attempt limit, output limit, or coverage threshold changes",
    "Batch selection, aggregation, report presentation, deployment, or retention behavior changes",
    "A test establishes supported behavior that this document does not describe"
  ],
  "coverage": {
    "purpose": {"heading": "1 Purpose and goals", "status": "documented"},
    "constraints": {"heading": "2 Constraints and assumptions", "status": "documented"},
    "context": {"heading": "3 System context", "status": "documented"},
    "strategy": {"heading": "4 Solution strategy", "status": "documented"},
    "building_blocks": {"heading": "5 Building blocks", "status": "documented"},
    "runtime": {"heading": "6 Runtime behavior", "status": "documented"},
    "deployment": {"heading": "7 Deployment and operations", "status": "documented"},
    "data": {"heading": "8.1 Data and persistence", "status": "documented"},
    "interfaces": {"heading": "8.2 APIs and integrations", "status": "documented"},
    "protection": {"heading": "8.3 Security and resilience", "status": "documented"},
    "decisions": {"heading": "9 Decisions and alternatives", "status": "documented"},
    "quality": {"heading": "10 Quality scenarios", "status": "documented"},
    "risks": {"heading": "11 Risks and limitations", "status": "documented"},
    "glossary": {"heading": "12 Glossary and references", "status": "documented"},
    "verification": {"heading": "13 Testing and verification", "status": "documented"},
    "governance": {"heading": "14 Ownership and maintenance", "status": "documented"}
  }
}
```

## 1 Purpose and goals

The skill analyzes retained Codex session evidence to find avoidable **model
calls** and avoidable context or output volume. Shell commands and tool calls
are supporting evidence; they are not the unit being counted. The skill can
analyze one thread, one named waste surface, or every thread selected by a
recent-thread or recent-days batch.

Its readers are operators running an analysis and maintainers changing the
controller. Operators need to know which sources are eligible, what gets
reviewed, and how to resume a run. Maintainers need to know which component owns
selection, capacity, model judgment, validation, transport, persistence, and
reporting.

The primary goals, in order, are:

1. Account for every model call in every selected completed run.
2. Preserve every confirmed finding and every known coverage omission.
3. Use model calls for semantic judgment while keeping selection, routing,
   copying, validation, accounting, retry, and persistence deterministic.
4. Prevent analysis from mutating the producer or workflow being analyzed.
5. Bound the analysis itself by proven context capacity and fixed attempt caps.
6. Resume safely after interruption without recollecting evidence or repeating
   accepted model work.

The skill does not apply recommendations, edit analyzed repositories, infer
savings from repeated commands alone, or classify a still-running turn as a
completed run. Its default chat presentation is limited to five
recommendations unless the user requests another limit; the complete machine
result keeps all confirmed findings.

## 2 Constraints and assumptions

The following constraints are enforced by the skill and controller:

- Analysis requests set `mutation_authority` to `false`.
- A single-thread run uses an exact source identity. A batch freezes an exact
  UTC `as_of` boundary and the selected thread list before analysis.
- Unfinished and archived threads are eligible. Completed runs inside them are
  analyzed; a currently running run is reported as unassessed.
- A completed run is the semantic unit. Oversized runs may be divided into the
  minimum ordered transport parts, then recombined as one run report.
- Luna discovery uses `gpt-5.6-luna`; Sol review and synthesis use
  `gpt-5.6-sol`. Both use maximum reasoning effort.
- The controller allows at most 70 Luna attempts with at most 15 concurrent
  Luna tasks. It plans at most 8 Sol calls and allows at most 16 Sol
  invocations, including corrective attempts.
- Invalid model output is rejected as a whole. The controller never truncates
  a valid result to make it fit.
- All mutable state and retained evidence live below a caller-selected task
  temporary root. Requests bind the expected contract versions.
- The host must provide a working Codex executable, the declared models, Python,
  access to the local Codex thread index and session files, and the source
  working directories recorded by those sessions.

Capacity estimates assume the byte-to-token and reserve values in
[credit-analysis-contract.json](scripts/credit-analysis-contract.json). The
controller validates the current model catalog before planning. Those values
are conservative planning inputs, not a promise that a model provider will
never change its limits. Before admitting final deep-review evidence, the
controller subtracts the exact response-schema and prompt-framing bytes from
the proven input envelope.

## 3 System context

The analysis controller is a local, file-backed process. It reads session and
instruction evidence, launches read-only Codex child processes, validates their
structured results, and writes retained evidence and reports.

```text
User / calling Codex thread
        |
        | request, execution, resume, final presentation
        v
Credit-analysis controller ----------------------+
        |                                         |
        | read                                    | launch with no-tools prompt,
        v                                         | read-only sandbox, explicit model
Codex thread index and session files              v
                                                  Luna and Sol Codex children
        ^                                         |
        | read effective rules and source cwd     | structured result/events/usage
        |                                         v
Source checkout and AGENTS chain          Task temporary artifact store
```

The local filesystem boundary contains potentially sensitive conversation,
tool, and instruction content. Model children receive only controller-prepared
evidence. They have no tools, no approval path, and a read-only sandbox. The
controller itself may read the selected sessions, their descendant sessions,
their source directories, and applicable instruction files; it has no
authority to edit the analyzed producer.

## 4 Solution strategy

The controller separates high-recall discovery from higher-precision review:

1. Deterministic code selects threads and completed runs, collects evidence
   once, freezes identities and hashes, and plans capacity.
2. Luna reviews each admitted semantic run across all five waste surfaces and
   returns candidates plus exact evidence references.
3. Sol reviewers adjudicate disjoint, frozen groups of Luna output. An optional
   focused recovery or direct-evidence review may run when deterministic signals
   and the call budget permit it.
4. A dependent final Sol call merges judgments, ranks and expands the strongest
   findings, and supplies synthesis text.
5. Deterministic code copies the complete accepted finding, risk, temporary
   control, classification, and evidence records into the final result. The
   final model is not responsible for reproducing those records.

This split matters because a language model can judge meaning but is an
unreliable bulk transport mechanism. Earlier assembly expected the final model
to repeat already accepted records; omissions then looked like new analytical
failures and prompted more diagnostic calls. The current design keeps the
judgment with the models and makes record transport controller-owned.

The fixed review surfaces are helper contracts, context and evidence reuse,
rework and validation, tool and handoff flow, and instruction and reasoning
flow. One Luna pass considers them together so a finding that crosses surfaces
is not split into unrelated partial findings.

## 5 Building blocks

### 5.1 C4 system and container view

The skill has one executable system, the local credit-analysis controller. Its
containers are Python modules and task-owned files rather than separately
deployed services.

| Container | Responsibility | Implementation |
| --- | --- | --- |
| Public instruction layer | Selects the public action, defines policy, completion, and presentation | [SKILL.md](SKILL.md), [full-analysis.md](references/full-analysis.md), and the other action references |
| Stable executable entry point | Keeps one script path while forwarding to modular implementation | [credit-analysis-workflow.py](scripts/credit-analysis-workflow.py) |
| CLI dispatcher | Parses `run`, `plan`, `execute`, compatibility, and batch commands | [command_line_interface.py](scripts/credit_analysis/command_line_interface.py) |
| Contract loader and evidence core | Validates the contract and requests, collects single-thread evidence, and retains the sequential compatibility controller | [single_thread_analysis.py](scripts/credit_analysis/single_thread_analysis.py) |
| Session collector | Resolves active or archived sessions, descendant lineage, completed runs, model calls, token usage, and evidence references | [session_evidence_collector.py](scripts/credit_analysis/session_evidence_collector.py) |
| Source execution context | Resolves run working directories, recovers identity-matched deleted worktrees, and freezes effective `AGENTS.md` chains | [source_execution_context.py](scripts/credit_analysis/source_execution_context.py) |
| Capacity planner | Partitions oversized runs, admits Luna tasks, sizes Sol reviewer bins, and enforces attempt capacity | [model_capacity_planning.py](scripts/credit_analysis/model_capacity_planning.py) |
| Model input preparation | Builds bounded evidence packets and compact final-review transport | [model_input_preparation.py](scripts/credit_analysis/model_input_preparation.py) |
| Holistic planner and assembler | Builds the current manifest and state, validates Luna/Sol domain results, freezes routing, reconciles judgments, and assembles the final machine result | [luna_sol_analysis.py](scripts/credit_analysis/luna_sol_analysis.py) |
| Attempt executor | Runs ready tasks concurrently, records attempts, applies narrow response corrections, retries diagnosed failures, records omissions, and checkpoints state | [orchestration_execution.py](scripts/credit_analysis/orchestration_execution.py) |
| Response contract | Builds closed model-output schemas and limits corrective responses to the rejected fields | [model_response_contract.py](scripts/credit_analysis/model_response_contract.py) |
| Final record transport | Copies and validates accepted source records so final synthesis cannot silently drop them | [report_bookkeeping.py](scripts/credit_analysis/report_bookkeeping.py) |
| Report renderer | Produces the compact human runs table while leaving full detail in machine evidence | [report_rendering.py](scripts/credit_analysis/report_rendering.py) |
| Batch controller | Freezes recent-thread selection, prepares one holistic child per thread, indexes accepted child results, and aggregates them | [multi_thread_analysis.py](scripts/credit_analysis/multi_thread_analysis.py) |
| Artifact store | Persists request, evidence, manifest, state, attempt, routing, result, report, and batch files | Caller-selected task temporary root |

### 5.2 Authority boundaries

The JSON contract owns executable identifiers, fixed limits, models, surface
order, classifications, and public actions. Python owns field shape,
cross-field rules, state transitions, persistence, and failure behavior. The
skill text owns operator-facing policy and presentation. Tests establish which
behaviors have been exercised. This README is the authoritative explanation of
that design; it does not override the executable sources.

## 6 Runtime behavior

### 6.1 Fresh single-thread full analysis

`run --request REQUEST` is the normal single-thread entry point.

```text
validate request and contract
        -> resolve source and descendants
        -> collect completed-run evidence once
        -> freeze evidence, rule chains, manifest, capacity, and state
        -> run admitted Luna tasks concurrently
        -> validate each result; correct once or record an omission
        -> freeze Sol routing and exact byte allowances
        -> run Sol reviewers in parallel
        -> optionally run focused recovery or direct-evidence review
        -> run dependent final Sol synthesis
        -> copy accepted source records and reconcile call accounting
        -> write machine result and compact report
        -> mark state complete
```

Planning assigns immutable task IDs, prompt and input hashes, execution working
directories, applicable rule-chain hashes, response schemas, and byte limits.
Luna starts from the verified working directory for the run it reviews. Sol
starts from the source thread's primary working directory and receives the text
of any run-local rules that differ from the primary rule chain.

Every retained model candidate receives one disposition. Every selected model
call receives a reviewed classification or remains explicitly unassessed. A
context-volume finding may be retained even when it saves no calls and is not
included in call-savings arithmetic.

### 6.2 Correction, retry, and omission

The response schema is closed. When a model response fails validation, the
controller derives a correction schema that permits changes only at the
rejected paths and verifies that every other value remains unchanged. A valid
retained corrected result can complete the task without a new model call.

Each Luna task gets at most one smaller-output retry for a diagnosed output
size or schema failure. Each rejected Sol task gets one corrective retry while
the global Sol attempt cap permits it. If validation still fails, the
controller records the exact task, call inventory, byte inventory, and reason
as omitted or unassessed and continues when the workflow can still produce an
honest final result.

Sibling attempts that finished before one concurrent failure are checkpointed
before that failure is surfaced. Timeouts and interruption terminate the child
process tree rather than leaving an untracked model process running.

### 6.3 Resume and idempotency

Running the same request again finds its existing state and enters `execute`
instead of planning again. Before reuse, the controller revalidates request and
contract hashes, evidence, rule chains, prompt identity, task input, schema,
and complete attempt artifacts. Accepted tasks are not launched again.
Incomplete or conflicting artifacts block the resume because their identity
cannot be proved.

State writes are checkpointed atomically. Result files are write-once in
meaning: an existing file is accepted only when its content matches the
expected identity and hash. `plan` stops after planning, `execute --state`
continues a frozen plan, and `orchestration-status --state` reads public status
without launching models.

### 6.4 Recent-thread batch

`prepare-batch --request REQUEST` reads the Codex thread index at one frozen
`as_of` timestamp. A `recent_days` selector includes entries whose index
`updated_at` falls within the interval; a `recent_threads` selector takes the
latest positive count. An optional project selector matches one exact name,
absolute path, or repository URL.

Selection does not require the thread to be finished. The collector resolves
both active and archived session locations. For each selected thread, the
batch prepares one ordinary holistic child request covering all completed runs.
Threads are processed through their frozen child states and accepted final
results are appended once to the batch index. The pending child's
`orchestration_final_schema` identity and thread ID must match before the batch
advances.

After every child completes, the controller opens one batch-summary phase over
the accepted findings. The summary may group findings only when the shared
owner and recommended control preserve each member's evidence. Finalization
keeps each thread's accounting and produces a batch machine result with the
cross-thread presentation groups. A batch is complete only after every
selected child and the batch summary are accepted and indexed exactly once.

### 6.5 Sequential compatibility path

The CLI still supports `prepare`, `advance`, `status`, and `finalize`, plus the
older `start` and `submit` aliases. That path runs fixed surface passes followed
by synthesis and emits the `synthesis_result_schema` and
`final_result_schema` artifacts described below. The current default
`run`/`plan`/`execute` full analysis uses the holistic v5 orchestration schemas.
The compatibility commands remain for existing callers; new full analyses use
the holistic controller.

## 7 Deployment and operations

The skill is source-controlled as one directory. The repository deployment
script copies the entire directory, so this README is automatically included
when the skill is deployed to
`$CODEX_HOME/skills/ceratops-credit-savings-analysis`. No separate runtime
payload declaration is needed for skill-local files.

Deployment changes the installed skill only when the repository lifecycle
workflow is explicitly asked to promote and deploy. Running from a development
worktree can use that worktree's `scripts/credit-analysis-workflow.py` directly
without deploying it.

The controller is a local Python program and launches the local `codex`
executable as child processes. Its primary configuration is the versioned
contract plus the request JSON. `CODEX_HOME` locates local Codex state;
`CODEX_THREAD_ID` is required only for the `current-thread` selector. Progress
comes from controller stdout and retained state, event, attempt, and usage
files. Successful payload-free commands print `OK`; status and run commands
print compact JSON.

Retained analysis artifacts are operational evidence and remain below the task
root. The controller removes only its declared transient files at their
cleanup trigger. The caller owns eventual removal of the retained task root.

## 8 Cross-cutting design

### 8.1 Data and persistence

The workflow uses JSON, JSONL, Markdown, and child event files. There is no
database and no hidden in-memory source of truth after a checkpoint.

The main artifact groups are:

- **Input:** request, optional pricing profile, exact source and selection
  boundary.
- **Frozen evidence:** normalized session evidence, semantic completed runs,
  call and token inventories, canonical source snapshots, descendant lineage,
  execution working directories, and effective rule-chain hashes.
- **Plan:** orchestration state, chunk manifest, Luna tasks, Sol routing,
  response schemas, byte allowances, and task order.
- **Attempts:** prompt, input, native session identity, events, raw response,
  validated response, latency, and usage for every launched child.
- **Results:** accepted Luna and Sol outputs, omission inventory, final machine
  result, compact human report, and batch index or batch final result.

Immutable artifacts are bound by path and SHA-256 or content hashes. Atomic
state replacement makes the latest checkpoint the resume point. Schema tags
make incompatible artifacts fail explicitly; there is no automatic migration
between schema versions. Retaining an old task root therefore also requires
retaining the compatible skill version if that analysis must be resumed.

#### Schema and version registry

Every `*_schema` value in the contract is a **type and version discriminator**
stored in an artifact's `schema` field. It is not a JSON Schema filename, URL,
or executable definition. Python builds or checks the actual closed field
shape and validates that the discriminator exactly matches the contract.

| Contract key | Artifact and active consumer |
| --- | --- |
| `schema` | Identifies the contract document itself as `ceratops-credit-analysis-contract.v1`. |
| `request_schema` | Single-thread request accepted by the evidence and holistic controllers. |
| `batch_request_schema` | Recent-thread batch request accepted by `prepare-batch`. |
| `batch_manifest_schema` | Frozen batch selection and child inventory. |
| `evidence_schema` | Retained normalized analysis evidence. |
| `canonical_state_schema` | Read-only canonical implementation snapshot used by the sequential compatibility controller. |
| `surface_result_schema` | One named-surface result in the sequential compatibility path. |
| `synthesis_result_schema` | Internal synthesis artifact in the sequential `prepare`/`advance`/`finalize` path. `ceratops-credit-analysis-synthesis-result.v1` means “this object conforms to synthesis-result version 1”; the string does not define its fields. |
| `final_result_schema` | Final standalone or full result in the sequential compatibility path. `ceratops-credit-analysis-final-result.v1` is its exact version tag. |
| `orchestration_state_schema` | Resumable state for the current holistic controller. |
| `chunk_manifest_schema` | Frozen semantic-run parts, task identities, assignments, and capacity plan for the current controller. |
| `luna_result_schema` | Validated high-recall discovery result for one admitted semantic run or ordered run part. |
| `adjudication_result_schema` | Validated Sol reviewer or final synthesis result. |
| `orchestration_final_schema` | Current holistic single-thread final machine result accepted by batch aggregation. |
| `routing_manifest_schema` | Frozen assignment of accepted Luna output and candidates to Sol tasks. |

The numeric `surface_contract_version` and
`source_selection_contract_version` version policy and selection semantics that
must match before planning. They are separate from artifact schema versions so
a policy-only incompatibility can invalidate a request without renaming every
artifact type.

### 8.2 APIs and integrations

The public executable interface is:

```text
python scripts/credit-analysis-workflow.py run --request REQUEST
python scripts/credit-analysis-workflow.py plan --request REQUEST
python scripts/credit-analysis-workflow.py execute --state STATE
python scripts/credit-analysis-workflow.py orchestration-status --state STATE
python scripts/credit-analysis-workflow.py prepare-batch --request REQUEST
python scripts/credit-analysis-workflow.py status-batch --state STATE
python scripts/credit-analysis-workflow.py advance-batch --state STATE --result RESULT
python scripts/credit-analysis-workflow.py finalize-batch --state STATE
```

The compatibility interface adds `start`, `submit`, `prepare`, `advance`,
`status`, and `finalize`. The exact command set and accepted artifact versions
are registered in the contract; the CLI parser is the executable command
authority.

Requests and results are local files. There is no remote service API or
authentication exchange. Child Codex processes use the host's existing Codex
authentication and model availability. Each launch has an explicit model,
maximum reasoning effort, read-only sandbox, no approvals, self-contained
no-tools prompt, response schema, timeout handling, and controller-owned event
and result paths.

### 8.3 Security and resilience

The controller enforces task-root path containment, rejects unsafe or
conflicting artifacts, validates regular files and symlinks, freezes contract
and instruction hashes, and sets mutation authority to false. Child prompts
cannot call tools and child processes run read-only. Missing source worktrees
can map to a primary checkout only when canonical topology and the retained and
live Git repository URLs prove the same repository identity.

Session evidence can contain private conversation, source snippets, command
text, tool output, local paths, and instruction files. The task root must be
treated as sensitive local data. The controller uses path-reduced semantic
evidence for model transport where supported, but retained machine evidence is
not a general-purpose redaction product.

Reliability comes from immutable identities, closed schemas, atomic
checkpoints, write-or-verify publication, bounded retries, explicit omissions,
and process-tree termination. There is no independent backup service. The
retained task root is the recovery record; if it is deleted, the analysis must
be planned again. Provider or host outages remain external dependencies and are
reported rather than hidden by unlimited retries.

## 9 Decisions and alternatives

| Decision | Status and reason | Alternative rejected |
| --- | --- | --- |
| Count model calls as the savings unit | Accepted. Credits are consumed by model calls; commands are evidence about why a call happened. | Counting repeated commands as waste, which confuses tool activity with credit consumption. |
| Admit unfinished and archived threads | Accepted. Thread lifecycle is independent of whether it contains completed runs that can be reviewed. | Requiring task completion, which silently discards eligible evidence. |
| Keep completed runs as semantic units | Accepted. User intent, corrections, results, and validation form one causal episode. | Reviewing independent calls or commands, which loses the reason a call was necessary. |
| Use Luna discovery followed by Sol review | Accepted. It combines broad candidate recall with stronger adjudication under explicit limits. | One large synthesis call, which is harder to fit, validate, and recover. |
| Analyze all surfaces together | Accepted. Cross-surface causes and fixes remain connected. | One model pass per surface, which multiplies calls and creates duplicate findings. |
| Make the controller own accepted-record transport | Accepted. Models judge and summarize; code preserves exact accepted findings, classifications, evidence, and references. | Asking the final model to copy every accepted record, which can omit valid results and cause avoidable diagnostic reruns. |
| Reject rather than truncate oversized output | Accepted. Coverage loss stays explicit and evidence remains intact. | Silent truncation, which can corrupt identities and accounting. |
| Persist file-backed state after each boundary | Accepted. It supports inspection and idempotent resume without a service. | Memory-only orchestration or a database service, which adds operational complexity. |
| Preserve the sequential command interface | Accepted for existing callers while new full analyses use holistic orchestration. | Immediate removal, which would break retained callers and task roots. |
| Keep analysis read-only | Accepted. Findings must not change the evidence or producer they assess. | Automatic remediation, which would mix diagnosis, authorization, and mutation. |

## 10 Quality scenarios

These are required behavior targets; passing tests or retained run evidence is
needed to claim a measured result.

| Scenario | Stimulus and condition | Expected response and threshold | Verification |
| --- | --- | --- | --- |
| Deterministic recent-days selection | The same index, request, and UTC `as_of` are prepared twice | The frozen selected thread IDs and order are identical; active and archived session locations are eligible | Batch selector behavior tests and manifest comparison |
| Unfinished-thread coverage | A selected active thread contains completed runs and one running run | All completed runs enter evidence; the running run is reported unassessed | Session collector and batch tests |
| Bounded discovery | Prepared evidence exceeds one Luna input but fits the global budget | The minimum ordered parts are admitted, no more than 15 run concurrently, and attempts never exceed 70 | Capacity and orchestration tests plus state totals |
| Invalid Luna output | A Luna result violates schema or its byte allowance | The exact task is retried at most once with a smaller allowance, then omitted with identity, bytes, and reason | Response and retry tests |
| Invalid Sol output | A Sol result violates its frozen schema | Only rejected fields may change, at most one corrective retry is used per task, and total Sol invocations never exceed 16 | Correction-scope and attempt-budget tests |
| Interrupted run | The controller stops after some sibling tasks complete | Completed siblings are checkpointed; resume reuses accepted outputs and launches only proven pending work | Resume and sibling-failure tests |
| No silent copying loss | Final Sol returns synthesis judgments after reviewers accepted findings | Controller assembly contains every accepted source record exactly once or fails validation | Report bookkeeping and finalization tests |
| Honest capacity shortfall | A run part or reviewer cannot fit or validate within limits | Final coverage is incomplete and the exact omitted calls, records, and bytes are retained; no zero is substituted for unreviewed work | Omission and final-accounting tests |
| Read-only analysis | Any full or batch analysis runs | No analyzed producer file is changed and every child uses a read-only sandbox with no tools | Command construction tests and source-worktree status |
| Idempotent batch advance | An accepted child result is submitted again unchanged | Status is returned without a duplicate index entry; a changed resubmission is rejected | Batch resume tests |

## 11 Risks and limitations

- **Model judgment remains probabilistic.** Closed schemas prove shape and
  identity, not the truth of a semantic conclusion. Cross-model review,
  evidence references, and direct verification reduce this risk.
- **Capacity can force omissions.** The controller records them, but a report
  with omissions is not semantically complete. Larger source histories may
  require a narrower selection or later continuation.
- **Local session availability is required.** Missing or malformed thread-index
  records, session files, source directories, or instruction chains can exclude
  or block analysis. Identity-matched worktree recovery covers only canonical
  deleted-worktree cases.
- **The model catalog and real provider envelopes can change.** Planning checks
  the live catalog and uses reserves, but external limit changes can still
  cause a bounded failure.
- **Compatibility code increases maintenance cost.** The sequential and
  holistic controllers use different result families. Changes must state which
  path they affect and keep the public command contract coherent.
- **Retained evidence is sensitive and can be large.** There is no automatic
  archival, encryption, or expiry policy beyond local filesystem controls and
  caller-owned cleanup.
- **Pricing is optional.** Call and token accounting remains available without
  a pricing profile, but monetary savings cannot be complete.
- **Compact human reports omit detail by design.** The machine result and
  retained evidence are required for full findings, classifications, coverage,
  and provenance.
- **A batch is per-thread before aggregation.** Cross-thread grouping improves
  presentation but does not retroactively change each thread's model-call
  classifications or totals.

## 12 Glossary and references

- **Model call:** One non-empty assistant response recorded in selected session
  evidence and assigned a stable call ID.
- **Completed run:** A finished user turn and its resulting model and tool
  activity, treated as one semantic episode.
- **Unfinished thread:** A task that may still be active but can contain earlier
  completed runs eligible for review.
- **Surface:** One of the five fixed perspectives used to search for credit
  waste.
- **Luna task:** A high-recall discovery review of one complete semantic run or
  one ordered part of an oversized run.
- **Sol reviewer:** A higher-precision adjudication task over a frozen subset of
  accepted Luna output.
- **Final Sol:** The dependent synthesis task that merges judgments and expands
  the strongest findings; it does not own bulk copying of accepted records.
- **Temporary control:** A run-local or provisional mechanism whose durability
  must be assessed separately from the finding it accompanies.
- **Omission:** Evidence or a task that could not be admitted or accepted within
  the frozen capacity, schema, or retry contract.
- **Schema tag:** An exact artifact type/version string checked against the
  contract; the field shape is enforced by Python.
- **Task root:** The caller-selected temporary directory containing one
  resumable analysis and its retained evidence.

Operational references:

- [Skill instructions](SKILL.md)
- [Full-analysis action](references/full-analysis.md)
- [Executable contract](scripts/credit-analysis-contract.json)
- [Stable controller entry point](scripts/credit-analysis-workflow.py)
- [Credit-analysis tests](../../tests/credit_analysis/)

## 13 Testing and verification

Behavior tests under [tests/credit_analysis](../../tests/credit_analysis/)
cover source selection, evidence collection, schema validation, capacity
planning, Luna and Sol routing, output correction, retries, resume, batch
aggregation, report preservation, and failure accounting. Changes should run
the narrowest existing test nodes that cover each modified behavior before any
broader suite.

The design-document validator checks this file's metadata, mapped sections,
local links, declared source paths, fenced blocks, and diagram syntax when
applicable. It does not prove semantic agreement with the controller. A design
review must compare changed runtime behavior with this document, the contract,
the applicable action reference, and the behavior tests.

Operational verification for an actual analysis comes from retained state:
controller status must report completion; every admitted Luna and Sol task must
have a terminal disposition; every call must be classified or explicitly
unassessed; and the machine result must retain the omission and accounting
inventories. A clean report alone is insufficient completion evidence.

## 14 Ownership and maintenance

The maintainers of `ceratops-credit-savings-analysis` own this document. Its
authoritative path is
`skills/ceratops-credit-savings-analysis/README.md`. The root repository README
contains only a relative discoverability link; installed copies are deployment
artifacts rather than the editing source.

When an update trigger in the metadata fires, review the change in this order:

1. Update executable policy in the contract or behavior in the owning Python
   module.
2. Update the operational skill or action reference when user-facing behavior
   changed.
3. Update this README's affected architecture, flow, schema, quality, risk, and
   verification sections.
4. Update the narrowest existing behavior tests.
5. Validate the document and its local links, then deploy through the normal
   skill and repository lifecycle only when deployment is requested.

If the README conflicts with executable behavior, treat that as documentation
drift: verify the code and contract, then update the README in the same change.
Do not patch an installed copy directly.
