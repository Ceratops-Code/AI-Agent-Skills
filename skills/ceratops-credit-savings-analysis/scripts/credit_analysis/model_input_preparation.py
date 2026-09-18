"""Prepare bounded retained evidence for model input."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .execution_outcomes import structured_outcome
from .single_surface_analysis import CreditAnalysisError


def _review_record_index(evidence: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Index retained model-review records without changing their content."""

    model_review = evidence.get("model_review")
    if not isinstance(model_review, Mapping):
        raise CreditAnalysisError("model-review evidence is invalid")
    records = model_review.get("records")
    if not isinstance(records, list):
        raise CreditAnalysisError("model-review records are invalid")
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise CreditAnalysisError("model-review record is invalid")
        record_id = record.get("record_id")
        if not isinstance(record_id, str) or record_id in indexed:
            raise CreditAnalysisError("model-review record ID is invalid")
        indexed[record_id] = record
    return indexed


SURFACE_EVIDENCE_KEYWORDS = {
    "helper-contracts": (
        "helper",
        "script",
        "contract",
        "cleanup",
        "rollback",
        "dependency",
        "output",
    ),
    "context-evidence": (
        "read",
        "search",
        "context",
        "evidence",
        "token",
        "cached",
        "path",
    ),
    "rework-validation": (
        "failed",
        "error",
        "retry",
        "again",
        "temporary",
        "workaround",
        "patch",
        "revert",
        "correct",
    ),
    "tool-flow": (
        "tool",
        "command",
        "wait",
        "timeout",
        "terminated",
        "result",
        "exit",
    ),
    "instruction-reasoning": (
        "instruction",
        "rule",
        "prompt",
        "clarif",
        "approve",
        "plan",
        "skill",
    ),
}

FINAL_ADJUDICATION_FIELDS = {
    "candidate_decisions": (
        "luna_candidate_id",
        "disposition",
        "reason",
        "evidence_refs",
        "finding_ids",
        "risk_ids",
    ),
    "confirmed_findings": (
        "id",
        "title",
        "problem_summary",
        "waste_kind",
        "affected_call_ids",
        "evidence_refs",
        "producer_type",
        "producer_owner",
        "workstream",
        "proposed_durable_control",
        "implementation_status",
        "targeted_verification",
        "recurrence",
        "confidence",
        "complexity",
        "one_time_implementation_cost",
        "helper_categories",
    ),
    "plausible_risks": (
        "id",
        "description",
        "affected_call_ids",
        "evidence_refs",
        "workstream",
        "competing_explanations",
        "missing_fact",
        "verification_needed",
    ),
    "temporary_control_reviews": (
        "id",
        "source_luna_candidate_ids",
        "problem_solved",
        "affected_call_ids",
        "observed_temporary_control",
        "final_canonical_evidence_refs",
        "disposition",
        "owning_producer",
        "recurrence_inputs",
        "savings_inputs",
        "finding_id",
        "no_finding_reason",
    ),
    "temporary_control_merges": (
        "control_key",
        "owning_producer",
        "review_ids",
        "finding_id",
    ),
    "helper_category_reviews": (
        "category",
        "applies",
        "evidence_refs",
        "reason",
    ),
    "call_classifications": (
        "call_ids",
        "classification",
        "reason_code",
        "rationale",
        "evidence_refs",
        "workstream",
    ),
}


def _compact_final_adjudication_result(
    result: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Keep every semantic adjudication field without derived report prose."""

    compact: dict[str, list[dict[str, Any]]] = {}
    for key, fields in FINAL_ADJUDICATION_FIELDS.items():
        items = result.get(key)
        if not isinstance(items, list) or any(
            not isinstance(item, Mapping) for item in items
        ):
            raise CreditAnalysisError(f"final adjudication input is invalid: {key}")
        compact[key] = [
            {field: item[field] for field in fields if field in item}
            for item in items
        ]
    return compact


def _compact_final_call_inventory(
    records: Sequence[Mapping[str, Any]],
) -> list[list[Any]]:
    """Retain final call order and identity without repeated raw telemetry."""

    return [
        [
            record["candidate_id"],
            record["call_id"],
            record["workstream"],
            [],
            [],
            {},
            record["evidence_refs"][0],
        ]
        for record in records
    ]


def _prepare_final_review_transport(
    *,
    compact: Mapping[str, Any],
    routed_call_ids: Sequence[str],
    direct_evidence_candidate_ids: Sequence[str],
    audit_result: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Exclude failed-review inventory from every final-model input surface."""

    records = compact.get("records")
    if not isinstance(records, list) or any(
        not isinstance(record, Mapping) for record in records
    ):
        raise CreditAnalysisError("final review records are invalid")
    routed_call_set = set(routed_call_ids)
    routed_records = [
        dict(record) for record in records if record.get("call_id") in routed_call_set
    ]
    if {str(record["call_id"]) for record in routed_records} != routed_call_set:
        raise CreditAnalysisError("final routed-call inventory is incomplete")
    routed_candidate_ids = {
        str(record["candidate_id"]) for record in routed_records
    }
    retained_audit = dict(audit_result) if audit_result is not None else None
    if retained_audit is not None and not set(direct_evidence_candidate_ids).issubset(
        routed_candidate_ids
    ):
        retained_audit = None
    return (
        {
            **compact,
            "records": routed_records,
            "candidate_ids": [record["candidate_id"] for record in routed_records],
            "call_ids": list(routed_call_ids),
        },
        retained_audit,
    )


def _encoded_bytes(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )


def _fit_final_supplemental_evidence(
    *,
    base_payload: Mapping[str, Any],
    evidence_groups: Sequence[Mapping[str, Any]],
    byte_budget: int,
    transform: Callable[[Mapping[str, Any]], Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Round-robin complete deep-review records into the measured final input."""

    if byte_budget < 1:
        raise CreditAnalysisError("final Sol byte budget is invalid")
    base = {**base_payload, "deep_review_evidence": []}
    if _encoded_bytes(transform(base)) > byte_budget:
        raise CreditAnalysisError("final semantic packet exceeds the dynamic byte budget")
    selected = [
        {
            **{key: value for key, value in group.items() if key != "original_evidence"},
            "original_evidence": [],
        }
        for group in evidence_groups
    ]
    source_records: list[list[Mapping[str, Any]]] = []
    for group in evidence_groups:
        records = group.get("original_evidence")
        if not isinstance(records, list) or any(
            not isinstance(record, Mapping) for record in records
        ):
            raise CreditAnalysisError("deep-review evidence group is invalid")
        source_records.append(records)
    omissions: list[dict[str, Any]] = []
    for record_ordinal in range(max((len(records) for records in source_records), default=0)):
        for group_ordinal, records in enumerate(source_records):
            if record_ordinal >= len(records):
                continue
            record = dict(records[record_ordinal])
            proposed = [
                {
                    **group,
                    "original_evidence": [
                        *group["original_evidence"],
                        record,
                    ]
                    if index == group_ordinal
                    else list(group["original_evidence"]),
                }
                for index, group in enumerate(selected)
            ]
            retained = [group for group in proposed if group["original_evidence"]]
            candidate = {**base, "deep_review_evidence": retained}
            if _encoded_bytes(transform(candidate)) <= byte_budget:
                selected = proposed
                continue
            omissions.append(
                {
                    "stage": "sol-final",
                    "reason": "deep-review-capacity",
                    "task_id": "sol.final",
                    "turn_id": record.get("turn_id"),
                    "omitted_window_task_ids": [str(record.get("call_id", "-"))],
                    "finding_id": str(evidence_groups[group_ordinal]["finding_id"]),
                    "record_count": 1,
                    "candidate_count": 0,
                    "evidence_bytes": _encoded_bytes(record),
                    "output_bytes": 0,
                }
            )
    return (
        [group for group in selected if group["original_evidence"]],
        omissions,
    )


def _relevant_segments(text: str, surface_id: str) -> list[dict[str, Any]]:
    """Retain bounded deterministic windows around surface-relevant terms."""

    lowered = text.casefold()
    segments: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for keyword in SURFACE_EVIDENCE_KEYWORDS[surface_id]:
        start = 0
        while len(segments) < 4:
            position = lowered.find(keyword, start)
            if position < 0:
                break
            left = max(0, position - 350)
            right = min(len(text), position + len(keyword) + 650)
            bounds = (left, right)
            if not any(
                left < old_right and right > old_left
                for old_left, old_right in seen
            ):
                seen.add(bounds)
                segments.append(
                    {"start": left, "end": right, "text": text[left:right]}
                )
            start = position + len(keyword)
        if len(segments) >= 4:
            break
    return segments


def _shared_relevant_segments(
    text: str,
    surface_ids: Sequence[str],
    *,
    text_limit: int,
) -> list[dict[str, Any]]:
    """Keep one deterministic non-overlapping segment per applicable surface."""

    result: list[dict[str, Any]] = []
    bounds: list[tuple[int, int]] = []
    for surface_id in surface_ids:
        for segment in _relevant_segments(text, surface_id):
            start = int(segment["start"])
            end = int(segment["end"])
            if any(
                start < prior_end and end > prior_start
                for prior_start, prior_end in bounds
            ):
                continue
            bounds.append((start, end))
            result.append(
                {
                    "surface_id": surface_id,
                    "start": start,
                    "end": end,
                    "text": str(segment["text"])[:text_limit],
                }
            )
            break
    return result


def _prepare_bounded_evidence(
    value: Any,
    *,
    limit: int,
    surface_ids: Sequence[str],
) -> Any:
    """Keep useful bounded evidence while the complete value remains retained."""

    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    if len(serialized) <= limit:
        return {"mode": "complete", "value": value}
    segments = _shared_relevant_segments(
        serialized,
        surface_ids,
        text_limit=max(160, min(420, limit // 2)),
    )[:2]
    return {
        "mode": "retained-projection",
        "chars": len(serialized),
        "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "structured_outcome": structured_outcome(value),
        "head": serialized[: min(300, limit // 3)],
        "relevant_segments": segments,
        "tail": serialized[-min(300, limit // 3) :],
    }


__all__ = (
    "FINAL_ADJUDICATION_FIELDS",
    "SURFACE_EVIDENCE_KEYWORDS",
    "_compact_final_adjudication_result",
    "_compact_final_call_inventory",
    "_fit_final_supplemental_evidence",
    "_prepare_final_review_transport",
    "_prepare_bounded_evidence",
    "_relevant_segments",
    "_review_record_index",
    "_shared_relevant_segments",
)
