"""Own model response schemas and their shared structural enforcement.

Schemas travel unchanged through Codex CLI --output-schema and are also
validated locally with the repository's existing jsonschema dependency.
Evidence membership, coverage, and semantic consistency remain the callers'
independent responsibilities; this module never changes model judgments.
"""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .single_thread_analysis import (
    HOLISTIC_LUNA_RESULT_SCHEMA,
    HOLISTIC_SOL_TRANSPORT_SCHEMA,
    IDENTIFIER_RE,
    CreditAnalysisError,
)


def identifier_schema(
    *, max_length: int | None = None, nullable: bool = False
) -> dict[str, Any]:
    """Preserve complete identifier matches in the API and Python 3.14 validators."""

    result: dict[str, Any] = {
        "type": ["string", "null"] if nullable else "string",
        # $ can match before a terminal newline in Python. The absolute-end
        # anchor preserves fullmatch semantics without API-unsupported lookaround.
        "pattern": IDENTIFIER_RE.pattern.removesuffix("$") + r"\z",
        "minLength": 1,
    }
    if max_length is not None:
        result["maxLength"] = max_length
    return result


def identifiers(*, nonempty: bool = False) -> dict[str, Any]:
    """Describe result-owned identifiers, distinct from frozen evidence aliases."""

    result: dict[str, Any] = {
        "type": "array",
        "items": identifier_schema(max_length=96),
    }
    if nonempty:
        result["minItems"] = 1
    return result


def classification_reason_schema(
    contract: Mapping[str, Any],
    *,
    properties: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Require a supplied reason only for necessary calls, through nested anyOf."""

    common = dict(properties or {})
    branches = []
    for classifications, reason in (
        (["necessary"], {"type": "string", "enum": list(contract["necessary_reason_codes"])}),
        (
            [item for item in contract["call_classifications"] if item != "necessary"],
            {"type": "null"},
        ),
    ):
        branch_properties = {
            **common,
            "classification": {"type": "string", "enum": classifications},
            "reason_code": reason,
        }
        branches.append(
            {
                "type": "object",
                "properties": branch_properties,
                "required": list(branch_properties),
                "additionalProperties": False,
            }
        )
    return {"anyOf": branches}


def _applicable_errors(error: ValidationError) -> list[ValidationError]:
    """Unwrap a union only when its supplied classification picks one branch."""

    if error.validator != "anyOf" or not isinstance(error.instance, Mapping):
        return [error]
    classification = error.instance.get("classification")
    selected = [
        index for index, branch in enumerate(error.validator_value)
        if classification in branch.get("properties", {}).get("classification", {}).get("enum", [])
    ]
    if len(selected) != 1:
        return [error]
    return [
        leaf
        for child in error.context
        if child.schema_path and child.schema_path[0] == selected[0]
        for leaf in _applicable_errors(child)
    ]


def _validation_message(error: ValidationError, label: str) -> str:
    """Describe the exact failing location without echoing private response data."""

    path = label + "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}"
        for part in error.absolute_path
    )
    keyword = error.validator
    expected = error.validator_value
    if keyword == "maxLength":
        return f"{path} exceeds its {expected}-character semantic bound"
    if keyword == "pattern":
        return f"{path} must match pattern {expected!r}"
    if keyword == "type":
        return f"{path} must have type {expected!r}"
    if keyword == "enum":
        return f"{path} must be one of {expected!r}"
    if keyword == "const":
        return f"{path} must equal its frozen constant"
    if keyword == "required":
        missing = [key for key in expected if key not in error.instance]
        return f"{path} is missing required fields {missing!r}"
    if keyword == "additionalProperties":
        extra = sorted(set(error.instance) - set(error.schema.get("properties", {})))
        return f"{path} has unexpected fields {extra!r}"
    if keyword == "anyOf":
        return f"{path} must match an allowed classification/reason form"
    return f"{path} violates {keyword}={expected!r}"


def _validate_holistic_transport_value(
    value: Any, schema: Mapping[str, Any], label: str
) -> None:
    """Enforce the exact supplied JSON Schema with deterministic correction errors."""

    errors = [
        leaf
        for error in Draft202012Validator(schema).iter_errors(value)
        for leaf in _applicable_errors(error)
    ]
    if errors:
        messages = sorted({_validation_message(error, label) for error in errors})
        raise CreditAnalysisError("; ".join(messages))


def validate_classification_reason(
    group: Mapping[str, Any], contract: Mapping[str, Any], label: str
) -> None:
    """Reuse the transport contract when independently validating canonical results."""

    _validate_holistic_transport_value(
        {key: group.get(key) for key in ("classification", "reason_code")},
        classification_reason_schema(contract),
        label,
    )


def _correction_schema(
    schema: Mapping[str, Any], prior: Any, current: Any,
) -> Mapping[str, Any]:
    """Resolve a generated union through its stable classification discriminator."""

    branches = schema.get("anyOf")
    if not isinstance(branches, list):
        return schema
    for value in (prior, current):
        if isinstance(value, Mapping) and "classification" in value:
            selected = [
                branch for branch in branches
                if "classification" in branch.get("properties", {})
                and Draft202012Validator(branch["properties"]["classification"]).is_valid(
                    value["classification"]
                )
            ]
            if len(selected) == 1:
                return selected[0]
        selected = [branch for branch in branches if Draft202012Validator(branch).is_valid(value)]
        if len(selected) == 1:
            return selected[0]
    raise CreditAnalysisError("corrective retry has no unambiguous response form")


def response_correction_scope(
    prior: Mapping[str, Any], schema: Mapping[str, Any],
) -> dict[str, Any]:
    """Diagnose invalid recurrence and finding/accounting conflicts together.

    This grants no new evidence or call budget. Only uniquely identified model-
    call findings qualify. Well-formed non-positive estimates permit recurrence
    reconsideration; contradictory call accounting permits reconsidering those
    calls or withdrawing the claim. Malformed fields retain structural repair.
    The semantic validator independently checks the complete corrected result.
    """

    findings = prior.get("confirmed_findings", [])
    definition = schema.get("properties", {}).get("confirmed_findings", {}).get("items", {})
    properties = definition.get("properties", {})
    if not isinstance(findings, list) or not properties:
        return {"invalid_recurrence_finding_ids": []}
    invalid, conflicts = [], []
    by_call: dict[str, set[str]] = {}
    groups = prior.get("call_classifications")
    for group in groups if isinstance(groups, list) else []:
        if isinstance(group, Mapping) and isinstance(group.get("call_ids"), list):
            for call in group["call_ids"]:
                if isinstance(call, str):
                    by_call.setdefault(call, set()).add(str(group.get("classification")))
    for finding in findings:
        if not isinstance(finding, Mapping) or finding.get("waste_kind") != "model-calls":
            continue
        identity, recurrence = finding.get("id"), finding.get("recurrence")
        if (
            not Draft202012Validator(properties["id"]).is_valid(identity)
            or sum(isinstance(item, Mapping) and item.get("id") == identity for item in findings) != 1
        ):
            continue
        calls = finding.get("affected_call_ids")
        if isinstance(calls, list) and Draft202012Validator(properties["affected_call_ids"]).is_valid(calls) and all(len(by_call.get(call, set())) == 1 for call in calls):
            judgments = {next(iter(by_call[call])) for call in calls}
            avoidable = {"avoidable_implemented", "avoidable_unimplemented"}
            if (
                not judgments <= avoidable
                or finding.get("implementation_status") == "implemented" and judgments != {"avoidable_implemented"}
                or finding.get("implementation_status") != "implemented" and "avoidable_unimplemented" not in judgments
            ):
                conflicts.append(identity)
        if not isinstance(recurrence, Mapping) or not Draft202012Validator(properties["recurrence"]).is_valid(recurrence):
            continue
        saved = recurrence["calls_saved_per_affected_run"]
        added = recurrence["additional_recurring_calls_per_affected_run"]
        frequency = recurrence["affected_similar_run_frequency"]
        if all(math.isfinite(value) for value in (saved, added, frequency)) and (saved - added) * frequency <= 0:
            invalid.append(identity)
    return {"invalid_recurrence_finding_ids": invalid, "conflicting_call_finding_ids": conflicts}


def _correction_comparison_values(
    prior: Mapping[str, Any], current: Mapping[str, Any], schema: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """Build comparison copies permitting only diagnosed claim-local changes.

    The actual model result is never mutated or accepted here. Withdrawals must
    retain every other finding and every candidate decision; only their exact
    dependent links may change. Grouping is transport, so classifications are
    compared by call identity and out-of-scope aliases carry no protected claim.
    """

    old, new = copy.deepcopy(dict(prior)), copy.deepcopy(dict(current))
    arrays = ("confirmed_findings", "candidate_decisions", "temporary_control_reviews", "temporary_control_merges", "call_classifications")
    if any(not isinstance(value.get(key), list) for value in (old, new) for key in arrays):
        return old, new
    scope = response_correction_scope(prior, schema)
    invalid = set(scope["invalid_recurrence_finding_ids"])
    conflicts = set(scope.get("conflicting_call_finding_ids", []))
    current_findings = current.get("confirmed_findings", [])
    if isinstance(current_findings, list):
        current_by_id = {item.get("id"): item for item in current_findings if isinstance(item, Mapping) and isinstance(item.get("id"), str)}
        withdrawn = (invalid | conflicts) - current_by_id.keys()
        for finding in old.get("confirmed_findings", []):
            if isinstance(finding, dict) and finding.get("id") in invalid & current_by_id.keys():
                corrected = current_by_id[finding["id"]]
                if "recurrence" in corrected:
                    finding["recurrence"] = copy.deepcopy(corrected["recurrence"])
        if withdrawn:
            old["confirmed_findings"] = [item for item in old["confirmed_findings"] if not isinstance(item, Mapping) or item.get("id") not in withdrawn]
            current_decisions = {item.get("luna_candidate_id"): item for item in new.get("candidate_decisions", []) if isinstance(item, Mapping)}
            for decision in old.get("candidate_decisions", []):
                ids = decision.get("finding_ids", []) if isinstance(decision, dict) else []
                if not isinstance(ids, list) or not withdrawn.intersection(ids):
                    continue
                decision["finding_ids"] = [identity for identity in ids if identity not in withdrawn]
                decision["disposition"] = (
                    "confirmed-finding" if decision["finding_ids"] else
                    "plausible-risk" if decision.get("risk_ids") else "dismissed-candidate"
                )
                corrected = current_decisions.get(decision.get("luna_candidate_id"), {})
                if "reason" in corrected:
                    decision["reason"] = corrected["reason"]
            current_reviews = {item.get("id"): item for item in new.get("temporary_control_reviews", []) if isinstance(item, Mapping)}
            for review in old.get("temporary_control_reviews", []):
                if isinstance(review, dict) and review.get("finding_id") in withdrawn:
                    review["finding_id"] = None
                    review["no_finding_reason"] = current_reviews.get(review.get("id"), {}).get("no_finding_reason")
            old["temporary_control_merges"] = [item for item in old.get("temporary_control_merges", []) if not isinstance(item, Mapping) or item.get("finding_id") not in withdrawn]
    else:
        withdrawn = set()

    group_schema = schema.get("properties", {}).get("call_classifications", {}).get("items", {})
    branches = group_schema.get("anyOf", [])
    allowed = branches[0].get("properties", {}).get("call_ids", {}).get("items", {}).get("enum") if branches else None
    if not isinstance(allowed, list):
        return old, new

    def by_call(groups: Any) -> dict[str, Any] | None:
        if not isinstance(groups, list):
            return None
        result: dict[str, Any] = {}
        for group in groups:
            if not isinstance(group, Mapping) or not isinstance(group.get("call_ids"), list):
                return None
            for identity in group["call_ids"]:
                if not isinstance(identity, str):
                    return None
                detail = {key: value for key, value in group.items() if key != "call_ids"}
                if identity in result and result[identity] != detail:
                    raise CreditAnalysisError("corrective retry has conflicting prior call judgments")
                result[identity] = detail
        return result

    before, after = by_call(old.get("call_classifications")), by_call(new.get("call_classifications"))
    if before is None or after is None:
        return old, new
    surviving_calls = {call for item in old.get("confirmed_findings", []) if isinstance(item, Mapping) and item.get("waste_kind") == "model-calls" for call in item.get("affected_call_ids", [])}
    withdrawn_calls = {call for item in prior.get("confirmed_findings", []) if isinstance(item, Mapping) and item.get("id") in withdrawn for call in item.get("affected_call_ids", [])} - surviving_calls
    retained = [identity for identity in allowed if identity in before]
    if any(identity not in after for identity in retained):
        raise CreditAnalysisError("corrective retry changed protected response field $response.call_classifications: removed prior call coverage")
    protected_calls = {call for item in prior.get("confirmed_findings", []) if isinstance(item, Mapping) and item.get("waste_kind") == "model-calls" and item.get("id") not in invalid | conflicts for call in item.get("affected_call_ids", [])}
    conflicting_calls = {call for item in prior.get("confirmed_findings", []) if isinstance(item, Mapping) and item.get("id") in conflicts for call in item.get("affected_call_ids", [])} - protected_calls
    for identity in conflicting_calls & before.keys() & after.keys():
        for key in ("classification", "reason_code", "rationale"):
            before[identity][key] = after[identity].get(key)
    for identity in withdrawn_calls & before.keys() & after.keys():
        if before[identity].get("classification") in {"avoidable_implemented", "avoidable_unimplemented"} and after[identity].get("classification") == "unassessed":
            for key in ("classification", "reason_code", "rationale"):
                before[identity][key] = after[identity].get(key)
    old["call_classifications"] = [{"call_ids": [identity], **before[identity]} for identity in retained]
    new["call_classifications"] = [{"call_ids": [identity], **after[identity]} for identity in retained]
    return old, new


def validate_response_correction(
    prior: Mapping[str, Any], current: Mapping[str, Any], schema: Mapping[str, Any],
) -> None:
    """Protect unaffected judgments through structural and diagnosed ROI repair.

    Callers supply the authoritative schema and independently validate current
    semantics and evidence. The first rejection remains the baseline. Invalid
    ROI claims may be reconsidered or withdrawn with their dependent links;
    valid findings stay protected. Schema-invalid identifiers may change with
    their references. Byte overflow never permits rewriting valid text.
    """

    prior, current = _correction_comparison_values(prior, current, schema)
    identifier_pattern = identifier_schema()["pattern"]
    replacements: dict[str, str] = {}

    def collect_ids(old: Any, new: Any, definition: Mapping[str, Any]) -> None:
        definition = _correction_schema(definition, old, new)
        if isinstance(old, Mapping) and isinstance(new, Mapping):
            properties = definition.get("properties", {})
            id_definition = properties.get("id", {})
            old_id, new_id = old.get("id"), new.get("id")
            if (
                id_definition.get("pattern") == identifier_pattern
                and isinstance(old_id, str)
                and not Draft202012Validator(id_definition).is_valid(old_id)
                and isinstance(new_id, str)
                and Draft202012Validator(id_definition).is_valid(new_id)
            ):
                if old_id in replacements and replacements[old_id] != new_id:
                    raise CreditAnalysisError("corrective retry renamed one invalid identifier inconsistently")
                replacements[old_id] = new_id
            for key in old.keys() & new.keys() & properties.keys():
                collect_ids(old[key], new[key], properties[key])
        elif isinstance(old, list) and isinstance(new, list):
            item_schema = definition.get("items", {})
            for old_item, new_item in zip(old, new, strict=False):
                collect_ids(old_item, new_item, item_schema)

    def protected(path: str) -> None:
        raise CreditAnalysisError(f"corrective retry changed protected response field {path}")

    def compare(old: Any, new: Any, definition: Mapping[str, Any], path: str) -> None:
        definition = _correction_schema(definition, old, new)
        if isinstance(old, Mapping) and isinstance(new, Mapping):
            properties = definition.get("properties", {})
            if "classification" in old and old["classification"] != new.get("classification"):
                protected(f"{path}.classification")
            for key, value in old.items():
                if key not in properties and definition.get("additionalProperties") is False:
                    continue
                child = properties.get(key, {})
                if key not in new:
                    protected(f"{path}.{key}")
                compare(value, new[key], child, f"{path}.{key}")
            return
        if isinstance(old, list) and isinstance(new, list):
            if len(old) != len(new):
                invalid_length = any(
                    not error.path and error.validator in {"minItems", "maxItems"}
                    for error in Draft202012Validator(definition).iter_errors(old)
                )
                if not invalid_length:
                    protected(path)
            for index, (old_item, new_item) in enumerate(zip(old, new, strict=False)):
                compare(old_item, new_item, definition.get("items", {}), f"{path}[{index}]")
            return
        if (
            isinstance(old, str) and old in replacements
            and definition.get("pattern") == identifier_pattern
        ):
            if new != replacements[old]:
                protected(path)
            return
        if old != new and Draft202012Validator(definition).is_valid(old):
            protected(path)

    collect_ids(prior, current, schema)
    compare(prior, current, schema, "$response")


def _holistic_luna_schema(
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    input_sha256: str,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    surface_values = list(state["manifest"]["surface_order"])
    candidate_pattern = rf"^{re.escape(str(state['analysis_id']))}\.c\.[0-9]{{6}}$"
    properties = {
        "schema": {"type": "string", "const": HOLISTIC_LUNA_RESULT_SCHEMA},
        "analysis_id": {"type": "string", "const": state["analysis_id"]},
        "task_id": {"type": "string", "const": task["task_id"]},
        "input_sha256": {"type": "string", "const": input_sha256},
        "coverage": {
            "type": "object",
            "properties": {
                "candidate_count": {"type": "integer", "const": len(task["candidate_ids"])},
                "candidate_ids_sha256": {
                    "type": "string",
                    "const": task["candidate_ids_sha256"],
                },
                "first_candidate_id": {
                    "type": "string",
                    "const": task["candidate_ids"][0],
                },
                "last_candidate_id": {
                    "type": "string",
                    "const": task["candidate_ids"][-1],
                },
            },
            "required": [
                "candidate_count",
                "candidate_ids_sha256",
                "first_candidate_id",
                "last_candidate_id",
            ],
            "additionalProperties": False,
        },
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": identifier_schema(),
                    "kind": {"type": "string", "enum": contract["luna_candidate_kinds"]},
                    "title": {"type": "string", "minLength": 1},
                    "hypothesis": {"type": "string", "minLength": 1},
                    "surface_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "enum": surface_values},
                    },
                    "candidate_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "pattern": candidate_pattern},
                    },
                    "evidence_refs": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "string",
                            "pattern": r"^(?:evidence|analysis)://",
                        },
                    },
                    "producer_owner_hint": {"type": "string", "minLength": 1},
                },
                "required": [
                    "id",
                    "kind",
                    "title",
                    "hypothesis",
                    "surface_ids",
                    "candidate_ids",
                    "evidence_refs",
                    "producer_owner_hint",
                ],
                "additionalProperties": False,
            },
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def build_sol_schema(
    *,
    contract: Mapping[str, Any],
    luna_aliases: Sequence[str],
    call_aliases: Sequence[str],
    evidence_aliases: Sequence[str],
) -> dict[str, Any]:
    """Build the one model-facing Sol contract from frozen alias inventories."""

    def string(max_length: int) -> dict[str, Any]:
        return {"type": "string", "minLength": 1, "maxLength": max_length}

    def strings(max_length: int, *, nonempty: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": "array",
            "items": string(max_length),
        }
        if nonempty:
            result["minItems"] = 1
        return result

    def aliases(values: Sequence[str], *, nonempty: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": "array",
            "items": {"type": "string", "enum": list(values)},
        }
        if nonempty:
            result["minItems"] = 1
        return result

    def number() -> dict[str, Any]:
        return {"type": "number", "minimum": 0}

    def boolean() -> dict[str, Any]:
        return {"type": "boolean"}

    def nullable_string(max_length: int) -> dict[str, Any]:
        return {"type": ["string", "null"], "maxLength": max_length}

    def closed(properties: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": dict(properties),
            "required": list(properties),
            "additionalProperties": False,
        }

    def objects(item: Mapping[str, Any]) -> dict[str, Any]:
        return {"type": "array", "items": dict(item)}

    recurrence = closed(
        {
            "calls_saved_per_affected_run": {
                **number(),
                "description": "Gross model calls prevented in one affected run, supported by the supplied evidence.",
            },
            "additional_recurring_calls_per_affected_run": {
                **number(),
                "description": "New model calls required on every affected run by the proposed control; use zero for deterministic controls that make no model calls. Exclude one-time implementation work.",
            },
            "affected_similar_run_frequency": {
                **number(),
                "description": "Evidence-supported frequency of affected similar runs; positive model-call savings require (saved minus new recurring calls) times frequency to exceed zero.",
            },
            "affected_similar_run_frequency_range": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": number(),
            },
            "assumptions": strings(240, nonempty=True),
        }
    )
    cost = closed(
        {
            "estimated_model_calls": number(),
            "description": string(240),
        }
    )
    finding = closed(
        {
            "id": identifier_schema(max_length=96),
            "title": string(160),
            "problem_summary": string(600),
            "waste_kind": {"type": "string", "enum": contract["waste_kinds"]},
            "affected_call_ids": aliases(call_aliases, nonempty=True),
            "evidence_refs": aliases(evidence_aliases, nonempty=True),
            "producer_type": {"type": "string", "enum": contract["producer_types"]},
            "producer_owner": string(240),
            "proposed_durable_control": string(600),
            "implementation_status": {
                "type": "string",
                "enum": contract["implementation_statuses"],
            },
            "targeted_verification": strings(320, nonempty=True),
            "recurrence": recurrence,
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "complexity": {"type": "string", "enum": contract["complexities"]},
            "one_time_implementation_cost": cost,
            "helper_categories": {
                "type": "array",
                "items": {"type": "string", "enum": contract["helper_categories"]},
            },
        }
    )
    risk = closed(
        {
            "id": identifier_schema(max_length=96),
            "description": string(480),
            "affected_call_ids": aliases(call_aliases, nonempty=True),
            "evidence_refs": aliases(evidence_aliases, nonempty=True),
            "competing_explanations": strings(320, nonempty=True),
            "missing_fact": string(320),
            "verification_needed": strings(320, nonempty=True),
        }
    )
    temporary_review = closed(
        {
            "id": identifier_schema(max_length=96),
            "source_luna_candidate_ids": aliases(luna_aliases, nonempty=True),
            "problem_solved": string(360),
            "affected_call_ids": aliases(call_aliases, nonempty=True),
            "observed_temporary_control": string(480),
            "final_canonical_evidence_refs": aliases(
                evidence_aliases,
                nonempty=True,
            ),
            "disposition": {
                "type": "string",
                "enum": contract["temporary_control_dispositions"],
            },
            "owning_producer": nullable_string(240),
            "recurrence_inputs": closed(
                {
                    "likely": boolean(),
                    "frequency_range": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 2,
                        "items": number(),
                    },
                    "basis": string(320),
                }
            ),
            "savings_inputs": closed(
                {
                    "expected_calls_saved": number(),
                    "maintenance_model_calls": number(),
                    "justifies_maintenance": boolean(),
                    "basis": string(320),
                }
            ),
            "finding_id": identifier_schema(max_length=96, nullable=True),
            "no_finding_reason": nullable_string(360),
        }
    )
    properties = {
        "candidate_decisions": objects(
            closed(
                {
                    "luna_candidate_id": {
                        "type": "string",
                        "enum": luna_aliases,
                    },
                    "disposition": {
                        "type": "string",
                        "enum": contract["adjudication_dispositions"],
                    },
                    "reason": string(320),
                    "evidence_refs": aliases(evidence_aliases, nonempty=True),
                    "finding_ids": identifiers(),
                    "risk_ids": identifiers(),
                }
            )
        ),
        "confirmed_findings": objects(finding),
        "plausible_risks": objects(risk),
        "temporary_control_reviews": objects(temporary_review),
        "temporary_control_merges": objects(
            closed(
                {
                    "control_key": string(160),
                    "owning_producer": string(240),
                    "review_ids": identifiers(nonempty=True),
                    "finding_id": identifier_schema(max_length=96),
                }
            )
        ),
        "helper_category_reviews": objects(
            closed(
                {
                    "category": {"type": "string", "enum": contract["helper_categories"]},
                    "applies": boolean(),
                    "evidence_refs": aliases(evidence_aliases),
                    "reason": string(320),
                }
            )
        ),
        "call_classifications": objects(
            classification_reason_schema(
                contract,
                properties={
                    "call_ids": aliases(call_aliases, nonempty=True),
                    "rationale": string(240),
                    "evidence_refs": aliases(evidence_aliases, nonempty=True),
                },
            )
        ),
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": HOLISTIC_SOL_TRANSPORT_SCHEMA,
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _holistic_sol_schema(
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    input_sha256: str,
    contract: Mapping[str, Any],
    luna_candidate_ids: Sequence[str],
    alias_record: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind aliases to the exact call scope independently enforced by Sol.

    Deferred imports avoid a schema/analysis initialization cycle. The caller
    verifies the frozen alias record against input_sha256 before binding.
    """
    from .luna_sol_analysis import (
        _holistic_alias_lookups, _holistic_runtime_task, _routed_call_ids,
    )

    canonical_to_alias, _ = _holistic_alias_lookups(alias_record)
    if task["phase"] == "sol-adjudication":
        # Saved slots acquire their exact assignment through the same owner
        # used at launch; recovery tasks already carry their narrower scope.
        scoped_task = task if "call_ids" in task else _holistic_runtime_task(state, task)
        call_ids = list(scoped_task["call_ids"])
    else:
        call_ids = _routed_call_ids(state)
    return build_sol_schema(
        contract=contract,
        luna_aliases=[canonical_to_alias[item] for item in luna_candidate_ids],
        call_aliases=[canonical_to_alias[item] for item in call_ids],
        evidence_aliases=list(alias_record["aliases"]["evidence"]),
    )
