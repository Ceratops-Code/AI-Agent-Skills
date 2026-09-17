"""Build immutable model prompts for holistic Luna and Sol tasks."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


def _holistic_prompt_prefix(
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    input_sha256: str,
    luna_candidate_ids: Sequence[str],
) -> str:
    lineage = json.dumps(
        {
            "controller_analysis_id": state["analysis_id"],
            "task_id": task["task_id"],
            "ephemeral_child": False,
            "execution_cwd": str(task["execution_cwd"]),
            "instruction_chain_sha256": str(task["instruction_chain_sha256"]),
            "source_cutoff_precedes_this_child": True,
        },
        separators=(",", ":"),
    )
    common = f"""Controller lineage: {lineage}
This is an analysis-only child. Do not use tools, read files, run commands, or
modify any repository, skill, prompt, helper, workflow, or instruction. Analyze
only the supplied packet and return one JSON object matching the output schema.
Apply the supplied analysis_policy exactly. Intentional full skill-body injection
is required runtime context, never credit waste. Never recommend a reasoning
setting, effort, or level. Use only frozen local and canonical-state evidence;
when broader or deep research would be required, preserve the uncertainty and
provide a concise paste-ready targeted official-source check instead of guessing.
Describe the concrete episode and the proposed before-and-after behavior. For
script findings, name the verified repository-relative filename and relevant
function, command, or setting in the problem and proposed control. Distinguish
maintained source, installed copies, deleted temporary scripts, and direct tool
invocations; if the owner or correction is unverified, state the missing check.
Do not substitute generic labels such as validation or caller sequence for the
actual actions. A rule's existence does not prove corrected behavior works;
preserve the required machine implementation classification. Verify one- or
two-line effort claims against the actual change.
The input identity is {input_sha256}.
"""
    if task["phase"] == "luna-discovery":
        instructions = f"""
Act as the high-recall discovery tier. The packet contains every selected call
assigned to it in causal order and exposes the supplied fixed lenses in order.
Inspect all calls. Emit only plausible findings and plausible risks, plus every
observed temporary control for mandatory Sol review even when it appears
intentional or harmless. Do not enumerate routine dismissals,
do not classify every action or call-surface pair, do not calculate savings, and
do not make final findings. Every emitted candidate must cite supplied candidate
IDs and packet-local original evidence references. Put candidate IDs only in
`candidate_ids`; put only `evidence://` or `analysis://` values in
`evidence_refs`. When citing an adjacent record, add its candidate ID to
`candidate_ids` and its original reference to `evidence_refs`. Keep shared producer/control episodes
together and keep analysis-overhead work separate from producer work. Stay
within the controller-supplied {int(task['output_byte_limit'])}-byte result
target; concise hypotheses are sufficient and genuine candidates must not be
silently dropped.
"""
        candidate_limit = task.get("candidate_limit")
        if candidate_limit is not None:
            # Preserve the exact old prompt for already frozen, unbounded tasks.
            instructions = instructions.replace(
                "Act as the high-recall discovery tier.",
                "Act as the prioritized discovery tier.",
            ).replace(
                "Inspect all calls. Emit only plausible findings and plausible risks, plus every\n"
                "observed temporary control for mandatory Sol review even when it appears\n"
                "intentional or harmless.",
                "Inspect all calls. Select the strongest plausible findings, risks, and\n"
                "observed temporary controls. Rank them by evidence strength,\n"
                "observed avoidable model calls, and likely credit savings. Retain\n"
                "one-off waste; exclude risks without a causal credit-use link.\n"
                "Consolidate repeated producer/control issues.",
            ).replace(
                "target; concise hypotheses are sufficient and genuine candidates must not be\n"
                "silently dropped.",
                f"target. Return no more than {candidate_limit} candidates. If more are\n"
                "plausible, keep the strongest and leave the rest unassessed. Do not claim\n"
                "exhaustive discovery.",
            )
    elif task["phase"] == "sol-direct-evidence":
        instructions = """
Act as an independent direct-evidence tier. Inspect only the supplied prepared
run part, without using Luna reports. Emit only material candidates Luna may have missed,
using the same candidate schema and exact evidence rules as Luna discovery.
Do not classify calls, calculate savings, or synthesize the final report.
"""
    elif (
        task["phase"] == "sol-adjudication"
        and task.get("review_kind") == "unassessed-recovery"
    ):
        instructions = f"""
Act as the focused unresolved-call reviewer. Review only the
{len(task['call_ids'])} target calls in `call_inventory`; the supplied Luna
reports and complete ordered run parts are context, not additional classification
targets. Adjudicate every supplied Luna candidate exactly once so findings remain
traceable, but do not reconsider calls already classified by the preliminary
reviewers. Replace each target call's preliminary `unassessed` classification
with the strongest evidence-supported classification. Preserve `unassessed` only
for a remaining decision-blocking gap. Return the ordinary adjudication fields
without an analysis summary or surface summaries. Link each candidate to its
findings or risks and give a reason; the controller derives its disposition.
"""
    elif task["phase"] == "sol-adjudication":
        instructions = f"""
Act as one independent Luna-report reviewer. Review every routed Luna candidate
exactly once ({len(luna_candidate_ids)} total) from its hypothesis and embedded
evidence references. Do not independently re-read the source evidence. Review
every supplied surface section in its fixed order,
merge overlapping findings once by owning producer/control, and preserve every
confirmed finding. Retain risks only when the missing fact could change credit
use; dismiss unrelated implementation-correctness questions. Give each
candidate its finding/risk links and a reason;
empty links dismiss it, and the controller derives its disposition. Perform the
mandatory temporary-control review for every
temporary-control candidate, using exactly one allowed disposition; transient
work is not automatically defective, and a permanent recommendation requires
likely recurrence plus positive maintenance-adjusted savings. Review a
temporary control recognized during adjudication even if Luna gave it another
candidate kind. Only `durable-control-missing` with the recurrence and savings
gate satisfied may link to a finding; every other disposition needs an explicit
no-finding reason.

Classify every source call exactly once in compact groups; group order and
contiguity are transport-only and the controller canonicalizes source order and
derives workstreams. Use only the packet-local call, Luna-candidate, and evidence
aliases exposed in the packet and output schema; do not reproduce canonical IDs.
Keep analysis-overhead findings separate from producer findings and savings.
Use `necessary` only for a specific active gate with a supplied reason code;
never use it as a catch-all. Use `reviewed_no_confirmed_waste` for inspected calls
without confirmed waste. `unassessed` is only for a decision-blocking evidence
gap and must stay within the supplied cap. Classify evidenced avoidable calls
even when a single occurrence or weak recurrence does not justify a durable
fix; a finding is optional for those calls. Let explicit avoidable call
classifications govern model-call finding membership and observed counts; an
unimplemented finding may include already-implemented calls when at least one
affected call remains unimplemented. Use Luna's supplied canonical-status
evidence before labeling a durable control missing. When it shows the safeguard
already exists, preserve `implementation_status` as `implemented` and describe
violating behavior as a compliance or runtime gap; do not propose a duplicate
control. Do not perform broad rediscovery that duplicates Luna. Return only the semantic
fields in the schema: do not restate identity, surface summaries, workstreams,
observed counts, recurrence arithmetic, or an analysis summary. Keep rationales
compact and do not repeat evidence text already addressed by an evidence alias.
Aim for about 1,500 visible output tokens while retaining every candidate
decision, confirmed finding, material variant, required review, and call
classification.
"""
    else:
        instructions = """
Act as the final review tier. Earlier accepted Sol results are authoritative:
do not repeat their candidate decisions, findings, risks, temporary-control
reviews, merges, or call classifications. The controller carries them forward,
including validated recovery results, evidence, cost, and ROI inputs. Review
only candidate IDs permitted by this output schema: separate direct-evidence
candidates and any candidate lacking an accepted earlier judgment. For each,
return finding/risk links, evidence references, and a reason; empty links dismiss
it, and the controller derives its disposition. Emit only new outcomes and
temporary-control records needed for those judgments, plus evidence-supported
call-classification changes. Deep-verify the supplied top three findings against
their raw evidence and emit a revised finding under its existing ID only when
the supplied evidence warrants a change. The controller retains its earlier
source calls and references. Preserve evidenced one-off avoidable calls without
requiring a recurring finding. Keep material variants distinct. Do not emit
helper-category reviews; the controller assembles accepted reviewer records.
Return concise semantic fields only. The controller builds report summaries,
deduplicates exact owner/control findings, and checks complete call accounting.
"""
    return common + instructions + "\nInput packet:\n"


def _holistic_prompt(
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    input_payload: Mapping[str, Any],
    input_sha256: str,
    luna_candidate_ids: Sequence[str],
) -> str:
    prefix = _holistic_prompt_prefix(
        state=state,
        task=task,
        input_sha256=input_sha256,
        luna_candidate_ids=luna_candidate_ids,
    )
    packet = json.dumps(input_payload, ensure_ascii=False, separators=(",", ":"))
    return prefix + packet + "\n"
