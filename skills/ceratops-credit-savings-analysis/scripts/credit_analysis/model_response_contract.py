"""Own model response schemas and their shared structural enforcement.

Schemas travel unchanged through Codex CLI --output-schema and are also
validated locally with the repository's existing jsonschema dependency.
Evidence membership, coverage, and semantic consistency remain the callers'
independent responsibilities. Mechanical transport normalization never changes
model judgments, and callers retain the raw response separately.
"""

from __future__ import annotations

import copy
import hashlib
import json
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


def _bounded_explanation(value: str, limit: int) -> str:
    """Fit retained explanatory text to its destination without changing its judgment."""

    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def normalize_sol_transport_mechanics(
    response: Mapping[str, Any],
) -> dict[str, Any]:
    """Canonicalize code-owned IDs and bound explanatory Sol transport text.

    The returned copy is suitable for validation and persistence as the accepted
    result. The caller keeps the unmodified raw response as attempt evidence.
    Ambiguous identifier collections remain unchanged so ordinary validation and
    corrective retry can diagnose them instead of guessing at references.
    """

    result = copy.deepcopy(dict(response))

    def canonicalize(field: str, prefix: str) -> dict[str, str]:
        items = result.get(field)
        if not isinstance(items, list):
            return {}
        identities: list[str] = []
        for item in items:
            if (
                not isinstance(item, Mapping)
                or not isinstance(item.get("id"), str)
                or not item["id"]
            ):
                return {}
            identities.append(item["id"])
        if len(identities) != len(set(identities)):
            return {}
        used = {
            identity
            for identity in identities
            if len(identity) <= 96 and IDENTIFIER_RE.fullmatch(identity)
        }
        mapping: dict[str, str] = {}
        next_index = 1
        for identity in identities:
            if identity in used:
                mapping[identity] = identity
                continue
            candidate = f"{prefix}-{next_index:04d}"
            while candidate in used:
                next_index += 1
                candidate = f"{prefix}-{next_index:04d}"
            mapping[identity] = candidate
            used.add(candidate)
            next_index += 1
        for item, identity in zip(items, identities, strict=True):
            item["id"] = mapping[identity]
        return mapping

    finding_ids = canonicalize("confirmed_findings", "finding")
    risk_ids = canonicalize("plausible_risks", "risk")
    review_ids = canonicalize("temporary_control_reviews", "review")

    def rewrite_list(item: Any, field: str, mapping: Mapping[str, str]) -> None:
        if not isinstance(item, dict) or not isinstance(item.get(field), list):
            return
        item[field] = [
            mapping.get(identity, identity) if isinstance(identity, str) else identity
            for identity in item[field]
        ]

    decisions = result.get("candidate_decisions")
    for decision in decisions if isinstance(decisions, list) else []:
        rewrite_list(decision, "finding_ids", finding_ids)
        rewrite_list(decision, "risk_ids", risk_ids)

    reviews = result.get("temporary_control_reviews")
    for review in reviews if isinstance(reviews, list) else []:
        if isinstance(review, dict) and isinstance(review.get("finding_id"), str):
            review["finding_id"] = finding_ids.get(
                review["finding_id"], review["finding_id"]
            )

    merges = result.get("temporary_control_merges")
    for merge in merges if isinstance(merges, list) else []:
        rewrite_list(merge, "review_ids", review_ids)
        if isinstance(merge, dict) and isinstance(merge.get("finding_id"), str):
            merge["finding_id"] = finding_ids.get(
                merge["finding_id"], merge["finding_id"]
            )

    classifications = result.get("call_classifications")
    for classification in classifications if isinstance(classifications, list) else []:
        if not isinstance(classification, dict):
            continue
        rationale = classification.get("rationale")
        if isinstance(rationale, str) and len(rationale) > 240:
            classification["rationale"] = _bounded_explanation(rationale, 240)
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
    prior: Mapping[str, Any], schema: Mapping[str, Any], source_call_count: int = 0,
) -> dict[str, Any]:
    """Diagnose invalid recurrence, review ROI, and accounting conflicts.

    This grants no new evidence or call budget. Only uniquely identified model-
    call findings qualify. Well-formed estimates below the source-call floor permit recurrence
    reconsideration. A well-formed temporary-control subclaim that fails its ROI
    gate may be dismissed without withdrawing its independent finding.
    Contradictory call accounting permits reconsidering those calls or
    withdrawing the claim. Malformed fields retain structural repair. The
    semantic validator independently checks the complete corrected result.
    """

    scope: dict[str, list[str]] = {
        "invalid_recurrence_finding_ids": [],
        "conflicting_call_finding_ids": [],
        "invalid_temporary_control_review_ids": [],
    }
    findings = prior.get("confirmed_findings", [])
    definition = schema.get("properties", {}).get("confirmed_findings", {}).get("items", {})
    properties = definition.get("properties", {})
    if not isinstance(findings, list) or not properties:
        return scope
    invalid: list[str] = []
    conflicts: list[str] = []
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
            not isinstance(identity, str)
            or not Draft202012Validator(properties["id"]).is_valid(identity)
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
        if all(math.isfinite(value) for value in (saved, added, frequency)) and (saved - added) * frequency < source_call_count * 3 // 100:
            invalid.append(identity)
    scope["invalid_recurrence_finding_ids"] = invalid
    scope["conflicting_call_finding_ids"] = conflicts

    finding_ids = {
        finding.get("id")
        for finding in findings
        if isinstance(finding, Mapping) and isinstance(finding.get("id"), str)
    }
    reviews = prior.get("temporary_control_reviews", [])
    if not isinstance(reviews, list):
        return scope
    for review in reviews:
        if not isinstance(review, Mapping):
            continue
        identity = review.get("id")
        finding_id = review.get("finding_id")
        recurrence = review.get("recurrence_inputs")
        savings = review.get("savings_inputs")
        if (
            not isinstance(identity, str)
            or sum(
                isinstance(item, Mapping) and item.get("id") == identity
                for item in reviews
            )
            != 1
            or finding_id not in finding_ids
            or not isinstance(recurrence, Mapping)
            or not isinstance(savings, Mapping)
        ):
            continue
        expected = savings.get("expected_calls_saved")
        maintenance = savings.get("maintenance_model_calls")
        if not (
            isinstance(expected, (int, float))
            and not isinstance(expected, bool)
            and math.isfinite(expected)
            and expected >= 0
            and isinstance(maintenance, (int, float))
            and not isinstance(maintenance, bool)
            and math.isfinite(maintenance)
            and maintenance >= 0
        ):
            continue
        if (
            review.get("disposition") != "durable-control-missing"
            or recurrence.get("likely") is not True
            or savings.get("justifies_maintenance") is not True
            or expected <= maintenance
            or review.get("no_finding_reason") is not None
        ):
            scope["invalid_temporary_control_review_ids"].append(identity)
    return scope


def _correction_comparison_values(
    prior: Mapping[str, Any], current: Mapping[str, Any], schema: Mapping[str, Any], source_call_count: int = 0,
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
    if any(not isinstance(item, Mapping) or not isinstance(item.get("affected_call_ids"), list)
           for value in (old, new) for item in value["confirmed_findings"]):
        # Structural repair must finish before claim-local call permissions can
        # be derived from malformed finding coverage.
        return old, new
    scope = response_correction_scope(prior, schema, source_call_count)
    invalid = set(scope["invalid_recurrence_finding_ids"])
    conflicts = set(scope.get("conflicting_call_finding_ids", []))
    dismissed_reviews = set(scope.get("invalid_temporary_control_review_ids", []))
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

    if dismissed_reviews:
        current_reviews = {
            item.get("id"): item
            for item in new.get("temporary_control_reviews", [])
            if isinstance(item, Mapping)
        }
        for review in old.get("temporary_control_reviews", []):
            if isinstance(review, dict) and review.get("id") in dismissed_reviews:
                review["finding_id"] = None
                review["no_finding_reason"] = current_reviews.get(
                    review.get("id"), {}
                ).get("no_finding_reason")
        retained_merges = []
        for merge in old.get("temporary_control_merges", []):
            if not isinstance(merge, dict) or not isinstance(
                merge.get("review_ids"), list
            ):
                retained_merges.append(merge)
                continue
            merge["review_ids"] = [
                identity
                for identity in merge["review_ids"]
                if identity not in dismissed_reviews
            ]
            if merge["review_ids"]:
                retained_merges.append(merge)
        old["temporary_control_merges"] = retained_merges

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
    prior: Mapping[str, Any], current: Mapping[str, Any], schema: Mapping[str, Any], source_call_count: int = 0,
) -> None:
    """Protect unaffected judgments through structural and diagnosed ROI repair.

    Callers supply the authoritative schema and independently validate current
    semantics and evidence. The first rejection remains the baseline. Invalid
    ROI claims may be reconsidered or withdrawn with their dependent links;
    valid findings stay protected. Schema-invalid identifiers may change with
    their references. Byte overflow never permits rewriting valid text.
    """

    prior, current = _correction_comparison_values(prior, current, schema, source_call_count)
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


def _closed_object(properties: Mapping[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": dict(properties),
            "required": list(properties), "additionalProperties": False}


def _list_field(value: Mapping[str, Any], key: str) -> list[Any]:
    field = value.get(key)
    return field if isinstance(field, list) else []


def _pointer(parts: Sequence[str | int]) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _pointer_parts(path: str) -> list[str]:
    return [part.replace("~1", "/").replace("~0", "~") for part in path.split("/")[1:]]


def _at_pointer(value: Any, path: str) -> Any:
    for part in _pointer_parts(path):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _corresponding_value(prior: Any, current: Any, path: str) -> Any:
    """Match identified array members before projecting a retained full result."""
    for part in _pointer_parts(path):
        if isinstance(prior, list):
            index = int(part)
            old = prior[index]
            identity = old.get("id") if isinstance(old, Mapping) else None
            if isinstance(identity, str) and IDENTIFIER_RE.fullmatch(identity):
                matches = [item for item in current if isinstance(item, Mapping) and item.get("id") == identity]
                if len(matches) != 1:
                    raise KeyError("retained correction target is absent or ambiguous")
                current = matches[0]
            else:
                current = current[index]
            prior = old
        else:
            current = current[part]
            prior = prior.get(part) if isinstance(prior, Mapping) else None
    return current


def correction_response_schema(
    prior: Mapping[str, Any], schema: Mapping[str, Any], source_call_count: int = 0,
) -> dict[str, Any]:
    """Compile a closed edit vocabulary from the rejected immutable response.

    This is deliberately not general JSON Patch: only schema-invalid locations
    and diagnosed claim-local judgments are expressible. The controller owns
    protected content, dependent links, and grouping. No new evidence is granted.
    """
    edits: list[dict[str, Any]] = []

    def replacement(path: Sequence[str | int], definition: Mapping[str, Any]) -> None:
        edits.append(_closed_object({"path": {"type": "string", "const": _pointer(path)},
                                     "value": dict(definition)}))

    def removal(path: Sequence[str | int]) -> None:
        edits.append(_closed_object({"remove": {"type": "string", "const": _pointer(path)}}))

    def visit(value: Any, definition: Mapping[str, Any], path: list[str | int]) -> None:
        if Draft202012Validator(definition).is_valid(value):
            return
        try:
            selected = _correction_schema(definition, value, value)
        except CreditAnalysisError:
            replacement(path, definition)
            return
        if isinstance(value, Mapping) and selected.get("type") == "object":
            properties = selected.get("properties", {})
            for key, child in properties.items():
                if key in value:
                    visit(value[key], child, [*path, key])
                elif key in selected.get("required", []):
                    replacement([*path, key], child)
            if selected.get("additionalProperties") is False:
                for key in sorted(value.keys() - properties.keys()):
                    removal([*path, key])
        elif isinstance(value, list) and selected.get("type") == "array":
            if any(not error.path and error.validator in {"minItems", "maxItems"}
                   for error in Draft202012Validator(selected).iter_errors(value)):
                replacement(path, selected)
                return
            child = selected.get("items", {})
            for index, item in enumerate(value):
                # An out-of-scope accounting alias carries no admitted judgment.
                if (len(path) == 3 and path[0] == "call_classifications"
                        and path[2] == "call_ids" and "enum" in child
                        and not Draft202012Validator(child).is_valid(item)):
                    removal([*path, index])
                else:
                    visit(item, child, [*path, index])
        else:
            replacement(path, selected)

    visit(prior, schema, [])
    scope = response_correction_scope(prior, schema, source_call_count)
    invalid = set(scope["invalid_recurrence_finding_ids"])
    diagnosed = invalid | set(scope.get("conflicting_call_finding_ids", []))
    invalid_reviews = set(scope.get("invalid_temporary_control_review_ids", []))
    findings = prior.get("confirmed_findings", [])
    findings = findings if isinstance(findings, list) else []
    finding_schema = schema.get("properties", {}).get("confirmed_findings", {}).get("items", {})
    for index, finding in enumerate(findings):
        if isinstance(finding, Mapping) and finding.get("id") in invalid:
            replacement(["confirmed_findings", index, "recurrence"], finding_schema["properties"]["recurrence"])
    if diagnosed:
        edits.append(_closed_object({
            "withdraw_finding": {"type": "string", "enum": sorted(diagnosed)},
            "reason": {"type": "string", "minLength": 1, "maxLength": 2_000},
        }))
    if invalid_reviews:
        edits.append(_closed_object({
            "dismiss_temporary_review": {
                "type": "string",
                "enum": sorted(invalid_reviews),
            },
            "reason": {"type": "string", "minLength": 1, "maxLength": 2_000},
        }))
    protected_calls = {call for finding in findings if isinstance(finding, Mapping)
                       and finding.get("waste_kind") == "model-calls" and finding.get("id") not in diagnosed
                       for call in _list_field(finding, "affected_call_ids")}
    calls = {call for finding in findings if isinstance(finding, Mapping) and finding.get("id") in diagnosed
             for call in _list_field(finding, "affected_call_ids")} - protected_calls
    groups = schema.get("properties", {}).get("call_classifications", {}).get("items", {})
    for branch in groups.get("anyOf", []) if calls else []:
        properties = branch["properties"]
        edits.append(_closed_object({
            "call_id": {"type": "string", "enum": sorted(calls)},
            **{key: properties[key] for key in ("classification", "reason_code", "rationale")},
        }))
    digest = hashlib.sha256(json.dumps(prior, sort_keys=True, ensure_ascii=False,
                                      separators=(",", ":")).encode("utf-8")).hexdigest()
    return _closed_object({
        "baseline_sha256": {"type": "string", "const": digest},
        "edits": {"type": "array", "items": {"anyOf": edits} if edits else {"type": "null"},
                  "maxItems": len(edits) + len(diagnosed) + len(invalid_reviews) + len(calls)},
    })


def _call_details(value: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    groups = value.get("call_classifications", [])
    result: dict[str, dict[str, Any]] = {}
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, Mapping) or not isinstance(group.get("call_ids"), list):
            continue
        for identity in group["call_ids"]:
            if not isinstance(identity, str):
                continue
            detail = {key: copy.deepcopy(item) for key, item in group.items() if key != "call_ids"}
            if identity in result and result[identity] != detail:
                raise CreditAnalysisError("corrective retry has conflicting prior call judgments")
            result[identity] = detail
    return result


def project_response_correction(
    prior: Mapping[str, Any], current: Mapping[str, Any], edit_schema: Mapping[str, Any],
) -> dict[str, Any]:
    """Extract permitted edits from an already retained full-response attempt.

    The caller must verify the recorded attempt used a full-response schema.
    Live retries use edits directly. Projection copies no protected prose and
    mutates neither retained response; ordinary reconstruction validates it next.
    """
    edits: list[dict[str, Any]] = []
    calls: set[str] = set()
    withdrawals: set[str] = set()
    review_dismissals: set[str] = set()
    for branch in edit_schema["properties"]["edits"]["items"].get("anyOf", []):
        properties = branch["properties"]
        if "path" in properties:
            path = properties["path"]["const"]
            try:
                value = _corresponding_value(prior, current, path)
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            try:
                unchanged = value == _at_pointer(prior, path)
            except (KeyError, IndexError, TypeError, ValueError):
                unchanged = False
            if not unchanged:
                edits.append({"path": path, "value": copy.deepcopy(value)})
        elif "remove" in properties:
            edits.append({"remove": properties["remove"]["const"]})
        elif "call_id" in properties:
            calls.update(properties["call_id"]["enum"])
        elif "withdraw_finding" in properties:
            withdrawals.update(properties["withdraw_finding"]["enum"])
        elif "dismiss_temporary_review" in properties:
            review_dismissals.update(
                properties["dismiss_temporary_review"]["enum"]
            )
    current_ids = {finding.get("id") for finding in _list_field(current, "confirmed_findings")
                   if isinstance(finding, Mapping)}
    decisions = {item.get("luna_candidate_id"): item for item in _list_field(current, "candidate_decisions")
                 if isinstance(item, Mapping)}
    for identity in sorted(withdrawals - current_ids):
        reasons = [decisions.get(item.get("luna_candidate_id"), {}).get("reason")
                   for item in _list_field(prior, "candidate_decisions")
                   if isinstance(item, Mapping) and identity in _list_field(item, "finding_ids")]
        reason = next((value for value in reasons if isinstance(value, str) and value.strip()), None)
        if reason is None:
            raise CreditAnalysisError("retained withdrawal has no candidate explanation")
        edits.append({"withdraw_finding": identity, "reason": reason})
    prior_reviews = {
        item.get("id"): item
        for item in _list_field(prior, "temporary_control_reviews")
        if isinstance(item, Mapping)
    }
    current_reviews = {
        item.get("id"): item
        for item in _list_field(current, "temporary_control_reviews")
        if isinstance(item, Mapping)
    }
    for identity in sorted(review_dismissals):
        before_review = prior_reviews.get(identity)
        after_review = current_reviews.get(identity)
        if (
            not isinstance(before_review, Mapping)
            or not isinstance(after_review, Mapping)
            or before_review.get("finding_id") is None
            or after_review.get("finding_id") is not None
        ):
            continue
        reason = after_review.get("no_finding_reason")
        if isinstance(reason, str) and reason.strip():
            edits.append({"dismiss_temporary_review": identity, "reason": reason})
    before, after = _call_details(prior), _call_details(current)
    for identity in sorted(calls & before.keys() & after.keys()):
        keys = ("classification", "reason_code", "rationale")
        if any(before[identity].get(key) != after[identity].get(key) for key in keys):
            edits.append({"call_id": identity, **{key: after[identity].get(key) for key in keys}})
    return {"baseline_sha256": edit_schema["properties"]["baseline_sha256"]["const"], "edits": edits}


def apply_response_correction(
    prior: Mapping[str, Any], correction: Mapping[str, Any], schema: Mapping[str, Any], source_call_count: int = 0,
) -> dict[str, Any]:
    """Reconstruct one full response, retaining every unaffected original value.

    The original response and raw edit attempt remain immutable evidence. Closed
    transport validation precedes writes, then preservation and full structural
    checks precede the caller's independent evidence and accounting validation.
    """
    edit_schema = correction_response_schema(prior, schema, source_call_count)
    allowed_paths = {branch["properties"]["path"]["const"]
                     for branch in edit_schema["properties"]["edits"]["items"].get("anyOf", [])
                     if "path" in branch["properties"]}
    supplied = correction.get("edits", [])
    for edit in supplied if isinstance(supplied, list) else []:
        if isinstance(edit, Mapping) and "path" in edit and edit["path"] not in allowed_paths:
            raise CreditAnalysisError("corrective retry changed protected response field " + str(edit["path"]))
    _validate_holistic_transport_value(correction, edit_schema, "$correction")
    result = copy.deepcopy(dict(prior))
    seen: set[tuple[str, str]] = set()
    removals: list[str] = []
    withdrawals: dict[str, str] = {}
    review_dismissals: dict[str, str] = {}
    call_edits: dict[str, dict[str, Any]] = {}
    for edit in correction["edits"]:
        kind = next(
            key
            for key in (
                "path",
                "remove",
                "withdraw_finding",
                "dismiss_temporary_review",
                "call_id",
            )
            if key in edit
        )
        target = edit[kind]
        if (kind, target) in seen:
            raise CreditAnalysisError("corrective retry contains duplicate edit targets")
        seen.add((kind, target))
        if kind == "path":
            parts = _pointer_parts(target)
            if not parts:
                result = copy.deepcopy(edit["value"])
            else:
                parent = _at_pointer(result, _pointer(parts[:-1]))
                key = int(parts[-1]) if isinstance(parent, list) else parts[-1]
                parent[key] = copy.deepcopy(edit["value"])
        elif kind == "remove":
            removals.append(target)
        elif kind == "withdraw_finding":
            withdrawals[target] = edit["reason"]
        elif kind == "dismiss_temporary_review":
            review_dismissals[target] = _bounded_explanation(edit["reason"], 360)
        else:
            call_edits[target] = {key: edit[key] for key in ("classification", "reason_code", "rationale")}
    # Descending numeric indices retain the original address of every deletion.
    for path in sorted(removals, key=lambda item: [f"{int(part):020d}" if part.isdecimal() else part
                                                 for part in _pointer_parts(item)], reverse=True):
        parts = _pointer_parts(path)
        parent = _at_pointer(result, _pointer(parts[:-1]))
        del parent[int(parts[-1]) if isinstance(parent, list) else parts[-1]]
    draft = copy.deepcopy(result)
    if withdrawals:
        draft["confirmed_findings"] = [item for item in draft["confirmed_findings"] if item["id"] not in withdrawals]
        for decision in draft["candidate_decisions"]:
            reasons = [withdrawals[identity] for identity in decision["finding_ids"] if identity in withdrawals]
            if reasons:
                decision["reason"] = _bounded_explanation(
                    " ".join(dict.fromkeys(reasons)), 320
                )
        for review in draft["temporary_control_reviews"]:
            if review["finding_id"] in withdrawals:
                review["no_finding_reason"] = _bounded_explanation(
                    withdrawals[review["finding_id"]], 360
                )
        surviving = {call for item in draft["confirmed_findings"] if item["waste_kind"] == "model-calls"
                     for call in item["affected_call_ids"]}
        orphan_reasons = {call: withdrawals[item["id"]] for item in result["confirmed_findings"]
                          if item["id"] in withdrawals for call in item["affected_call_ids"] if call not in surviving}
        calls = _call_details(draft)
        for identity, reason in orphan_reasons.items():
            if identity in calls and calls[identity].get("classification") in {"avoidable_implemented", "avoidable_unimplemented"}:
                calls[identity].update(
                    classification="unassessed",
                    reason_code=None,
                    rationale=_bounded_explanation(reason, 240),
                )
        draft["call_classifications"] = [{"call_ids": [identity], **detail} for identity, detail in calls.items()]
    if review_dismissals:
        for review in draft["temporary_control_reviews"]:
            if review["id"] in review_dismissals:
                review["finding_id"] = None
                review["no_finding_reason"] = review_dismissals[review["id"]]
        retained_merges = []
        for merge in draft["temporary_control_merges"]:
            merge["review_ids"] = [
                identity
                for identity in merge["review_ids"]
                if identity not in review_dismissals
            ]
            if merge["review_ids"]:
                retained_merges.append(merge)
        draft["temporary_control_merges"] = retained_merges
    if call_edits:
        calls = _call_details(draft)
        for identity, detail in call_edits.items():
            if identity not in calls:
                raise CreditAnalysisError("corrective retry cannot introduce call coverage")
            calls[identity].update(detail)
        draft["call_classifications"] = [{"call_ids": [identity], **detail} for identity, detail in calls.items()]
    if withdrawals or review_dismissals or call_edits:
        reconstructed, _ = _correction_comparison_values(result, draft, schema, source_call_count)
        result = dict(reconstructed)
    actual_calls = _call_details(result)
    for identity, detail in call_edits.items():
        if any(actual_calls.get(identity, {}).get(key) != value for key, value in detail.items()):
            raise CreditAnalysisError("corrective retry call edit lacks a diagnosed conflict or unsupported withdrawal")
    for identity in withdrawals:
        if any(item["id"] == identity for item in result["confirmed_findings"]):
            raise CreditAnalysisError("corrective retry withdrawal changed its diagnosed basis")
    if review_dismissals:
        final_reviews = {
            item["id"]: item for item in result["temporary_control_reviews"]
        }
        for identity, reason in review_dismissals.items():
            review = final_reviews.get(identity)
            if (
                review is None
                or review.get("finding_id") is not None
                or review.get("no_finding_reason") != reason
            ):
                raise CreditAnalysisError(
                    "corrective retry temporary-review dismissal changed its diagnosed basis"
                )
    validate_response_correction(prior, result, schema, source_call_count)
    _validate_holistic_transport_value(result, schema, "$response")
    return result


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
    final_synthesis: bool = False,
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
                "description": "Evidence-supported frequency of affected similar runs; model-call findings must meet the 3% floor, rounded down against the frozen source-call count.",
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
    category_reviews = objects(
        closed(
            {
                "category": {"type": "string", "enum": contract["helper_categories"]},
                "applies": boolean(),
                "evidence_refs": aliases(evidence_aliases),
                "reason": string(320),
            }
        )
    )
    if final_synthesis:
        category_reviews.update(
            maxItems=0,
            description=(
                "Return an empty array. The controller copies accepted shard "
                "assessments and assembles the final category summaries."
            ),
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
        "helper_category_reviews": category_reviews,
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
        final_synthesis=task["phase"] == "sol-final",
    )
