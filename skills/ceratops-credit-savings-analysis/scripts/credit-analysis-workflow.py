#!/usr/bin/env python3
"""Own resumable single-thread and per-thread-batch credit analyses.

The primary workflow collects one selected session once, freezes shared causal
episodes and a finite Luna manifest, launches explicitly modeled analysis-only
Codex children, validates complete semantic coverage, runs one Sol confirmation
per public surface and one Sol synthesis, and retains
hashed prompts, evidence, results, telemetry, and the final report. The
controller performs deterministic orchestration and validation only; child
models make every semantic classification. Legacy direct-result commands remain
lower-level controller interfaces for validated callers and batch composition.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from types import ModuleType
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CONTRACT_PATH = SCRIPT_DIR / "credit-analysis-contract.json"
LEDGER_PATH = SCRIPT_DIR / "model-call-ledger.py"
STATE_SCHEMA = "ceratops-credit-analysis-state.v1"
CONTEXT_SCHEMA = "ceratops-credit-analysis-context.v1"
PASS_PACKET_SCHEMA = "ceratops-credit-analysis-pass-packet.v1"
FINAL_PACKET_SCHEMA = "ceratops-credit-analysis-final-packet.v1"
SURFACE_DECISION_SCHEMA = "ceratops-credit-analysis-surface-decision.v1"
SYNTHESIS_DECISION_SCHEMA = "ceratops-credit-analysis-synthesis-decision.v1"
INDEX_SCHEMA = "ceratops-credit-analysis-index-record.v1"
BATCH_STATE_SCHEMA = "ceratops-credit-analysis-batch-state.v1"
BATCH_INDEX_SCHEMA = "ceratops-credit-analysis-batch-index-record.v1"
ORCHESTRATION_STATE_SCHEMA = "ceratops-credit-analysis-orchestration-state.v3"
CHUNK_MANIFEST_SCHEMA = "ceratops-credit-analysis-chunk-manifest.v3"
LUNA_RESULT_SCHEMA = "ceratops-credit-analysis-luna-result.v3"
CONFIRMATION_RESULT_SCHEMA = "ceratops-credit-analysis-confirmation-result.v3"
LUNA_CHILD_RESULT_SCHEMA = "ceratops-credit-analysis-luna-child-result.v5"
CONFIRMATION_CHILD_RESULT_SCHEMA = (
    "ceratops-credit-analysis-confirmation-child-result.v4"
)
ORCHESTRATION_SYNTHESIS_SCHEMA = (
    "ceratops-credit-analysis-orchestration-synthesis.v3"
)
ORCHESTRATION_FINAL_SCHEMA = "ceratops-credit-analysis-orchestration-final.v3"
FORMATTED_EVIDENCE_SCHEMA = "ceratops-credit-analysis-formatted-evidence.v3"
CANONICAL_STATE_SCHEMA = "ceratops-credit-analysis-canonical-state.v1"
MODEL_TASK_SCHEMA = "ceratops-credit-analysis-model-task.v3"
MODEL_PROGRESS_SECONDS = 60
EVIDENCE_NARRATIVE_LIMIT = 1200
PASS_PACKET_CHAR_LIMIT = 29_500
SURFACE_PACKET_BUDGETS = {
    "helper-contracts": {"calls": 1_500, "reviews": 0, "users": 800, "outcomes": 500},
    "context-evidence": {"calls": 2_500, "reviews": 0, "users": 2_500, "outcomes": 500},
    "rework-validation": {"calls": 3_000, "reviews": 2_000, "users": 3_500, "outcomes": 750},
    "tool-flow": {"calls": 2_000, "reviews": 0, "users": 800, "outcomes": 500},
    "instruction-reasoning": {"calls": 2_000, "reviews": 2_500, "users": 3_000, "outcomes": 500},
}
STATE_VERSION = 1
BATCH_STATE_VERSION = 1
STATE_FIELDS = {
    "schema",
    "version",
    "analysis_id",
    "action",
    "mode",
    "mutation_authority",
    "surface_contract_version",
    "queue",
    "current_index",
    "pending",
    "completed",
    "source",
    "window",
    "evidence",
    "immutable_artifacts",
    "paths",
    "cleanup",
    "finalized",
    "final_result",
}
COMPLETED_FIELDS = {
    "ordinal",
    "surface_id",
    "pass_id",
    "path",
    "sha256",
    "content_hash",
    "candidate_call_ids",
    "context_path",
    "result_path",
}
REQUEST_FIELDS = {
    "schema",
    "action",
    "mode",
    "source",
    "window",
    "task_temp_root",
    "evidence_output",
    "pricing_profile",
    "expected_surface_contract_version",
    "mutation_authority",
}
SOURCE_ALLOWED_FIELDS = {"thread_id", "session", "current_thread", "thread_name"}
WINDOW_FIELDS = {"mode", "last_runs", "turn_ids"}
BATCH_REQUEST_FIELDS = {
    "schema",
    "action",
    "mode",
    "selector",
    "as_of",
    "task_temp_root",
    "manifest_output",
    "pricing_profile",
    "expected_surface_contract_version",
    "expected_source_selection_contract_version",
    "mutation_authority",
}
BATCH_SELECTOR_FIELDS = {"kind", "count", "days", "project"}
PROJECT_SELECTOR_FIELDS = {"kind", "value"}
BATCH_STATE_FIELDS = {
    "schema",
    "version",
    "batch_id",
    "phase",
    "action",
    "mode",
    "mutation_authority",
    "surface_contract_version",
    "source_selection_contract_version",
    "selector",
    "as_of",
    "source_index",
    "candidates",
    "candidate_index",
    "items",
    "exclusions",
    "current_index",
    "completed",
    "batch_summary",
    "paths",
    "immutable_artifacts",
    "cleanup",
    "finalized",
    "final_result",
}
BATCH_ITEM_FIELDS = {
    "ordinal",
    "thread_id",
    "thread_name",
    "updated_at",
    "project",
    "session",
    "source_fingerprint",
    "request_path",
    "state_path",
    "evidence_path",
    "final_result_path",
}
BATCH_COMPLETED_FIELDS = {
    "ordinal",
    "thread_id",
    "path",
    "sha256",
    "content_hash",
}
BATCH_SUMMARY_STATE_FIELDS = {
    "pass_id",
    "finding_fingerprint",
    "finding_ids",
    "context_path",
    "result_path",
    "context_sha256",
    "accepted",
}
BATCH_SUMMARY_ACCEPTED_FIELDS = {"path", "sha256", "content_hash"}
BATCH_SUMMARY_RESULT_FIELD_ORDER = (
    "batch_id",
    "pass_id",
    "finding_fingerprint",
    "artifact_paths",
    "groups",
)
BATCH_SUMMARY_RESULT_FIELDS = set(BATCH_SUMMARY_RESULT_FIELD_ORDER)
BATCH_SUMMARY_GROUP_FIELD_ORDER = (
    "id",
    "title",
    "producer_type",
    "owner",
    "finding_ids",
    "recommended_control",
    "material_variants",
    "confidence",
)
BATCH_SUMMARY_GROUP_FIELDS = set(BATCH_SUMMARY_GROUP_FIELD_ORDER)
SURFACE_RESULT_FIELDS = {
    "schema",
    "analysis_id",
    "pass_id",
    "surface_id",
    "evidence_fingerprint",
    "artifact_paths",
    "reviewed_candidate_call_ids",
    "confirmed_findings",
    "plausible_risks",
    "dismissed_candidates",
    "necessary_call_exclusions",
    "evidence_references",
    "helper_category_reviews",
    "remediation_groups",
}
FINDING_FIELDS = {
    "id",
    "title",
    "problem_summary",
    "waste_kind",
    "affected_call_ids",
    "evidence_refs",
    "evidence_narrative",
    "producer_type",
    "producer_owner",
    "proposed_durable_control",
    "implementation_status",
    "targeted_verification",
    "observed_avoidable_call_count",
    "recurrence",
    "confidence",
    "complexity",
    "one_time_implementation_cost",
    "helper_categories",
}
RECURRENCE_FIELDS = {
    "calls_saved_per_affected_run",
    "additional_recurring_calls_per_affected_run",
    "affected_similar_run_frequency",
    "affected_similar_run_frequency_range",
    "estimated_calls_saved_per_similar_run",
    "assumptions",
}
COST_FIELDS = {"estimated_model_calls", "description"}
RISK_FIELDS = {
    "id",
    "description",
    "observed_sequence",
    "competing_explanations",
    "missing_fact",
    "affected_call_ids",
    "evidence_refs",
    "verification_needed",
}
DISMISSAL_FIELDS = {"call_id", "reason"}
EXCLUSION_FIELDS = {"call_id", "reason_code", "reason"}
HELPER_REVIEW_FIELDS = {"category", "status", "finding_ids", "reason"}
REMEDIATION_FIELDS = {
    "owner",
    "finding_ids",
    "proposed_control",
    "targeted_verification",
}
SYNTHESIS_FIELDS = {
    "schema",
    "analysis_id",
    "pass_id",
    "surface_id",
    "evidence_fingerprint",
    "artifact_paths",
    "finding_order",
    "risk_order",
    "finding_dispositions",
    "classification_groups",
    "secondary_call_mappings",
    "producer_groups",
}
DISPOSITION_FIELDS = {"finding_id", "primary_call_ids", "secondary_call_ids"}
CLASSIFICATION_GROUP_FIELDS = {
    "classification",
    "inventory_positions",
    "primary_finding_id",
    "reason_code",
    "reason",
}
SECONDARY_FIELDS = {"call_id", "finding_ids"}
PRODUCER_GROUP_FIELDS = {
    "id",
    "producer_type",
    "owner",
    "finding_ids",
    "recommended_control",
    "targeted_verification",
}
SURFACE_DECISION_FIELDS = {
    "schema",
    "findings",
    "risks",
    "exclusions",
    "dismissal_reason",
}
DECISION_FINDING_FIELDS = {
    "id",
    "title",
    "problem_summary",
    "waste_kind",
    "affected_selectors",
    "additional_evidence_selectors",
    "evidence_narrative",
    "producer_type",
    "producer_owner",
    "proposed_durable_control",
    "implementation_status",
    "targeted_verification",
    "recurrence",
    "confidence",
    "complexity",
    "one_time_implementation_cost",
    "helper_categories",
}
DECISION_RECURRENCE_FIELDS = {
    "additional_recurring_calls_per_affected_run",
    "affected_similar_run_frequency",
    "affected_similar_run_frequency_range",
    "assumptions",
}
DECISION_RISK_FIELDS = {
    "id",
    "description",
    "observed_sequence",
    "competing_explanations",
    "missing_fact",
    "affected_selectors",
    "additional_evidence_selectors",
    "verification_needed",
}
DECISION_EXCLUSION_FIELDS = {"selectors", "reason_code", "reason"}
SYNTHESIS_DECISION_FIELDS = {
    "schema",
    "finding_order",
    "risk_order",
    "remaining_call_assessments",
}
SYNTHESIS_ASSESSMENT_FIELDS = {
    "cluster_ids",
    "classification",
    "reason_code",
    "reason",
}
CALL_SELECTOR_FIELDS = {"call_ids", "cluster_ids", "turn_id", "ranges"}
IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
ACTION_REFERENCE_RE = re.compile(r"`(references/[a-z0-9]+(?:-[a-z0-9]+)*\.md)`")
READ_SEARCH_TOKENS = (
    "read",
    "open",
    "find",
    "search",
    "list",
    "grep",
    "get-content",
    "view",
    "fetch",
    "query",
)


class CreditAnalysisError(RuntimeError):
    """One compact request, evidence, state, result, or integrity failure."""


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")


def _content_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_hash(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError as exc:
        raise CreditAnalysisError(f"could not hash {path.name}: {exc}") from exc
    return digest.hexdigest()


def _read_json(path: pathlib.Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CreditAnalysisError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise CreditAnalysisError(f"{label} must be a JSON object")
    return value


def _closed(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append("missing " + ", ".join(missing))
    if extra:
        details.append("unknown " + ", ".join(extra))
    raise CreditAnalysisError(f"{label} fields are invalid: {'; '.join(details)}")


def _allowed_fields(
    value: Mapping[str, Any],
    allowed: set[str],
    label: str,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CreditAnalysisError(
            f"{label} fields are invalid: unknown {', '.join(unknown)}"
        )


def _strings(
    value: Any,
    label: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or (not value and not allow_empty)
        or not all(isinstance(item, str) and item for item in value)
    ):
        qualifier = "string list" if allow_empty else "nonempty string list"
        raise CreditAnalysisError(f"{label} must be a {qualifier}")
    result = list(value)
    if len(result) != len(set(result)):
        raise CreditAnalysisError(f"{label} values must be unique")
    return result


def _positive_integers(value: Any, label: str) -> list[int]:
    if (
        not isinstance(value, list)
        or not value
        or not all(
            isinstance(item, int) and not isinstance(item, bool) and item > 0
            for item in value
        )
    ):
        raise CreditAnalysisError(f"{label} must be a nonempty positive-integer list")
    if len(value) != len(set(value)):
        raise CreditAnalysisError(f"{label} values must be unique")
    return list(value)


def _objects(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise CreditAnalysisError(f"{label} must be an object list")
    return list(value)


def _number(value: Any, label: str, *, minimum: float = 0) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < minimum
    ):
        raise CreditAnalysisError(f"{label} must be a finite number >= {minimum}")
    return float(value)


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or IDENTIFIER_RE.fullmatch(value) is None:
        raise CreditAnalysisError(f"{label} must be a lowercase identifier")
    return value


def _existing_file(value: Any, label: str) -> pathlib.Path:
    if not isinstance(value, str) or not value:
        raise CreditAnalysisError(f"{label} must be nonempty text")
    try:
        path = pathlib.Path(value).expanduser().resolve(strict=True)
    except OSError as exc:
        raise CreditAnalysisError(f"{label} does not exist: {value}") from exc
    if path.is_symlink() or not path.is_file():
        raise CreditAnalysisError(f"{label} must be a regular file")
    return path


def _existing_directory(value: Any, label: str) -> pathlib.Path:
    if not isinstance(value, str) or not value:
        raise CreditAnalysisError(f"{label} must be nonempty text")
    try:
        path = pathlib.Path(value).expanduser().resolve(strict=True)
    except OSError as exc:
        raise CreditAnalysisError(f"{label} does not exist: {value}") from exc
    if path.is_symlink() or not path.is_dir():
        raise CreditAnalysisError(f"{label} must be a real directory")
    return path


def _task_directory(value: Any, label: str) -> pathlib.Path:
    """Return the caller-selected directory, creating only its final component."""

    if not isinstance(value, str) or not value:
        raise CreditAnalysisError(f"{label} must be nonempty text")
    requested = pathlib.Path(value).expanduser()
    if requested.exists() or requested.is_symlink():
        return _existing_directory(value, label)
    if requested.name in {"", ".", ".."}:
        raise CreditAnalysisError(f"{label} must name a child directory")
    try:
        parent = requested.parent.resolve(strict=True)
    except OSError as exc:
        raise CreditAnalysisError(f"{label} parent does not exist: {value}") from exc
    if requested.parent.is_symlink() or not parent.is_dir():
        raise CreditAnalysisError(f"{label} parent must be a real directory")
    path = parent / requested.name
    try:
        path.mkdir()
    except FileExistsError:
        return _existing_directory(str(path), label)
    except OSError as exc:
        raise CreditAnalysisError(f"cannot create {label}: {value}") from exc
    return path.resolve(strict=True)


def _new_file(value: Any, label: str) -> pathlib.Path:
    if not isinstance(value, str) or not value:
        raise CreditAnalysisError(f"{label} must be nonempty text")
    path = pathlib.Path(value).expanduser().resolve()
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise CreditAnalysisError(f"{label} parent must be a real directory")
    if path.exists() or path.is_symlink():
        raise CreditAnalysisError(f"refusing to overwrite {label}: {path}")
    return path


def _atomic_write(path: pathlib.Path, payload: bytes, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise CreditAnalysisError(f"could not write {label}: {exc}") from exc
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_json(path: pathlib.Path, value: Any, label: str) -> None:
    _atomic_write(path, _canonical_bytes(value), label)


def _exclusive_json(path: pathlib.Path, value: Any, label: str) -> None:
    payload = _canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise CreditAnalysisError(f"refusing to overwrite {label}: {path}") from exc
    except OSError as exc:
        raise CreditAnalysisError(f"could not write {label}: {exc}") from exc


def _load_ledger() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ceratops_credit_model_call_ledger",
        LEDGER_PATH,
    )
    if spec is None or spec.loader is None:
        raise CreditAnalysisError("could not load model-call-ledger.py")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (ImportError, OSError, SyntaxError) as exc:
        raise CreditAnalysisError(f"could not import model-call-ledger.py: {exc}") from exc
    return module


def _action_title(action_id: str) -> str:
    return " ".join(part.capitalize() for part in action_id.split("-"))


def _load_contract() -> dict[str, Any]:
    contract = _read_json(CONTRACT_PATH, "surface contract")
    if contract.get("schema") != "ceratops-credit-analysis-contract.v1":
        raise CreditAnalysisError("unsupported surface contract schema")
    version = contract.get("surface_contract_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise CreditAnalysisError("surface contract version must be positive")
    source_version = contract.get("source_selection_contract_version")
    if (
        not isinstance(source_version, int)
        or isinstance(source_version, bool)
        or source_version < 1
    ):
        raise CreditAnalysisError("source selection contract version must be positive")
    source_selectors = _objects(
        contract.get("source_selectors"), "source selectors"
    )
    expected_source_selectors = [
        "current-thread",
        "thread-id",
        "session",
        "thread-name",
        "recent-threads",
        "recent-days",
    ]
    if [item.get("id") for item in source_selectors] != expected_source_selectors:
        raise CreditAnalysisError("source selectors do not match the fixed contract")
    for item in source_selectors:
        if set(item) != {"id", "cardinality"} or item.get("cardinality") not in {
            "single",
            "batch",
        }:
            raise CreditAnalysisError("source selector metadata is invalid")
    if contract.get("single_controller_commands") != [
        "prepare",
        "advance",
        "status",
        "finalize",
    ] or contract.get("end_to_end_controller_commands") != [
        "plan",
        "execute",
    ] or contract.get("batch_controller_commands") != [
        "prepare-batch",
        "advance-batch",
        "status-batch",
        "finalize-batch",
    ]:
        raise CreditAnalysisError("controller command contract is invalid")
    public = _objects(contract.get("public_actions"), "public actions")
    surfaces = _objects(contract.get("surfaces"), "surfaces")
    surface_order = _strings(contract.get("surface_order"), "surface order")
    full_queue = _strings(contract.get("full_queue"), "full queue")
    public_ids = [_identifier(item.get("id"), "public action id") for item in public]
    if public_ids != ["full-analysis", *surface_order]:
        raise CreditAnalysisError("public actions do not match the surface order")
    if [_identifier(item.get("id"), "surface id") for item in surfaces] != surface_order:
        raise CreditAnalysisError("surface metadata does not match surface order")
    if full_queue != [*surface_order, "synthesis"]:
        raise CreditAnalysisError("full queue must be the fixed surfaces plus synthesis")
    references: list[str] = []
    for item in public:
        if set(item) != {"id", "reference", "mode"}:
            raise CreditAnalysisError("public action metadata fields are invalid")
        reference = item.get("reference")
        if not isinstance(reference, str) or ACTION_REFERENCE_RE.fullmatch(
            f"`{reference}`"
        ) is None:
            raise CreditAnalysisError("public action reference is invalid")
        expected_mode = "full-analysis" if item["id"] == "full-analysis" else "standalone"
        if item.get("mode") != expected_mode:
            raise CreditAnalysisError(f"public action mode is invalid: {item['id']}")
        references.append(reference)
    if len(references) != len(set(references)):
        raise CreditAnalysisError("public action references must be unique")
    for item in surfaces:
        if set(item) != {"id", "reference", "candidate_selectors"}:
            raise CreditAnalysisError("surface metadata fields are invalid")
        if item["reference"] not in references:
            raise CreditAnalysisError(f"surface reference is not public: {item['id']}")
        _strings(item["candidate_selectors"], f"{item['id']} selectors")
    internal = _objects(contract.get("internal_phases"), "internal phases")
    if internal != [
        {"id": "synthesis", "public": False},
        {"id": "batch-summary", "public": False},
    ]:
        raise CreditAnalysisError("internal phases do not match the fixed contract")
    helper_categories = _strings(
        contract.get("helper_categories"), "helper categories"
    )
    if len(helper_categories) != 10:
        raise CreditAnalysisError("helper contract must declare exactly ten categories")

    skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    heading_matches = list(
        re.finditer(r"(?m)^### Action References\s*$", skill_text)
    )
    if len(heading_matches) != 1:
        raise CreditAnalysisError("parent skill must contain one Action References index")
    action_section = skill_text[heading_matches[0].end() :]
    next_heading = re.search(r"\n###? ", action_section)
    if next_heading:
        action_section = action_section[: next_heading.start()]
    indexed = ACTION_REFERENCE_RE.findall(action_section)
    if indexed != references:
        raise CreditAnalysisError("parent action references do not match the contract")
    for item in public:
        reference_path = SKILL_DIR / item["reference"]
        if not reference_path.is_file() or reference_path.is_symlink():
            raise CreditAnalysisError(f"action reference is missing: {item['reference']}")
        first_line = reference_path.read_text(encoding="utf-8").splitlines()[0]
        expected_title = f"# {_action_title(item['id'])} Action"
        if first_line != expected_title:
            raise CreditAnalysisError(f"action title is invalid: {item['reference']}")
    if (SKILL_DIR / "references" / "synthesis.md").exists():
        raise CreditAnalysisError("internal synthesis must not be a public reference")
    orchestration_schemas = {
        "canonical_state_schema": CANONICAL_STATE_SCHEMA,
        "orchestration_state_schema": ORCHESTRATION_STATE_SCHEMA,
        "chunk_manifest_schema": CHUNK_MANIFEST_SCHEMA,
        "luna_result_schema": LUNA_RESULT_SCHEMA,
        "confirmation_result_schema": CONFIRMATION_RESULT_SCHEMA,
        "orchestration_synthesis_schema": ORCHESTRATION_SYNTHESIS_SCHEMA,
        "orchestration_final_schema": ORCHESTRATION_FINAL_SCHEMA,
    }
    if any(contract.get(key) != value for key, value in orchestration_schemas.items()):
        raise CreditAnalysisError("orchestration schema contract is invalid")
    models = contract.get("models")
    if not isinstance(models, Mapping) or set(models) != {
        "luna",
        "confirmation",
        "synthesis",
    } or not all(isinstance(value, str) and value for value in models.values()):
        raise CreditAnalysisError("orchestration model contract is invalid")
    if contract.get("model_reasoning_effort") != "max":
        raise CreditAnalysisError("orchestration reasoning effort contract is invalid")
    semantic_calls = contract.get("semantic_call_contract")
    if semantic_calls != {
        "full_analysis_sol_calls": 6,
        "surface_confirmation_calls": 5,
        "synthesis_calls": 1,
        "bookkeeping_calls": 0,
    }:
        raise CreditAnalysisError("semantic call contract is invalid")
    chunking = contract.get("chunking")
    chunking_keys = {
        "target_chars",
        "maximum_chars",
        "maximum_candidates",
        "large_payload_inline_chars",
        "confirmation_packet_chars",
        "synthesis_packet_chars",
        "consolidation_fan_in",
        "maximum_luna_tasks",
        "maximum_semantic_tasks",
        "maximum_consolidation_depth",
        "confirmation_audit_fraction",
        "confirmation_audit_minimum",
    }
    integer_chunking_keys = chunking_keys - {"confirmation_audit_fraction"}
    if (
        not isinstance(chunking, Mapping)
        or set(chunking) != chunking_keys
        or any(
            not isinstance(chunking[key], int)
            or isinstance(chunking[key], bool)
            or chunking[key] < 1
            for key in integer_chunking_keys
        )
        or not isinstance(chunking["confirmation_audit_fraction"], (int, float))
        or isinstance(chunking["confirmation_audit_fraction"], bool)
        or not 0 < chunking["confirmation_audit_fraction"] <= 1
        or chunking["target_chars"] > chunking["maximum_chars"]
        or chunking["large_payload_inline_chars"] >= chunking["maximum_chars"]
        or chunking["consolidation_fan_in"] < 2
        or chunking["maximum_luna_tasks"] + semantic_calls["full_analysis_sol_calls"]
        > chunking["maximum_semantic_tasks"]
    ):
        raise CreditAnalysisError("orchestration chunking contract is invalid")
    if contract.get("luna_dispositions") != [
        "provisional-finding-evidence",
        "plausible-risk",
        "dismissed-candidate",
        "necessary-exclusion",
    ] or contract.get("confirmation_dispositions") != [
        "confirmed-finding",
        "plausible-risk",
        "dismissed-candidate",
        "necessary-exclusion",
    ] or contract.get("temporary_control_dispositions") != [
        "transient-by-design",
        "permanently-implemented",
        "run-only-useful",
        "durable-control-missing",
        "final-state-unclear",
    ]:
        raise CreditAnalysisError("orchestration disposition contract is invalid")
    return contract


def _request_source(
    raw: Any,
    ledger: ModuleType,
) -> tuple[dict[str, Any], pathlib.Path]:
    if not isinstance(raw, dict):
        raise CreditAnalysisError("source must be an object")
    _allowed_fields(raw, SOURCE_ALLOWED_FIELDS, "source")
    thread_id = raw.get("thread_id")
    session = raw.get("session")
    current_thread = raw.get("current_thread")
    thread_name = raw.get("thread_name")
    string_values = (thread_id, session, thread_name)
    if any(
        value not in (None, "") and not isinstance(value, str)
        for value in string_values
    ) or current_thread not in (None, False, True):
        raise CreditAnalysisError("source selector values are invalid")
    selected = sum(
        [
            isinstance(thread_id, str) and bool(thread_id),
            isinstance(session, str) and bool(session),
            current_thread is True,
            isinstance(thread_name, str) and bool(thread_name.strip()),
        ]
    )
    if selected != 1:
        raise CreditAnalysisError(
            "source must name exactly one thread ID, session, current thread, or thread name"
        )
    try:
        if isinstance(thread_id, str) and thread_id:
            canonical_id = ledger.canonical_thread_id(thread_id)
            resolved = ledger.resolve_thread_session(canonical_id)
            descriptor = {"kind": "thread_id", "value": canonical_id}
        elif isinstance(session, str) and session:
            resolved = pathlib.Path(str(session)).expanduser().resolve(strict=True)
            descriptor = {"kind": "session", "value": str(resolved)}
        elif current_thread is True:
            canonical_id, resolved = ledger.resolve_current_thread_source()
            descriptor = {"kind": "current_thread", "value": canonical_id}
        else:
            assert isinstance(thread_name, str)
            canonical_id, resolved, index_fingerprint = (
                ledger.resolve_named_thread_source(thread_name)
            )
            descriptor = {
                "kind": "thread_name",
                "value": thread_name.strip(),
                "thread_id": canonical_id,
                "thread_index_fingerprint": index_fingerprint,
            }
    except (OSError, ValueError, RuntimeError) as exc:
        raise CreditAnalysisError(f"could not resolve selected session: {exc}") from exc
    if resolved.is_symlink() or not resolved.is_file():
        raise CreditAnalysisError("selected session must be a regular file")
    return descriptor, resolved


def _request_window(raw: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(raw, dict):
        raise CreditAnalysisError("window must be an object")
    _closed(raw, WINDOW_FIELDS, "window")
    mode = raw.get("mode")
    last_runs = raw.get("last_runs")
    turn_ids = raw.get("turn_ids")
    if mode == "full_thread":
        if last_runs is not None or turn_ids != []:
            raise CreditAnalysisError("full_thread requires null last_runs and empty turn_ids")
        return dict(raw), {"last_runs": None, "completed_turn_ids": None}
    if mode == "last_runs":
        if (
            not isinstance(last_runs, int)
            or isinstance(last_runs, bool)
            or last_runs < 1
            or turn_ids != []
        ):
            raise CreditAnalysisError("last_runs requires a positive count and empty turn_ids")
        return dict(raw), {"last_runs": last_runs, "completed_turn_ids": None}
    if mode == "completed_turn_ids":
        if last_runs is not None:
            raise CreditAnalysisError("completed_turn_ids requires null last_runs")
        ids = _strings(turn_ids, "window turn_ids")
        return dict(raw), {"last_runs": None, "completed_turn_ids": ids}
    raise CreditAnalysisError("window mode is invalid")


def _validate_request(
    request_path: pathlib.Path,
    contract: dict[str, Any],
    ledger: ModuleType,
) -> dict[str, Any]:
    request = _read_json(request_path, "request")
    _closed(request, REQUEST_FIELDS, "request")
    if request.get("schema") != contract["request_schema"]:
        raise CreditAnalysisError(f"request schema must be {contract['request_schema']}")
    actions = {item["id"]: item for item in contract["public_actions"]}
    action = request.get("action")
    if action not in actions:
        raise CreditAnalysisError("request action is not public")
    mode = request.get("mode")
    if mode != actions[action]["mode"]:
        raise CreditAnalysisError("request action and mode do not match")
    if request.get("mutation_authority") is not False:
        raise CreditAnalysisError("mutation_authority must be false")
    if request.get("expected_surface_contract_version") != contract[
        "surface_contract_version"
    ]:
        raise CreditAnalysisError("surface contract version mismatch")
    source, session = _request_source(request.get("source"), ledger)
    window, collector_window = _request_window(request.get("window"))
    task_root = _task_directory(request.get("task_temp_root"), "task_temp_root")
    state_path = task_root / "state.json"
    evidence_path = _new_file(request.get("evidence_output"), "evidence output")
    findings_dir = task_root / "findings"
    index_path = task_root / "findings.jsonl"
    context_dir = task_root / "context"
    pending_dir = task_root / "pending"
    final_path = task_root / "final-machine-result.json"
    reserved = [state_path, findings_dir, index_path, context_dir, pending_dir, final_path]
    existing = [path for path in reserved if path.exists() or path.is_symlink()]
    if existing:
        raise CreditAnalysisError(f"task_temp_root already contains controller state: {existing[0].name}")
    if evidence_path in reserved:
        raise CreditAnalysisError("evidence output collides with a controller path")
    for transient_dir in (context_dir, pending_dir):
        try:
            evidence_path.relative_to(transient_dir)
        except ValueError:
            pass
        else:
            raise CreditAnalysisError("evidence output must not be transient")
    pricing_value = request.get("pricing_profile")
    pricing = None if pricing_value is None else _existing_file(pricing_value, "pricing profile")
    if pricing == evidence_path:
        raise CreditAnalysisError("pricing profile and evidence output must differ")
    queue = (
        list(contract["full_queue"])
        if mode == "full-analysis"
        else [str(action)]
    )
    return {
        "request": request,
        "request_path": request_path,
        "request_hash": _file_hash(request_path),
        "action": action,
        "mode": mode,
        "source": source,
        "session": session,
        "window": window,
        "collector_window": collector_window,
        "task_root": task_root,
        "state_path": state_path,
        "evidence_path": evidence_path,
        "pricing": pricing,
        "queue": queue,
        "paths": {
            "state": str(state_path),
            "findings_dir": str(findings_dir),
            "index": str(index_path),
            "context_dir": str(context_dir),
            "pending_dir": str(pending_dir),
            "final_result": str(final_path),
        },
    }


def _all_calls(evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    runs = evidence.get("runs")
    if not isinstance(runs, list):
        raise CreditAnalysisError("evidence runs are invalid")
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("calls"), list):
            raise CreditAnalysisError("evidence run calls are invalid")
        for call in run["calls"]:
            if not isinstance(call, dict):
                raise CreditAnalysisError("evidence call is invalid")
            calls.append(call)
    return calls


def _candidate_ids(
    surface_id: str,
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> list[str]:
    metadata = next(
        item for item in contract["surfaces"] if item["id"] == surface_id
    )
    selectors = set(metadata["candidate_selectors"])
    candidates: list[str] = []
    for call in _all_calls(evidence):
        tool_results = call.get("tool_results", [])
        semantic_actions = call.get("semantic_actions", [])
        names = [
            str(action.get("name", "")).casefold()
            for action in [*tool_results, *semantic_actions]
            if isinstance(action, dict)
        ]
        selected = "all-calls" in selectors
        selected |= "tool-action" in selectors and bool(tool_results)
        selected |= "read-search-action" in selectors and any(
            token in name for name in names for token in READ_SEARCH_TOKENS
        )
        selected |= "repeated-action" in selectors and any(
            bool(action.get("repeated")) for action in tool_results
        )
        selected |= "failure-retry-repeat" in selectors and any(
            bool(action.get("explicit_failure"))
            or bool(action.get("retry"))
            or bool(action.get("repeated"))
            for action in tool_results
        )
        if selected:
            candidates.append(str(call["call_id"]))
    return candidates


def _compact_call(call: Mapping[str, Any], *, semantic: bool) -> dict[str, Any]:
    semantic_actions = call.get("semantic_actions", [])
    compact_semantics = []
    for action in semantic_actions if isinstance(semantic_actions, list) else []:
        if not isinstance(action, dict):
            continue
        compact = {key: action[key] for key in ("kind", "name") if key in action}
        if semantic and "summary" in action:
            compact["summary"] = action["summary"]
        compact_semantics.append(compact)
    result = {
        "call_id": call["call_id"],
        "turn_id": call["turn_id"],
        "index": call["index"],
        "user_message_ids": call.get("user_message_ids", []),
        "model_review_record_ids": call.get("model_review_record_ids", []),
        "tokens": call["tokens"],
        "estimated_credit_cost": call.get("estimated_credit_cost"),
        "semantic_actions": compact_semantics,
        "tool_results": call.get("tool_results", []),
    }
    if semantic:
        result["timestamp"] = call.get("timestamp")
        result["actions"] = call.get("actions", [])
        result["run_duration_ms"] = call.get("run_duration_ms")
    return result


def _user_messages_for_calls(
    evidence: Mapping[str, Any],
    call_ids: list[str],
) -> list[dict[str, Any]]:
    """Return each formatted user message referenced by selected calls once."""

    selected = set(call_ids)
    required_message_ids: set[str] = set()
    for call in _all_calls(evidence):
        if call.get("call_id") not in selected:
            continue
        message_ids = call.get("user_message_ids", [])
        if not isinstance(message_ids, list) or not all(
            isinstance(message_id, str) for message_id in message_ids
        ):
            raise CreditAnalysisError("evidence user-message references are invalid")
        required_message_ids.update(message_ids)

    messages: list[dict[str, Any]] = []
    found: set[str] = set()
    runs = evidence.get("runs")
    if not isinstance(runs, list):
        raise CreditAnalysisError("evidence runs are invalid")
    for run in runs:
        if not isinstance(run, dict) or not isinstance(
            run.get("user_messages"), list
        ):
            raise CreditAnalysisError("evidence user messages are invalid")
        for message in run["user_messages"]:
            if not isinstance(message, dict):
                raise CreditAnalysisError("evidence user message is invalid")
            message_id = message.get("message_id")
            if message_id in required_message_ids:
                messages.append(message)
                found.add(str(message_id))
    if found != required_message_ids:
        raise CreditAnalysisError("evidence user-message reference is missing")
    return messages


def _model_review_records_for_calls(
    evidence: Mapping[str, Any],
    call_ids: list[str],
    focused_runs: set[str],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Project retained prepared records without discarding full disk evidence."""

    model_review = evidence.get("model_review")
    if not isinstance(model_review, Mapping):
        raise CreditAnalysisError("model-review evidence is invalid")
    preparation = model_review.get("preparation")
    exclusions = model_review.get("excluded_by_design")
    records = model_review.get("records")
    global_ids = model_review.get("global_record_ids")
    if not isinstance(preparation, dict) or not isinstance(exclusions, dict):
        raise CreditAnalysisError("model-review evidence contract is invalid")
    if not isinstance(records, list) or not isinstance(global_ids, list):
        raise CreditAnalysisError("model-review evidence records are invalid")

    selected_calls = set(call_ids)
    required_ids = set(global_ids)
    for call in _all_calls(evidence):
        if call.get("call_id") not in selected_calls:
            continue
        record_ids = call.get("model_review_record_ids")
        if not isinstance(record_ids, list) or not all(
            isinstance(record_id, str) for record_id in record_ids
        ):
            raise CreditAnalysisError("model-review call references are invalid")
        required_ids.update(record_ids)

    projected: list[dict[str, Any]] = []
    found_ids: set[str] = set()
    all_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise CreditAnalysisError("model-review record is invalid")
        record_id = record.get("record_id")
        if not isinstance(record_id, str) or record_id in all_ids:
            raise CreditAnalysisError("model-review record ID is invalid")
        all_ids.add(record_id)
        if record_id not in required_ids:
            continue
        required_fields = {
            "available_to_model_call_index",
            "call_id",
            "content",
            "content_hash",
            "kind",
            "model_call_index",
            "name",
            "prepared_chars",
            "preview",
            "preview_truncated",
            "record_id",
            "source_chars",
            "timestamp",
            "turn_id",
        }
        if set(record) != required_fields:
            raise CreditAnalysisError("model-review record fields are invalid")
        turn_id = record["turn_id"]
        prepared_chars = record["prepared_chars"]
        if not isinstance(prepared_chars, int) or prepared_chars < 0:
            raise CreditAnalysisError("model-review record size is invalid")
        content_limit = 4000 if turn_id in focused_runs else 1200
        include_full = prepared_chars <= content_limit
        compact = {
            key: value
            for key, value in record.items()
            if key not in {"content", "preview", "preview_truncated"}
        }
        compact["evidence_ref"] = f"evidence://review/{record_id}"
        model_call_index = record["model_call_index"]
        compact["model_call_id"] = (
            f"{turn_id}:{model_call_index}"
            if isinstance(turn_id, str)
            and isinstance(model_call_index, int)
            and not isinstance(model_call_index, bool)
            else None
        )
        compact["context_content"] = (
            record["content"] if include_full else record["preview"]
        )
        compact["context_content_mode"] = "full" if include_full else "preview"
        compact["full_content_retained"] = True
        projected.append(compact)
        found_ids.add(record_id)
    if found_ids != required_ids:
        raise CreditAnalysisError("model-review record reference is missing")
    return dict(preparation), projected, dict(exclusions)


def _accepted_payloads(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for record in state.get("completed", []):
        path = pathlib.Path(record["path"])
        results.append(_read_json(path, f"accepted {record['surface_id']} result"))
    return results


def _open_pending(
    state: dict[str, Any],
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> None:
    index = state["current_index"]
    if index >= len(state["queue"]):
        state["pending"] = None
        return
    surface_id = state["queue"][index]
    ordinal = index + 1
    pass_id = f"{state['analysis_id']}.{ordinal:03d}.{secrets.token_hex(8)}"
    context_path = pathlib.Path(state["paths"]["context_dir"]) / (
        f"{ordinal:03d}-{surface_id}.json"
    )
    result_path = pathlib.Path(state["paths"]["pending_dir"]) / (
        f"{ordinal:03d}-{surface_id}.json"
    )
    if context_path.exists() or result_path.exists():
        raise CreditAnalysisError("pending artifact path already exists")
    if surface_id == "synthesis":
        accepted = _accepted_payloads(state)
        context = {
            "schema": CONTEXT_SCHEMA,
            "analysis_id": state["analysis_id"],
            "pass_id": pass_id,
            "surface_id": surface_id,
            "internal": True,
            "evidence_fingerprint": state["evidence"]["fingerprint"],
            "surface_contract_version": state["surface_contract_version"],
            "action_reference": None,
            "candidate_call_ids": list(evidence["call_inventory"]),
            "call_inventory": [
                {
                    "inventory_position": position,
                    **_compact_call(call, semantic=False),
                }
                for position, call in enumerate(_all_calls(evidence), start=1)
            ],
            "classification_group_contract": {
                "fields": sorted(CLASSIFICATION_GROUP_FIELDS),
                "position_base": 1,
                "coverage": "every-inventory-position-once",
                "semantic_scope": "group-level-approximate",
                "classifications": list(contract["call_classifications"]),
                "necessary_reason_codes": list(
                    contract["necessary_reason_codes"]
                ),
            },
            "accepted_surface_results": accepted,
            "deterministic_totals": evidence["totals"],
            "pricing": evidence["pricing"],
            "artifact_paths": {
                "state": state["paths"]["state"],
                "evidence": state["evidence"]["path"],
                "context": str(context_path),
                "result": str(result_path),
            },
        }
        candidates = list(evidence["call_inventory"])
    else:
        candidates = _candidate_ids(surface_id, evidence, contract)
        focused_runs = set(evidence["semantic_coverage"]["run_ids"])
        candidate_set = set(candidates)
        review_preparation, review_records, review_exclusions = (
            _model_review_records_for_calls(evidence, candidates, focused_runs)
        )
        context = {
            "schema": CONTEXT_SCHEMA,
            "analysis_id": state["analysis_id"],
            "pass_id": pass_id,
            "surface_id": surface_id,
            "internal": False,
            "evidence_fingerprint": state["evidence"]["fingerprint"],
            "surface_contract_version": state["surface_contract_version"],
            "action_reference": next(
                item["reference"]
                for item in contract["surfaces"]
                if item["id"] == surface_id
            ),
            "candidate_call_ids": candidates,
            "focused_run_ids": list(focused_runs),
            "user_messages": _user_messages_for_calls(evidence, candidates),
            "model_review_preparation": review_preparation,
            "model_review_records": review_records,
            "model_review_exclusions": review_exclusions,
            "candidate_evidence": [
                _compact_call(
                    call,
                    semantic=call["turn_id"] in focused_runs,
                )
                for call in _all_calls(evidence)
                if call["call_id"] in candidate_set
            ],
            "complete_call_inventory": [
                _compact_call(call, semantic=False) for call in _all_calls(evidence)
            ],
            "artifact_paths": {
                "state": state["paths"]["state"],
                "evidence": state["evidence"]["path"],
                "context": str(context_path),
                "result": str(result_path),
            },
        }
    _exclusive_json(context_path, context, "pending context")
    state["pending"] = {
        "ordinal": ordinal,
        "surface_id": surface_id,
        "pass_id": pass_id,
        "candidate_call_ids": candidates,
        "context_path": str(context_path),
        "result_path": str(result_path),
    }
    state["cleanup"]["transient_paths"].extend(
        [str(context_path), str(result_path)]
    )


def _public_status(state: Mapping[str, Any]) -> dict[str, Any]:
    pending = state.get("pending")
    if state.get("finalized") is True:
        return {
            "analysis_id": state["analysis_id"],
            "complete": True,
            "state_path": state["paths"]["state"],
            "evidence_path": state["evidence"]["path"],
            "final_result_path": state["final_result"]["path"],
        }
    if isinstance(pending, Mapping):
        return {
            "analysis_id": state["analysis_id"],
            "pending_surface": pending["surface_id"],
            "pass_id": pending["pass_id"],
            "state_path": state["paths"]["state"],
            "evidence_path": state["evidence"]["path"],
            "context_path": pending["context_path"],
            "required_result_path": pending["result_path"],
        }
    accepted_path = state["completed"][-1]["path"] if state["completed"] else None
    return {
        "analysis_id": state["analysis_id"],
        "pending_surface": None,
        "ready_to_finalize": True,
        "state_path": state["paths"]["state"],
        "evidence_path": state["evidence"]["path"],
        "required_result_path": accepted_path,
    }


def _truncate_text(value: Any, limit: int) -> Any:
    """Bound prepared semantic text while retaining exact disk evidence."""

    if not isinstance(value, str) or len(value) <= limit:
        return value
    return value[:limit] + f"...[{len(value) - limit} chars retained on disk]"


def _bounded_value(value: Any, *, text_limit: int) -> Any:
    if isinstance(value, str):
        return _truncate_text(value, text_limit)
    if isinstance(value, list):
        return [_bounded_value(item, text_limit=text_limit) for item in value]
    if isinstance(value, dict):
        return {
            key: _bounded_value(item, text_limit=text_limit)
            for key, item in value.items()
        }
    return value


def _integer_ranges(values: Sequence[int]) -> list[list[int]]:
    ordered = sorted(set(values))
    if not ordered:
        return []
    ranges: list[list[int]] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append([start, previous])
        start = previous = value
    ranges.append([start, previous])
    return ranges


def _call_signal_score(call: Mapping[str, Any], focused_runs: set[str]) -> int:
    score = 5 if call.get("turn_id") in focused_runs else 0
    tokens = call.get("tokens")
    if isinstance(tokens, Mapping):
        total = tokens.get("total_tokens")
        if isinstance(total, int) and not isinstance(total, bool):
            score += min(total // 5_000, 20)
    for action in call.get("tool_results", []):
        if not isinstance(action, Mapping):
            continue
        outcomes = action.get("outcomes")
        if isinstance(outcomes, Mapping):
            score += 120 * int(bool(outcomes.get("nonzero_process_result")))
            score += 120 * int(bool(outcomes.get("structured_tool_error")))
            score += 100 * int(bool(outcomes.get("timeout")))
            score += 100 * int(bool(outcomes.get("termination")))
        score += 80 * int(bool(action.get("explicit_failure")))
        score += 60 * int(bool(action.get("retry")))
        score += 40 * int(bool(action.get("repeated")))
        name = str(action.get("name", "")).casefold()
        if any(token in name for token in ("wait", "poll", "write_stdin")):
            score += 35
        result_chars = action.get("result_chars")
        if isinstance(result_chars, int) and result_chars >= 20_000:
            score += min(result_chars // 2_000, 50)
        argument_chars = action.get("argument_chars")
        if isinstance(argument_chars, int) and argument_chars >= 4_000:
            score += min(argument_chars // 1_000, 20)
    return score


def _json_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _budgeted_values(
    values: Sequence[Any],
    *,
    text_limit: int,
    character_budget: int,
) -> list[Any]:
    """Retain the highest-priority prepared values within one packet budget."""

    included: list[Any] = []
    used = 2
    for value in values:
        bounded = _bounded_value(value, text_limit=text_limit)
        size = _json_chars(bounded) + int(bool(included))
        if used + size > character_budget:
            continue
        included.append(bounded)
        used += size
    return included


def _packet_call(call: Mapping[str, Any], focused_runs: set[str]) -> dict[str, Any]:
    semantics: list[dict[str, Any]] = []
    for raw in call.get("semantic_actions", []):
        if not isinstance(raw, Mapping):
            continue
        semantics.append(
            {
                key: _truncate_text(raw[key], 700)
                for key in ("kind", "name", "summary")
                if key in raw
            }
        )
    tool_results = []
    for raw in call.get("tool_results", []):
        if not isinstance(raw, Mapping):
            continue
        tool_results.append(
            {
                key: raw[key]
                for key in (
                    "name",
                    "repeated",
                    "retry",
                    "explicit_failure",
                    "argument_chars",
                    "result_chars",
                    "duration_ms",
                    "outcomes",
                )
                if key in raw
            }
        )
    return {
        "call_id": call["call_id"],
        "turn_id": call["turn_id"],
        "index": call["index"],
        "signal_score": _call_signal_score(call, focused_runs),
        "tokens": call["tokens"],
        "semantic_actions": semantics,
        "tool_results": tool_results,
        "user_message_ids": call.get("user_message_ids", []),
        "run_duration_ms": call.get("run_duration_ms"),
    }


def _detail_packet_calls(
    candidates: Sequence[str],
    call_by_id: Mapping[str, Mapping[str, Any]],
    focused_runs: set[str],
    *,
    character_budget: int,
) -> list[dict[str, Any]]:
    """Select extra high-signal detail by packet size, not as a coverage proxy."""

    positions = {call_id: index for index, call_id in enumerate(candidates)}
    by_turn: defaultdict[str, list[str]] = defaultdict(list)
    for call_id in candidates:
        by_turn[str(call_by_id[call_id]["turn_id"])].append(call_id)
    boundaries = {
        call_id
        for turn_calls in by_turn.values()
        for call_id in (turn_calls[0], turn_calls[-1])
    }
    ranked = sorted(
        candidates,
        key=lambda call_id: (
            -_call_signal_score(call_by_id[call_id], focused_runs),
            -int(call_id in boundaries),
            positions[call_id],
        ),
    )
    prepared = [
        _packet_call(call_by_id[call_id], focused_runs) for call_id in ranked
    ]
    included = _budgeted_values(
        prepared,
        text_limit=700,
        character_budget=character_budget,
    )
    selected = {str(call["call_id"]) for call in included}
    return [
        _packet_call(call_by_id[call_id], focused_runs)
        for call_id in candidates
        if call_id in selected
    ]


def _size_band(value: Any) -> str:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return "unknown"
    if value == 0:
        return "zero"
    if value < 1_000:
        return "under-1k"
    if value < 20_000:
        return "1k-20k"
    if value < 100_000:
        return "20k-100k"
    return "100k-plus"


def _observable_call_signature(
    call: Mapping[str, Any],
) -> dict[str, Any]:
    """Describe only mechanically observable traits; this is not a judgment."""

    semantic_actions = sorted(
        {
            ":".join(
                part
                for part in (
                    str(action.get("kind", "unknown")),
                    str(action.get("name", "unknown")),
                )
                if part
            )
            for action in call.get("semantic_actions", [])
            if isinstance(action, Mapping)
        }
    )
    tool_names: set[str] = set()
    signals: set[str] = set()
    argument_chars = 0
    result_chars = 0
    for action in call.get("tool_results", []):
        if not isinstance(action, Mapping):
            continue
        name = str(action.get("name", "unknown"))
        tool_names.add(name)
        lowered = name.casefold()
        if any(token in lowered for token in ("wait", "poll", "write_stdin")):
            signals.add("wait-or-poll")
        for key, label in (
            ("repeated", "repeated"),
            ("retry", "retry"),
            ("explicit_failure", "explicit-failure"),
        ):
            if action.get(key):
                signals.add(label)
        outcomes = action.get("outcomes")
        if isinstance(outcomes, Mapping):
            for key, label in (
                ("nonzero_process_result", "nonzero-process-result"),
                ("structured_tool_error", "structured-tool-error"),
                ("timeout", "timeout"),
                ("termination", "termination"),
            ):
                if outcomes.get(key):
                    signals.add(label)
        raw_argument_chars = action.get("argument_chars")
        if isinstance(raw_argument_chars, int) and not isinstance(
            raw_argument_chars, bool
        ):
            argument_chars += max(raw_argument_chars, 0)
        raw_result_chars = action.get("result_chars")
        if isinstance(raw_result_chars, int) and not isinstance(
            raw_result_chars, bool
        ):
            result_chars += max(raw_result_chars, 0)
    return {
        "semantic_actions": semantic_actions,
        "tools": sorted(tool_names),
        "signals": sorted(signals),
        "argument_size": _size_band(argument_chars),
        "result_size": _size_band(result_chars),
    }


def _cluster_representative(
    call: Mapping[str, Any],
    focused_runs: set[str],
) -> dict[str, Any]:
    summaries: list[str] = []
    for action in call.get("semantic_actions", []):
        if not isinstance(action, Mapping):
            continue
        label = ":".join(
            str(action[key]) for key in ("kind", "name") if key in action
        )
        summary = str(_truncate_text(action.get("summary", ""), 100))
        summaries.append(f"{label} - {summary}" if summary else label)
    representative = {
        "call_id": call["call_id"],
        "signal_score": _call_signal_score(call, focused_runs),
        "summary": " | ".join(summaries[:2]),
    }
    return representative


def _cluster_token_totals(members: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Aggregate recorded usage without inferring whether the usage was waste."""

    totals = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "uncached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
    }
    for call in members:
        tokens = call.get("tokens")
        if not isinstance(tokens, Mapping):
            continue
        values: dict[str, int] = {}
        for name in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
            "total_tokens",
        ):
            value = tokens.get(name)
            values[name] = (
                value
                if isinstance(value, int) and not isinstance(value, bool) and value > 0
                else 0
            )
            totals[name] += values[name]
        totals["uncached_input_tokens"] += max(
            values["input_tokens"] - values["cached_input_tokens"], 0
        )
    return totals


def _cluster_tool_totals(members: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Aggregate emitted tool volume and mechanically recorded outcome signals."""

    totals = {
        "tool_calls": 0,
        "argument_chars": 0,
        "result_chars": 0,
        "failures": 0,
        "retries": 0,
        "repeats": 0,
        "waits_or_polls": 0,
    }
    for call in members:
        for action in call.get("tool_results", []):
            if not isinstance(action, Mapping):
                continue
            totals["tool_calls"] += 1
            for source, target in (
                ("argument_chars", "argument_chars"),
                ("result_chars", "result_chars"),
            ):
                value = action.get(source)
                if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                    totals[target] += value
            outcomes = action.get("outcomes")
            totals["failures"] += int(
                bool(action.get("explicit_failure"))
                or (
                    isinstance(outcomes, Mapping)
                    and any(
                        outcomes.get(name)
                        for name in (
                            "nonzero_process_result",
                            "structured_tool_error",
                            "timeout",
                            "termination",
                        )
                    )
                )
            )
            totals["retries"] += int(bool(action.get("retry")))
            totals["repeats"] += int(bool(action.get("repeated")))
            name = str(action.get("name", "")).casefold()
            totals["waits_or_polls"] += int(
                any(token in name for token in ("wait", "poll", "write_stdin"))
            )
    return totals


def _candidate_cluster_partition(
    candidates: Sequence[str],
    evidence: Mapping[str, Any],
    focused_runs: set[str],
) -> list[dict[str, Any]]:
    """Partition candidates across turns by coarse observable behavior.

    The internal call mapping is never printed. Model decisions select the stable
    cluster IDs, and the controller expands them from the retained evidence.
    """

    call_by_id = {str(call["call_id"]): call for call in _all_calls(evidence)}
    if any(call_id not in call_by_id for call_id in candidates):
        raise CreditAnalysisError("candidate cluster input references an unknown call")
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    signatures: dict[str, dict[str, Any]] = {}
    for call_id in candidates:
        call = call_by_id[call_id]
        signature = _observable_call_signature(call)
        key = json.dumps(signature, sort_keys=True, separators=(",", ":"))
        grouped.setdefault(key, []).append(call)
        signatures[key] = signature

    partitions: list[dict[str, Any]] = []
    covered: list[str] = []
    cluster_ids: set[str] = set()
    for key, members in grouped.items():
        cluster_id = "cluster-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        if cluster_id in cluster_ids:
            raise CreditAnalysisError("candidate cluster ID collision")
        cluster_ids.add(cluster_id)
        representative = max(
            members,
            key=lambda call: (
                _call_signal_score(call, focused_runs),
                -int(call["index"]),
            ),
        )
        call_ids = [str(call["call_id"]) for call in members]
        covered.extend(call_ids)
        turn_ids = {str(call["turn_id"]) for call in members}
        token_totals = _cluster_token_totals(members)
        tool_totals = _cluster_tool_totals(members)
        summary = {
            "cluster_id": cluster_id,
            "call_count": len(members),
            "turn_count": len(turn_ids),
            "observable_signature": signatures[key],
            "volume": {
                "input_tokens": token_totals["input_tokens"],
                "cached_input_tokens": token_totals["cached_input_tokens"],
                "uncached_input_tokens": token_totals["uncached_input_tokens"],
                "output_tokens": token_totals["output_tokens"],
                "tool_argument_chars": tool_totals["argument_chars"],
                "tool_result_chars": tool_totals["result_chars"],
            },
            "event_counts": {
                name: tool_totals[name]
                for name in (
                    "failures",
                    "retries",
                    "repeats",
                    "waits_or_polls",
                )
                if tool_totals[name]
            },
            "representative_summary": _truncate_text(
                _cluster_representative(representative, focused_runs)["summary"],
                140,
            ),
            "representative_call_id": representative["call_id"],
        }
        partitions.append(
            {"cluster_id": cluster_id, "call_ids": call_ids, "summary": summary}
        )
    if len(covered) != len(candidates) or set(covered) != set(candidates):
        raise CreditAnalysisError("candidate clusters do not partition the queue")
    return partitions


def _candidate_clusters(
    candidates: Sequence[str],
    evidence: Mapping[str, Any],
    focused_runs: set[str],
    *,
    include_representative: bool = False,
) -> list[dict[str, Any]]:
    """Return only model-facing cluster summaries, never the complete call map."""

    summaries = [
        dict(partition["summary"])
        for partition in _candidate_cluster_partition(
            candidates, evidence, focused_runs
        )
    ]
    if not include_representative:
        for summary in summaries:
            summary.pop("representative_summary", None)
            summary.pop("representative_call_id", None)
    return summaries


def _surface_cluster_summary(
    surface_id: str, cluster: Mapping[str, Any]
) -> dict[str, Any]:
    """Project each cluster to the evidence fields relevant to one surface."""

    signature = cluster["observable_signature"]
    volume = cluster["volume"]
    summary: dict[str, Any] = {
        "cluster_id": cluster["cluster_id"],
        "call_count": cluster["call_count"],
        "turn_count": cluster["turn_count"],
        "semantic_actions": signature["semantic_actions"],
        "signals": signature["signals"],
    }
    if surface_id in {"helper-contracts", "tool-flow"}:
        summary.update(
            {
                "tools": signature["tools"],
                "argument_size": signature["argument_size"],
                "result_size": signature["result_size"],
            }
        )
    if surface_id == "context-evidence":
        summary.update(
            {
                "input_tokens": volume["input_tokens"],
                "cached_input_tokens": volume["cached_input_tokens"],
                "uncached_input_tokens": volume["uncached_input_tokens"],
            }
        )
    if surface_id == "tool-flow":
        summary.update(
            {
                "tool_argument_chars": volume["tool_argument_chars"],
                "tool_result_chars": volume["tool_result_chars"],
            }
        )
    if surface_id in {"helper-contracts", "rework-validation", "tool-flow"} and cluster[
        "event_counts"
    ]:
        summary["event_counts"] = cluster["event_counts"]
    representative = cluster.get("representative_summary")
    if representative:
        summary["representative_summary"] = representative
        summary["representative_call_id"] = cluster["representative_call_id"]
    return summary


def _volume_hotspot_ids(
    clusters: Sequence[Mapping[str, Any]],
    *,
    kind: str,
    limit: int = 12,
) -> list[str]:
    """Order cluster IDs by recorded volume without duplicating cluster payloads."""

    if kind not in {"input", "output"}:
        raise CreditAnalysisError("volume hotspot kind is invalid")

    def score(cluster: Mapping[str, Any]) -> int:
        if kind == "input":
            return int(cluster["volume"]["uncached_input_tokens"])
        return int(cluster["volume"]["output_tokens"]) + int(
            cluster["volume"]["tool_result_chars"]
        )

    ranked = sorted(
        clusters,
        key=lambda cluster: (-score(cluster), str(cluster["cluster_id"])),
    )
    return [str(cluster["cluster_id"]) for cluster in ranked[:limit] if score(cluster) > 0]


def _compact_synthesis_cluster(
    cluster: Mapping[str, Any],
    *,
    keep_representative: bool,
) -> dict[str, Any]:
    """Project one full cluster into the smallest synthesis-useful record."""

    signature = cluster["observable_signature"]
    volume = cluster["volume"]
    compact = {
        "cluster_id": cluster["cluster_id"],
        "call_count": cluster["call_count"],
        "semantic_actions": signature["semantic_actions"],
        "tools": signature["tools"],
        "signals": signature["signals"],
        "argument_size": signature["argument_size"],
        "result_size": signature["result_size"],
        "input_tokens": volume["input_tokens"],
        "uncached_input_tokens": volume["uncached_input_tokens"],
        "output_tokens": volume["output_tokens"],
        "tool_result_chars": volume["tool_result_chars"],
    }
    if cluster["event_counts"]:
        compact["event_counts"] = cluster["event_counts"]
    representative = cluster.get("representative_summary")
    if keep_representative and representative:
        compact["representative_summary"] = representative
    return compact


def _run_outcome_calls(
    evidence: Mapping[str, Any],
    focused_runs: set[str],
    *,
    recent_limit: int = 5,
) -> list[dict[str, Any]]:
    """Expose each focused or recent run's last call to prevent stale findings."""

    ordered_turns: list[str] = []
    last_by_turn: dict[str, Mapping[str, Any]] = {}
    for call in _all_calls(evidence):
        turn_id = str(call["turn_id"])
        if turn_id not in last_by_turn:
            ordered_turns.append(turn_id)
        last_by_turn[turn_id] = call
    selected_turns = focused_runs | set(ordered_turns[-recent_limit:])
    return [
        {
            "turn_id": turn_id,
            **_cluster_representative(last_by_turn[turn_id], focused_runs),
        }
        for turn_id in ordered_turns
        if turn_id in selected_turns
    ]


def _surface_decision_contract(
    surface_id: str,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    template: dict[str, Any] = {
        "schema": SURFACE_DECISION_SCHEMA,
        "findings": [],
        "risks": [],
        "exclusions": [],
        "dismissal_reason": "State why remaining candidates do not confirm this surface's waste.",
    }
    return {
        "template": template,
        "selector_forms": [
            {"cluster_ids": ["exact-cluster-id"]},
            {"call_ids": ["exact-call-id"]},
            {"turn_id": "exact-turn-id", "ranges": [[1, 3], [7, 7]]},
        ],
        "cluster_rule": (
            "Review every candidate cluster. Select a cluster ID only when the "
            "judgment applies to every mapped call; otherwise select the supported "
            "exact calls or turn ranges. Clusters describe observable similarity and "
            "are not deterministic classifications."
        ),
        "computed_by_controller": [
            "identity and artifact paths",
            "affected call expansion and evidence references",
            "observed and expected savings arithmetic",
            "candidate dismissals and exact coverage",
            "helper category reviews and owner remediation groups",
            "persistence, advancement, cleanup, and final rendering",
        ],
        "surface_specific_note": (
            "Findings on helper-contracts must list every applicable helper category."
            if surface_id == "helper-contracts"
            else "Keep helper_categories empty outside helper-contracts."
        ),
        "producer_types": list(contract["producer_types"]),
        "implementation_statuses": list(contract["implementation_statuses"]),
        "evidence_narrative_limit": EVIDENCE_NARRATIVE_LIMIT,
        "evidence_narrative_note": (
            "State the concrete observed evidence without exact call IDs, controller "
            "paths, or bookkeeping fields."
        ),
        "all_fields_required_no_extras": True,
        "field_shapes": {
            "finding": {
                "identifier": ["id"],
                "nonempty_strings": [
                    "title",
                    "problem_summary",
                    "evidence_narrative",
                    "proposed_durable_control",
                ],
                "producer_owner": "nonempty string; null only when producer_type is unknown",
                "selector_lists": {
                    "affected_selectors": "min 1",
                    "additional_evidence_selectors": "may be empty",
                },
                "targeted_verification": "string list; min 1",
                "helper_categories": "enum list; helper-contracts min 1, other surfaces empty",
                "confidence": "number 0..1",
                "enums": {
                    "waste_kind": list(contract["waste_kinds"]),
                    "producer_type": list(contract["producer_types"]),
                    "implementation_status": list(contract["implementation_statuses"]),
                    "complexity": list(contract["complexities"]),
                    "helper_categories": list(contract["helper_categories"]),
                },
                "recurrence": {
                    "additional_recurring_calls_per_affected_run": "number >= 0",
                    "affected_similar_run_frequency": "number 0..1",
                    "affected_similar_run_frequency_range": "two numbers low <= frequency <= high, all 0..1",
                    "assumptions": "string list; min 1",
                },
                "one_time_implementation_cost": {
                    "estimated_model_calls": "number >= 0",
                    "description": "nonempty string",
                },
            },
            "risk": {
                "identifier": ["id"],
                "nonempty_strings": ["description", "observed_sequence", "missing_fact"],
                "competing_explanations": "string list; min 2",
                "verification_needed": "string list; min 1",
                "selector_lists": {
                    "affected_selectors": "min 1",
                    "additional_evidence_selectors": "may be empty",
                },
            },
            "exclusion": {
                "selectors": "selector list; min 1",
                "reason_code": list(contract["necessary_reason_codes"]),
                "reason": "nonempty string",
            },
        },
    }


def _protocol_budget(state: Mapping[str, Any], semantic_number: int) -> dict[str, Any]:
    semantic_total = 6 if state["mode"] == "full-analysis" else 1
    return {
        "target_total_model_calls": semantic_total + 2,
        "preparation_model_calls": 1,
        "semantic_model_calls": semantic_total,
        "semantic_call_number": semantic_number,
        "delivery_model_calls": 1,
        "bookkeeping_model_calls": 0,
    }


def _surface_pass_packet(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    pending = state.get("pending")
    if not isinstance(pending, Mapping):
        raise CreditAnalysisError("no semantic pass is pending")
    surface_id = str(pending["surface_id"])
    semantic_number = int(pending["ordinal"])
    common = {
        "schema": PASS_PACKET_SCHEMA,
        "analysis_id": state["analysis_id"],
        "mode": state["mode"],
        "surface_id": surface_id,
        "pass_id": pending["pass_id"],
        "protocol_budget": _protocol_budget(state, semantic_number),
        "evidence_fingerprint": state["evidence"]["fingerprint"],
        "retained_evidence_path": state["evidence"]["path"],
        "retained_context_path": pending["context_path"],
        "decision_path": pending["result_path"],
        "submit_argv": [
            "python",
            "scripts/credit-analysis-workflow.py",
            "submit",
            "--state",
            state["paths"]["state"],
            "--decision",
            pending["result_path"],
        ],
    }
    if surface_id == "synthesis":
        findings, finding_surfaces, risks = _finding_inventory(state)
        remaining_calls = _synthesis_remaining_calls(state, evidence, findings)
        focused_runs = set(evidence["semantic_coverage"]["run_ids"])
        cluster_details = _candidate_clusters(
            remaining_calls,
            evidence,
            focused_runs,
            include_representative=True,
        )
        input_hotspots = _volume_hotspot_ids(cluster_details, kind="input")
        output_hotspots = _volume_hotspot_ids(cluster_details, kind="output")
        remaining_clusters = [
            _compact_synthesis_cluster(
                cluster,
                keep_representative=True,
            )
            for cluster in cluster_details
        ]
        finding_items = []
        for finding_id, finding in findings.items():
            recurrence = finding["recurrence"]
            finding_items.append(
                {
                    "id": finding_id,
                    "title": finding["title"],
                    "source_surface": finding_surfaces[finding_id],
                    "problem_summary": finding["problem_summary"],
                    "producer_type": finding["producer_type"],
                    "producer_owner": finding["producer_owner"],
                    "helper_categories": finding["helper_categories"],
                    "affected_call_count": len(finding["affected_call_ids"]),
                    "waste_kind": finding["waste_kind"],
                    "expected_calls_saved_per_similar_run": recurrence[
                        "estimated_calls_saved_per_similar_run"
                    ],
                    "complexity": finding["complexity"],
                    "proposed_durable_control": finding[
                        "proposed_durable_control"
                    ],
                }
            )
        return {
            **common,
            "internal": True,
            "action_reference": None,
            "decision_contract": {
                "template": {
                    "schema": SYNTHESIS_DECISION_SCHEMA,
                    "finding_order": list(findings),
                    "risk_order": list(risks),
                    "remaining_call_assessments": [],
                },
                "rule": (
                    "Rank every finding and risk exactly once. The controller already "
                    "carries accepted surface exclusions into necessary classifications; "
                    "synthesis must not invent necessity. Mark a remaining cluster "
                    "unassessed only when the stated missing fact prevents a supported "
                    "decision; omitted clusters become reviewed-no-confirmed-waste. "
                    "Review every listed input and output hotspot. A full analysis leaving more "
                    "than half of the inventory unassessed is rejected in the same "
                    "pending pass. The controller expands and validates the judgments "
                    "and derives all bookkeeping."
                ),
                "assessment_shape": {
                    "cluster_ids": "string list; min 1; each cluster at most once",
                    "classification": ["unassessed"],
                    "reason_code": None,
                    "reason": "nonempty string",
                },
            },
            "accepted_findings": finding_items,
            "accepted_risks": [
                {
                    "id": risk_id,
                    "description": risk["description"],
                    "missing_fact": risk["missing_fact"],
                }
                for risk_id, risk in risks.items()
            ],
            "deterministic_totals": evidence["totals"],
            "remaining_calls": {
                "call_count": len(remaining_calls),
                "cluster_count": len(remaining_clusters),
                "clusters": remaining_clusters,
                "input_volume_hotspots": input_hotspots,
                "output_volume_hotspots": output_hotspots,
            },
        }

    reference = next(
        item["reference"] for item in contract["surfaces"] if item["id"] == surface_id
    )
    candidates = list(pending["candidate_call_ids"])
    call_by_id = {call["call_id"]: call for call in _all_calls(evidence)}
    focused_runs = set(evidence["semantic_coverage"]["run_ids"])
    budgets = SURFACE_PACKET_BUDGETS[surface_id]
    clusters = _candidate_clusters(
        candidates,
        evidence,
        focused_runs,
        include_representative=True,
    )
    input_volume_hotspots: list[str] = []
    output_volume_hotspots: list[str] = []
    if surface_id == "context-evidence":
        input_volume_hotspots = _volume_hotspot_ids(clusters, kind="input")
        input_hotspot_ids = set(input_volume_hotspots)
        for cluster in clusters:
            if cluster["cluster_id"] not in input_hotspot_ids:
                cluster.pop("representative_summary", None)
                cluster.pop("representative_call_id", None)
    if surface_id == "tool-flow":
        output_volume_hotspots = _volume_hotspot_ids(clusters, kind="output")
    clusters = [_surface_cluster_summary(surface_id, cluster) for cluster in clusters]
    detailed_calls = _detail_packet_calls(
        candidates,
        call_by_id,
        focused_runs,
        character_budget=budgets["calls"],
    )
    detailed_ids = [str(call["call_id"]) for call in detailed_calls]
    _, review_records, _ = _model_review_records_for_calls(
        evidence, candidates, focused_runs
    )
    user_messages = _user_messages_for_calls(evidence, candidates)
    run_outcomes = _run_outcome_calls(evidence, focused_runs)
    detailed_message_ids = {
        str(message_id)
        for call in detailed_calls
        for message_id in call.get("user_message_ids", [])
    }
    message_positions = {
        str(message["message_id"]): index
        for index, message in enumerate(user_messages)
    }
    prioritized_messages = sorted(
        user_messages,
        key=lambda message: (
            str(message["message_id"]) not in detailed_message_ids,
            -message_positions[str(message["message_id"])],
        ),
    )
    bounded_messages = _budgeted_values(
        prioritized_messages,
        text_limit=400,
        character_budget=budgets["users"],
    )
    detailed_id_set = set(detailed_ids)
    candidate_id_set = set(candidates)

    def review_priority(record: Mapping[str, Any]) -> tuple[int, int]:
        model_call_id = record.get("model_call_id")
        if model_call_id in detailed_id_set:
            rank = 0
        elif model_call_id in candidate_id_set:
            rank = 1
        elif surface_id == "instruction-reasoning" and record.get("kind") == "developer":
            rank = 2
        elif surface_id == "rework-validation" and record.get("kind") in {
            "message",
            "tool-result",
        }:
            rank = 2
        elif surface_id == "instruction-reasoning" and record.get("kind") == "base":
            rank = 3
        else:
            rank = 4
        raw_index = record.get("model_call_index")
        index = raw_index if isinstance(raw_index, int) else -1
        return rank, -index

    prioritized_records = sorted(
        review_records,
        key=review_priority,
    )
    bounded_records = _budgeted_values(
        prioritized_records,
        text_limit=450,
        character_budget=budgets["reviews"],
    )
    bounded_outcomes = _budgeted_values(
        list(reversed(run_outcomes)),
        text_limit=240,
        character_budget=budgets["outcomes"],
    )
    packet_evidence = {
        "deterministic_totals": evidence["totals"],
        "semantic_coverage": evidence["semantic_coverage"],
        "candidate_call_count": len(candidates),
        "candidate_cluster_count": len(clusters),
        "candidate_clusters": clusters,
        "detailed_call_count": len(detailed_calls),
        "detailed_calls": detailed_calls,
        "detail_character_budget": budgets["calls"],
        "candidate_user_message_count": len(user_messages),
        "included_user_message_count": len(bounded_messages),
        "candidate_user_messages": bounded_messages,
        "relevant_model_review_record_count": len(review_records),
        "included_model_review_record_count": len(bounded_records),
        "included_model_review_records": bounded_records,
        "run_outcome_purpose": (
            "Check later run outcomes before confirming a historical gap; "
            "do not return a finding whose durable control is already implemented."
        ),
        "run_outcome_count": len(run_outcomes),
        "included_run_outcome_count": len(bounded_outcomes),
        "run_outcomes": bounded_outcomes,
        "complete_evidence_retained_on_disk": True,
    }
    if surface_id == "context-evidence":
        packet_evidence["input_volume_hotspots"] = input_volume_hotspots
    if surface_id == "tool-flow":
        packet_evidence["output_volume_hotspots"] = output_volume_hotspots
    return {
        **common,
        "internal": False,
        "action_reference": {
            "path": reference,
            "content": (SKILL_DIR / reference).read_text(encoding="utf-8"),
        },
        "decision_contract": _surface_decision_contract(surface_id, contract),
        "evidence": packet_evidence,
    }


def _pass_packet(state_path: pathlib.Path) -> dict[str, Any]:
    state, evidence, contract = _load_state(state_path)
    if state["finalized"]:
        return _final_packet(state, evidence, contract)
    packet = _surface_pass_packet(state, evidence, contract)
    size = _json_chars(packet)
    if size >= PASS_PACKET_CHAR_LIMIT:
        raise CreditAnalysisError(
            f"semantic pass packet must stay below {PASS_PACKET_CHAR_LIMIT} characters "
            f"({size}); refine deterministic clustering or detail budgets"
        )
    return packet


def _initialize_analysis(
    request: Mapping[str, Any],
    contract: Mapping[str, Any],
    collected: dict[str, Any],
) -> dict[str, Any]:
    """Persist one validated controller from an already collected evidence set."""

    analysis_id = secrets.token_hex(12)
    if collected["collection"]["model_calls"] < 1:
        raise CreditAnalysisError("selected completed-run window has no model calls")
    collector_schema = collected.pop("schema")
    evidence = {
        **collected,
        "schema": contract["evidence_schema"],
        "collector_schema": collector_schema,
        "analysis_id": analysis_id,
        "source": request["source"],
        "requested_window": request["window"],
        "surface_contract_version": contract["surface_contract_version"],
        "surface_contract_hash": _file_hash(CONTRACT_PATH),
        "mutation_authority": False,
    }
    fingerprint = _content_hash(evidence)
    evidence["evidence_fingerprint"] = fingerprint
    _exclusive_json(request["evidence_path"], evidence, "retained evidence")
    evidence_hash = _file_hash(request["evidence_path"])
    pathlib.Path(request["paths"]["findings_dir"]).mkdir(parents=True)
    pathlib.Path(request["paths"]["context_dir"]).mkdir(parents=True)
    pathlib.Path(request["paths"]["pending_dir"]).mkdir(parents=True)
    state = {
        "schema": STATE_SCHEMA,
        "version": STATE_VERSION,
        "analysis_id": analysis_id,
        "action": request["action"],
        "mode": request["mode"],
        "mutation_authority": False,
        "surface_contract_version": contract["surface_contract_version"],
        "queue": request["queue"],
        "current_index": 0,
        "pending": None,
        "completed": [],
        "source": {
            **request["source"],
            "resolved_session": str(request["session"]),
            "fingerprint": evidence["source_fingerprint"],
        },
        "window": {
            "requested": request["window"],
            "resolved": evidence["window"],
            "fingerprint": evidence["window_fingerprint"],
        },
        "evidence": {
            "path": str(request["evidence_path"]),
            "fingerprint": fingerprint,
            "sha256": evidence_hash,
        },
        "immutable_artifacts": {
            "request": {
                "path": str(request["request_path"]),
                "sha256": request["request_hash"],
            },
            "surface_contract": {
                "path": str(CONTRACT_PATH),
                "sha256": _file_hash(CONTRACT_PATH),
            },
            "evidence": {
                "path": str(request["evidence_path"]),
                "sha256": evidence_hash,
            },
            "pricing_profile": (
                {
                    "path": str(request["pricing"]),
                    "sha256": _file_hash(request["pricing"]),
                }
                if request["pricing"] is not None
                else None
            ),
        },
        "paths": request["paths"],
        "cleanup": {
            "owner": "credit-analysis-workflow",
            "trigger": "successful-finalization",
            "transient_paths": [],
        },
        "finalized": False,
        "final_result": None,
    }
    _open_pending(state, evidence, contract)
    _exclusive_json(request["state_path"], state, "controller state")
    return _public_status(state)


def command_prepare(request_path: pathlib.Path) -> dict[str, Any]:
    contract = _load_contract()
    ledger = _load_ledger()
    request = _validate_request(request_path, contract, ledger)
    collector_window = request["collector_window"]
    try:
        collected = ledger.collect_session_evidence(
            request["session"],
            last_runs=collector_window["last_runs"],
            completed_turn_ids=collector_window["completed_turn_ids"],
            pricing_profile=request["pricing"],
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise CreditAnalysisError(f"session collection failed: {exc}") from exc
    return _initialize_analysis(request, contract, collected)


def _read_index(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise CreditAnalysisError("findings index must be a regular file")
    records: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    raise CreditAnalysisError(
                        f"findings index has a blank record at line {line_number}"
                    )
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise CreditAnalysisError("findings index record must be an object")
                records.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CreditAnalysisError(f"findings index is unreadable: {exc}") from exc
    return records


def _verify_completed(
    state: Mapping[str, Any],
    *,
    require_exact_index: bool = True,
) -> list[dict[str, Any]]:
    raw_completed = state.get("completed")
    if not isinstance(raw_completed, list):
        raise CreditAnalysisError("state completed records must be a list")
    findings_dir = pathlib.Path(state["paths"]["findings_dir"]).resolve()
    index_path = pathlib.Path(state["paths"]["index"])
    index = _read_index(index_path)
    if require_exact_index and len(index) != len(raw_completed):
        raise CreditAnalysisError("findings index and state record counts differ")
    if len(index) < len(raw_completed):
        raise CreditAnalysisError("findings index is missing an accepted result")
    completed: list[dict[str, Any]] = []
    seen_passes: set[str] = set()
    seen_surfaces: set[str] = set()
    for position, raw in enumerate(raw_completed):
        if not isinstance(raw, dict):
            raise CreditAnalysisError("state completed record must be an object")
        _closed(raw, COMPLETED_FIELDS, "completed record")
        ordinal = raw.get("ordinal")
        surface_id = raw.get("surface_id")
        if ordinal != position + 1 or surface_id != state["queue"][position]:
            raise CreditAnalysisError("accepted results are reordered or skipped")
        pass_id = raw.get("pass_id")
        if not isinstance(pass_id, str) or pass_id in seen_passes:
            raise CreditAnalysisError("accepted pass IDs must be unique")
        if not isinstance(surface_id, str) or surface_id in seen_surfaces:
            raise CreditAnalysisError("accepted surfaces must be unique")
        seen_passes.add(pass_id)
        seen_surfaces.add(surface_id)
        expected_path = (findings_dir / f"{ordinal:03d}-{surface_id}.json").resolve()
        recorded_path = pathlib.Path(str(raw.get("path"))).resolve()
        if recorded_path != expected_path or not expected_path.is_file() or expected_path.is_symlink():
            raise CreditAnalysisError(f"accepted result path is invalid: {surface_id}")
        if _file_hash(expected_path) != raw.get("sha256"):
            raise CreditAnalysisError(f"accepted result hash mismatch: {surface_id}")
        parsed = _read_json(expected_path, f"accepted {surface_id} result")
        if _content_hash(parsed) != raw.get("content_hash"):
            raise CreditAnalysisError(f"accepted result content mismatch: {surface_id}")
        index_record = index[position]
        expected_index = {
            "schema": INDEX_SCHEMA,
            "ordinal": ordinal,
            "surface_id": surface_id,
            "pass_id": pass_id,
            "path": str(expected_path),
            "sha256": raw["sha256"],
            "content_hash": raw["content_hash"],
        }
        if index_record != expected_index:
            raise CreditAnalysisError(f"findings index record mismatch: {surface_id}")
        completed.append(dict(raw))
    if require_exact_index and len(index) != len(completed):
        raise CreditAnalysisError("findings index contains an unrecorded result")
    return completed


def _load_state(
    state_path: pathlib.Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        resolved = state_path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise CreditAnalysisError(f"state does not exist: {state_path}") from exc
    if resolved.is_symlink() or not resolved.is_file():
        raise CreditAnalysisError("state must be a regular file")
    state = _read_json(resolved, "state")
    _closed(state, STATE_FIELDS, "state")
    if state.get("schema") != STATE_SCHEMA or state.get("version") != STATE_VERSION:
        raise CreditAnalysisError("unsupported state schema or version")
    if state.get("mutation_authority") is not False:
        raise CreditAnalysisError("state mutation authority must remain false")
    paths = state.get("paths")
    if not isinstance(paths, dict) or pathlib.Path(str(paths.get("state"))).resolve() != resolved:
        raise CreditAnalysisError("state path does not match controller ownership")
    task_root = resolved.parent
    expected_paths = {
        "state": task_root / "state.json",
        "findings_dir": task_root / "findings",
        "index": task_root / "findings.jsonl",
        "context_dir": task_root / "context",
        "pending_dir": task_root / "pending",
        "final_result": task_root / "final-machine-result.json",
    }
    if set(paths) != set(expected_paths):
        raise CreditAnalysisError("state controller paths are invalid")
    for key, expected in expected_paths.items():
        if pathlib.Path(str(paths[key])).resolve() != expected.resolve():
            raise CreditAnalysisError(f"state {key} path escapes controller ownership")
    contract = _load_contract()
    if state.get("surface_contract_version") != contract["surface_contract_version"]:
        raise CreditAnalysisError("state surface contract version is stale")
    queue = state.get("queue")
    expected_queue = (
        contract["full_queue"]
        if state.get("mode") == "full-analysis"
        else [state.get("action")]
    )
    if queue != expected_queue:
        raise CreditAnalysisError("state queue does not match the fixed contract")
    current_index = state.get("current_index")
    if (
        not isinstance(current_index, int)
        or isinstance(current_index, bool)
        or current_index < 0
        or current_index > len(queue)
    ):
        raise CreditAnalysisError("state current index is invalid")
    artifacts = state.get("immutable_artifacts")
    if not isinstance(artifacts, dict):
        raise CreditAnalysisError("state immutable artifacts are invalid")
    for label in ("request", "surface_contract", "evidence"):
        record = artifacts.get(label)
        if not isinstance(record, dict):
            raise CreditAnalysisError(f"state {label} artifact is invalid")
        artifact = _existing_file(record.get("path"), f"state {label} artifact")
        if _file_hash(artifact) != record.get("sha256"):
            raise CreditAnalysisError(f"state {label} artifact changed")
    pricing = artifacts.get("pricing_profile")
    if pricing is not None:
        if not isinstance(pricing, dict):
            raise CreditAnalysisError("state pricing artifact is invalid")
        pricing_path = _existing_file(pricing.get("path"), "state pricing artifact")
        if _file_hash(pricing_path) != pricing.get("sha256"):
            raise CreditAnalysisError("state pricing artifact changed")
    evidence_record = state.get("evidence")
    if not isinstance(evidence_record, dict):
        raise CreditAnalysisError("state evidence record is invalid")
    evidence_path = _existing_file(evidence_record.get("path"), "retained evidence")
    if _file_hash(evidence_path) != evidence_record.get("sha256"):
        raise CreditAnalysisError("retained evidence hash mismatch")
    evidence = _read_json(evidence_path, "retained evidence")
    if (
        evidence.get("schema") != contract["evidence_schema"]
        or evidence.get("analysis_id") != state.get("analysis_id")
        or evidence.get("evidence_fingerprint") != evidence_record.get("fingerprint")
    ):
        raise CreditAnalysisError("retained evidence identity mismatch")
    without_fingerprint = dict(evidence)
    without_fingerprint.pop("evidence_fingerprint", None)
    if _content_hash(without_fingerprint) != evidence_record.get("fingerprint"):
        raise CreditAnalysisError("retained evidence fingerprint mismatch")
    _verify_completed(state, require_exact_index=False)
    _recover_indexed_pending(state, evidence, contract)
    completed = _verify_completed(state)
    current_index = state["current_index"]
    if current_index != len(completed):
        raise CreditAnalysisError("state index does not match accepted results")
    pending = state.get("pending")
    if pending is not None:
        if not isinstance(pending, dict):
            raise CreditAnalysisError("state pending record is invalid")
        if current_index >= len(queue) or pending.get("surface_id") != queue[current_index]:
            raise CreditAnalysisError("pending surface is reordered")
        if pending.get("ordinal") != current_index + 1:
            raise CreditAnalysisError("pending ordinal is invalid")
        expected_context = pathlib.Path(paths["context_dir"]) / (
            f"{pending['ordinal']:03d}-{pending['surface_id']}.json"
        )
        expected_result = pathlib.Path(paths["pending_dir"]) / (
            f"{pending['ordinal']:03d}-{pending['surface_id']}.json"
        )
        if pathlib.Path(str(pending.get("context_path"))).resolve() != expected_context.resolve():
            raise CreditAnalysisError("pending context path is invalid")
        if pathlib.Path(str(pending.get("result_path"))).resolve() != expected_result.resolve():
            raise CreditAnalysisError("pending result path is invalid")
        if not expected_context.is_file() or expected_context.is_symlink():
            raise CreditAnalysisError("pending context is missing")
        context = _read_json(expected_context, "pending context")
        if (
            context.get("analysis_id") != state["analysis_id"]
            or context.get("pass_id") != pending.get("pass_id")
            or context.get("surface_id") != pending.get("surface_id")
            or context.get("candidate_call_ids") != pending.get("candidate_call_ids")
        ):
            raise CreditAnalysisError("pending context identity mismatch")
    elif current_index < len(queue) and state.get("finalized") is not True:
        _open_pending(state, evidence, contract)
        _save_state(state)
        pending = state["pending"]
    if state.get("finalized") is True:
        final = state.get("final_result")
        if not isinstance(final, dict):
            raise CreditAnalysisError("finalized state lacks final result")
        final_path = _existing_file(final.get("path"), "final machine result")
        if _file_hash(final_path) != final.get("sha256"):
            raise CreditAnalysisError("final machine result hash mismatch")
    return state, evidence, contract


def _save_state(state: Mapping[str, Any]) -> None:
    _atomic_json(pathlib.Path(state["paths"]["state"]), state, "controller state")


def _recover_indexed_pending(
    state: dict[str, Any],
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> None:
    """Recover one accepted pass appended before its atomic state checkpoint."""

    index = _read_index(pathlib.Path(state["paths"]["index"]))
    completed_count = len(state["completed"])
    if len(index) == completed_count:
        return
    if len(index) != completed_count + 1:
        raise CreditAnalysisError("findings index contains unrecoverable extra records")
    pending = state.get("pending")
    if not isinstance(pending, Mapping):
        raise CreditAnalysisError("findings index has an orphan without a pending pass")
    record = index[-1]
    expected_path = (
        pathlib.Path(state["paths"]["findings_dir"])
        / f"{pending['ordinal']:03d}-{pending['surface_id']}.json"
    ).resolve()
    expected_identity = {
        "schema": INDEX_SCHEMA,
        "ordinal": pending["ordinal"],
        "surface_id": pending["surface_id"],
        "pass_id": pending["pass_id"],
        "path": str(expected_path),
    }
    if any(record.get(field) != value for field, value in expected_identity.items()):
        raise CreditAnalysisError("orphaned findings index record is not the pending pass")
    if not expected_path.is_file() or expected_path.is_symlink():
        raise CreditAnalysisError("orphaned findings index result is missing")
    raw = _read_json(expected_path, "orphaned accepted result")
    normalized = (
        _validate_synthesis(raw, state=state, evidence=evidence, contract=contract)
        if pending["surface_id"] == "synthesis"
        else _validate_surface_result(
            raw,
            state=state,
            evidence=evidence,
            contract=contract,
        )
    )
    if (
        _content_hash(normalized) != record.get("content_hash")
        or _file_hash(expected_path) != record.get("sha256")
    ):
        raise CreditAnalysisError("orphaned accepted result hash mismatch")
    state["completed"].append(
        {
            "ordinal": pending["ordinal"],
            "surface_id": pending["surface_id"],
            "pass_id": pending["pass_id"],
            "path": str(expected_path),
            "sha256": record["sha256"],
            "content_hash": record["content_hash"],
            "candidate_call_ids": list(pending["candidate_call_ids"]),
            "context_path": pending["context_path"],
            "result_path": pending["result_path"],
        }
    )
    state["current_index"] += 1
    state["pending"] = None
    _save_state(state)


def _evidence_ref(call_id: str) -> str:
    return f"evidence://calls/{call_id}"


def _validate_evidence_refs(
    refs: Any,
    known_calls: set[str],
    label: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    values = _strings(refs, label, allow_empty=allow_empty)
    allowed = {_evidence_ref(call_id) for call_id in known_calls}
    unknown = [value for value in values if value not in allowed]
    if unknown:
        raise CreditAnalysisError(f"{label} references unknown evidence: {unknown[0]}")
    return values


def _validate_recurrence(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CreditAnalysisError(f"{label} must be an object")
    _closed(value, RECURRENCE_FIELDS, label)
    saved = _number(value["calls_saved_per_affected_run"], f"{label} calls saved")
    added = _number(
        value["additional_recurring_calls_per_affected_run"],
        f"{label} additional calls",
    )
    frequency = _number(value["affected_similar_run_frequency"], f"{label} frequency")
    if frequency > 1:
        raise CreditAnalysisError(f"{label} frequency must be <= 1")
    raw_range = value["affected_similar_run_frequency_range"]
    if (
        not isinstance(raw_range, list)
        or len(raw_range) != 2
        or any(
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not math.isfinite(float(item))
            for item in raw_range
        )
    ):
        raise CreditAnalysisError(f"{label} frequency range must contain two numbers")
    low, high = map(float, raw_range)
    if not 0 <= low <= frequency <= high <= 1:
        raise CreditAnalysisError(f"{label} frequency range is inconsistent")
    estimate = _number(
        value["estimated_calls_saved_per_similar_run"],
        f"{label} similar-run saving",
    )
    expected = round((saved - added) * frequency, 6)
    if saved - added < 0 or not math.isclose(estimate, expected, abs_tol=1e-6):
        raise CreditAnalysisError(f"{label} savings arithmetic is invalid")
    assumptions = _strings(value["assumptions"], f"{label} assumptions")
    return {
        **value,
        "calls_saved_per_affected_run": saved,
        "additional_recurring_calls_per_affected_run": added,
        "affected_similar_run_frequency": frequency,
        "affected_similar_run_frequency_range": [low, high],
        "estimated_calls_saved_per_similar_run": estimate,
        "assumptions": assumptions,
    }


def _validate_finding(
    raw: dict[str, Any],
    *,
    known_calls: set[str],
    contract: Mapping[str, Any],
    surface_id: str,
) -> dict[str, Any]:
    _closed(raw, FINDING_FIELDS, "finding")
    finding_id = _identifier(raw.get("id"), "finding id")
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise CreditAnalysisError(f"finding {finding_id} title is required")
    problem_summary = raw.get("problem_summary")
    if not isinstance(problem_summary, str) or not problem_summary.strip():
        raise CreditAnalysisError(f"finding {finding_id} problem summary is required")
    waste_kind = raw.get("waste_kind")
    if waste_kind not in contract["waste_kinds"]:
        raise CreditAnalysisError(f"finding {finding_id} waste kind is invalid")
    affected = _strings(raw.get("affected_call_ids"), f"finding {finding_id} calls")
    unknown = sorted(set(affected) - known_calls)
    if unknown:
        raise CreditAnalysisError(f"finding {finding_id} uses unknown call: {unknown[0]}")
    refs = _validate_evidence_refs(
        raw.get("evidence_refs"), known_calls, f"finding {finding_id} evidence"
    )
    required_refs = {_evidence_ref(call_id) for call_id in affected}
    if not required_refs.issubset(refs):
        raise CreditAnalysisError(f"finding {finding_id} lacks affected-call evidence")
    narrative = raw.get("evidence_narrative")
    if not isinstance(narrative, str) or not narrative.strip():
        raise CreditAnalysisError(f"finding {finding_id} evidence narrative is required")
    narrative = narrative.strip()
    if len(narrative) > EVIDENCE_NARRATIVE_LIMIT:
        raise CreditAnalysisError(f"finding {finding_id} evidence narrative is too long")
    exposed_call = next((call_id for call_id in known_calls if call_id in narrative), None)
    if exposed_call is not None:
        raise CreditAnalysisError(
            f"finding {finding_id} evidence narrative exposes an exact call id"
        )
    producer_type = raw.get("producer_type")
    if producer_type not in contract["producer_types"]:
        raise CreditAnalysisError(f"finding {finding_id} producer type is invalid")
    owner = raw.get("producer_owner")
    if owner is not None and (not isinstance(owner, str) or not owner.strip()):
        raise CreditAnalysisError(f"finding {finding_id} producer owner is invalid")
    if owner is None and producer_type != "unknown":
        raise CreditAnalysisError(f"finding {finding_id} must name its producer owner")
    control = raw.get("proposed_durable_control")
    if not isinstance(control, str) or not control.strip():
        raise CreditAnalysisError(f"finding {finding_id} durable control is required")
    status = raw.get("implementation_status")
    if status not in contract["implementation_statuses"]:
        raise CreditAnalysisError(f"finding {finding_id} implementation status is invalid")
    verification = _strings(
        raw.get("targeted_verification"), f"finding {finding_id} verification"
    )
    observed = raw.get("observed_avoidable_call_count")
    if not isinstance(observed, int) or isinstance(observed, bool) or observed < 0:
        raise CreditAnalysisError(f"finding {finding_id} avoidable count is invalid")
    if waste_kind == "model-calls" and observed != len(affected):
        raise CreditAnalysisError(f"finding {finding_id} avoidable count must match its calls")
    if waste_kind == "context-volume" and observed != 0:
        raise CreditAnalysisError(f"finding {finding_id} context volume must save zero calls")
    recurrence = _validate_recurrence(raw.get("recurrence"), f"finding {finding_id} recurrence")
    if waste_kind == "context-volume" and any(
        recurrence[field] != 0
        for field in (
            "calls_saved_per_affected_run",
            "additional_recurring_calls_per_affected_run",
            "estimated_calls_saved_per_similar_run",
        )
    ):
        raise CreditAnalysisError(
            f"finding {finding_id} context volume must stay outside call savings"
        )
    confidence = _number(raw.get("confidence"), f"finding {finding_id} confidence")
    if confidence > 1:
        raise CreditAnalysisError(f"finding {finding_id} confidence must be <= 1")
    complexity = raw.get("complexity")
    if complexity not in contract["complexities"]:
        raise CreditAnalysisError(f"finding {finding_id} complexity is invalid")
    cost = raw.get("one_time_implementation_cost")
    if not isinstance(cost, dict):
        raise CreditAnalysisError(f"finding {finding_id} implementation cost must be an object")
    _closed(cost, COST_FIELDS, f"finding {finding_id} implementation cost")
    cost_calls = _number(cost.get("estimated_model_calls"), f"finding {finding_id} cost")
    description = cost.get("description")
    if not isinstance(description, str) or not description.strip():
        raise CreditAnalysisError(f"finding {finding_id} cost description is required")
    helper_categories = _strings(
        raw.get("helper_categories"),
        f"finding {finding_id} helper categories",
        allow_empty=True,
    )
    unknown_categories = sorted(set(helper_categories) - set(contract["helper_categories"]))
    if unknown_categories:
        raise CreditAnalysisError(
            f"finding {finding_id} helper category is invalid: {unknown_categories[0]}"
        )
    if surface_id == "helper-contracts" and not helper_categories:
        raise CreditAnalysisError(f"helper finding {finding_id} must name a category")
    if surface_id != "helper-contracts" and helper_categories:
        raise CreditAnalysisError(f"non-helper finding {finding_id} must not name helper categories")
    return {
        **raw,
        "id": finding_id,
        "title": title.strip(),
        "problem_summary": problem_summary.strip(),
        "waste_kind": waste_kind,
        "affected_call_ids": affected,
        "evidence_refs": refs,
        "evidence_narrative": narrative,
        "producer_owner": owner.strip() if isinstance(owner, str) else None,
        "proposed_durable_control": control.strip(),
        "targeted_verification": verification,
        "recurrence": recurrence,
        "confidence": confidence,
        "one_time_implementation_cost": {
            "estimated_model_calls": cost_calls,
            "description": description.strip(),
        },
        "helper_categories": helper_categories,
    }


def _validate_surface_result(
    result: dict[str, Any],
    *,
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    _closed(result, SURFACE_RESULT_FIELDS, "surface result")
    pending = state.get("pending")
    if not isinstance(pending, Mapping):
        raise CreditAnalysisError("no surface pass is pending")
    surface_id = pending["surface_id"]
    if surface_id == "synthesis":
        raise CreditAnalysisError("synthesis must be submitted through finalize")
    expected_identity = {
        "schema": contract["surface_result_schema"],
        "analysis_id": state["analysis_id"],
        "pass_id": pending["pass_id"],
        "surface_id": surface_id,
        "evidence_fingerprint": state["evidence"]["fingerprint"],
    }
    for field, expected in expected_identity.items():
        if result.get(field) != expected:
            raise CreditAnalysisError(f"surface result {field} does not match pending state")
    artifacts = result.get("artifact_paths")
    if not isinstance(artifacts, dict) or set(artifacts) != {
        "state",
        "evidence",
        "context",
        "result",
    }:
        raise CreditAnalysisError("surface result artifact paths are invalid")
    expected_artifacts = {
        "state": state["paths"]["state"],
        "evidence": state["evidence"]["path"],
        "context": pending["context_path"],
        "result": pending["result_path"],
    }
    if artifacts != expected_artifacts:
        raise CreditAnalysisError("surface result artifact paths do not match pending state")
    known_calls = set(evidence["call_inventory"])
    candidates = list(pending["candidate_call_ids"])
    reviewed = _strings(
        result.get("reviewed_candidate_call_ids"),
        "reviewed candidate call IDs",
        allow_empty=True,
    )
    if reviewed != candidates:
        raise CreditAnalysisError("surface result does not cover the exact candidate queue")
    top_refs = _validate_evidence_refs(
        result.get("evidence_references"),
        known_calls,
        "surface evidence references",
        allow_empty=True,
    )
    required_candidate_refs = {_evidence_ref(call_id) for call_id in candidates}
    if not required_candidate_refs.issubset(top_refs):
        raise CreditAnalysisError("surface result lacks candidate evidence references")

    findings = [
        _validate_finding(
            raw,
            known_calls=known_calls,
            contract=contract,
            surface_id=surface_id,
        )
        for raw in _objects(result.get("confirmed_findings"), "confirmed findings")
    ]
    finding_ids = [finding["id"] for finding in findings]
    if len(finding_ids) != len(set(finding_ids)):
        raise CreditAnalysisError("surface finding IDs must be unique")

    risks: list[dict[str, Any]] = []
    for raw in _objects(result.get("plausible_risks"), "plausible risks"):
        _closed(raw, RISK_FIELDS, "plausible risk")
        risk_id = _identifier(raw.get("id"), "risk id")
        description = raw.get("description")
        if not isinstance(description, str) or not description.strip():
            raise CreditAnalysisError(f"risk {risk_id} description is required")
        observed_sequence = raw.get("observed_sequence")
        if not isinstance(observed_sequence, str) or not observed_sequence.strip():
            raise CreditAnalysisError(
                f"risk {risk_id} observed sequence is required"
            )
        competing_explanations = _strings(
            raw.get("competing_explanations"),
            f"risk {risk_id} competing explanations",
        )
        if len(competing_explanations) < 2:
            raise CreditAnalysisError(
                f"risk {risk_id} requires at least two competing explanations"
            )
        missing_fact = raw.get("missing_fact")
        if not isinstance(missing_fact, str) or not missing_fact.strip():
            raise CreditAnalysisError(f"risk {risk_id} missing fact is required")
        affected = _strings(raw.get("affected_call_ids"), f"risk {risk_id} calls")
        unknown = sorted(set(affected) - known_calls)
        if unknown:
            raise CreditAnalysisError(f"risk {risk_id} uses unknown call: {unknown[0]}")
        refs = _validate_evidence_refs(
            raw.get("evidence_refs"), known_calls, f"risk {risk_id} evidence"
        )
        if not {_evidence_ref(call_id) for call_id in affected}.issubset(refs):
            raise CreditAnalysisError(f"risk {risk_id} lacks affected-call evidence")
        verification = _strings(
            raw.get("verification_needed"), f"risk {risk_id} verification"
        )
        risks.append(
            {
                **raw,
                "id": risk_id,
                "description": description.strip(),
                "observed_sequence": observed_sequence.strip(),
                "competing_explanations": competing_explanations,
                "missing_fact": missing_fact.strip(),
                "affected_call_ids": affected,
                "evidence_refs": refs,
                "verification_needed": verification,
            }
        )
    risk_ids = [risk["id"] for risk in risks]
    if len(risk_ids) != len(set(risk_ids)):
        raise CreditAnalysisError("surface risk IDs must be unique")

    dismissals: list[dict[str, str]] = []
    for raw in _objects(result.get("dismissed_candidates"), "dismissed candidates"):
        _closed(raw, DISMISSAL_FIELDS, "dismissed candidate")
        call_id = raw.get("call_id")
        reason = raw.get("reason")
        if (
            not isinstance(call_id, str)
            or call_id not in known_calls
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise CreditAnalysisError("dismissed candidate is invalid")
        dismissals.append({"call_id": call_id, "reason": reason.strip()})
    if len({item["call_id"] for item in dismissals}) != len(dismissals):
        raise CreditAnalysisError("dismissed candidates must be unique")

    exclusions: list[dict[str, str]] = []
    for raw in _objects(
        result.get("necessary_call_exclusions"), "necessary call exclusions"
    ):
        _closed(raw, EXCLUSION_FIELDS, "necessary call exclusion")
        call_id = raw.get("call_id")
        reason_code = raw.get("reason_code")
        reason = raw.get("reason")
        if (
            not isinstance(call_id, str)
            or call_id not in known_calls
            or not isinstance(reason_code, str)
            or reason_code not in contract["necessary_reason_codes"]
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise CreditAnalysisError("necessary call exclusion is invalid")
        exclusions.append(
            {
                "call_id": call_id,
                "reason_code": reason_code,
                "reason": reason.strip(),
            }
        )
    if len({item["call_id"] for item in exclusions}) != len(exclusions):
        raise CreditAnalysisError("necessary call exclusions must be unique")
    if {item["call_id"] for item in dismissals} & {
        item["call_id"] for item in exclusions
    }:
        raise CreditAnalysisError("a candidate cannot be both dismissed and necessary")

    affected_confirmed = {
        call_id for finding in findings for call_id in finding["affected_call_ids"]
    }
    affected_risks = {call_id for risk in risks for call_id in risk["affected_call_ids"]}
    accounted = (
        affected_confirmed
        | affected_risks
        | {item["call_id"] for item in dismissals}
        | {item["call_id"] for item in exclusions}
    )
    missing = [call_id for call_id in candidates if call_id not in accounted]
    if missing:
        raise CreditAnalysisError(f"candidate is not accounted for: {missing[0]}")
    if not findings:
        zero_accounted = {item["call_id"] for item in dismissals} | {
            item["call_id"] for item in exclusions
        }
        missing_zero = [call_id for call_id in candidates if call_id not in zero_accounted]
        if missing_zero:
            raise CreditAnalysisError(
                f"zero-finding result must dismiss or exclude candidate: {missing_zero[0]}"
            )

    nested_refs = {
        ref
        for item in [*findings, *risks]
        for ref in item["evidence_refs"]
    }
    if not nested_refs.issubset(top_refs):
        raise CreditAnalysisError("surface evidence index omits a finding or risk reference")

    helper_reviews = _objects(
        result.get("helper_category_reviews"), "helper category reviews"
    )
    remediation_groups = _objects(result.get("remediation_groups"), "remediation groups")
    if surface_id == "helper-contracts":
        normalized_reviews: list[dict[str, Any]] = []
        for raw in helper_reviews:
            _closed(raw, HELPER_REVIEW_FIELDS, "helper category review")
            category = raw.get("category")
            status = raw.get("status")
            ids = _strings(
                raw.get("finding_ids"),
                f"helper category {category} findings",
                allow_empty=True,
            )
            reason = raw.get("reason")
            if (
                category not in contract["helper_categories"]
                or status not in {"applies", "not-applicable"}
                or not isinstance(reason, str)
                or not reason.strip()
                or bool(ids) != (status == "applies")
                or not set(ids).issubset(finding_ids)
            ):
                raise CreditAnalysisError(f"helper category review is invalid: {category}")
            normalized_reviews.append(
                {
                    "category": category,
                    "status": status,
                    "finding_ids": ids,
                    "reason": reason.strip(),
                }
            )
        if [item["category"] for item in normalized_reviews] != contract["helper_categories"]:
            raise CreditAnalysisError("helper reviews must cover all ten categories in order")
        mapped_categories: dict[str, set[str]] = defaultdict(set)
        for review in normalized_reviews:
            for finding_id in review["finding_ids"]:
                mapped_categories[finding_id].add(review["category"])
        for finding in findings:
            if mapped_categories[finding["id"]] != set(finding["helper_categories"]):
                raise CreditAnalysisError(
                    f"helper category mappings disagree for finding: {finding['id']}"
                )
        normalized_groups: list[dict[str, Any]] = []
        grouped: list[str] = []
        findings_by_id = {finding["id"]: finding for finding in findings}
        for raw in remediation_groups:
            _closed(raw, REMEDIATION_FIELDS, "helper remediation group")
            owner = raw.get("owner")
            ids = _strings(raw.get("finding_ids"), "helper remediation finding IDs")
            control = raw.get("proposed_control")
            verification = _strings(
                raw.get("targeted_verification"), "helper remediation verification"
            )
            if (
                not isinstance(owner, str)
                or not owner.strip()
                or not set(ids).issubset(findings_by_id)
                or not isinstance(control, str)
                or not control.strip()
            ):
                raise CreditAnalysisError("helper remediation group is invalid")
            if any(findings_by_id[item]["producer_owner"] != owner for item in ids):
                raise CreditAnalysisError("helper remediation group mixes producer owners")
            required_verification = {
                check
                for item in ids
                for check in findings_by_id[item]["targeted_verification"]
            }
            if not required_verification.issubset(verification):
                raise CreditAnalysisError("helper remediation group drops targeted verification")
            grouped.extend(ids)
            normalized_groups.append(
                {
                    "owner": owner.strip(),
                    "finding_ids": ids,
                    "proposed_control": control.strip(),
                    "targeted_verification": verification,
                }
            )
        if sorted(grouped) != sorted(finding_ids) or len(grouped) != len(set(grouped)):
            raise CreditAnalysisError("helper remediation groups must partition findings")
        protocol_calls = {
            item["call_id"]
            for item in exclusions
            if item["reason_code"] == "protocol-overhead"
        }
        if protocol_calls & affected_confirmed:
            raise CreditAnalysisError("protocol overhead cannot be a helper defect")
        helper_reviews = normalized_reviews
        remediation_groups = normalized_groups
    elif helper_reviews or remediation_groups:
        raise CreditAnalysisError("only helper-contracts may emit helper review data")

    previous_ids = {
        finding["id"]
        for accepted in _accepted_payloads(state)
        for finding in accepted.get("confirmed_findings", [])
        if isinstance(finding, dict) and isinstance(finding.get("id"), str)
    }
    duplicate = sorted(previous_ids & set(finding_ids))
    if duplicate:
        raise CreditAnalysisError(f"finding ID already exists in another surface: {duplicate[0]}")
    previous_risks = {
        risk["id"]
        for accepted in _accepted_payloads(state)
        for risk in accepted.get("plausible_risks", [])
        if isinstance(risk, dict) and isinstance(risk.get("id"), str)
    }
    duplicate_risk = sorted(previous_risks & set(risk_ids))
    if duplicate_risk:
        raise CreditAnalysisError(f"risk ID already exists in another surface: {duplicate_risk[0]}")
    return {
        **result,
        "confirmed_findings": findings,
        "plausible_risks": risks,
        "dismissed_candidates": dismissals,
        "necessary_call_exclusions": exclusions,
        "evidence_references": top_refs,
        "helper_category_reviews": helper_reviews,
        "remediation_groups": remediation_groups,
    }


def _expand_decision_selectors(
    raw: Any,
    known_calls: set[str],
    label: str,
    *,
    cluster_calls: Mapping[str, Sequence[str]] | None = None,
    allow_empty: bool = False,
) -> list[str]:
    selectors = _objects(raw, label)
    if not selectors and not allow_empty:
        raise CreditAnalysisError(f"{label} must select at least one call")
    selected: list[str] = []
    for index, selector in enumerate(selectors, start=1):
        _allowed_fields(selector, CALL_SELECTOR_FIELDS, f"{label} selector {index}")
        candidates: list[str]
        if "cluster_ids" in selector:
            if set(selector) != {"cluster_ids"}:
                raise CreditAnalysisError(
                    f"{label} selector {index} mixes cluster IDs with another form"
                )
            cluster_ids = _strings(
                selector["cluster_ids"], f"{label} selector {index} cluster IDs"
            )
            candidates = []
            for cluster_id in cluster_ids:
                if cluster_calls is None or cluster_id not in cluster_calls:
                    raise CreditAnalysisError(
                        f"{label} selects unknown cluster: {cluster_id}"
                    )
                candidates.extend(str(call_id) for call_id in cluster_calls[cluster_id])
        elif "call_ids" in selector:
            if set(selector) != {"call_ids"}:
                raise CreditAnalysisError(
                    f"{label} selector {index} mixes exact IDs and ranges"
                )
            candidates = _strings(
                selector["call_ids"], f"{label} selector {index} call IDs"
            )
        else:
            if set(selector) != {"turn_id", "ranges"}:
                raise CreditAnalysisError(
                    f"{label} selector {index} must use cluster IDs, exact IDs, "
                    "or one turn range"
                )
            turn_id = selector.get("turn_id")
            ranges = selector.get("ranges")
            if (
                not isinstance(turn_id, str)
                or not turn_id
                or not isinstance(ranges, list)
                or not ranges
            ):
                raise CreditAnalysisError(f"{label} selector {index} range is invalid")
            candidates = []
            for raw_range in ranges:
                if (
                    not isinstance(raw_range, list)
                    or len(raw_range) != 2
                    or not all(
                        isinstance(value, int)
                        and not isinstance(value, bool)
                        and value > 0
                        for value in raw_range
                    )
                    or raw_range[0] > raw_range[1]
                ):
                    raise CreditAnalysisError(
                        f"{label} selector {index} range is invalid"
                    )
                candidates.extend(
                    f"{turn_id}:{call_index}"
                    for call_index in range(raw_range[0], raw_range[1] + 1)
                )
        for call_id in candidates:
            if call_id not in known_calls:
                raise CreditAnalysisError(f"{label} selects unknown call: {call_id}")
            if call_id not in selected:
                selected.append(call_id)
    return selected


def _decision_recurrence(
    raw: Any,
    *,
    observed_calls: int,
    waste_kind: str,
    label: str,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CreditAnalysisError(f"{label} must be an object")
    _closed(raw, DECISION_RECURRENCE_FIELDS, label)
    added = _number(
        raw["additional_recurring_calls_per_affected_run"],
        f"{label} additional calls",
    )
    frequency = _number(
        raw["affected_similar_run_frequency"], f"{label} frequency"
    )
    if frequency > 1:
        raise CreditAnalysisError(f"{label} frequency must be <= 1")
    raw_range = raw["affected_similar_run_frequency_range"]
    if (
        not isinstance(raw_range, list)
        or len(raw_range) != 2
        or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            for value in raw_range
        )
    ):
        raise CreditAnalysisError(f"{label} frequency range is invalid")
    low, high = map(float, raw_range)
    if not 0 <= low <= frequency <= high <= 1:
        raise CreditAnalysisError(f"{label} frequency range is inconsistent")
    assumptions = _strings(raw["assumptions"], f"{label} assumptions")
    saved = 0.0 if waste_kind == "context-volume" else float(observed_calls)
    if waste_kind == "context-volume":
        added = 0.0
    if saved - added < 0:
        raise CreditAnalysisError(f"{label} introduces more calls than it saves")
    return {
        "calls_saved_per_affected_run": saved,
        "additional_recurring_calls_per_affected_run": added,
        "affected_similar_run_frequency": frequency,
        "affected_similar_run_frequency_range": [low, high],
        "estimated_calls_saved_per_similar_run": round(
            (saved - added) * frequency, 6
        ),
        "assumptions": assumptions,
    }


def _decision_finding(
    raw: dict[str, Any],
    *,
    known_calls: set[str],
    cluster_calls: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    _closed(raw, DECISION_FINDING_FIELDS, "surface decision finding")
    waste_kind = raw.get("waste_kind")
    affected = _expand_decision_selectors(
        raw.get("affected_selectors"),
        known_calls,
        "finding affected selectors",
        cluster_calls=cluster_calls,
    )
    additional = _expand_decision_selectors(
        raw.get("additional_evidence_selectors"),
        known_calls,
        "finding additional evidence selectors",
        cluster_calls=cluster_calls,
        allow_empty=True,
    )
    recurrence = _decision_recurrence(
        raw.get("recurrence"),
        observed_calls=len(affected),
        waste_kind=str(waste_kind),
        label=f"finding {raw.get('id')} recurrence",
    )
    refs = list(dict.fromkeys([*affected, *additional]))
    return {
        "id": raw.get("id"),
        "title": raw.get("title"),
        "problem_summary": raw.get("problem_summary"),
        "waste_kind": waste_kind,
        "affected_call_ids": affected,
        "evidence_refs": [_evidence_ref(call_id) for call_id in refs],
        "evidence_narrative": raw.get("evidence_narrative"),
        "producer_type": raw.get("producer_type"),
        "producer_owner": raw.get("producer_owner"),
        "proposed_durable_control": raw.get("proposed_durable_control"),
        "implementation_status": raw.get("implementation_status"),
        "targeted_verification": raw.get("targeted_verification"),
        "observed_avoidable_call_count": (
            0 if waste_kind == "context-volume" else len(affected)
        ),
        "recurrence": recurrence,
        "confidence": raw.get("confidence"),
        "complexity": raw.get("complexity"),
        "one_time_implementation_cost": raw.get("one_time_implementation_cost"),
        "helper_categories": raw.get("helper_categories"),
    }


def _decision_risk(
    raw: dict[str, Any],
    *,
    known_calls: set[str],
    cluster_calls: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    _closed(raw, DECISION_RISK_FIELDS, "surface decision risk")
    affected = _expand_decision_selectors(
        raw.get("affected_selectors"),
        known_calls,
        "risk affected selectors",
        cluster_calls=cluster_calls,
    )
    additional = _expand_decision_selectors(
        raw.get("additional_evidence_selectors"),
        known_calls,
        "risk additional evidence selectors",
        cluster_calls=cluster_calls,
        allow_empty=True,
    )
    refs = list(dict.fromkeys([*affected, *additional]))
    return {
        "id": raw.get("id"),
        "description": raw.get("description"),
        "observed_sequence": raw.get("observed_sequence"),
        "competing_explanations": raw.get("competing_explanations"),
        "missing_fact": raw.get("missing_fact"),
        "affected_call_ids": affected,
        "evidence_refs": [_evidence_ref(call_id) for call_id in refs],
        "verification_needed": raw.get("verification_needed"),
    }


def _helper_decision_metadata(
    findings: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reviews: list[dict[str, Any]] = []
    for category in contract["helper_categories"]:
        finding_ids = [
            str(finding["id"])
            for finding in findings
            if category in finding["helper_categories"]
        ]
        reviews.append(
            {
                "category": category,
                "status": "applies" if finding_ids else "not-applicable",
                "finding_ids": finding_ids,
                "reason": (
                    "Confirmed by the mapped findings."
                    if finding_ids
                    else "No reviewed candidate confirmed this category."
                ),
            }
        )
    by_owner: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for finding in findings:
        owner = finding.get("producer_owner")
        if not isinstance(owner, str) or not owner.strip():
            raise CreditAnalysisError(
                "helper decision finding must name a concrete remediation owner"
            )
        by_owner[owner.strip()].append(finding)
    groups: list[dict[str, Any]] = []
    for owner, members in by_owner.items():
        groups.append(
            {
                "owner": owner,
                "finding_ids": [str(item["id"]) for item in members],
                "proposed_control": " ".join(
                    dict.fromkeys(
                        str(item["proposed_durable_control"]) for item in members
                    )
                ),
                "targeted_verification": list(
                    dict.fromkeys(
                        str(check)
                        for item in members
                        for check in item["targeted_verification"]
                    )
                ),
            }
        )
    return reviews, groups


def _assemble_surface_decision(
    decision: dict[str, Any],
    *,
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    _closed(decision, SURFACE_DECISION_FIELDS, "surface decision")
    if decision.get("schema") != SURFACE_DECISION_SCHEMA:
        raise CreditAnalysisError("surface decision schema is invalid")
    pending = state.get("pending")
    if not isinstance(pending, Mapping) or pending.get("surface_id") == "synthesis":
        raise CreditAnalysisError("a public surface decision is not pending")
    known_calls = set(evidence["call_inventory"])
    focused_runs = set(evidence["semantic_coverage"]["run_ids"])
    cluster_calls = {
        str(partition["cluster_id"]): list(partition["call_ids"])
        for partition in _candidate_cluster_partition(
            list(pending["candidate_call_ids"]), evidence, focused_runs
        )
    }
    findings = [
        _decision_finding(
            raw, known_calls=known_calls, cluster_calls=cluster_calls
        )
        for raw in _objects(decision.get("findings"), "surface decision findings")
    ]
    risks = [
        _decision_risk(raw, known_calls=known_calls, cluster_calls=cluster_calls)
        for raw in _objects(decision.get("risks"), "surface decision risks")
    ]
    exclusions: list[dict[str, str]] = []
    for raw in _objects(decision.get("exclusions"), "surface decision exclusions"):
        _closed(raw, DECISION_EXCLUSION_FIELDS, "surface decision exclusion")
        reason_code = raw.get("reason_code")
        reason = raw.get("reason")
        if (
            reason_code not in contract["necessary_reason_codes"]
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise CreditAnalysisError("surface decision exclusion is invalid")
        exclusions.extend(
            {
                "call_id": call_id,
                "reason_code": str(reason_code),
                "reason": reason.strip(),
            }
            for call_id in _expand_decision_selectors(
                raw.get("selectors"),
                known_calls,
                "exclusion selectors",
                cluster_calls=cluster_calls,
            )
        )
    exclusion_calls = {item["call_id"] for item in exclusions}
    if len(exclusion_calls) != len(exclusions):
        raise CreditAnalysisError("surface decision exclusions repeat a call")
    finding_calls = {
        call_id for finding in findings for call_id in finding["affected_call_ids"]
    }
    if finding_calls & exclusion_calls:
        raise CreditAnalysisError("a call cannot be both avoidable and necessary")
    risk_calls = {call_id for risk in risks for call_id in risk["affected_call_ids"]}
    dismissal_reason = decision.get("dismissal_reason")
    if not isinstance(dismissal_reason, str) or not dismissal_reason.strip():
        raise CreditAnalysisError("surface decision dismissal reason is required")
    candidates = list(pending["candidate_call_ids"])
    protected = finding_calls | exclusion_calls
    if findings:
        protected |= risk_calls
    dismissals = [
        {"call_id": call_id, "reason": dismissal_reason.strip()}
        for call_id in candidates
        if call_id not in protected
    ]
    nested_refs = [
        ref for item in [*findings, *risks] for ref in item["evidence_refs"]
    ]
    top_refs = list(
        dict.fromkeys(
            [*[_evidence_ref(call_id) for call_id in candidates], *nested_refs]
        )
    )
    if pending["surface_id"] == "helper-contracts":
        helper_reviews, remediation_groups = _helper_decision_metadata(
            findings, contract
        )
    else:
        helper_reviews, remediation_groups = [], []
    result = {
        "schema": contract["surface_result_schema"],
        "analysis_id": state["analysis_id"],
        "pass_id": pending["pass_id"],
        "surface_id": pending["surface_id"],
        "evidence_fingerprint": state["evidence"]["fingerprint"],
        "artifact_paths": {
            "state": state["paths"]["state"],
            "evidence": state["evidence"]["path"],
            "context": pending["context_path"],
            "result": pending["result_path"],
        },
        "reviewed_candidate_call_ids": candidates,
        "confirmed_findings": findings,
        "plausible_risks": risks,
        "dismissed_candidates": dismissals,
        "necessary_call_exclusions": exclusions,
        "evidence_references": top_refs,
        "helper_category_reviews": helper_reviews,
        "remediation_groups": remediation_groups,
    }
    return _validate_surface_result(
        result, state=state, evidence=evidence, contract=contract
    )


def _append_index(path: pathlib.Path, record: Mapping[str, Any]) -> None:
    payload = _canonical_bytes(record)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "ab") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise CreditAnalysisError(f"could not append findings index: {exc}") from exc


def _accept_result(
    state: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    pending = state["pending"]
    ordinal = pending["ordinal"]
    surface_id = pending["surface_id"]
    immutable_path = pathlib.Path(state["paths"]["findings_dir"]) / (
        f"{ordinal:03d}-{surface_id}.json"
    )
    content_hash = _content_hash(result)
    existing_index = _read_index(pathlib.Path(state["paths"]["index"]))
    if len(existing_index) not in {
        len(state["completed"]),
        len(state["completed"]) + 1,
    }:
        raise CreditAnalysisError("findings index changed before acceptance")
    if immutable_path.exists():
        existing = _read_json(immutable_path, f"immutable {surface_id} result")
        if _content_hash(existing) != content_hash:
            raise CreditAnalysisError(f"conflicting immutable {surface_id} result")
    else:
        _exclusive_json(immutable_path, result, f"immutable {surface_id} result")
    sha256 = _file_hash(immutable_path)
    index_record = {
        "schema": INDEX_SCHEMA,
        "ordinal": ordinal,
        "surface_id": surface_id,
        "pass_id": pending["pass_id"],
        "path": str(immutable_path.resolve()),
        "sha256": sha256,
        "content_hash": content_hash,
    }
    if len(existing_index) == len(state["completed"]):
        _append_index(pathlib.Path(state["paths"]["index"]), index_record)
    elif existing_index[-1] != index_record:
        raise CreditAnalysisError("conflicting orphaned findings index record")
    record = {
        "ordinal": ordinal,
        "surface_id": surface_id,
        "pass_id": pending["pass_id"],
        "path": str(immutable_path.resolve()),
        "sha256": sha256,
        "content_hash": content_hash,
        "candidate_call_ids": list(pending["candidate_call_ids"]),
        "context_path": pending["context_path"],
        "result_path": pending["result_path"],
    }
    state["completed"].append(record)
    state["current_index"] += 1
    state["pending"] = None
    return record


def _idempotent_resubmission(
    state: Mapping[str, Any],
    result: Mapping[str, Any],
) -> bool:
    pass_id = result.get("pass_id")
    matches = [record for record in state["completed"] if record["pass_id"] == pass_id]
    if not matches:
        return False
    record = matches[0]
    if result.get("analysis_id") != state["analysis_id"] or result.get("surface_id") != record["surface_id"]:
        raise CreditAnalysisError("resubmission identity conflicts with an accepted pass")
    if _content_hash(result) != record["content_hash"]:
        raise CreditAnalysisError("conflicting resubmission for an accepted pass")
    return True


def command_advance(
    state_path: pathlib.Path,
    result_path: pathlib.Path,
) -> dict[str, Any]:
    state, evidence, contract = _load_state(state_path)
    if state["finalized"]:
        raise CreditAnalysisError("analysis is already finalized")
    result_file = _existing_file(str(result_path), "surface result")
    result = _read_json(result_file, "surface result")
    if _idempotent_resubmission(state, result):
        return _public_status(state)
    pending = state.get("pending")
    if not isinstance(pending, Mapping):
        raise CreditAnalysisError("no surface pass is pending")
    if pending["surface_id"] == "synthesis":
        raise CreditAnalysisError("synthesis must be submitted through finalize")
    if result_file.resolve() != pathlib.Path(pending["result_path"]).resolve():
        raise CreditAnalysisError("result path is not the exact pending path")
    normalized = _validate_surface_result(
        result,
        state=state,
        evidence=evidence,
        contract=contract,
    )
    _accept_result(state, normalized)
    _save_state(state)
    if state["current_index"] < len(state["queue"]):
        _open_pending(state, evidence, contract)
        _save_state(state)
    _verify_completed(state)
    return _public_status(state)


def command_status(state_path: pathlib.Path) -> dict[str, Any]:
    state, _, _ = _load_state(state_path)
    return _public_status(state)


def _public_surface_results(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        result
        for result in _accepted_payloads(state)
        if result.get("surface_id") != "synthesis"
    ]


def _finding_inventory(
    state: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, dict[str, Any]]]:
    findings: dict[str, dict[str, Any]] = {}
    finding_surfaces: dict[str, str] = {}
    risks: dict[str, dict[str, Any]] = {}
    for result in _public_surface_results(state):
        surface_id = result["surface_id"]
        for finding in result["confirmed_findings"]:
            finding_id = finding["id"]
            if finding_id in findings:
                raise CreditAnalysisError(f"duplicate accepted finding ID: {finding_id}")
            findings[finding_id] = finding
            finding_surfaces[finding_id] = surface_id
        for risk in result["plausible_risks"]:
            risk_id = risk["id"]
            if risk_id in risks:
                raise CreditAnalysisError(f"duplicate accepted risk ID: {risk_id}")
            risks[risk_id] = risk
    return findings, finding_surfaces, risks


def _synthesis_remaining_calls(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    findings: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Return calls not already claimed by a finding or surface exclusion."""

    claimed_calls = {
        str(call_id)
        for finding in findings.values()
        if finding["waste_kind"] != "context-volume"
        for call_id in finding["affected_call_ids"]
    }
    excluded_calls = {
        str(exclusion["call_id"])
        for surface in _public_surface_results(state)
        for exclusion in surface["necessary_call_exclusions"]
    }
    return [
        str(call_id)
        for call_id in evidence["call_inventory"]
        if call_id not in claimed_calls and call_id not in excluded_calls
    ]


def _validated_classification_groups(
    value: Any,
    *,
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    findings: Mapping[str, Mapping[str, Any]],
    dispositions: Mapping[str, Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Expand judgments while refusing unsupported semantic necessity claims."""

    inventory = list(evidence["call_inventory"])
    necessary_evidence: defaultdict[str, set[tuple[str, str]]] = defaultdict(set)
    for surface in _public_surface_results(state):
        for exclusion in surface["necessary_call_exclusions"]:
            necessary_evidence[str(exclusion["call_id"])].add(
                (str(exclusion["reason_code"]), str(exclusion["reason"]).strip())
            )
    groups: list[dict[str, Any]] = []
    group_by_position: dict[int, dict[str, Any]] = {}
    for index, raw in enumerate(
        _objects(value, "classification groups"), start=1
    ):
        _closed(raw, CLASSIFICATION_GROUP_FIELDS, "classification group")
        positions = _positive_integers(
            raw.get("inventory_positions"),
            f"classification group {index} inventory positions",
        )
        category = raw.get("classification")
        finding_id = raw.get("primary_finding_id")
        reason_code = raw.get("reason_code")
        reason = raw.get("reason")
        if category not in contract["call_classifications"]:
            raise CreditAnalysisError(
                f"classification group {index} category is invalid"
            )
        if not isinstance(reason, str) or not reason.strip():
            raise CreditAnalysisError(
                f"classification group {index} reason is required"
            )
        if category == "necessary":
            if (
                finding_id is not None
                or reason_code not in contract["necessary_reason_codes"]
            ):
                raise CreditAnalysisError(
                    f"classification group {index} necessary reason is invalid"
                )
        elif category in {"unassessed", "reviewed_no_confirmed_waste"}:
            if finding_id is not None or reason_code is not None:
                raise CreditAnalysisError(
                    f"classification group {index} non-finding mapping is invalid"
                )
        else:
            if (
                not isinstance(finding_id, str)
                or finding_id not in findings
                or reason_code is not None
            ):
                raise CreditAnalysisError(
                    f"classification group {index} avoidable mapping is invalid"
                )
            expected_category = (
                "avoidable_implemented"
                if findings[finding_id]["implementation_status"] == "implemented"
                else "avoidable_unimplemented"
            )
            if category != expected_category:
                raise CreditAnalysisError(
                    f"classification group {index} implementation status disagrees"
                )
        normalized = {
            "classification": category,
            "inventory_positions": positions,
            "primary_finding_id": finding_id,
            "reason_code": reason_code,
            "reason": reason.strip(),
        }
        for position in positions:
            if position > len(inventory):
                raise CreditAnalysisError(
                    f"classification group {index} position is outside the inventory"
                )
            if position in group_by_position:
                raise CreditAnalysisError(
                    f"classification position is assigned more than once: {position}"
                )
            call_id = inventory[position - 1]
            if category == "necessary" and (
                str(reason_code), reason.strip()
            ) not in necessary_evidence.get(call_id, set()):
                raise CreditAnalysisError(
                    "necessary classification lacks an exact accepted surface "
                    f"exclusion at inventory position {position}"
                )
            if category.startswith("avoidable_") and call_id not in dispositions[
                str(finding_id)
            ]["primary_call_ids"]:
                raise CreditAnalysisError(
                    f"primary finding mapping disagrees at inventory position {position}"
                )
            group_by_position[position] = normalized
        groups.append(normalized)
    expected_positions = set(range(1, len(inventory) + 1))
    if set(group_by_position) != expected_positions:
        raise CreditAnalysisError(
            "classification groups must cover every inventory position exactly once"
        )

    classifications: list[dict[str, Any]] = []
    classification_by_call: dict[str, dict[str, Any]] = {}
    primary_by_finding: dict[str, set[str]] = defaultdict(set)
    for position, call_id in enumerate(inventory, start=1):
        group = group_by_position[position]
        classification = {
            "call_id": call_id,
            "classification": group["classification"],
            "primary_finding_id": group["primary_finding_id"],
            "reason_code": group["reason_code"],
            "reason": group["reason"],
        }
        classifications.append(classification)
        classification_by_call[call_id] = classification
        finding_id = classification["primary_finding_id"]
        if isinstance(finding_id, str):
            primary_by_finding[finding_id].add(call_id)
    for finding_id, disposition in dispositions.items():
        if primary_by_finding[finding_id] != set(disposition["primary_call_ids"]):
            raise CreditAnalysisError(
                "finding primary calls are multiply or inconsistently assigned: "
                f"{finding_id}"
            )
        for call_id in disposition["secondary_call_ids"]:
            if not classification_by_call[call_id]["classification"].startswith(
                "avoidable_"
            ):
                raise CreditAnalysisError(
                    f"secondary avoidable evidence lacks an avoidable primary: {call_id}"
                )
    return groups, classifications


def _assemble_synthesis_decision(
    decision: dict[str, Any],
    *,
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    _closed(decision, SYNTHESIS_DECISION_FIELDS, "synthesis decision")
    if decision.get("schema") != SYNTHESIS_DECISION_SCHEMA:
        raise CreditAnalysisError("synthesis decision schema is invalid")
    pending = state.get("pending")
    if not isinstance(pending, Mapping) or pending.get("surface_id") != "synthesis":
        raise CreditAnalysisError("internal synthesis is not pending")
    findings, _, risks = _finding_inventory(state)
    finding_order = _strings(
        decision.get("finding_order"), "synthesis decision finding order", allow_empty=True
    )
    risk_order = _strings(
        decision.get("risk_order"), "synthesis decision risk order", allow_empty=True
    )
    if set(finding_order) != set(findings) or len(finding_order) != len(findings):
        raise CreditAnalysisError("synthesis decision must rank every finding once")
    if set(risk_order) != set(risks) or len(risk_order) != len(risks):
        raise CreditAnalysisError("synthesis decision must rank every risk once")

    remaining_calls = _synthesis_remaining_calls(state, evidence, findings)
    focused_runs = set(evidence["semantic_coverage"]["run_ids"])
    remaining_partitions = _candidate_cluster_partition(
        remaining_calls, evidence, focused_runs
    )
    remaining_cluster_calls = {
        str(partition["cluster_id"]): list(partition["call_ids"])
        for partition in remaining_partitions
    }
    inventory = list(evidence["call_inventory"])
    position_by_call = {
        call_id: position for position, call_id in enumerate(inventory, start=1)
    }
    claimed_by_call: dict[str, str] = {}
    dispositions: list[dict[str, Any]] = []
    for finding_id in finding_order:
        finding = findings[finding_id]
        if finding["waste_kind"] == "context-volume":
            primary: list[str] = []
            secondary: list[str] = []
        else:
            primary = []
            secondary = []
            for call_id in finding["affected_call_ids"]:
                if call_id in claimed_by_call:
                    secondary.append(call_id)
                else:
                    claimed_by_call[call_id] = finding_id
                    primary.append(call_id)
        dispositions.append(
            {
                "finding_id": finding_id,
                "primary_call_ids": primary,
                "secondary_call_ids": secondary,
            }
        )

    classification_groups: list[dict[str, Any]] = []
    for disposition in dispositions:
        positions = sorted(
            position_by_call[call_id]
            for call_id in disposition["primary_call_ids"]
        )
        if not positions:
            continue
        finding = findings[disposition["finding_id"]]
        classification_groups.append(
            {
                "classification": (
                    "avoidable_implemented"
                    if finding["implementation_status"] == "implemented"
                    else "avoidable_unimplemented"
                ),
                "inventory_positions": positions,
                "primary_finding_id": finding["id"],
                "reason_code": None,
                "reason": finding["problem_summary"],
            }
        )

    necessary_by_call: dict[str, dict[str, str]] = {}
    for surface in _public_surface_results(state):
        for exclusion in surface["necessary_call_exclusions"]:
            call_id = exclusion["call_id"]
            if call_id not in claimed_by_call and call_id not in necessary_by_call:
                necessary_by_call[call_id] = exclusion
    necessary_groups: defaultdict[tuple[str, str], list[int]] = defaultdict(list)
    for call_id, exclusion in necessary_by_call.items():
        necessary_groups[(exclusion["reason_code"], exclusion["reason"])].append(
            position_by_call[call_id]
        )
    for (reason_code, reason), positions in necessary_groups.items():
        classification_groups.append(
            {
                "classification": "necessary",
                "inventory_positions": sorted(positions),
                "primary_finding_id": None,
                "reason_code": reason_code,
                "reason": reason,
            }
        )
    semantically_assessed_calls: set[str] = set()
    selected_clusters: set[str] = set()
    for index, raw in enumerate(
        _objects(
            decision.get("remaining_call_assessments"),
            "synthesis remaining-call assessments",
        ),
        start=1,
    ):
        _closed(raw, SYNTHESIS_ASSESSMENT_FIELDS, "synthesis call assessment")
        cluster_ids = _strings(
            raw.get("cluster_ids"),
            f"synthesis call assessment {index} cluster IDs",
        )
        duplicate_clusters = selected_clusters & set(cluster_ids)
        if duplicate_clusters:
            raise CreditAnalysisError(
                "synthesis call assessment repeats cluster: "
                f"{sorted(duplicate_clusters)[0]}"
            )
        selected_clusters.update(cluster_ids)
        selected_calls: list[str] = []
        for cluster_id in cluster_ids:
            if cluster_id not in remaining_cluster_calls:
                raise CreditAnalysisError(
                    f"synthesis call assessment selects unknown cluster: {cluster_id}"
                )
            selected_calls.extend(remaining_cluster_calls[cluster_id])
        assessment_classification = raw.get("classification")
        assessment_reason_code = raw.get("reason_code")
        assessment_reason = raw.get("reason")
        if not isinstance(assessment_reason, str) or not assessment_reason.strip():
            raise CreditAnalysisError(
                f"synthesis call assessment {index} reason is required"
            )
        if assessment_classification == "unassessed":
            if assessment_reason_code is not None:
                raise CreditAnalysisError(
                    f"synthesis call assessment {index} unassessed reason is invalid"
                )
        else:
            raise CreditAnalysisError(
                "synthesis remaining-call assessments may only be unassessed; "
                "necessary calls must come from accepted surface exclusions"
            )
        semantically_assessed_calls.update(selected_calls)
        classification_groups.append(
            {
                "classification": assessment_classification,
                "inventory_positions": sorted(
                    position_by_call[call_id] for call_id in selected_calls
                ),
                "primary_finding_id": None,
                "reason_code": assessment_reason_code,
                "reason": assessment_reason.strip(),
            }
        )
    reviewed_positions = [
        position_by_call[call_id]
        for call_id in inventory
        if call_id not in claimed_by_call
        and call_id not in necessary_by_call
        and call_id not in semantically_assessed_calls
    ]
    if reviewed_positions:
        classification_groups.append(
            {
                "classification": "reviewed_no_confirmed_waste",
                "inventory_positions": reviewed_positions,
                "primary_finding_id": None,
                "reason_code": None,
                "reason": (
                    "Every relevant surface reviewed these calls without confirming "
                    "avoidable waste or a necessary exclusion."
                ),
            }
        )
    unassessed_count = sum(
        len(group["inventory_positions"])
        for group in classification_groups
        if group["classification"] == "unassessed"
    )
    if state["mode"] == "full-analysis" and unassessed_count * 2 > len(inventory):
        raise CreditAnalysisError(
            "full-analysis synthesis leaves "
            f"{unassessed_count} of {len(inventory)} calls unassessed; "
            "assess enough clusters to keep unassessed at or below 50% and "
            "resubmit the same synthesis pass"
        )

    secondary_by_call: defaultdict[str, list[str]] = defaultdict(list)
    for disposition in dispositions:
        for call_id in disposition["secondary_call_ids"]:
            secondary_by_call[call_id].append(disposition["finding_id"])
    secondary_mappings = [
        {"call_id": call_id, "finding_ids": finding_ids}
        for call_id, finding_ids in sorted(
            secondary_by_call.items(), key=lambda item: position_by_call[item[0]]
        )
    ]

    grouped: defaultdict[tuple[str, str | None], list[str]] = defaultdict(list)
    for finding_id in finding_order:
        finding = findings[finding_id]
        grouped[(finding["producer_type"], finding["producer_owner"])].append(
            finding_id
        )
    producer_groups: list[dict[str, Any]] = []
    for index, ((producer_type, owner), finding_ids) in enumerate(
        grouped.items(), start=1
    ):
        producer_groups.append(
            {
                "id": f"producer-group-{index:03d}",
                "producer_type": producer_type,
                "owner": owner,
                "finding_ids": finding_ids,
                "recommended_control": " ".join(
                    dict.fromkeys(
                        findings[finding_id]["proposed_durable_control"]
                        for finding_id in finding_ids
                    )
                ),
                "targeted_verification": list(
                    dict.fromkeys(
                        check
                        for finding_id in finding_ids
                        for check in findings[finding_id]["targeted_verification"]
                    )
                ),
            }
        )
    result = {
        "schema": contract["synthesis_result_schema"],
        "analysis_id": state["analysis_id"],
        "pass_id": pending["pass_id"],
        "surface_id": "synthesis",
        "evidence_fingerprint": state["evidence"]["fingerprint"],
        "artifact_paths": {
            "state": state["paths"]["state"],
            "evidence": state["evidence"]["path"],
            "context": pending["context_path"],
            "result": pending["result_path"],
        },
        "finding_order": finding_order,
        "risk_order": risk_order,
        "finding_dispositions": dispositions,
        "classification_groups": classification_groups,
        "secondary_call_mappings": secondary_mappings,
        "producer_groups": producer_groups,
    }
    return _validate_synthesis(
        result, state=state, evidence=evidence, contract=contract
    )


def _validate_synthesis(
    result: dict[str, Any],
    *,
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    _closed(result, SYNTHESIS_FIELDS, "synthesis result")
    pending = state.get("pending")
    if not isinstance(pending, Mapping) or pending.get("surface_id") != "synthesis":
        raise CreditAnalysisError("internal synthesis is not pending")
    expected_identity = {
        "schema": contract["synthesis_result_schema"],
        "analysis_id": state["analysis_id"],
        "pass_id": pending["pass_id"],
        "surface_id": "synthesis",
        "evidence_fingerprint": state["evidence"]["fingerprint"],
    }
    for field, expected in expected_identity.items():
        if result.get(field) != expected:
            raise CreditAnalysisError(f"synthesis {field} does not match pending state")
    expected_artifacts = {
        "state": state["paths"]["state"],
        "evidence": state["evidence"]["path"],
        "context": pending["context_path"],
        "result": pending["result_path"],
    }
    if result.get("artifact_paths") != expected_artifacts:
        raise CreditAnalysisError("synthesis artifact paths do not match pending state")
    findings, _, risks = _finding_inventory(state)
    finding_order = _strings(
        result.get("finding_order"), "synthesis finding order", allow_empty=True
    )
    if set(finding_order) != set(findings) or len(finding_order) != len(findings):
        raise CreditAnalysisError("synthesis must rank every accepted finding exactly once")
    risk_order = _strings(result.get("risk_order"), "synthesis risk order", allow_empty=True)
    if set(risk_order) != set(risks) or len(risk_order) != len(risks):
        raise CreditAnalysisError("synthesis must preserve every plausible risk")
    known_calls = set(evidence["call_inventory"])

    dispositions: list[dict[str, Any]] = []
    disposition_by_id: dict[str, dict[str, Any]] = {}
    for raw in _objects(result.get("finding_dispositions"), "finding dispositions"):
        _closed(raw, DISPOSITION_FIELDS, "finding disposition")
        finding_id = raw.get("finding_id")
        if finding_id not in findings or finding_id in disposition_by_id:
            raise CreditAnalysisError(f"finding disposition is invalid: {finding_id}")
        primary = _strings(
            raw.get("primary_call_ids"),
            f"finding {finding_id} primary calls",
            allow_empty=True,
        )
        secondary = _strings(
            raw.get("secondary_call_ids"),
            f"finding {finding_id} secondary calls",
            allow_empty=True,
        )
        if set(primary) & set(secondary):
            raise CreditAnalysisError(f"finding {finding_id} repeats primary as secondary")
        if not set(primary + secondary).issubset(known_calls):
            raise CreditAnalysisError(f"finding {finding_id} maps an unknown call")
        if findings[finding_id]["waste_kind"] == "context-volume":
            if primary or secondary:
                raise CreditAnalysisError(
                    f"context-volume finding {finding_id} must not claim call savings"
                )
        elif set(primary + secondary) != set(
            findings[finding_id]["affected_call_ids"]
        ):
            raise CreditAnalysisError(
                f"finding {finding_id} call mapping drops surface evidence"
            )
        normalized = {
            "finding_id": finding_id,
            "primary_call_ids": primary,
            "secondary_call_ids": secondary,
        }
        dispositions.append(normalized)
        disposition_by_id[finding_id] = normalized
    if set(disposition_by_id) != set(findings):
        raise CreditAnalysisError("synthesis lacks a disposition for an accepted finding")

    classification_groups, classifications = _validated_classification_groups(
        result.get("classification_groups"),
        state=state,
        evidence=evidence,
        findings=findings,
        dispositions=disposition_by_id,
        contract=contract,
    )
    classification_by_call = {
        item["call_id"]: item for item in classifications
    }

    secondary_mappings: list[dict[str, Any]] = []
    secondary_by_call: dict[str, set[str]] = defaultdict(set)
    for raw in _objects(result.get("secondary_call_mappings"), "secondary call mappings"):
        _closed(raw, SECONDARY_FIELDS, "secondary call mapping")
        call_id = raw.get("call_id")
        ids = _strings(raw.get("finding_ids"), f"secondary findings for {call_id}")
        if (
            not isinstance(call_id, str)
            or call_id not in known_calls
            or call_id in secondary_by_call
            or not set(ids).issubset(findings)
        ):
            raise CreditAnalysisError(f"secondary call mapping is invalid: {call_id}")
        if classification_by_call[call_id]["primary_finding_id"] in ids:
            raise CreditAnalysisError(f"primary finding repeated as secondary: {call_id}")
        secondary_by_call[call_id] = set(ids)
        secondary_mappings.append({"call_id": call_id, "finding_ids": ids})
    expected_secondary: dict[str, set[str]] = defaultdict(set)
    for finding_id, disposition in disposition_by_id.items():
        for call_id in disposition["secondary_call_ids"]:
            expected_secondary[call_id].add(finding_id)
    if dict(secondary_by_call) != dict(expected_secondary):
        raise CreditAnalysisError("secondary mappings do not preserve every overlap")

    producer_groups: list[dict[str, Any]] = []
    grouped_findings: list[str] = []
    group_ids: set[str] = set()
    for raw in _objects(result.get("producer_groups"), "producer groups"):
        _closed(raw, PRODUCER_GROUP_FIELDS, "producer group")
        group_id = _identifier(raw.get("id"), "producer group id")
        producer_type = raw.get("producer_type")
        owner = raw.get("owner")
        ids = _strings(raw.get("finding_ids"), f"producer group {group_id} findings")
        control = raw.get("recommended_control")
        verification = _strings(
            raw.get("targeted_verification"), f"producer group {group_id} verification"
        )
        if (
            group_id in group_ids
            or producer_type not in contract["producer_types"]
            or owner is not None and (not isinstance(owner, str) or not owner.strip())
            or not set(ids).issubset(findings)
            or not isinstance(control, str)
            or not control.strip()
        ):
            raise CreditAnalysisError(f"producer group is invalid: {group_id}")
        if any(
            findings[finding_id]["producer_type"] != producer_type
            or findings[finding_id]["producer_owner"] != owner
            for finding_id in ids
        ):
            raise CreditAnalysisError(f"producer group mixes owners or types: {group_id}")
        required_checks = {
            check
            for finding_id in ids
            for check in findings[finding_id]["targeted_verification"]
        }
        if not required_checks.issubset(verification):
            raise CreditAnalysisError(f"producer group drops targeted verification: {group_id}")
        group_ids.add(group_id)
        grouped_findings.extend(ids)
        producer_groups.append(
            {
                "id": group_id,
                "producer_type": producer_type,
                "owner": owner.strip() if isinstance(owner, str) else None,
                "finding_ids": ids,
                "recommended_control": control.strip(),
                "targeted_verification": verification,
            }
        )
    if sorted(grouped_findings) != sorted(findings) or len(grouped_findings) != len(set(grouped_findings)):
        raise CreditAnalysisError("producer groups must partition every confirmed finding")
    return {
        **result,
        "finding_order": finding_order,
        "risk_order": risk_order,
        "finding_dispositions": dispositions,
        "classification_groups": classification_groups,
        "secondary_call_mappings": secondary_mappings,
        "producer_groups": producer_groups,
    }


def _group_standalone_findings(
    findings: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str | None, str], list[Mapping[str, Any]]] = defaultdict(list)
    for finding in findings:
        key = (
            str(finding["producer_type"]),
            finding["producer_owner"],
            str(finding["proposed_durable_control"]),
        )
        groups[key].append(finding)
    result: list[dict[str, Any]] = []
    for index, ((producer_type, owner, control), members) in enumerate(groups.items(), start=1):
        result.append(
            {
                "id": f"standalone-group-{index}",
                "producer_type": producer_type,
                "owner": owner,
                "finding_ids": [str(member["id"]) for member in members],
                "recommended_control": control,
                "targeted_verification": list(
                    dict.fromkeys(
                        check
                        for member in members
                        for check in member["targeted_verification"]
                    )
                ),
            }
        )
    return result


def _build_standalone_final(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    accepted = _accepted_payloads(state)
    if len(accepted) != 1 or accepted[0].get("surface_id") != state["action"]:
        raise CreditAnalysisError("standalone finalization requires one accepted surface")
    surface = accepted[0]
    affected_calls = {
        call_id
        for finding in surface["confirmed_findings"]
        if finding["waste_kind"] == "model-calls"
        for call_id in finding["affected_call_ids"]
    }
    findings = [
        {
            **finding,
            "source_surface": surface["surface_id"],
            "deduplicated_avoidable_call_count": (
                len(set(finding["affected_call_ids"]))
                if finding["waste_kind"] == "model-calls"
                else 0
            ),
        }
        for finding in surface["confirmed_findings"]
    ]
    priced_cost: dict[str, Any] | None = None
    if evidence["pricing"].get("provided"):
        call_by_id = {call["call_id"]: call for call in _all_calls(evidence)}
        avoidable_cost = sum(
            float(call_by_id[call_id].get("estimated_credit_cost") or 0)
            for call_id in affected_calls
        )
        priced_cost = {
            "total": evidence["totals"].get("estimated_credit_cost"),
            "selected_surface_observed_avoidable": round(avoidable_cost, 12),
        }
    return {
        "schema": contract["final_result_schema"],
        "analysis_id": state["analysis_id"],
        "mode": "standalone",
        "selected_surface": state["action"],
        "scope_limitation": (
            "Conclusions are limited to the selected surface and are not a "
            "whole-thread credit reconciliation."
        ),
        "evidence_fingerprint": state["evidence"]["fingerprint"],
        "source": state["source"],
        "window": state["window"],
        "accepted_surface_results": accepted,
        "confirmed_findings": findings,
        "plausible_risks": surface["plausible_risks"],
        "dismissals": surface["dismissed_candidates"],
        "necessary_call_exclusions": surface["necessary_call_exclusions"],
        "primary_call_mappings": [],
        "secondary_call_mappings": [],
        "producer_grouped_recommendations": _group_standalone_findings(findings),
        "totals": {
            "total_model_calls": len(evidence["call_inventory"]),
            "surface_candidates": len(surface["reviewed_candidate_call_ids"]),
            "surface_observed_avoidable_calls": len(affected_calls),
            "confirmed_findings": len(findings),
            "plausible_risks": len(surface["plausible_risks"]),
            "classification_scope": "selected-surface-only",
        },
        "pricing": evidence["pricing"],
        "priced_cost": priced_cost,
        "retained_paths": {
            "evidence": state["evidence"]["path"],
            "findings_index": state["paths"]["index"],
            "findings_directory": state["paths"]["findings_dir"],
            "final_machine_result": state["paths"]["final_result"],
        },
    }


def _build_full_final(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    accepted = _accepted_payloads(state)
    if [item.get("surface_id") for item in accepted] != contract["full_queue"]:
        raise CreditAnalysisError("full analysis did not accept every fixed pass exactly once")
    synthesis = accepted[-1]
    findings, finding_surfaces, risks = _finding_inventory(state)
    dispositions = {
        item["finding_id"]: item for item in synthesis["finding_dispositions"]
    }
    group_by_finding = {
        finding_id: group["id"]
        for group in synthesis["producer_groups"]
        for finding_id in group["finding_ids"]
    }
    final_findings: list[dict[str, Any]] = []
    roi_calculations: list[dict[str, Any]] = []
    for rank, finding_id in enumerate(synthesis["finding_order"], start=1):
        finding = findings[finding_id]
        disposition = dispositions[finding_id]
        recurrence = finding["recurrence"]
        net = round(
            recurrence["calls_saved_per_affected_run"]
            - recurrence["additional_recurring_calls_per_affected_run"],
            6,
        )
        low_case = round(
            net * recurrence["affected_similar_run_frequency_range"][0], 6
        )
        roi = {
            "finding_id": finding_id,
            "net_calls_saved_per_affected_run": net,
            "estimated_calls_saved_per_similar_run": recurrence[
                "estimated_calls_saved_per_similar_run"
            ],
            "low_case_calls_saved_per_similar_run": low_case,
            "one_time_implementation_cost": finding[
                "one_time_implementation_cost"
            ],
            "ongoing_complexity": finding["complexity"],
            "confidence": finding["confidence"],
            "assumptions": recurrence["assumptions"],
        }
        roi_calculations.append(roi)
        final_findings.append(
            {
                **finding,
                "source_surface": finding_surfaces[finding_id],
                "expected_value_rank": rank,
                "primary_call_ids": disposition["primary_call_ids"],
                "secondary_call_ids": disposition["secondary_call_ids"],
                "deduplicated_avoidable_call_count": len(
                    disposition["primary_call_ids"]
                ),
                "producer_group_id": group_by_finding[finding_id],
                "roi": roi,
            }
        )
    _, classifications = _validated_classification_groups(
        synthesis["classification_groups"],
        state=state,
        evidence=evidence,
        findings=findings,
        dispositions=dispositions,
        contract=contract,
    )
    classification_totals = Counter(
        item["classification"] for item in classifications
    )
    call_by_id = {call["call_id"]: call for call in _all_calls(evidence)}
    pricing_provided = bool(evidence["pricing"].get("provided"))
    priced_cost: dict[str, Any] | None = None
    if pricing_provided:
        category_costs: defaultdict[str, float] = defaultdict(float)
        for item in classifications:
            cost = call_by_id[item["call_id"]].get("estimated_credit_cost")
            if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                category_costs[item["classification"]] += float(cost)
        priced_cost = {
            "total": evidence["totals"].get("estimated_credit_cost"),
            "necessary": round(category_costs["necessary"], 12),
            "avoidable_implemented": round(
                category_costs["avoidable_implemented"], 12
            ),
            "avoidable_unimplemented": round(
                category_costs["avoidable_unimplemented"], 12
            ),
            "reviewed_no_confirmed_waste": round(
                category_costs["reviewed_no_confirmed_waste"], 12
            ),
            "unassessed": round(category_costs["unassessed"], 12),
        }
    surface_totals = {}
    category_totals: Counter[str] = Counter()
    all_dismissals: list[dict[str, Any]] = []
    all_exclusions: list[dict[str, Any]] = []
    for surface in accepted[:-1]:
        surface_totals[surface["surface_id"]] = {
            "candidates": len(surface["reviewed_candidate_call_ids"]),
            "confirmed_findings": len(surface["confirmed_findings"]),
            "plausible_risks": len(surface["plausible_risks"]),
            "dismissals": len(surface["dismissed_candidates"]),
            "necessary_exclusions": len(surface["necessary_call_exclusions"]),
        }
        all_dismissals.extend(
            {"surface_id": surface["surface_id"], **item}
            for item in surface["dismissed_candidates"]
        )
        all_exclusions.extend(
            {"surface_id": surface["surface_id"], **item}
            for item in surface["necessary_call_exclusions"]
        )
        for finding in surface["confirmed_findings"]:
            category_totals.update(finding["helper_categories"])
    avoidable = (
        classification_totals["avoidable_implemented"]
        + classification_totals["avoidable_unimplemented"]
    )
    protocol_overhead = sum(
        1
        for item in classifications
        if item["classification"] == "necessary"
        and item["reason_code"] == "protocol-overhead"
    )
    return {
        "schema": contract["final_result_schema"],
        "analysis_id": state["analysis_id"],
        "mode": "full-analysis",
        "selected_surface": None,
        "scope_limitation": None,
        "evidence_fingerprint": state["evidence"]["fingerprint"],
        "source": state["source"],
        "window": state["window"],
        "accepted_surface_results": accepted,
        "confirmed_findings": final_findings,
        "plausible_risks": [risks[risk_id] for risk_id in synthesis["risk_order"]],
        "dismissals": all_dismissals,
        "necessary_call_exclusions": all_exclusions,
        "primary_call_mappings": classifications,
        "secondary_call_mappings": synthesis["secondary_call_mappings"],
        "producer_grouped_recommendations": synthesis["producer_groups"],
        "roi_inputs_and_calculations": roi_calculations,
        "surface_totals": surface_totals,
        "helper_category_totals": dict(sorted(category_totals.items())),
        "totals": {
            "total_model_calls": len(evidence["call_inventory"]),
            "necessary_calls": classification_totals["necessary"],
            "protocol_overhead_calls": protocol_overhead,
            "reviewed_no_confirmed_waste_calls": classification_totals[
                "reviewed_no_confirmed_waste"
            ],
            "unassessed_calls": classification_totals["unassessed"],
            "avoidable_calls": avoidable,
            "avoidable_implemented_calls": classification_totals[
                "avoidable_implemented"
            ],
            "avoidable_unimplemented_calls": classification_totals[
                "avoidable_unimplemented"
            ],
            "confirmed_findings": len(final_findings),
            "plausible_risks": len(risks),
        },
        "pricing": evidence["pricing"],
        "priced_cost": priced_cost,
        "retained_paths": {
            "evidence": state["evidence"]["path"],
            "findings_index": state["paths"]["index"],
            "findings_directory": state["paths"]["findings_dir"],
            "final_machine_result": state["paths"]["final_result"],
        },
    }


def _write_final_result(path: pathlib.Path, value: Mapping[str, Any]) -> str:
    if path.exists():
        existing = _read_json(path, "final machine result")
        if _content_hash(existing) != _content_hash(value):
            raise CreditAnalysisError("conflicting final machine result already exists")
    else:
        _exclusive_json(path, value, "final machine result")
    return _file_hash(path)


def _cleanup_transients(state: Mapping[str, Any]) -> None:
    cleanup = state.get("cleanup")
    if not isinstance(cleanup, Mapping) or cleanup.get("owner") != "credit-analysis-workflow":
        raise CreditAnalysisError("cleanup ownership is invalid")
    context_root = pathlib.Path(state["paths"]["context_dir"]).resolve()
    pending_root = pathlib.Path(state["paths"]["pending_dir"]).resolve()
    raw_paths = cleanup.get("transient_paths")
    paths = _strings(raw_paths, "cleanup transient paths", allow_empty=True)
    for raw_path in paths:
        path = pathlib.Path(raw_path).resolve()
        if not any(
            path == root or path.is_relative_to(root)
            for root in (context_root, pending_root)
        ):
            raise CreditAnalysisError(f"cleanup path escapes controller ownership: {path}")
        if path.is_symlink():
            raise CreditAnalysisError(f"refusing to delete symlinked transient: {path}")
        if path.exists():
            if not path.is_file():
                raise CreditAnalysisError(f"transient path is not a file: {path}")
            path.unlink()
    for directory in (context_root, pending_root):
        if directory.exists() and directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()


def _finding_savings(finding: Mapping[str, Any]) -> float:
    roi = finding.get("roi")
    if isinstance(roi, Mapping):
        value = roi.get("estimated_calls_saved_per_similar_run")
    else:
        recurrence = finding.get("recurrence")
        value = (
            recurrence.get("estimated_calls_saved_per_similar_run")
            if isinstance(recurrence, Mapping)
            else 0
        )
    return float(value) if isinstance(value, (int, float)) else 0.0


def _finding_presentation_key(finding: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        0 if finding.get("complexity") == "Minimal" else 1,
        -_finding_savings(finding),
        -int(finding.get("deduplicated_avoidable_call_count", 0)),
        str(finding.get("id", "")),
    )


def _render_final_report(final: Mapping[str, Any]) -> str:
    """Render every finding without exposing controller bookkeeping fields."""

    all_findings = list(final.get("confirmed_findings", []))
    findings = sorted(
        (
            finding
            for finding in all_findings
            if finding.get("implementation_status") != "implemented"
        ),
        key=_finding_presentation_key,
    )
    lines = [
        "# Credit-savings analysis",
        "",
        (
            f"Confirmed: {len(all_findings)}; outstanding: {len(findings)}; "
            f"already addressed: {len(all_findings) - len(findings)}"
        ),
        "",
    ]
    if final.get("scope_limitation"):
        lines.extend([str(final["scope_limitation"]), ""])
    if not findings:
        lines.extend(["No outstanding findings.", ""])
    for finding in findings:
        affected = finding.get("primary_call_ids") or finding.get(
            "affected_call_ids", []
        )
        observed_calls = finding.get("deduplicated_avoidable_call_count")
        if not isinstance(observed_calls, int):
            observed_calls = len(affected)
        recurrence = finding.get("recurrence", {})
        owner = finding.get("producer_owner") or finding.get("producer_type")
        lines.extend(
            [
                f"## {finding['title']}",
                "",
                f"Problem: {finding['problem_summary']} The owning producer is {owner}.",
                "",
                f"Evidence: {finding['evidence_narrative']}",
                "",
                f"Fix: {finding['proposed_durable_control']}",
                "",
                "Verification: " + "; ".join(finding["targeted_verification"]),
                "",
                (
                    "Savings: "
                    f"{observed_calls} deduplicated observed call(s); "
                    f"{_finding_savings(finding):g} estimated call(s) per similar run; "
                    f"implementation cost {finding['one_time_implementation_cost']['estimated_model_calls']:g} "
                    f"call(s); complexity {finding['complexity']}."
                ),
            ]
        )
        assumptions = recurrence.get("assumptions", [])
        if assumptions:
            lines.extend(["", "Assumptions: " + "; ".join(assumptions)])
        lines.append("")
    volume_findings = [
        finding for finding in findings if finding.get("waste_kind") == "context-volume"
    ]
    lines.extend(["## Input/output token reduction", ""])
    if not volume_findings:
        lines.extend(["No input/output-volume reduction was confirmed.", ""])
    for finding in volume_findings:
        lines.extend(
            [
                f"- {finding['title']}: {finding['evidence_narrative']} "
                f"Recommended control: {finding['proposed_durable_control']}",
                "",
            ]
        )
    risks = final.get("plausible_risks", [])
    lines.extend(["## Plausible but unverified", ""])
    if not risks:
        lines.extend(["None.", ""])
    for risk in risks:
        verification = risk.get("verification_needed", [])
        lines.extend(
            [
                f"### {risk['description']}",
                "",
                f"Observed: {risk['observed_sequence']}",
                "",
                "Unknown: " + "; ".join(risk["competing_explanations"]),
                "",
                (
                    f"Why not confirmed: {risk['missing_fact']}; choosing between "
                    "the competing explanations would be speculation."
                ),
                "",
                "How to confirm: " + "; ".join(verification),
                "",
            ]
        )
    totals = final.get("totals", {})
    lines.extend(["## Totals", ""])
    if final.get("mode") == "full-analysis":
        lines.extend(
            [
                f"- Avoidable: {totals.get('avoidable_calls', 0)} of "
                f"{totals.get('total_model_calls', 0)} calls.",
                f"- Necessary: {totals.get('necessary_calls', 0)}, including "
                f"{totals.get('protocol_overhead_calls', 0)} protocol-overhead calls.",
                "- Reviewed without confirmed waste: "
                f"{totals.get('reviewed_no_confirmed_waste_calls', 0)} calls.",
                f"- Unassessed: {totals.get('unassessed_calls', 0)} calls. These were "
                "not deterministically treated as necessary.",
            ]
        )
    else:
        lines.append(
            f"- Surface avoidable: {totals.get('surface_observed_avoidable_calls', 0)} "
            f"of {totals.get('surface_candidates', 0)} candidates."
        )
    priced = final.get("priced_cost")
    if isinstance(priced, Mapping):
        lines.append(f"- Priced cost: {json.dumps(priced, sort_keys=True)}")
    retained = final.get("retained_paths", {})
    lines.extend(
        [
            "",
            "Retained analysis result: " + str(retained.get("final_machine_result")),
        ]
    )
    return "\n".join(lines).rstrip()


def _final_packet(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    del evidence, contract
    if state.get("finalized") is not True:
        raise CreditAnalysisError("analysis is not finalized")
    final = _read_json(
        pathlib.Path(state["final_result"]["path"]), "final machine result"
    )
    semantic_total = 6 if state["mode"] == "full-analysis" else 1
    return {
        "schema": FINAL_PACKET_SCHEMA,
        "analysis_id": state["analysis_id"],
        "complete": True,
        "protocol_budget": _protocol_budget(state, semantic_total),
        "report_markdown": _render_final_report(final),
        "retained_result_path": state["final_result"]["path"],
        "retained_evidence_path": state["evidence"]["path"],
    }


def _persist_final_result(
    state: dict[str, Any],
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    _verify_completed(state)
    final_result = (
        _build_full_final(state, evidence, contract)
        if state["mode"] == "full-analysis"
        else _build_standalone_final(state, evidence, contract)
    )
    final_path = pathlib.Path(state["paths"]["final_result"])
    final_hash = _write_final_result(final_path, final_result)
    _cleanup_transients(state)
    state["finalized"] = True
    state["final_result"] = {
        "path": str(final_path.resolve()),
        "sha256": final_hash,
        "content_hash": _content_hash(final_result),
    }
    _save_state(state)
    return _final_packet(state, evidence, contract)


def command_start(request_path: pathlib.Path) -> dict[str, Any]:
    """Collect once and return the first model-ready semantic pass packet."""

    status = command_prepare(request_path)
    return _pass_packet(pathlib.Path(status["state_path"]))


def command_submit(
    state_path: pathlib.Path,
    decision_path: pathlib.Path,
) -> dict[str, Any]:
    """Expand one compact judgment, persist it, and return the next pass."""

    state, evidence, contract = _load_state(state_path)
    if state["finalized"]:
        return _final_packet(state, evidence, contract)
    pending = state.get("pending")
    if not isinstance(pending, Mapping):
        raise CreditAnalysisError("no semantic pass is pending")
    decision_file = _existing_file(str(decision_path), "semantic decision")
    if decision_file.resolve() != pathlib.Path(pending["result_path"]).resolve():
        raise CreditAnalysisError("decision path is not the exact pending path")
    decision = _read_json(decision_file, "semantic decision")
    if pending["surface_id"] == "synthesis":
        normalized = _assemble_synthesis_decision(
            decision, state=state, evidence=evidence, contract=contract
        )
    else:
        normalized = _assemble_surface_decision(
            decision, state=state, evidence=evidence, contract=contract
        )
    _accept_result(state, normalized)
    _save_state(state)
    if pending["surface_id"] == "synthesis" or state["mode"] != "full-analysis":
        return _persist_final_result(state, evidence, contract)
    _open_pending(state, evidence, contract)
    _save_state(state)
    _verify_completed(state)
    return _pass_packet(state_path)


def command_finalize(
    state_path: pathlib.Path,
    result_path: pathlib.Path,
) -> None:
    state, evidence, contract = _load_state(state_path)
    if state["finalized"]:
        return
    result_file = _existing_file(str(result_path), "final result input")
    if state["mode"] == "full-analysis":
        pending = state.get("pending")
        if isinstance(pending, Mapping):
            if pending.get("surface_id") != "synthesis":
                raise CreditAnalysisError("full analysis has an unfinished public surface")
            if result_file.resolve() != pathlib.Path(pending["result_path"]).resolve():
                raise CreditAnalysisError("synthesis path is not the exact pending path")
            synthesis = _validate_synthesis(
                _read_json(result_file, "synthesis result"),
                state=state,
                evidence=evidence,
                contract=contract,
            )
            _accept_result(state, synthesis)
            _save_state(state)
        else:
            if not state["completed"] or state["completed"][-1]["surface_id"] != "synthesis":
                raise CreditAnalysisError("full analysis has no accepted synthesis")
            submitted = _read_json(result_file, "synthesis result")
            if not _idempotent_resubmission(state, submitted):
                raise CreditAnalysisError("final result input is not the accepted synthesis")
    else:
        if state.get("pending") is not None or state["current_index"] != len(state["queue"]):
            raise CreditAnalysisError("standalone surface has not been accepted")
        accepted_path = pathlib.Path(state["completed"][-1]["path"]).resolve()
        if result_file.resolve() != accepted_path:
            raise CreditAnalysisError("standalone finalization requires its accepted result path")
        if _content_hash(_read_json(result_file, "accepted surface result")) != state["completed"][-1]["content_hash"]:
            raise CreditAnalysisError("standalone accepted result changed")
    _persist_final_result(state, evidence, contract)


def _project_selector(raw: Any) -> dict[str, str] | None:
    """Normalize one exact project selector without filesystem discovery."""

    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise CreditAnalysisError("project selector must be an object or null")
    _closed(raw, PROJECT_SELECTOR_FIELDS, "project selector")
    kind = raw.get("kind")
    value = raw.get("value")
    if kind not in {"name", "path", "repository_url"}:
        raise CreditAnalysisError("project selector kind is invalid")
    if not isinstance(value, str) or not value.strip():
        raise CreditAnalysisError("project selector value must be nonempty")
    normalized = value.strip()
    if kind == "name":
        normalized = normalized.casefold()
    elif kind == "repository_url":
        normalized = normalized.rstrip("/").removesuffix(".git").casefold()
    else:
        candidate = pathlib.Path(normalized).expanduser()
        if not candidate.is_absolute():
            raise CreditAnalysisError("project path selector must be absolute")
        normalized = os.path.normcase(os.path.normpath(str(candidate.resolve())))
    return {"kind": str(kind), "value": normalized}


def _project_matches(
    metadata: Mapping[str, Any],
    selector: Mapping[str, str] | None,
) -> bool:
    if selector is None:
        return True
    kind = selector["kind"]
    value = selector["value"]
    if kind == "name":
        aliases = metadata.get("project_aliases")
        return isinstance(aliases, list) and value in aliases
    if kind == "repository_url":
        return metadata.get("normalized_repository_url") == value
    cwd = metadata.get("normalized_cwd")
    if not isinstance(cwd, str):
        return False
    try:
        return pathlib.Path(cwd) == pathlib.Path(value) or pathlib.Path(
            cwd
        ).is_relative_to(pathlib.Path(value))
    except (OSError, ValueError):
        return False


def _batch_request_paths(
    request: Mapping[str, Any],
) -> tuple[pathlib.Path, dict[str, pathlib.Path]]:
    task_root = _task_directory(request.get("task_temp_root"), "task_temp_root")
    manifest_value = request.get("manifest_output")
    if not isinstance(manifest_value, str) or not manifest_value:
        raise CreditAnalysisError("manifest_output must be nonempty text")
    manifest = pathlib.Path(manifest_value).expanduser().resolve()
    if not manifest.parent.is_dir():
        raise CreditAnalysisError("manifest output directory does not exist")
    if manifest.is_symlink() or manifest.is_dir():
        raise CreditAnalysisError("manifest output must be a regular-file path")
    paths = {
        "state": task_root / "batch-state.json",
        "manifest": manifest,
        "requests_dir": task_root / "requests",
        "analyses_dir": task_root / "analyses",
        "evidence_dir": task_root / "evidence",
        "index": task_root / "batch-results.jsonl",
        "batch_summary_context": task_root / "batch-summary-context.json",
        "batch_summary_result": task_root / "batch-summary.json",
        "final_result": task_root / "batch-final-machine-result.json",
    }
    collisions = [path.resolve() for path in paths.values()]
    if len(collisions) != len(set(collisions)):
        raise CreditAnalysisError("batch controller paths must be distinct")
    for key in (
        "requests_dir",
        "analyses_dir",
        "evidence_dir",
        "batch_summary_context",
        "batch_summary_result",
    ):
        try:
            paths[key].resolve().relative_to(task_root)
        except ValueError as exc:
            raise CreditAnalysisError(f"batch {key} escapes task_temp_root") from exc
    return task_root, paths


def _validated_batch_request(
    request_path: pathlib.Path,
    contract: Mapping[str, Any],
    ledger: ModuleType,
) -> dict[str, Any]:
    """Validate one bounded, analysis-only batch request before side effects."""

    request = _read_json(request_path, "batch request")
    _closed(request, BATCH_REQUEST_FIELDS, "batch request")
    if request.get("schema") != contract["batch_request_schema"]:
        raise CreditAnalysisError(
            f"batch request schema must be {contract['batch_request_schema']}"
        )
    if request.get("action") != "full-analysis" or request.get("mode") != "per-thread-batch":
        raise CreditAnalysisError("batch requests must use full-analysis per-thread-batch")
    if request.get("mutation_authority") is not False:
        raise CreditAnalysisError("mutation_authority must be false")
    if request.get("expected_surface_contract_version") != contract[
        "surface_contract_version"
    ]:
        raise CreditAnalysisError("surface contract version mismatch")
    if request.get("expected_source_selection_contract_version") != contract[
        "source_selection_contract_version"
    ]:
        raise CreditAnalysisError("source selection contract version mismatch")
    selector_raw = request.get("selector")
    if not isinstance(selector_raw, dict):
        raise CreditAnalysisError("batch selector must be an object")
    _closed(selector_raw, BATCH_SELECTOR_FIELDS, "batch selector")
    kind = selector_raw.get("kind")
    count = selector_raw.get("count")
    days = selector_raw.get("days")
    if kind == "recent_threads":
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or count < 1
            or days is not None
        ):
            raise CreditAnalysisError(
                "recent_threads requires a positive count and null days"
            )
    elif kind == "recent_days":
        if (
            not isinstance(days, int)
            or isinstance(days, bool)
            or days < 1
            or count is not None
        ):
            raise CreditAnalysisError(
                "recent_days requires positive days and a null count"
            )
    else:
        raise CreditAnalysisError("batch selector kind is invalid")
    project = _project_selector(selector_raw.get("project"))
    try:
        as_of = ledger.parse_utc_timestamp(request.get("as_of"), "batch as_of")
    except RuntimeError as exc:
        raise CreditAnalysisError(str(exc)) from exc
    if as_of > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5):
        raise CreditAnalysisError("batch as_of cannot be in the future")
    task_root, paths = _batch_request_paths(request)
    reserved_existing = [
        path for path in paths.values() if path.exists() or path.is_symlink()
    ]
    if reserved_existing:
        raise CreditAnalysisError(
            f"task_temp_root already contains batch controller state: {reserved_existing[0].name}"
        )
    pricing_value = request.get("pricing_profile")
    pricing = (
        None
        if pricing_value is None
        else _existing_file(pricing_value, "pricing profile")
    )
    if pricing is not None and pricing.resolve() in {
        path.resolve() for path in paths.values()
    }:
        raise CreditAnalysisError("pricing profile collides with a batch path")
    selector = {
        "kind": kind,
        "count": count,
        "days": days,
        "project": project,
    }
    return {
        "request": request,
        "request_path": request_path,
        "request_hash": _file_hash(request_path),
        "task_root": task_root,
        "paths": paths,
        "selector": selector,
        "as_of": as_of,
        "pricing": pricing,
    }


def _select_batch_candidates(
    request: Mapping[str, Any],
    ledger: ModuleType,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, str]]]:
    """Freeze index-ordered candidates and reject ambiguous project names."""

    index = ledger.load_thread_index()
    as_of = request["as_of"]
    selector = request["selector"]
    assert isinstance(as_of, dt.datetime)
    assert isinstance(selector, Mapping)
    start = (
        as_of - dt.timedelta(days=int(selector["days"]))
        if selector["kind"] == "recent_days"
        else None
    )
    candidates: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    for entry in index["entries"]:
        updated_at = ledger.parse_utc_timestamp(
            entry["updated_at"], "thread index updated_at"
        )
        if updated_at > as_of or start is not None and updated_at < start:
            continue
        thread_id = entry["thread_id"]
        try:
            session = ledger.resolve_thread_session(thread_id)
            metadata = ledger.read_session_source_metadata(
                session,
                expected_thread_id=thread_id,
            )
        except (OSError, RuntimeError, ValueError):
            exclusions.append(
                {
                    "thread_id": thread_id,
                    "reason": "unresolvable-session-or-metadata",
                }
            )
            continue
        if not _project_matches(metadata, selector["project"]):
            continue
        candidates.append(
            {
                "thread_id": thread_id,
                "thread_name": entry["thread_name"],
                "updated_at": entry["updated_at"],
                "session": str(session),
                "project": {
                    "key": metadata["project_key"],
                    "cwd": metadata["cwd"],
                    "repository_url": metadata["repository_url"],
                },
            }
        )
    project = selector["project"]
    if isinstance(project, Mapping) and project.get("kind") == "name":
        project_keys = {
            candidate["project"]["key"]
            for candidate in candidates
            if candidate["project"]["key"] is not None
        }
        if len(project_keys) > 1:
            raise CreditAnalysisError(
                "project name is ambiguous; use an exact path or repository URL"
            )
    if not candidates:
        raise CreditAnalysisError("batch selector matched no resolvable threads")
    return index, candidates, exclusions


def _batch_item_paths(
    state: Mapping[str, Any],
    ordinal: int,
    thread_id: str,
) -> dict[str, pathlib.Path]:
    stem = f"{ordinal:03d}-{thread_id}"
    paths = state["paths"]
    return {
        "request": pathlib.Path(paths["requests_dir"]) / f"{stem}.json",
        "analysis_root": pathlib.Path(paths["analyses_dir"]) / stem,
        "evidence": pathlib.Path(paths["evidence_dir"]) / f"{stem}.json",
    }


def _write_or_verify_json(
    path: pathlib.Path,
    value: Mapping[str, Any],
    label: str,
) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise CreditAnalysisError(f"{label} must be a regular file")
        if _content_hash(_read_json(path, label)) != _content_hash(value):
            raise CreditAnalysisError(f"conflicting {label} already exists")
        return
    _exclusive_json(path, value, label)


def _save_batch_state(state: Mapping[str, Any]) -> None:
    _atomic_json(pathlib.Path(state["paths"]["state"]), state, "batch state")


def _batch_manifest(
    state: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    requested_count = state["selector"]["count"]
    return {
        "schema": contract["batch_manifest_schema"],
        "batch_id": state["batch_id"],
        "action": "full-analysis",
        "mode": "per-thread-batch",
        "mutation_authority": False,
        "surface_contract_version": state["surface_contract_version"],
        "source_selection_contract_version": state[
            "source_selection_contract_version"
        ],
        "selector": state["selector"],
        "as_of": state["as_of"],
        "source_index": state["source_index"],
        "selection": {
            "requested_count": requested_count,
            "selected_count": len(state["items"]),
            "excluded_count": len(state["exclusions"]),
            "unexamined_candidate_count": len(state["candidates"])
            - state["candidate_index"],
        },
        "items": state["items"],
        "exclusions": state["exclusions"],
    }


def _batch_item_record(
    candidate: Mapping[str, Any],
    child_paths: Mapping[str, pathlib.Path],
    *,
    ordinal: int,
    source_fingerprint: str,
) -> dict[str, Any]:
    analysis_root = child_paths["analysis_root"]
    return {
        "ordinal": ordinal,
        "thread_id": candidate["thread_id"],
        "thread_name": candidate["thread_name"],
        "updated_at": candidate["updated_at"],
        "project": candidate["project"],
        "session": candidate["session"],
        "source_fingerprint": source_fingerprint,
        "request_path": str(child_paths["request"]),
        "state_path": str(analysis_root / "state.json"),
        "evidence_path": str(child_paths["evidence"]),
        "final_result_path": str(analysis_root / "final-machine-result.json"),
    }


def _recover_prepared_batch_item(
    candidate: Mapping[str, Any],
    child_paths: Mapping[str, pathlib.Path],
    contract: Mapping[str, Any],
    *,
    ordinal: int,
) -> dict[str, Any] | None:
    """Recover a child committed before its outer batch-state checkpoint."""

    state_path = child_paths["analysis_root"] / "state.json"
    if not state_path.exists():
        return None
    child_state, evidence, _ = _load_state(state_path)
    request_path = pathlib.Path(child_state["immutable_artifacts"]["request"]["path"])
    if request_path.resolve() != child_paths["request"].resolve():
        raise CreditAnalysisError("prepared batch child request path changed")
    if pathlib.Path(child_state["evidence"]["path"]).resolve() != child_paths[
        "evidence"
    ].resolve():
        raise CreditAnalysisError("prepared batch child evidence path changed")
    if (
        child_state["action"] != "full-analysis"
        or child_state["mode"] != "full-analysis"
        or child_state["queue"] != contract["full_queue"]
        or child_state["source"].get("kind") != "thread_id"
        or child_state["source"].get("value") != candidate["thread_id"]
        or pathlib.Path(child_state["source"]["resolved_session"]).resolve()
        != pathlib.Path(candidate["session"]).resolve()
        or pathlib.Path(str(evidence.get("session"))).resolve()
        != pathlib.Path(candidate["session"]).resolve()
        or evidence.get("source_fingerprint") != child_state["source"]["fingerprint"]
        or evidence.get("collection", {}).get("session_reads") != 1
    ):
        raise CreditAnalysisError("prepared batch child identity is invalid")
    return _batch_item_record(
        candidate,
        child_paths,
        ordinal=ordinal,
        source_fingerprint=child_state["source"]["fingerprint"],
    )


def _resume_batch_preparation(
    state: dict[str, Any],
    contract: Mapping[str, Any],
    ledger: ModuleType,
) -> None:
    """Prepare each child once and checkpoint after every retained controller."""

    if state["phase"] != "preparing":
        return
    selector = state["selector"]
    target_count = selector["count"]
    pricing_record = state["immutable_artifacts"]["pricing_profile"]
    pricing = (
        pathlib.Path(pricing_record["path"])
        if isinstance(pricing_record, Mapping)
        else None
    )
    while state["candidate_index"] < len(state["candidates"]):
        if isinstance(target_count, int) and len(state["items"]) >= target_count:
            break
        candidate = state["candidates"][state["candidate_index"]]
        ordinal = len(state["items"]) + 1
        child_paths = _batch_item_paths(state, ordinal, candidate["thread_id"])
        recovered = _recover_prepared_batch_item(
            candidate,
            child_paths,
            contract,
            ordinal=ordinal,
        )
        if recovered is not None:
            state["items"].append(recovered)
            state["candidate_index"] += 1
            _save_batch_state(state)
            continue
        session = pathlib.Path(candidate["session"])
        try:
            rows, source_fingerprint = ledger.load_rows_with_fingerprint(session)
            metadata = ledger.session_source_metadata(
                rows,
                expected_thread_id=candidate["thread_id"],
            )
            if metadata["project_key"] != candidate["project"]["key"]:
                raise CreditAnalysisError("session project identity changed during prepare")
            collected = ledger.collect_session_evidence_from_rows(
                rows,
                session=session,
                source_fingerprint=source_fingerprint,
                pricing_profile=pricing,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise CreditAnalysisError(
                f"batch session collection failed for {candidate['thread_id']}: {exc}"
            ) from exc
        if collected["collection"]["model_calls"] < 1:
            state["exclusions"].append(
                {
                    "thread_id": candidate["thread_id"],
                    "reason": "no-completed-model-calls",
                }
            )
            state["candidate_index"] += 1
            _save_batch_state(state)
            continue
        child_paths["analysis_root"].mkdir()
        child_request = {
            "schema": contract["request_schema"],
            "action": "full-analysis",
            "mode": "full-analysis",
            "source": {"thread_id": candidate["thread_id"], "session": None},
            "window": {
                "mode": "full_thread",
                "last_runs": None,
                "turn_ids": [],
            },
            "task_temp_root": str(child_paths["analysis_root"]),
            "evidence_output": str(child_paths["evidence"]),
            "pricing_profile": str(pricing) if pricing is not None else None,
            "expected_surface_contract_version": state["surface_contract_version"],
            "mutation_authority": False,
        }
        _write_or_verify_json(
            child_paths["request"], child_request, "batch child request"
        )
        validated = _validate_request(child_paths["request"], dict(contract), ledger)
        _initialize_analysis(validated, contract, collected)
        item = _batch_item_record(
            candidate,
            child_paths,
            ordinal=ordinal,
            source_fingerprint=source_fingerprint,
        )
        state["items"].append(item)
        state["candidate_index"] += 1
        _save_batch_state(state)
    if not state["items"]:
        raise CreditAnalysisError("batch selector found no threads with completed model calls")
    manifest = _batch_manifest(state, contract)
    manifest_path = pathlib.Path(state["paths"]["manifest"])
    _write_or_verify_json(manifest_path, manifest, "retained batch manifest")
    state["immutable_artifacts"]["manifest"] = {
        "path": str(manifest_path),
        "sha256": _file_hash(manifest_path),
        "content_hash": _content_hash(manifest),
    }
    state["phase"] = "ready"
    _save_batch_state(state)


def _read_batch_index(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise CreditAnalysisError("batch result index must be a regular file")
    records: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    raise CreditAnalysisError(
                        f"batch result index has a blank record at line {line_number}"
                    )
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise CreditAnalysisError("batch result index record must be an object")
                records.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CreditAnalysisError(f"batch result index is unreadable: {exc}") from exc
    return records


def _recover_batch_indexed_result(state: dict[str, Any]) -> None:
    """Recover one child result indexed before its atomic batch-state checkpoint."""

    index = _read_batch_index(pathlib.Path(state["paths"]["index"]))
    completed_count = len(state["completed"])
    if len(index) == completed_count:
        return
    if len(index) != completed_count + 1 or completed_count >= len(state["items"]):
        raise CreditAnalysisError("batch result index contains unrecoverable records")
    raw = index[-1]
    if not isinstance(raw, dict):
        raise CreditAnalysisError("batch recovery index record must be an object")
    _closed(raw, {"schema", *BATCH_COMPLETED_FIELDS}, "batch recovery record")
    item = state["items"][completed_count]
    path = _existing_file(raw["path"], "recoverable batch child result")
    expected = {
        "schema": BATCH_INDEX_SCHEMA,
        "ordinal": item["ordinal"],
        "thread_id": item["thread_id"],
        "path": str(path),
        "sha256": _file_hash(path),
        "content_hash": _content_hash(
            _read_json(path, "recoverable batch child result")
        ),
    }
    if raw != expected or path.resolve() != pathlib.Path(
        item["final_result_path"]
    ).resolve():
        raise CreditAnalysisError("recoverable batch result does not match pending thread")
    state["completed"].append({key: raw[key] for key in BATCH_COMPLETED_FIELDS})
    state["current_index"] = completed_count + 1
    _save_batch_state(state)


def _verify_batch_completed(state: Mapping[str, Any]) -> None:
    completed = state.get("completed")
    if not isinstance(completed, list):
        raise CreditAnalysisError("batch completed records must be a list")
    index = _read_batch_index(pathlib.Path(state["paths"]["index"]))
    if len(index) != len(completed):
        raise CreditAnalysisError("batch result index and state counts differ")
    for position, raw in enumerate(completed):
        if not isinstance(raw, dict):
            raise CreditAnalysisError("batch completed record must be an object")
        _closed(raw, BATCH_COMPLETED_FIELDS, "batch completed record")
        item = state["items"][position]
        if raw["ordinal"] != position + 1 or raw["thread_id"] != item["thread_id"]:
            raise CreditAnalysisError("batch completed records are reordered")
        path = _existing_file(raw["path"], "batch child final result")
        if path.resolve() != pathlib.Path(item["final_result_path"]).resolve():
            raise CreditAnalysisError("batch completed result path is invalid")
        if _file_hash(path) != raw["sha256"]:
            raise CreditAnalysisError("batch completed result hash mismatch")
        if _content_hash(_read_json(path, "batch child final result")) != raw[
            "content_hash"
        ]:
            raise CreditAnalysisError("batch completed result content hash mismatch")
        expected_index = {"schema": BATCH_INDEX_SCHEMA, **raw}
        if index[position] != expected_index:
            raise CreditAnalysisError("batch result index record mismatch")


def _batch_finding_id(thread_id: str, finding_id: str) -> str:
    return f"{thread_id}:{finding_id}"


def _batch_finding_records(
    state: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build compact synthesis input from validated child final results only."""

    findings: list[dict[str, Any]] = []
    thread_totals: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item, record in zip(state["items"], state["completed"], strict=True):
        result = _read_json(pathlib.Path(record["path"]), "batch child final result")
        if result.get("schema") != contract["final_result_schema"]:
            raise CreditAnalysisError("batch child final result schema changed")
        thread_totals.append(
            {
                "thread_id": item["thread_id"],
                "thread_name": item["thread_name"],
                "analysis_id": result["analysis_id"],
                "totals": result["totals"],
            }
        )
        for finding in result["confirmed_findings"]:
            batch_finding_id = _batch_finding_id(item["thread_id"], finding["id"])
            if batch_finding_id in seen:
                raise CreditAnalysisError(
                    f"duplicate batch finding identity: {batch_finding_id}"
                )
            seen.add(batch_finding_id)
            findings.append(
                {
                    "batch_finding_id": batch_finding_id,
                    "thread_id": item["thread_id"],
                    "thread_name": item["thread_name"],
                    "analysis_id": result["analysis_id"],
                    "finding_id": finding["id"],
                    "title": finding["title"],
                    "problem_summary": finding["problem_summary"],
                    "waste_kind": finding["waste_kind"],
                    "source_surface": finding["source_surface"],
                    "producer_type": finding["producer_type"],
                    "producer_owner": finding["producer_owner"],
                    "proposed_durable_control": finding[
                        "proposed_durable_control"
                    ],
                    "implementation_status": finding["implementation_status"],
                    "deduplicated_avoidable_call_count": finding[
                        "deduplicated_avoidable_call_count"
                    ],
                    "targeted_verification": finding["targeted_verification"],
                    "helper_categories": finding["helper_categories"],
                    "complexity": finding["complexity"],
                    "confidence": finding["confidence"],
                }
            )
    return findings, thread_totals


def _open_batch_summary(
    state: dict[str, Any],
    contract: Mapping[str, Any],
) -> None:
    """Open the one deterministic cross-thread summary pass."""

    if state["phase"] != "ready" or state["current_index"] != len(state["items"]):
        raise CreditAnalysisError("batch summary cannot open before every child")
    if state.get("batch_summary") is not None:
        raise CreditAnalysisError("batch summary is already open")
    findings, thread_totals = _batch_finding_records(state, contract)
    pass_id = f"{state['batch_id']}.batch-summary"
    fingerprint = _content_hash(
        {"batch_id": state["batch_id"], "findings": findings}
    )
    context_path = pathlib.Path(state["paths"]["batch_summary_context"])
    result_path = pathlib.Path(state["paths"]["batch_summary_result"])
    context = {
        "batch_id": state["batch_id"],
        "pass_id": pass_id,
        "finding_fingerprint": fingerprint,
        "findings": findings,
        "thread_totals": thread_totals,
        "result_contract": {
            "fields": list(BATCH_SUMMARY_RESULT_FIELD_ORDER),
            "group_fields": list(BATCH_SUMMARY_GROUP_FIELD_ORDER),
        },
        "artifact_paths": {
            "state": state["paths"]["state"],
            "context": str(context_path),
            "result": str(result_path),
        },
    }
    _write_or_verify_json(context_path, context, "batch summary context")
    state["batch_summary"] = {
        "pass_id": pass_id,
        "finding_fingerprint": fingerprint,
        "finding_ids": [finding["batch_finding_id"] for finding in findings],
        "context_path": str(context_path),
        "result_path": str(result_path),
        "context_sha256": _file_hash(context_path),
        "accepted": None,
    }
    state["phase"] = "batch-summary"


def _validate_batch_summary(
    result: dict[str, Any],
    *,
    state: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate exact finding coverage without trusting model arithmetic."""

    _closed(result, BATCH_SUMMARY_RESULT_FIELDS, "batch summary result")
    pending = state.get("batch_summary")
    if state.get("phase") not in {
        "batch-summary",
        "ready-to-finalize",
        "finalized",
    } or not isinstance(pending, Mapping):
        raise CreditAnalysisError("batch summary is not pending")
    expected = {
        "batch_id": state["batch_id"],
        "pass_id": pending["pass_id"],
        "finding_fingerprint": pending["finding_fingerprint"],
        "artifact_paths": {
            "state": state["paths"]["state"],
            "context": pending["context_path"],
            "result": pending["result_path"],
        },
    }
    for field, value in expected.items():
        if result.get(field) != value:
            raise CreditAnalysisError(
                f"batch summary {field} does not match pending state"
            )
    findings, _ = _batch_finding_records(state, contract)
    finding_by_id = {
        finding["batch_finding_id"]: finding for finding in findings
    }
    if list(finding_by_id) != list(pending["finding_ids"]):
        raise CreditAnalysisError("batch summary finding inventory changed")
    normalized_groups: list[dict[str, Any]] = []
    grouped_findings: list[str] = []
    group_ids: set[str] = set()
    for raw in _objects(result.get("groups"), "batch summary groups"):
        _closed(raw, BATCH_SUMMARY_GROUP_FIELDS, "batch summary group")
        group_id = _identifier(raw.get("id"), "batch summary group id")
        title = raw.get("title")
        producer_type = raw.get("producer_type")
        owner = raw.get("owner")
        finding_ids = _strings(
            raw.get("finding_ids"), f"batch summary group {group_id} findings"
        )
        control = raw.get("recommended_control")
        variants = _strings(
            raw.get("material_variants"),
            f"batch summary group {group_id} variants",
            allow_empty=True,
        )
        confidence = _number(
            raw.get("confidence"), f"batch summary group {group_id} confidence"
        )
        if (
            group_id in group_ids
            or not isinstance(title, str)
            or not title.strip()
            or producer_type not in contract["producer_types"]
            or owner is not None and (not isinstance(owner, str) or not owner.strip())
            or not set(finding_ids).issubset(finding_by_id)
            or not isinstance(control, str)
            or not control.strip()
            or confidence > 1
        ):
            raise CreditAnalysisError(
                f"batch summary group is invalid: {group_id}"
            )
        normalized_owner = owner.strip() if isinstance(owner, str) else None
        if any(
            finding_by_id[finding_id]["producer_type"] != producer_type
            or finding_by_id[finding_id]["producer_owner"] != normalized_owner
            for finding_id in finding_ids
        ):
            raise CreditAnalysisError(
                f"batch summary group mixes producer owners: {group_id}"
            )
        group_ids.add(group_id)
        grouped_findings.extend(finding_ids)
        normalized_groups.append(
            {
                "id": group_id,
                "title": title.strip(),
                "producer_type": producer_type,
                "owner": normalized_owner,
                "finding_ids": finding_ids,
                "recommended_control": control.strip(),
                "material_variants": variants,
                "confidence": confidence,
            }
        )
    if (
        set(grouped_findings) != set(finding_by_id)
        or len(grouped_findings) != len(finding_by_id)
    ):
        raise CreditAnalysisError(
            "batch summary groups must partition every finding exactly once"
        )
    return {**result, "groups": normalized_groups}


def _cleanup_batch_transients(state: Mapping[str, Any]) -> None:
    cleanup = state.get("cleanup")
    expected_path = pathlib.Path(state["paths"]["batch_summary_context"]).resolve()
    if cleanup != {
        "owner": "credit-analysis-workflow",
        "trigger": "successful-finalization",
        "transient_paths": [str(expected_path)],
    }:
        raise CreditAnalysisError("batch cleanup ownership is invalid")
    if expected_path.is_symlink():
        raise CreditAnalysisError("refusing to delete symlinked batch context")
    if expected_path.exists():
        if not expected_path.is_file():
            raise CreditAnalysisError("batch summary context is not a file")
        expected_path.unlink()


def _load_batch_state(
    state_path: pathlib.Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate bounded batch ownership and recover one indexed child result."""

    resolved = _existing_file(str(state_path), "batch state")
    state = _read_json(resolved, "batch state")
    _closed(state, BATCH_STATE_FIELDS, "batch state")
    if (
        state.get("schema") != BATCH_STATE_SCHEMA
        or state.get("version") != BATCH_STATE_VERSION
    ):
        raise CreditAnalysisError("unsupported batch state schema or version")
    if state.get("mutation_authority") is not False:
        raise CreditAnalysisError("batch mutation authority must remain false")
    paths = state.get("paths")
    if not isinstance(paths, dict) or set(paths) != {
        "state",
        "manifest",
        "requests_dir",
        "analyses_dir",
        "evidence_dir",
        "index",
        "batch_summary_context",
        "batch_summary_result",
        "final_result",
    }:
        raise CreditAnalysisError("batch state paths are invalid")
    root = resolved.parent
    expected = {
        "state": root / "batch-state.json",
        "requests_dir": root / "requests",
        "analyses_dir": root / "analyses",
        "evidence_dir": root / "evidence",
        "index": root / "batch-results.jsonl",
        "batch_summary_context": root / "batch-summary-context.json",
        "batch_summary_result": root / "batch-summary.json",
        "final_result": root / "batch-final-machine-result.json",
    }
    for key, path in expected.items():
        if pathlib.Path(paths[key]).resolve() != path.resolve():
            raise CreditAnalysisError(f"batch {key} path escapes controller ownership")
    contract = _load_contract()
    if state["surface_contract_version"] != contract["surface_contract_version"]:
        raise CreditAnalysisError("batch surface contract version is stale")
    if state["source_selection_contract_version"] != contract[
        "source_selection_contract_version"
    ]:
        raise CreditAnalysisError("batch source selection contract is stale")
    artifacts = state.get("immutable_artifacts")
    if not isinstance(artifacts, dict):
        raise CreditAnalysisError("batch immutable artifacts are invalid")
    for label in ("request", "surface_contract"):
        record = artifacts.get(label)
        if not isinstance(record, dict):
            raise CreditAnalysisError(f"batch {label} artifact is invalid")
        path = _existing_file(record.get("path"), f"batch {label} artifact")
        if _file_hash(path) != record.get("sha256"):
            raise CreditAnalysisError(f"batch {label} artifact changed")
    pricing = artifacts.get("pricing_profile")
    if pricing is not None:
        if not isinstance(pricing, dict):
            raise CreditAnalysisError("batch pricing artifact is invalid")
        path = _existing_file(pricing.get("path"), "batch pricing artifact")
        if _file_hash(path) != pricing.get("sha256"):
            raise CreditAnalysisError("batch pricing artifact changed")
    phase = state.get("phase")
    if phase not in {
        "preparing",
        "ready",
        "batch-summary",
        "ready-to-finalize",
        "finalized",
    }:
        raise CreditAnalysisError("batch phase is invalid")
    manifest = artifacts.get("manifest")
    if phase == "preparing":
        if manifest is not None:
            raise CreditAnalysisError("preparing batch must not freeze a manifest")
    else:
        if not isinstance(manifest, dict):
            raise CreditAnalysisError("ready batch lacks an immutable manifest")
        path = _existing_file(manifest.get("path"), "batch manifest")
        if path.resolve() != pathlib.Path(paths["manifest"]).resolve():
            raise CreditAnalysisError("batch manifest path changed")
        if _file_hash(path) != manifest.get("sha256"):
            raise CreditAnalysisError("batch manifest hash mismatch")
    items = state.get("items")
    if not isinstance(items, list):
        raise CreditAnalysisError("batch items must be a list")
    seen_threads: set[str] = set()
    for position, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise CreditAnalysisError("batch item must be an object")
        _closed(item, BATCH_ITEM_FIELDS, "batch item")
        if item["ordinal"] != position or item["thread_id"] in seen_threads:
            raise CreditAnalysisError("batch item order or identity is invalid")
        seen_threads.add(item["thread_id"])
        for key in ("request_path", "state_path", "evidence_path"):
            _existing_file(item[key], f"batch item {key}")
    _recover_batch_indexed_result(state)
    current_index = state.get("current_index")
    if (
        not isinstance(current_index, int)
        or isinstance(current_index, bool)
        or current_index < 0
        or current_index > len(items)
    ):
        raise CreditAnalysisError("batch current index is invalid")
    _verify_batch_completed(state)
    if current_index != len(state["completed"]):
        raise CreditAnalysisError("batch current index does not match completed results")
    cleanup = state.get("cleanup")
    summary_context = pathlib.Path(paths["batch_summary_context"]).resolve()
    if cleanup != {
        "owner": "credit-analysis-workflow",
        "trigger": "successful-finalization",
        "transient_paths": [str(summary_context)],
    }:
        raise CreditAnalysisError("batch cleanup contract is invalid")
    if phase == "ready" and current_index == len(items):
        _open_batch_summary(state, contract)
        _save_batch_state(state)
        phase = state["phase"]
    if phase == "ready" and current_index >= len(items):
        raise CreditAnalysisError("ready batch must have one pending thread")
    if phase in {"batch-summary", "ready-to-finalize", "finalized"} and (
        current_index != len(items)
    ):
        raise CreditAnalysisError("batch summary opened before every thread finished")

    summary = state.get("batch_summary")
    if phase in {"preparing", "ready"}:
        if summary is not None:
            raise CreditAnalysisError("batch summary opened before its phase")
    else:
        if not isinstance(summary, dict):
            raise CreditAnalysisError("batch summary state is missing")
        _closed(summary, BATCH_SUMMARY_STATE_FIELDS, "batch summary state")
        expected_pass_id = f"{state['batch_id']}.batch-summary"
        finding_ids = _strings(
            summary.get("finding_ids"),
            "batch summary finding ids",
            allow_empty=True,
        )
        findings, thread_totals = _batch_finding_records(state, contract)
        expected_finding_ids = [item["batch_finding_id"] for item in findings]
        expected_fingerprint = _content_hash(
            {"batch_id": state["batch_id"], "findings": findings}
        )
        expected_context = {
            "batch_id": state["batch_id"],
            "pass_id": expected_pass_id,
            "finding_fingerprint": expected_fingerprint,
            "findings": findings,
            "thread_totals": thread_totals,
            "result_contract": {
                "fields": list(BATCH_SUMMARY_RESULT_FIELD_ORDER),
                "group_fields": list(BATCH_SUMMARY_GROUP_FIELD_ORDER),
            },
            "artifact_paths": {
                "state": paths["state"],
                "context": paths["batch_summary_context"],
                "result": paths["batch_summary_result"],
            },
        }
        if (
            summary.get("pass_id") != expected_pass_id
            or finding_ids != expected_finding_ids
            or summary.get("finding_fingerprint") != expected_fingerprint
            or pathlib.Path(str(summary.get("context_path"))).resolve()
            != summary_context
            or pathlib.Path(str(summary.get("result_path"))).resolve()
            != pathlib.Path(paths["batch_summary_result"]).resolve()
        ):
            raise CreditAnalysisError("batch summary state identity is invalid")
        if phase != "finalized" or summary_context.exists():
            context = _existing_file(
                summary.get("context_path"), "batch summary context"
            )
            if (
                _file_hash(context) != summary.get("context_sha256")
                or _content_hash(_read_json(context, "batch summary context"))
                != _content_hash(expected_context)
            ):
                raise CreditAnalysisError("batch summary context changed")
        accepted = summary.get("accepted")
        if phase == "batch-summary":
            if accepted is not None:
                raise CreditAnalysisError("pending batch summary is already accepted")
        else:
            if not isinstance(accepted, dict):
                raise CreditAnalysisError("accepted batch summary is missing")
            _closed(
                accepted,
                BATCH_SUMMARY_ACCEPTED_FIELDS,
                "accepted batch summary",
            )
            result = _existing_file(accepted.get("path"), "batch summary result")
            payload = _validate_batch_summary(
                _read_json(result, "batch summary result"),
                state=state,
                contract=contract,
            )
            if (
                result.resolve()
                != pathlib.Path(paths["batch_summary_result"]).resolve()
                or _file_hash(result) != accepted.get("sha256")
                or _content_hash(payload) != accepted.get("content_hash")
            ):
                raise CreditAnalysisError("accepted batch summary changed")

    finalized = state.get("finalized")
    if not isinstance(finalized, bool) or finalized != (phase == "finalized"):
        raise CreditAnalysisError("batch finalized status disagrees with its phase")
    if finalized:
        final = state.get("final_result")
        if not isinstance(final, dict):
            raise CreditAnalysisError("finalized batch state is incomplete")
        _closed(final, {"path", "sha256", "content_hash"}, "batch final result")
        final_path = _existing_file(final.get("path"), "batch final result")
        final_payload = _read_json(final_path, "batch final result")
        if (
            final_path.resolve() != pathlib.Path(paths["final_result"]).resolve()
            or _file_hash(final_path) != final.get("sha256")
            or _content_hash(final_payload) != final.get("content_hash")
        ):
            raise CreditAnalysisError("batch final result hash mismatch")
        _cleanup_batch_transients(state)
    elif state.get("final_result") is not None:
        raise CreditAnalysisError("unfinished batch records a final result")
    return state, contract


def _batch_public_status(
    state: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    if state["finalized"] is True:
        return {
            "batch_id": state["batch_id"],
            "complete": True,
            "selected_threads": len(state["items"]),
            "batch_state_path": state["paths"]["state"],
            "manifest_path": state["paths"]["manifest"],
            "batch_summary_result_path": state["batch_summary"]["result_path"],
            "final_result_path": state["final_result"]["path"],
        }
    common = {
        "batch_id": state["batch_id"],
        "selected_threads": len(state["items"]),
        "batch_state_path": state["paths"]["state"],
        "manifest_path": state["paths"]["manifest"],
    }
    if state["phase"] == "preparing":
        return {**common, "preparing": True, "resume_with": "prepare-batch"}
    if state["phase"] == "batch-summary":
        summary = state["batch_summary"]
        return {
            **common,
            "pending_phase": "batch-summary",
            "pass_id": summary["pass_id"],
            "context_path": summary["context_path"],
            "required_result_path": summary["result_path"],
        }
    if state["phase"] == "ready-to-finalize":
        return {
            **common,
            "ready_to_finalize": True,
            "batch_summary_result_path": state["batch_summary"]["result_path"],
        }
    item = state["items"][state["current_index"]]
    child_status = command_status(pathlib.Path(item["state_path"]))
    return {
        **common,
        "current_ordinal": item["ordinal"],
        "pending_thread_id": item["thread_id"],
        "pending_thread_name": item["thread_name"],
        "child_request_path": item["request_path"],
        "child_state_path": item["state_path"],
        "child_status": child_status,
    }


def command_prepare_batch(request_path: pathlib.Path) -> dict[str, Any]:
    """Freeze and prepare one resumable per-thread batch from an exact request."""

    raw = _read_json(request_path, "batch request")
    _closed(raw, BATCH_REQUEST_FIELDS, "batch request")
    task_root, paths = _batch_request_paths(raw)
    state_path = paths["state"]
    if state_path.exists():
        state, contract = _load_batch_state(state_path)
        request_record = state["immutable_artifacts"]["request"]
        if pathlib.Path(request_record["path"]).resolve() != request_path.resolve():
            raise CreditAnalysisError("batch request path does not match resumable state")
        if _file_hash(request_path) != request_record["sha256"]:
            raise CreditAnalysisError("batch request changed during resume")
        if state["phase"] == "preparing":
            _resume_batch_preparation(state, contract, _load_ledger())
        return _batch_public_status(state, contract)
    contract = _load_contract()
    ledger = _load_ledger()
    request = _validated_batch_request(request_path, contract, ledger)
    index, candidates, exclusions = _select_batch_candidates(request, ledger)
    for key in ("requests_dir", "analyses_dir", "evidence_dir"):
        request["paths"][key].mkdir()
    state = {
        "schema": BATCH_STATE_SCHEMA,
        "version": BATCH_STATE_VERSION,
        "batch_id": secrets.token_hex(12),
        "phase": "preparing",
        "action": "full-analysis",
        "mode": "per-thread-batch",
        "mutation_authority": False,
        "surface_contract_version": contract["surface_contract_version"],
        "source_selection_contract_version": contract[
            "source_selection_contract_version"
        ],
        "selector": request["selector"],
        "as_of": request["as_of"].isoformat().replace("+00:00", "Z"),
        "source_index": {
            "path": index["path"],
            "fingerprint": index["fingerprint"],
        },
        "candidates": candidates,
        "candidate_index": 0,
        "items": [],
        "exclusions": exclusions,
        "current_index": 0,
        "completed": [],
        "batch_summary": None,
        "paths": {key: str(value) for key, value in request["paths"].items()},
        "immutable_artifacts": {
            "request": {
                "path": str(request_path),
                "sha256": request["request_hash"],
            },
            "surface_contract": {
                "path": str(CONTRACT_PATH),
                "sha256": _file_hash(CONTRACT_PATH),
            },
            "manifest": None,
            "pricing_profile": (
                {
                    "path": str(request["pricing"]),
                    "sha256": _file_hash(request["pricing"]),
                }
                if request["pricing"] is not None
                else None
            ),
        },
        "cleanup": {
            "owner": "credit-analysis-workflow",
            "trigger": "successful-finalization",
            "transient_paths": [
                str(request["paths"]["batch_summary_context"].resolve())
            ],
        },
        "finalized": False,
        "final_result": None,
    }
    _exclusive_json(state_path, state, "batch state")
    _resume_batch_preparation(state, contract, ledger)
    return _batch_public_status(state, contract)


def command_status_batch(state_path: pathlib.Path) -> dict[str, Any]:
    state, contract = _load_batch_state(state_path)
    return _batch_public_status(state, contract)


def command_advance_batch(
    state_path: pathlib.Path,
    result_path: pathlib.Path,
) -> dict[str, Any]:
    """Accept the exact pending child or batch-summary result."""

    state, contract = _load_batch_state(state_path)
    result = _existing_file(str(result_path), "batch child final result")
    if state["completed"]:
        previous = state["completed"][-1]
        if result.resolve() == pathlib.Path(previous["path"]).resolve():
            if _file_hash(result) != previous["sha256"]:
                raise CreditAnalysisError("conflicting batch result resubmission")
            return _batch_public_status(state, contract)
    summary = state.get("batch_summary")
    if isinstance(summary, dict) and summary.get("accepted") is not None:
        accepted = summary["accepted"]
        if result.resolve() == pathlib.Path(accepted["path"]).resolve():
            if _file_hash(result) != accepted["sha256"]:
                raise CreditAnalysisError(
                    "conflicting batch summary resubmission"
                )
            return _batch_public_status(state, contract)
    if state["phase"] == "batch-summary":
        if not isinstance(summary, dict):
            raise CreditAnalysisError("batch summary state is missing")
        if result.resolve() != pathlib.Path(summary["result_path"]).resolve():
            raise CreditAnalysisError("result is not the pending batch summary")
        payload = _validate_batch_summary(
            _read_json(result, "batch summary result"),
            state=state,
            contract=contract,
        )
        summary["accepted"] = {
            "path": str(result),
            "sha256": _file_hash(result),
            "content_hash": _content_hash(payload),
        }
        state["phase"] = "ready-to-finalize"
        _save_batch_state(state)
        return _batch_public_status(state, contract)
    if state["phase"] != "ready" or state["current_index"] >= len(state["items"]):
        raise CreditAnalysisError("batch has no pending result")
    item = state["items"][state["current_index"]]
    if result.resolve() != pathlib.Path(item["final_result_path"]).resolve():
        raise CreditAnalysisError("batch result is not for the exact pending thread")
    child_state, _, _ = _load_state(pathlib.Path(item["state_path"]))
    if child_state["finalized"] is not True:
        raise CreditAnalysisError("pending thread analysis is not finalized")
    payload = _read_json(result, "batch child final result")
    if (
        payload.get("schema") != contract["final_result_schema"]
        or payload.get("mode") != "full-analysis"
        or child_state["source"].get("value") != item["thread_id"]
    ):
        raise CreditAnalysisError("batch child final result identity is invalid")
    record = {
        "ordinal": item["ordinal"],
        "thread_id": item["thread_id"],
        "path": str(result),
        "sha256": _file_hash(result),
        "content_hash": _content_hash(payload),
    }
    _append_index(
        pathlib.Path(state["paths"]["index"]),
        {"schema": BATCH_INDEX_SCHEMA, **record},
    )
    state["completed"].append(record)
    state["current_index"] += 1
    if state["current_index"] == len(state["items"]):
        _open_batch_summary(state, contract)
    _save_batch_state(state)
    return _batch_public_status(state, contract)


def _build_batch_final(
    state: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Group findings for presentation without changing per-thread accounting."""

    thread_results: list[dict[str, Any]] = []
    thread_totals: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    finding_by_batch_id: dict[str, dict[str, Any]] = {}
    risks: list[dict[str, Any]] = []
    dismissals: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    primary: list[dict[str, Any]] = []
    secondary: list[dict[str, Any]] = []
    producer_groups: list[dict[str, Any]] = []
    totals: Counter[str] = Counter()
    priced_totals: defaultdict[str, float] = defaultdict(float)
    pricing_complete = True
    for item, record in zip(state["items"], state["completed"], strict=True):
        result = _read_json(pathlib.Path(record["path"]), "batch child final result")
        if result.get("schema") != contract["final_result_schema"]:
            raise CreditAnalysisError("batch child final result schema changed")
        identity = {
            "thread_id": item["thread_id"],
            "thread_name": item["thread_name"],
            "analysis_id": result["analysis_id"],
        }
        thread_results.append({**identity, "path": record["path"], "result": result})
        thread_totals.append({**identity, "totals": result["totals"]})
        for value in result["confirmed_findings"]:
            batch_finding_id = _batch_finding_id(item["thread_id"], value["id"])
            if batch_finding_id in finding_by_batch_id:
                raise CreditAnalysisError(
                    f"duplicate batch finding identity: {batch_finding_id}"
                )
            entry = {
                **identity,
                "batch_finding_id": batch_finding_id,
                "finding": value,
            }
            finding_by_batch_id[batch_finding_id] = entry
            findings.append(entry)
        risks.extend({**identity, "risk": value} for value in result["plausible_risks"])
        dismissals.extend({**identity, "dismissal": value} for value in result["dismissals"])
        exclusions.extend(
            {**identity, "exclusion": value}
            for value in result["necessary_call_exclusions"]
        )
        primary.extend(
            {**identity, "mapping": value}
            for value in result["primary_call_mappings"]
        )
        secondary.extend(
            {**identity, "mapping": value}
            for value in result["secondary_call_mappings"]
        )
        producer_groups.extend(
            {**identity, "group": value}
            for value in result["producer_grouped_recommendations"]
        )
        for key, value in result["totals"].items():
            if isinstance(value, int) and not isinstance(value, bool):
                totals[key] += value
        priced = result.get("priced_cost")
        if not isinstance(priced, Mapping):
            pricing_complete = False
        else:
            for key, value in priced.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    priced_totals[key] += float(value)

    summary_state = state.get("batch_summary")
    if not isinstance(summary_state, Mapping) or not isinstance(
        summary_state.get("accepted"), Mapping
    ):
        raise CreditAnalysisError("batch summary is not accepted")
    summary_path = _existing_file(
        summary_state["accepted"].get("path"), "accepted batch summary"
    )
    summary = _validate_batch_summary(
        _read_json(summary_path, "accepted batch summary"),
        state=state,
        contract=contract,
    )
    surface_rank = {
        surface_id: rank
        for rank, surface_id in enumerate(contract["surface_order"])
    }
    helper_rank = {
        category: rank
        for rank, category in enumerate(contract["helper_categories"])
    }
    status_rank = {
        status: rank
        for rank, status in enumerate(contract["implementation_statuses"])
    }
    summary_groups: list[dict[str, Any]] = []
    for rank, group in enumerate(summary["groups"], start=1):
        members = [finding_by_batch_id[value] for value in group["finding_ids"]]
        affected_calls: list[dict[str, str]] = []
        seen_calls: set[tuple[str, str]] = set()
        for member in members:
            for call_id in member["finding"]["primary_call_ids"]:
                key = (member["thread_id"], call_id)
                if key not in seen_calls:
                    seen_calls.add(key)
                    affected_calls.append(
                        {"thread_id": member["thread_id"], "call_id": call_id}
                    )
        summary_groups.append(
            {
                "id": group["id"],
                "title": group["title"],
                "expected_value_rank": rank,
                "producer_type": group["producer_type"],
                "owner": group["owner"],
                "recommended_control": group["recommended_control"],
                "material_variants": group["material_variants"],
                "confidence": group["confidence"],
                "findings": [
                    {
                        "batch_finding_id": member["batch_finding_id"],
                        "thread_id": member["thread_id"],
                        "thread_name": member["thread_name"],
                        "analysis_id": member["analysis_id"],
                        "finding_id": member["finding"]["id"],
                        "title": member["finding"]["title"],
                        "source_surface": member["finding"]["source_surface"],
                    }
                    for member in members
                ],
                "threads": list(
                    dict.fromkeys(member["thread_id"] for member in members)
                ),
                "contributing_surfaces": sorted(
                    {member["finding"]["source_surface"] for member in members},
                    key=lambda value: surface_rank[value],
                ),
                "helper_categories": sorted(
                    {
                        category
                        for member in members
                        for category in member["finding"]["helper_categories"]
                    },
                    key=lambda value: helper_rank[value],
                ),
                "implementation_statuses": sorted(
                    {
                        member["finding"]["implementation_status"]
                        for member in members
                    },
                    key=lambda value: status_rank[value],
                ),
                "targeted_verification": [
                    {
                        "batch_finding_id": member["batch_finding_id"],
                        "checks": member["finding"]["targeted_verification"],
                    }
                    for member in members
                ],
                "affected_calls": affected_calls,
                "deduplicated_avoidable_call_count": len(affected_calls),
            }
        )
    return {
        "batch_id": state["batch_id"],
        "mode": "per-thread-batch",
        "scope_limitation": (
            "Similar findings are grouped only for presentation; each thread's "
            "findings, classifications, and savings totals remain independent."
        ),
        "selector": state["selector"],
        "as_of": state["as_of"],
        "source_index": state["source_index"],
        "selection_exclusions": state["exclusions"],
        "thread_results": thread_results,
        "per_thread_totals": thread_totals,
        "summary_groups": summary_groups,
        "confirmed_findings": findings,
        "plausible_risks": risks,
        "dismissals": dismissals,
        "necessary_call_exclusions": exclusions,
        "primary_call_mappings": primary,
        "secondary_call_mappings": secondary,
        "producer_grouped_recommendations": producer_groups,
        "totals": {
            "analyzed_threads": len(state["items"]),
            "session_collections": len(state["items"]),
            **dict(sorted(totals.items())),
        },
        "priced_cost": (
            {key: round(value, 12) for key, value in sorted(priced_totals.items())}
            if pricing_complete
            else None
        ),
        "retained_paths": {
            "manifest": state["paths"]["manifest"],
            "batch_state": state["paths"]["state"],
            "batch_index": state["paths"]["index"],
            "batch_summary_result": str(summary_path),
            "child_final_results": [record["path"] for record in state["completed"]],
            "batch_final_machine_result": state["paths"]["final_result"],
        },
    }


def command_finalize_batch(state_path: pathlib.Path) -> None:
    """Verify synthesis and retain one complete grouped batch result."""

    state, contract = _load_batch_state(state_path)
    if state["finalized"]:
        return
    if state["phase"] != "ready-to-finalize":
        raise CreditAnalysisError("batch summary is not accepted")
    _verify_batch_completed(state)
    final = _build_batch_final(state, contract)
    path = pathlib.Path(state["paths"]["final_result"])
    sha256 = _write_final_result(path, final)
    state["phase"] = "finalized"
    state["finalized"] = True
    state["final_result"] = {
        "path": str(path),
        "sha256": sha256,
        "content_hash": _content_hash(final),
    }
    _save_batch_state(state)
    _cleanup_batch_transients(state)


def _exclusive_text(path: pathlib.Path, value: str, label: str) -> None:
    """Create one immutable UTF-8 controller artifact."""

    if path.exists() or path.is_symlink():
        raise CreditAnalysisError(f"refusing to overwrite {label}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
    except OSError as exc:
        raise CreditAnalysisError(f"could not write {label}: {exc}") from exc


def _codex_model_catalog() -> dict[str, dict[str, Any]]:
    """Read local model, effort, and context limits without a model request."""

    executable = shutil.which("codex")
    if executable is None:
        raise CreditAnalysisError("Codex CLI is unavailable")
    try:
        completed = subprocess.run(
            [executable, "debug", "models"],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CreditAnalysisError(f"could not read the Codex model catalog: {exc}") from exc
    if completed.returncode:
        detail = " ".join((completed.stderr or completed.stdout).split())
        raise CreditAnalysisError(
            "could not read the Codex model catalog"
            + (f": {detail[:500]}" if detail else "")
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CreditAnalysisError("Codex model catalog is invalid JSON") from exc
    models = payload.get("models") if isinstance(payload, Mapping) else None
    if not isinstance(models, list):
        raise CreditAnalysisError("Codex model catalog has no model list")
    catalog: dict[str, dict[str, Any]] = {}
    for item in models:
        if not isinstance(item, Mapping) or not isinstance(item.get("slug"), str):
            continue
        levels = item.get("supported_reasoning_levels")
        efforts = (
            {
                str(level["effort"])
                for level in levels
                if isinstance(level, Mapping)
                and isinstance(level.get("effort"), str)
            }
            if isinstance(levels, list)
            else set()
        )
        context = item.get("context_window")
        percent = item.get("effective_context_window_percent")
        effective_context_tokens = None
        if (
            isinstance(context, int)
            and not isinstance(context, bool)
            and context > 0
            and isinstance(percent, (int, float))
            and not isinstance(percent, bool)
            and 0 < percent <= 100
        ):
            effective_context_tokens = math.floor(context * percent / 100)
        catalog[str(item["slug"])] = {
            "reasoning_efforts": efforts,
            "effective_context_tokens": effective_context_tokens,
        }
    if not catalog:
        raise CreditAnalysisError("Codex model catalog is empty")
    return catalog


def _required_orchestration_models(contract: Mapping[str, Any]) -> dict[str, str]:
    raw = contract.get("models")
    if not isinstance(raw, Mapping):
        raise CreditAnalysisError("orchestration model contract is missing")
    expected = {"luna", "confirmation", "synthesis"}
    if set(raw) != expected or not all(
        isinstance(raw[key], str) and raw[key] for key in expected
    ):
        raise CreditAnalysisError("orchestration model contract is invalid")
    return {key: str(raw[key]) for key in expected}


def _validate_orchestration_models(
    contract: Mapping[str, Any],
    available_models: set[str] | Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    models = _required_orchestration_models(contract)
    available = set(available_models)
    missing = sorted(set(models.values()) - available)
    if missing:
        raise CreditAnalysisError(f"required model is unavailable: {missing[0]}")
    effort = contract.get("model_reasoning_effort")
    if effort != "max":
        raise CreditAnalysisError("orchestration reasoning effort must be max")
    if isinstance(available_models, Mapping):
        for slug in set(models.values()):
            details = available_models[slug]
            efforts = details.get("reasoning_efforts")
            if not isinstance(efforts, set) or effort not in efforts:
                raise CreditAnalysisError(
                    f"required reasoning effort is unavailable for model: {slug}"
                )
        luna_details = available_models[models["luna"]]
        effective_tokens = luna_details.get("effective_context_tokens")
        if isinstance(effective_tokens, int):
            maximum_chars = int(contract["chunking"]["maximum_chars"])
            if maximum_chars > math.floor(effective_tokens * 2.4):
                raise CreditAnalysisError(
                    "Luna chunk maximum exceeds the local effective context budget"
                )
    return models


def _surface_order_for_request(
    request: Mapping[str, Any], contract: Mapping[str, Any]
) -> list[str]:
    if request["mode"] == "full-analysis":
        return list(contract["surface_order"])
    return [str(request["action"])]


def _review_record_index(evidence: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
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


def _run_index(evidence: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    runs = evidence.get("runs")
    if not isinstance(runs, list):
        raise CreditAnalysisError("evidence runs are invalid")
    result: dict[str, dict[str, Any]] = {}
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("turn_id"), str):
            raise CreditAnalysisError("evidence run is invalid")
        if run["turn_id"] in result:
            raise CreditAnalysisError("duplicate evidence run")
        result[run["turn_id"]] = run
    return result


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
OUTCOME_KEYS = frozenset(
    {
        "code",
        "error",
        "errors",
        "exit_code",
        "returncode",
        "status",
        "stderr",
        "success",
        "terminated",
        "termination",
        "timed_out",
        "timeout",
    }
)


def _structured_outcome(value: Any, *, depth: int = 0) -> Any:
    """Project explicit process/result telemetry without semantic judgment."""

    if depth > 5:
        return None
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized in OUTCOME_KEYS:
                result[str(key)] = _bounded_value(item, text_limit=600)
                continue
            nested = _structured_outcome(item, depth=depth + 1)
            if nested not in (None, {}, []):
                result[str(key)] = nested
        return result or None
    if isinstance(value, list):
        items = [
            projected
            for item in value
            if (projected := _structured_outcome(item, depth=depth + 1))
            is not None
        ]
        return items or None
    return None


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
            if not any(left < old_right and right > old_left for old_left, old_right in seen):
                seen.add(bounds)
                segments.append(
                    {
                        "start": left,
                        "end": right,
                        "text": text[left:right],
                    }
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
            if any(start < prior_end and end > prior_start for prior_start, prior_end in bounds):
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


WORKSPACE_REFERENCE_RE = re.compile(
    r"<workspace:[^>]+>(?:[\\/][^\s\"'<>|,;}\]]+)*"
)


def _canonical_artifact_references(text: str) -> list[str]:
    refs: list[str] = []
    for match in WORKSPACE_REFERENCE_RE.finditer(text):
        value = match.group(0).replace("\\", "/")
        if value not in refs:
            refs.append(value)
    return refs


def _canonical_references_from_evidence(evidence: Mapping[str, Any]) -> list[str]:
    """Inventory portable workspace references without exposing local roots."""

    references: list[str] = []
    model_review = evidence.get("model_review")
    records = model_review.get("records") if isinstance(model_review, Mapping) else None
    if not isinstance(records, list):
        raise CreditAnalysisError("model-review records are unavailable")
    for record in records:
        if not isinstance(record, Mapping):
            raise CreditAnalysisError("model-review record is invalid")
        serialized = json.dumps(
            record.get("content"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
        for reference in _canonical_artifact_references(serialized):
            if reference not in references:
                references.append(reference)
    return references


def _canonical_projection(text: str) -> dict[str, Any]:
    """Project protected final-state text while retaining its complete snapshot."""

    segments: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for surface_id in SURFACE_EVIDENCE_KEYWORDS:
        for segment in _relevant_segments(text, surface_id):
            bounds = (int(segment["start"]), int(segment["end"]))
            if bounds not in seen:
                seen.add(bounds)
                segments.append(segment)
            if len(segments) >= 8:
                break
        if len(segments) >= 8:
            break
    return {
        "protected_chars": len(text),
        "protected_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "head": text[:1400],
        "tail": text[-1400:],
        "relevant_segments": segments,
    }


def _collect_canonical_state_snapshot(
    *,
    evidence: Mapping[str, Any],
    path_roots: list[tuple[str, str]],
    orchestration_root: pathlib.Path,
    ledger: ModuleType,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Read referenced final artifacts once and retain protected immutable evidence."""

    snapshot_root = orchestration_root / "canonical-state"
    payload_root = snapshot_root / "payloads"
    snapshot_root.mkdir(parents=True, exist_ok=False)
    payload_root.mkdir()
    workspace_roots = {
        label: pathlib.Path(root).expanduser().resolve()
        for root, label in path_roots
        if label.startswith("<workspace:")
    }
    retained_records: list[dict[str, Any]] = []
    public_by_reference: dict[str, dict[str, Any]] = {}
    for ordinal, reference in enumerate(
        _canonical_references_from_evidence(evidence), start=1
    ):
        match = re.fullmatch(r"(<workspace:[^>]+>)(?:/(.*))?", reference)
        artifact_id = f"canonical.{ordinal:04d}"
        public: dict[str, Any] = {
            "id": artifact_id,
            "artifact_reference": reference,
            "evidence_ref": f"evidence://canonical-state/{artifact_id}",
            "status": "unresolved",
            "kind": None,
            "source_bytes": None,
            "source_sha256": None,
            "retained_snapshot": None,
            "projection": None,
        }
        snapshot_path: pathlib.Path | None = None
        if match is None or match.group(1) not in workspace_roots:
            public["status"] = "workspace-root-unavailable"
        else:
            workspace_root = workspace_roots[match.group(1)]
            relative = match.group(2) or ""
            parts = [part for part in re.split(r"[\\/]+", relative) if part]
            if any(part in {".", ".."} for part in parts):
                public["status"] = "unsafe-relative-reference"
            else:
                unresolved = workspace_root.joinpath(*parts)
                resolved = unresolved.resolve(strict=False)
                if not (
                    resolved == workspace_root
                    or resolved.is_relative_to(workspace_root)
                ):
                    public["status"] = "outside-workspace"
                elif unresolved.is_symlink():
                    public["status"] = "symlink-withheld"
                elif not unresolved.exists():
                    public["status"] = "missing"
                elif unresolved.is_dir():
                    try:
                        listing = "\n".join(
                            sorted(child.name for child in unresolved.iterdir())
                        )
                    except OSError:
                        public.update(
                            {"status": "read-error", "kind": "directory-listing"}
                        )
                    else:
                        protected = ledger.prepare_review_text(listing, path_roots)
                        snapshot_path = payload_root / f"{artifact_id}.txt"
                        _exclusive_text(
                            snapshot_path,
                            protected,
                            "canonical directory snapshot",
                        )
                        public.update(
                            {
                                "status": "captured",
                                "kind": "directory-listing",
                                "source_bytes": len(listing.encode("utf-8")),
                                "source_sha256": hashlib.sha256(
                                    listing.encode("utf-8")
                                ).hexdigest(),
                                "projection": _canonical_projection(protected),
                            }
                        )
                elif unresolved.is_file():
                    try:
                        data = unresolved.read_bytes()
                    except OSError:
                        public.update({"status": "read-error", "kind": "file"})
                    else:
                        public["source_bytes"] = len(data)
                        public["source_sha256"] = hashlib.sha256(data).hexdigest()
                        try:
                            decoded = data.decode("utf-8")
                        except UnicodeDecodeError:
                            public.update(
                                {"status": "captured", "kind": "binary-hash"}
                            )
                        else:
                            protected = ledger.prepare_review_text(decoded, path_roots)
                            snapshot_path = payload_root / f"{artifact_id}.txt"
                            _exclusive_text(
                                snapshot_path,
                                protected,
                                "canonical file snapshot",
                            )
                            public.update(
                                {
                                    "status": "captured",
                                    "kind": "protected-text",
                                    "projection": _canonical_projection(protected),
                                }
                            )
                else:
                    public["status"] = "unsupported-artifact-kind"
        retained = dict(public)
        if snapshot_path is not None:
            snapshot_hash = _file_hash(snapshot_path)
            retained["snapshot_path"] = str(snapshot_path)
            retained["snapshot_sha256"] = snapshot_hash
            public["retained_snapshot"] = {
                "complete": True,
                "sha256": snapshot_hash,
                "evidence_ref": public["evidence_ref"],
            }
        else:
            retained["snapshot_path"] = None
            retained["snapshot_sha256"] = None
        retained_records.append(retained)
        public_by_reference[reference] = public
    index = {
        "schema": CANONICAL_STATE_SCHEMA,
        "record_count": len(retained_records),
        "records": retained_records,
    }
    index_path = snapshot_root / "index.json"
    _exclusive_json(index_path, index, "canonical-state index")
    return public_by_reference, {
        "path": str(index_path),
        "sha256": _file_hash(index_path),
        "record_count": len(retained_records),
    }


def _formatted_review_record(
    record: Mapping[str, Any],
    *,
    surface_ids: Sequence[str],
    inline_limit: int,
) -> dict[str, Any]:
    """Format one complete record or an explicit retained-payload projection."""

    content = record.get("content")
    serialized = json.dumps(
        content,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    common = {
        key: record.get(key)
        for key in (
            "record_id",
            "kind",
            "name",
            "timestamp",
            "call_id",
            "content_hash",
        )
    }
    common["evidence_ref"] = f"evidence://review/{record['record_id']}"
    common["content_chars"] = len(serialized)
    common["content_sha256"] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    common["structured_outcome"] = _structured_outcome(content)
    common["canonical_artifact_references"] = _canonical_artifact_references(
        serialized
    )
    if record.get("name") in {"rate-limits", "user-message-metadata"}:
        common["content_mode"] = "complete-inventory"
        return common
    if len(serialized) <= min(inline_limit, 160):
        common["content_mode"] = "complete-inline"
        common["content"] = content
        return common
    common.update(
        {
            "content_mode": "retained-projection",
            "head": serialized[:180],
            "tail": serialized[-180:],
            "relevant_segments": _shared_relevant_segments(
                serialized,
                surface_ids,
                text_limit=400,
            ),
        }
    )
    return common


def _formatted_user_message(
    message: Mapping[str, Any],
    *,
    surface_ids: Sequence[str],
    inline_limit: int,
) -> dict[str, Any]:
    """Format one associated user message without inlining unbounded text."""

    message_id = message.get("message_id")
    text = message.get("text")
    if not isinstance(message_id, str) or not isinstance(text, str):
        raise CreditAnalysisError("candidate user message is invalid")
    formatted = {
        key: message.get(key)
        for key in (
            "message_id",
            "timestamp",
            "first_model_call_index",
        )
    }
    formatted["evidence_ref"] = f"evidence://user-messages/{message_id}"
    if len(text) <= min(inline_limit, 1_000):
        formatted["text_mode"] = "complete-inline"
        formatted["text"] = text
        return formatted
    formatted.update(
        {
            "text_mode": "retained-projection",
            "text_chars": len(text),
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "head": text[:400],
            "tail": text[-400:],
            "relevant_segments": _shared_relevant_segments(
                text,
                surface_ids,
                text_limit=700,
            ),
        }
    )
    return formatted


def _shared_canonical_record(
    record: Mapping[str, Any], surface_ids: Sequence[str]
) -> dict[str, Any]:
    """Keep one bounded view per applicable surface of a canonical snapshot."""

    result = dict(record)
    projection = record.get("projection")
    if not isinstance(projection, Mapping):
        return result
    segments: list[Mapping[str, Any]] = []
    for surface_id in surface_ids:
        keywords = SURFACE_EVIDENCE_KEYWORDS[surface_id]
        selected = next(
            (
                segment
                for segment in projection.get("relevant_segments", [])
                if isinstance(segment, Mapping)
                and any(
                    keyword in str(segment.get("text") or "").casefold()
                    for keyword in keywords
                )
                and segment not in segments
            ),
            None,
        )
        if selected is not None:
            segments.append(selected)
    if not segments:
        segments = [
            segment
            for segment in projection.get("relevant_segments", [])
            if isinstance(segment, Mapping)
        ][:1]
    result["projection"] = {
        "protected_chars": projection.get("protected_chars"),
        "protected_sha256": projection.get("protected_sha256"),
        "head": str(projection.get("head") or "")[:400],
        "tail": str(projection.get("tail") or "")[-400:],
        "relevant_segments": [
            {
                "start": segment.get("start"),
                "end": segment.get("end"),
                "text": str(segment.get("text") or "")[:500],
            }
            for segment in segments[: len(surface_ids)]
        ],
    }
    return result


def _call_neighbors(calls: Sequence[Mapping[str, Any]], index: int) -> dict[str, Any]:
    return {
        "previous_call_id": str(calls[index - 1]["call_id"]) if index > 0 else None,
        "next_call_id": (
            str(calls[index + 1]["call_id"]) if index + 1 < len(calls) else None
        ),
    }


def _has_failure_telemetry(value: Any) -> bool:
    """Detect only explicit observable failure, timeout, or termination fields."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized in {"exit_code", "returncode", "code"}:
                if isinstance(item, int) and not isinstance(item, bool) and item != 0:
                    return True
            elif normalized in {"timed_out", "timeout", "terminated", "termination"}:
                if item is True or (
                    isinstance(item, str)
                    and item.casefold() in {"true", "timeout", "terminated", "killed"}
                ):
                    return True
            elif normalized in {"error", "errors", "stderr"} and (
                item is not None and item != "" and item != [] and item != {}
            ):
                return True
            elif normalized == "status" and isinstance(item, str) and item.casefold() in {
                "error",
                "failed",
                "failure",
                "timeout",
                "terminated",
            }:
                return True
            if _has_failure_telemetry(item):
                return True
    elif isinstance(value, list):
        return any(_has_failure_telemetry(item) for item in value)
    return False


def _observable_high_signal_reasons(
    *,
    call: Mapping[str, Any],
    messages: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
    repeated_groups: Sequence[Mapping[str, Any]],
    volume: Mapping[str, Any],
) -> list[str]:
    """Route observable review signals without classifying waste or necessity."""

    reasons: list[str] = []
    telemetry = [
        call.get("tool_results"),
        *[record.get("structured_outcome") for record in records],
    ]
    if any(_has_failure_telemetry(item) for item in telemetry):
        reasons.append("failure-timeout-or-termination-telemetry")
    if repeated_groups:
        reasons.append("repeated-action-fingerprint")
    searchable = json.dumps(
        {
            "actions": call.get("actions"),
            "semantic_actions": call.get("semantic_actions"),
            "messages": messages,
            "records": records,
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    ).casefold()
    if re.search(
        r"\b(correct(?:ion|ed)?|revert(?:ed|ing)?|retry|workaround|temporary|"
        r"rolled back|undo|again)\b",
        searchable,
    ):
        reasons.append("correction-retry-or-temporary-control")
    tokens = volume.get("tokens")
    input_tokens = tokens.get("input_tokens") if isinstance(tokens, Mapping) else None
    output_tokens = tokens.get("output_tokens") if isinstance(tokens, Mapping) else None
    if (
        (isinstance(input_tokens, int) and input_tokens >= 100_000)
        or (isinstance(output_tokens, int) and output_tokens >= 25_000)
        or int(volume.get("tool_result_chars") or 0) >= 100_000
    ):
        reasons.append("large-input-output-volume")
    return reasons


def _format_shared_candidates(
    *,
    analysis_id: str,
    surface_order: Sequence[str],
    evidence: Mapping[str, Any],
    evidence_path: pathlib.Path,
    canonical_state: Mapping[str, Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Format the union of surface candidates once in source-call order."""

    calls = _all_calls(evidence)
    call_positions = {str(call["call_id"]): index for index, call in enumerate(calls)}
    if len(call_positions) != len(calls):
        raise CreditAnalysisError("evidence call IDs are not unique")
    selected_by_surface = {
        surface_id: set(_candidate_ids(surface_id, evidence, contract))
        for surface_id in surface_order
    }
    selected_ids = [
        str(call["call_id"])
        for call in calls
        if any(
            str(call["call_id"]) in selected_by_surface[surface_id]
            for surface_id in surface_order
        )
    ]
    if not selected_ids or len(selected_ids) != len(set(selected_ids)):
        raise CreditAnalysisError("shared candidate call IDs are empty or duplicated")
    records = _review_record_index(evidence)
    runs = _run_index(evidence)
    inline_limit = int(contract["chunking"]["large_payload_inline_chars"])
    repeated = evidence.get("repeated_tool_calls")
    if not isinstance(repeated, list):
        raise CreditAnalysisError("repeated-tool-call evidence is invalid")
    result: list[dict[str, Any]] = []
    for ordinal, call_id in enumerate(selected_ids, start=1):
        call = calls[call_positions[call_id]]
        applicable_surfaces = [
            surface_id
            for surface_id in surface_order
            if call_id in selected_by_surface[surface_id]
        ]
        if not applicable_surfaces:
            raise CreditAnalysisError("shared candidate has no applicable surface")
        turn_id = str(call["turn_id"])
        run = runs.get(turn_id)
        if run is None:
            raise CreditAnalysisError("candidate run is missing")
        message_ids = call.get("user_message_ids")
        if not isinstance(message_ids, list):
            raise CreditAnalysisError("candidate user-message IDs are invalid")
        raw_messages = [
            message
            for message in run.get("user_messages", [])
            if isinstance(message, Mapping) and message.get("message_id") in message_ids
        ]
        if {str(message.get("message_id")) for message in raw_messages} != set(
            message_ids
        ):
            raise CreditAnalysisError("candidate user message is missing")
        messages = [
            _formatted_user_message(
                message,
                surface_ids=applicable_surfaces,
                inline_limit=inline_limit,
            )
            for message in raw_messages
        ]
        raw_record_ids = call.get("model_review_record_ids")
        if not isinstance(raw_record_ids, list) or not all(
            isinstance(record_id, str) for record_id in raw_record_ids
        ):
            raise CreditAnalysisError("candidate review-record IDs are invalid")
        formatted_records: list[dict[str, Any]] = []
        for record_id in raw_record_ids:
            raw_record = records.get(record_id)
            if raw_record is None:
                raise CreditAnalysisError("candidate review record is missing")
            formatted_records.append(
                _formatted_review_record(
                    raw_record,
                    surface_ids=applicable_surfaces,
                    inline_limit=inline_limit,
                )
            )
        artifact_refs = list(
            dict.fromkeys(
                ref
                for record in formatted_records
                for ref in record["canonical_artifact_references"]
            )
        )
        canonical_records = [
            _shared_canonical_record(
                canonical_state[reference],
                applicable_surfaces,
            )
            for reference in artifact_refs
            if reference in canonical_state
        ]
        candidate_id = f"{analysis_id}.c.{ordinal:06d}"
        if not canonical_records:
            canonical_records.append(
                {
                    "id": f"canonical-unresolved.{ordinal:06d}",
                    "artifact_reference": None,
                    "evidence_ref": (
                        f"evidence://canonical-state/unresolved/{candidate_id}"
                    ),
                    "status": "no-resolvable-workspace-reference",
                    "kind": None,
                    "source_bytes": None,
                    "source_sha256": None,
                    "retained_snapshot": None,
                    "projection": None,
                }
            )
        repeated_groups = [
            group
            for group in repeated
            if isinstance(group, Mapping)
            and any(
                bool(item.get("repeated"))
                and item.get("fingerprint") == group.get("fingerprint")
                for item in call.get("tool_results", [])
                if isinstance(item, Mapping)
            )
        ]
        volume = {
            "tokens": call.get("tokens"),
            "estimated_credit_cost": call.get("estimated_credit_cost"),
            "tool_argument_chars": sum(
                int(item.get("argument_chars") or 0)
                for item in call.get("tool_results", [])
                if isinstance(item, Mapping)
            ),
            "tool_result_chars": sum(
                int(item.get("result_chars") or 0)
                for item in call.get("tool_results", [])
                if isinstance(item, Mapping)
            ),
        }
        high_signal_reasons = _observable_high_signal_reasons(
            call=call,
            messages=messages,
            records=formatted_records,
            repeated_groups=repeated_groups,
            volume=volume,
        )
        result.append(
            {
                "schema": FORMATTED_EVIDENCE_SCHEMA,
                "analysis_id": analysis_id,
                "applicable_surfaces": applicable_surfaces,
                "candidate_id": candidate_id,
                "candidate_ordinal": ordinal,
                "retained_evidence_path": str(evidence_path),
                "call_identity": {
                    "call_id": call_id,
                    "turn_id": turn_id,
                    "model_call_index": call.get("index"),
                    "timestamp": call.get("timestamp"),
                    "sequence_position": call_positions[call_id] + 1,
                    **_call_neighbors(calls, call_positions[call_id]),
                },
                "user_messages": messages,
                "assistant_and_tool_evidence": formatted_records,
                "actions": call.get("actions", []),
                "semantic_actions": call.get("semantic_actions", []),
                "tool_results": call.get("tool_results", []),
                "observable_high_signal": {
                    "selected": bool(high_signal_reasons),
                    "reasons": high_signal_reasons,
                },
                "process_and_run_telemetry": {
                    "run_duration_ms": call.get("run_duration_ms"),
                    "run_totals": run.get("totals"),
                    "run_tool_counts": run.get("tool_counts"),
                },
                "volume": volume,
                "relationships": {
                    "canonical_artifact_references": artifact_refs,
                    "final_canonical_state": canonical_records,
                    "repeated_tool_call_groups": repeated_groups,
                    "correction_reversion_and_final_outcome_evidence": [
                        record["evidence_ref"]
                        for record in formatted_records
                        if record.get("name")
                        in {
                            "agent_message",
                            "task_complete",
                            "turn_aborted",
                            "final",
                        }
                        or record.get("structured_outcome") is not None
                    ],
                },
                "original_evidence_refs": [
                    f"evidence://calls/{call_id}",
                    *[message["evidence_ref"] for message in messages],
                    *[record["evidence_ref"] for record in formatted_records],
                    *[record["evidence_ref"] for record in canonical_records],
                ],
            }
        )
    if [item["call_identity"]["call_id"] for item in result] != selected_ids:
        raise CreditAnalysisError("shared candidate formatting reordered calls")
    return result


def _verification_dossier(record: Mapping[str, Any]) -> dict[str, Any]:
    """Build a bounded original-evidence dossier for Sol verification."""

    projected_records: list[dict[str, Any]] = []
    for item in record["assistant_and_tool_evidence"]:
        projection = {
            key: item.get(key)
            for key in (
                "record_id",
                "kind",
                "name",
                "timestamp",
                "call_id",
                "content_hash",
                "content_mode",
                "structured_outcome",
                "canonical_artifact_references",
                "evidence_ref",
            )
        }
        if item.get("content_mode") == "complete-inline":
            serialized = json.dumps(
                item.get("content"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                default=str,
            )
            projection["excerpt"] = serialized[:300]
            projection["excerpt_complete"] = len(serialized) <= 300
        elif item.get("content_mode") == "retained-projection":
            projection["head"] = str(item.get("head") or "")[:150]
            projection["tail"] = str(item.get("tail") or "")[-150:]
            projection["relevant_segments"] = [
                {
                    "start": segment.get("start"),
                    "end": segment.get("end"),
                    "text": str(segment.get("text") or "")[:240],
                }
                for segment in item.get("relevant_segments", [])[:1]
                if isinstance(segment, Mapping)
            ]
        projected_records.append(projection)
    projected_messages: list[dict[str, Any]] = []
    for message in record["user_messages"]:
        projection = {
            key: message.get(key)
            for key in (
                "message_id",
                "timestamp",
                "first_model_call_index",
                "text_mode",
                "evidence_ref",
                "text_chars",
                "text_sha256",
            )
        }
        if message.get("text_mode") == "complete-inline":
            text = str(message.get("text") or "")
            projection["excerpt"] = text[:300]
            projection["excerpt_complete"] = len(text) <= 300
        else:
            projection["head"] = str(message.get("head") or "")[:150]
            projection["tail"] = str(message.get("tail") or "")[-150:]
            projection["relevant_segments"] = [
                {
                    "start": segment.get("start"),
                    "end": segment.get("end"),
                    "text": str(segment.get("text") or "")[:240],
                }
                for segment in message.get("relevant_segments", [])[:1]
                if isinstance(segment, Mapping)
            ]
        projected_messages.append(projection)
    relationships = record["relationships"]
    return {
        "candidate_id": record["candidate_id"],
        "applicable_surfaces": record["applicable_surfaces"],
        "observable_high_signal": record["observable_high_signal"],
        "call_identity": record["call_identity"],
        "user_messages": projected_messages,
        "original_evidence_refs": record["original_evidence_refs"],
        "evidence_excerpts": projected_records,
        "actions": record["actions"],
        "tool_results": record["tool_results"],
        "volume": record["volume"],
        "process_and_run_telemetry": record["process_and_run_telemetry"],
        "relationships": {
            "final_canonical_state": relationships["final_canonical_state"],
            "correction_reversion_and_final_outcome_evidence": relationships[
                "correction_reversion_and_final_outcome_evidence"
            ],
        },
    }


def _confirmation_evidence_map(
    dossiers: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Map every candidate to one original reference and bounded evidence excerpt."""

    rows: list[list[str]] = []
    for dossier in dossiers:
        excerpt = ""
        for item in dossier["evidence_excerpts"]:
            values = [
                item.get("excerpt"),
                item.get("head"),
                *[
                    segment.get("text")
                    for segment in item.get("relevant_segments", [])
                    if isinstance(segment, Mapping)
                ],
                item.get("tail"),
            ]
            excerpt = " ".join(str(value) for value in values if value).strip()[:120]
            if excerpt:
                break
        if not excerpt:
            for message in dossier["user_messages"]:
                values = [
                    message.get("excerpt"),
                    message.get("head"),
                    *[
                        segment.get("text")
                        for segment in message.get("relevant_segments", [])
                        if isinstance(segment, Mapping)
                    ],
                    message.get("tail"),
                ]
                excerpt = " ".join(
                    str(value) for value in values if value
                ).strip()[:120]
                if excerpt:
                    break
        rows.append(
            [
                str(dossier["candidate_id"]),
                str(dossier["original_evidence_refs"][0]),
                excerpt,
            ]
        )
    return {
        "fields": [
            "candidate_id",
            "original_evidence_ref",
            "original_evidence_excerpt",
        ],
        "rows": rows,
    }


def _semantic_candidate_ids(
    results: Sequence[Mapping[str, Any]], candidate_order: Sequence[str]
) -> list[str]:
    """Select candidates attached to a Luna finding, risk, or temporary control."""

    selected: set[str] = set()
    for result in results:
        for key in (
            "provisional_findings",
            "plausible_risks",
            "temporary_control_candidates",
        ):
            for item in result.get(key, []):
                if isinstance(item, Mapping):
                    selected.update(
                        str(candidate)
                        for candidate in item.get("candidate_ids", [])
                        if isinstance(candidate, str)
                    )
    return [candidate for candidate in candidate_order if candidate in selected]


def _confirmation_selection(
    *,
    results: Sequence[Mapping[str, Any]],
    surface_index: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, list[str]]:
    """Select material, observable high-signal, and deterministic audit evidence."""

    candidate_order = [str(item) for item in surface_index["candidate_ids"]]
    material = _semantic_candidate_ids(results, candidate_order)
    material_set = set(material)
    high_signal = [
        str(item)
        for item in surface_index["high_signal_candidate_ids"]
        if item not in material_set
    ]
    selected = material_set | set(high_signal)
    ordinary = [item for item in candidate_order if item not in selected]
    fraction = float(contract["chunking"]["confirmation_audit_fraction"])
    minimum = int(contract["chunking"]["confirmation_audit_minimum"])
    audit_count = min(len(ordinary), max(minimum, math.ceil(len(ordinary) * fraction)))
    ranked = sorted(
        ordinary,
        key=lambda item: hashlib.sha256(item.encode("utf-8")).hexdigest(),
    )
    audit_set = set(ranked[:audit_count])
    audit = [item for item in candidate_order if item in audit_set]
    all_selected = [
        item
        for item in candidate_order
        if item in selected or item in audit_set
    ]
    if not all_selected:
        raise CreditAnalysisError("confirmation selection is unexpectedly empty")
    return {
        "material_candidate_ids": material,
        "high_signal_candidate_ids": high_signal,
        "audit_candidate_ids": audit,
        "selected_candidate_ids": all_selected,
    }


def _build_causal_episodes(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Group consecutive calls by completed turn and deduplicate shared context."""

    episodes: list[dict[str, Any]] = []
    current: list[Mapping[str, Any]] = []

    def flush() -> None:
        if not current:
            return
        ordinal = len(episodes) + 1
        messages: dict[str, Mapping[str, Any]] = {}
        canonical: dict[str, Mapping[str, Any]] = {}
        calls: list[dict[str, Any]] = []
        for record in current:
            for message in record["user_messages"]:
                messages.setdefault(str(message["message_id"]), message)
            relationships = dict(record["relationships"])
            final_state_refs: list[str] = []
            for artifact in relationships["final_canonical_state"]:
                evidence_ref = str(artifact["evidence_ref"])
                canonical.setdefault(evidence_ref, artifact)
                final_state_refs.append(evidence_ref)
            relationships["final_canonical_state_refs"] = final_state_refs
            relationships.pop("final_canonical_state", None)
            calls.append(
                {
                    key: value
                    for key, value in record.items()
                    if key
                    not in {
                        "schema",
                        "analysis_id",
                        "retained_evidence_path",
                        "user_messages",
                        "process_and_run_telemetry",
                        "relationships",
                    }
                }
                | {
                    "user_message_ids": [
                        str(message["message_id"])
                        for message in record["user_messages"]
                    ],
                    "relationships": relationships,
                }
            )
        candidate_ids = [str(call["candidate_id"]) for call in calls]
        episodes.append(
            {
                "episode_id": f"episode.{ordinal:06d}",
                "episode_ordinal": ordinal,
                "turn_id": str(current[0]["call_identity"]["turn_id"]),
                "candidate_ids": candidate_ids,
                "applicable_surfaces": list(
                    dict.fromkeys(
                        surface
                        for call in calls
                        for surface in call["applicable_surfaces"]
                    )
                ),
                "high_signal_candidate_ids": [
                    str(call["candidate_id"])
                    for call in calls
                    if call["observable_high_signal"]["selected"]
                ],
                "user_messages": list(messages.values()),
                "process_and_run_telemetry": current[0][
                    "process_and_run_telemetry"
                ],
                "final_canonical_state": list(canonical.values()),
                "calls": calls,
            }
        )

    for record in records:
        turn_id = str(record["call_identity"]["turn_id"])
        if current and str(current[-1]["call_identity"]["turn_id"]) != turn_id:
            flush()
            current = []
        current.append(record)
    flush()
    observed = [
        str(call["candidate_id"])
        for episode in episodes
        for call in episode["calls"]
    ]
    expected = [str(record["candidate_id"]) for record in records]
    if observed != expected or len(observed) != len(set(observed)):
        raise CreditAnalysisError("causal episodes changed candidate coverage or order")
    return episodes


def _episode_fragments(
    episode: Mapping[str, Any], maximum_chars: int
) -> list[dict[str, Any]]:
    """Split only a genuinely over-limit episode, preserving adjacent calls."""

    if _json_chars(episode) < maximum_chars:
        return [dict(episode)]
    base = {key: value for key, value in episode.items() if key not in {
        "candidate_ids",
        "applicable_surfaces",
        "high_signal_candidate_ids",
        "calls",
    }}
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for raw_call in episode["calls"]:
        call = dict(raw_call)
        proposed = [*current, call]
        if current and _json_chars({**base, "calls": proposed}) >= maximum_chars:
            groups.append(current)
            current = [call]
        else:
            current = proposed
        if _json_chars({**base, "calls": current}) >= maximum_chars:
            raise CreditAnalysisError(
                f"single candidate exceeds the Luna chunk maximum: {call['candidate_id']}"
            )
    if current:
        groups.append(current)
    fragments: list[dict[str, Any]] = []
    for index, calls in enumerate(groups, start=1):
        fragments.append(
            {
                **base,
                "episode_fragment": index,
                "episode_fragment_count": len(groups),
                "candidate_ids": [str(call["candidate_id"]) for call in calls],
                "applicable_surfaces": list(
                    dict.fromkeys(
                        surface
                        for call in calls
                        for surface in call["applicable_surfaces"]
                    )
                ),
                "high_signal_candidate_ids": [
                    str(call["candidate_id"])
                    for call in calls
                    if call["observable_high_signal"]["selected"]
                ],
                "calls": calls,
            }
        )
    return fragments


def _chunk_episodes(
    episodes: list[dict[str, Any]], contract: Mapping[str, Any]
) -> list[list[dict[str, Any]]]:
    chunking = contract["chunking"]
    target = int(chunking["target_chars"])
    maximum = int(chunking["maximum_chars"])
    maximum_candidates = int(chunking["maximum_candidates"])
    if not (0 < target <= maximum) or maximum_candidates < 1:
        raise CreditAnalysisError("chunking contract is malformed")
    fragments = [
        fragment
        for episode in episodes
        for fragment in _episode_fragments(episode, maximum)
    ]
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_candidates = 0
    for episode in fragments:
        episode_candidates = len(episode["candidate_ids"])
        proposed = [*current, episode]
        if current and (
            current_candidates + episode_candidates > maximum_candidates
            or _json_chars(proposed) >= target
        ):
            chunks.append(current)
            current = [episode]
            current_candidates = episode_candidates
        else:
            current = proposed
            current_candidates += episode_candidates
    if current:
        chunks.append(current)
    if not chunks and episodes:
        raise CreditAnalysisError("chunk partition unexpectedly produced no chunks")
    return chunks


def _task_artifact_paths(root: pathlib.Path, task_id: str) -> dict[str, str]:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", task_id)
    return {
        "input": str(root / "inputs" / f"{safe}.json"),
        "prompt": str(root / "prompts" / f"{safe}.md"),
        "schema": str(root / "schemas" / f"{safe}.json"),
        "result": str(root / "results" / f"{safe}.json"),
        "attempts": str(root / "attempts" / safe),
    }


def _plan_shared_primary_tasks(
    *,
    analysis_id: str,
    records: list[dict[str, Any]],
    evidence_path: pathlib.Path,
    orchestration_root: pathlib.Path,
    contract: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Freeze one shared causal-episode stream for all public surfaces."""

    chunks = _chunk_episodes(_build_causal_episodes(records), contract)
    shared_dir = orchestration_root / "shared-evidence"
    shared_dir.mkdir(parents=True, exist_ok=False)
    tasks: list[dict[str, Any]] = []
    membership: dict[str, str] = {}
    for ordinal, episodes in enumerate(chunks, start=1):
        task_id = f"luna.shared.primary.{ordinal:04d}"
        calls = [call for episode in episodes for call in episode["calls"]]
        candidate_ids = [str(call["candidate_id"]) for call in calls]
        candidate_pairs = [
            [str(call["candidate_id"]), str(surface_id)]
            for call in calls
            for surface_id in call["applicable_surfaces"]
        ]
        if any(candidate_id in membership for candidate_id in candidate_ids):
            raise CreditAnalysisError("candidate belongs to multiple shared chunks")
        membership.update({candidate_id: task_id for candidate_id in candidate_ids})
        chunk_path = shared_dir / f"primary-{ordinal:04d}.json"
        payload = {
            "schema": FORMATTED_EVIDENCE_SCHEMA,
            "analysis_id": analysis_id,
            "chunk_ordinal": ordinal,
            "retained_evidence_path": str(evidence_path),
            "candidate_ids": candidate_ids,
            "candidate_pairs": candidate_pairs,
            "candidate_count": len(candidate_ids),
            "candidate_surface_pair_count": len(candidate_pairs),
            "episodes": episodes,
        }
        if _json_chars(payload) >= int(contract["chunking"]["maximum_chars"]):
            raise CreditAnalysisError(f"planned Luna chunk is oversized: {task_id}")
        _exclusive_json(chunk_path, payload, "shared Luna evidence")
        artifacts = _task_artifact_paths(orchestration_root, task_id)
        artifacts["input"] = str(chunk_path)
        tasks.append(
            {
                "task_id": task_id,
                "phase": "luna-primary",
                "stage": "primary",
                "surface_id": None,
                "ordinal": ordinal,
                "depth": 0,
                "dependencies": [],
                "candidate_ids": candidate_ids,
                "candidate_pairs": candidate_pairs,
                "input_sha256": _file_hash(chunk_path),
                "artifacts": artifacts,
            }
        )
    expected = [str(record["candidate_id"]) for record in records]
    if list(membership) != expected:
        raise CreditAnalysisError("shared chunks do not preserve candidate order")
    return tasks, membership


def _plan_surface_tasks(
    *,
    analysis_id: str,
    surface_id: str,
    records: list[dict[str, Any]],
    primary_tasks: Sequence[Mapping[str, Any]],
    shared_membership: Mapping[str, str],
    orchestration_root: pathlib.Path,
    contract: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Freeze one surface's Luna reduction and Sol confirmation over shared chunks."""

    all_candidate_ids = [str(record["candidate_id"]) for record in records]
    selected = set(all_candidate_ids)
    primary = [
        {
            **task,
            "candidate_ids": [
                candidate_id
                for candidate_id in task["candidate_ids"]
                if candidate_id in selected
            ],
        }
        for task in primary_tasks
        if any(candidate_id in selected for candidate_id in task["candidate_ids"])
    ]
    candidate_membership = {
        candidate_id: str(shared_membership[candidate_id])
        for candidate_id in all_candidate_ids
    }
    observed_primary = [
        candidate_id for task in primary for candidate_id in task["candidate_ids"]
    ]
    if observed_primary != all_candidate_ids:
        raise CreditAnalysisError("shared primary tasks reordered surface candidates")
    surface_dir = orchestration_root / "surface-evidence" / surface_id
    surface_dir.mkdir(parents=True, exist_ok=False)

    dossiers = [_verification_dossier(record) for record in records]
    evidence_map = _confirmation_evidence_map(dossiers)
    minimum_confirmation_chars = _json_chars(evidence_map) + len(all_candidate_ids) * 30
    confirmation_limit = int(contract["chunking"]["confirmation_packet_chars"])
    if minimum_confirmation_chars >= confirmation_limit:
        raise CreditAnalysisError(
            f"surface plan is clearly runaway before model execution: {surface_id}"
        )
    fan_in = int(contract["chunking"]["consolidation_fan_in"])
    maximum_depth = int(contract["chunking"]["maximum_consolidation_depth"])
    if fan_in < 2 or maximum_depth < 1:
        raise CreditAnalysisError("consolidation contract is malformed")
    consolidation: list[dict[str, Any]] = []
    current = primary
    depth = 0
    while len(current) > 1:
        depth += 1
        if depth > maximum_depth:
            raise CreditAnalysisError("Luna consolidation plan exceeds maximum depth")
        next_level: list[dict[str, Any]] = []
        for group_number, start in enumerate(range(0, len(current), fan_in), start=1):
            dependencies = current[start : start + fan_in]
            if len(dependencies) == 1:
                next_level.append(dependencies[0])
                continue
            task_id = (
                f"luna.{surface_id}.consolidate.{depth:02d}.{group_number:04d}"
            )
            candidate_ids = [
                candidate_id
                for dependency in dependencies
                for candidate_id in dependency["candidate_ids"]
            ]
            task = {
                "task_id": task_id,
                "phase": "luna-consolidation",
                "stage": "consolidation",
                "surface_id": surface_id,
                "ordinal": group_number,
                "depth": depth,
                "dependencies": [item["task_id"] for item in dependencies],
                "candidate_ids": candidate_ids,
                "input_sha256": None,
                "artifacts": _task_artifact_paths(orchestration_root, task_id),
            }
            consolidation.append(task)
            next_level.append(task)
        current = next_level
    final_units = [item["task_id"] for item in current]
    confirmation_task_id = f"confirm.{surface_id}"
    confirmation = {
        "task_id": confirmation_task_id,
        "phase": "surface-confirmation",
        "stage": "confirmation",
        "surface_id": surface_id,
        "ordinal": 1,
        "depth": 0,
        "dependencies": final_units,
        "candidate_ids": all_candidate_ids,
        "input_sha256": None,
        "artifacts": _task_artifact_paths(orchestration_root, confirmation_task_id),
    }
    surface_index = {
        "schema": FORMATTED_EVIDENCE_SCHEMA,
        "analysis_id": analysis_id,
        "surface_id": surface_id,
        "candidate_count": len(all_candidate_ids),
        "candidate_ids": all_candidate_ids,
        "call_ids": [str(record["call_identity"]["call_id"]) for record in records],
        "high_signal_candidate_ids": [
            str(record["candidate_id"])
            for record in records
            if record["observable_high_signal"]["selected"]
        ],
        "primary_membership": candidate_membership,
        "primary_task_ids": [task["task_id"] for task in primary],
        "consolidation_task_ids": [task["task_id"] for task in consolidation],
        "confirmation_task_id": confirmation_task_id,
        "final_luna_task_ids": final_units,
        "verification_dossiers": dossiers,
        "candidate_evidence_map": evidence_map,
    }
    index_path = surface_dir / "index.json"
    _exclusive_json(index_path, surface_index, "surface evidence index")
    surface_summary = {
        "surface_id": surface_id,
        "candidate_count": len(all_candidate_ids),
        "candidate_ids": all_candidate_ids,
        "call_ids": surface_index["call_ids"],
        "high_signal_candidate_ids": surface_index["high_signal_candidate_ids"],
        "primary_task_ids": surface_index["primary_task_ids"],
        "consolidation_task_ids": surface_index["consolidation_task_ids"],
        "final_luna_task_ids": final_units,
        "confirmation_task_id": confirmation_task_id,
        "index_path": str(index_path),
        "index_sha256": _file_hash(index_path),
    }
    return consolidation, confirmation, surface_summary


def _validate_frozen_manifest(manifest: Mapping[str, Any], contract: Mapping[str, Any]) -> None:
    if manifest.get("schema") != CHUNK_MANIFEST_SCHEMA:
        raise CreditAnalysisError("chunk manifest schema is invalid")
    source_freeze = manifest.get("source_freeze")
    if (
        not isinstance(source_freeze, Mapping)
        or source_freeze.get("controller_analysis_id") != manifest.get("analysis_id")
        or source_freeze.get("source_is_analysis_child") is not False
        or source_freeze.get("execution_recollects_session") is not False
        or not isinstance(source_freeze.get("collection_cutoff_utc"), str)
    ):
        raise CreditAnalysisError("chunk manifest source freeze is invalid")
    canonical_state = manifest.get("canonical_state")
    if (
        not isinstance(canonical_state, Mapping)
        or set(canonical_state) != {"path", "sha256", "record_count"}
        or not isinstance(canonical_state.get("record_count"), int)
        or isinstance(canonical_state.get("record_count"), bool)
        or canonical_state["record_count"] < 0
    ):
        raise CreditAnalysisError("chunk manifest canonical-state record is invalid")
    surface_order = manifest.get("surface_order")
    surfaces = manifest.get("surfaces")
    luna_tasks = manifest.get("luna_tasks")
    confirmations = manifest.get("confirmation_tasks")
    if (
        not isinstance(surface_order, list)
        or not isinstance(surfaces, list)
        or not isinstance(luna_tasks, list)
        or not isinstance(confirmations, list)
    ):
        raise CreditAnalysisError("chunk manifest collections are invalid")
    if [item.get("surface_id") for item in surfaces if isinstance(item, Mapping)] != surface_order:
        raise CreditAnalysisError("chunk manifest surface order is invalid")
    task_ids: set[str] = set()
    task_by_id: dict[str, Mapping[str, Any]] = {}
    for task in [*luna_tasks, *confirmations, manifest.get("synthesis_task")]:
        if not isinstance(task, Mapping):
            raise CreditAnalysisError("chunk manifest task is invalid")
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or task_id in task_ids:
            raise CreditAnalysisError("chunk manifest task identity is invalid")
        task_ids.add(task_id)
        task_by_id[task_id] = task
    shared_ids = manifest.get("shared_candidate_ids")
    shared_count = manifest.get("shared_candidate_count")
    membership = manifest.get("shared_primary_membership")
    primary_task_ids = manifest.get("shared_primary_task_ids")
    if (
        not isinstance(shared_ids, list)
        or not shared_ids
        or not all(isinstance(item, str) for item in shared_ids)
        or len(shared_ids) != len(set(shared_ids))
        or shared_count != len(shared_ids)
        or not isinstance(membership, Mapping)
        or not isinstance(primary_task_ids, list)
    ):
        raise CreditAnalysisError("shared candidate manifest is invalid")
    candidate_pattern = re.compile(
        rf"^{re.escape(str(manifest['analysis_id']))}\.c\.[0-9]{{6}}$"
    )
    if any(candidate_pattern.fullmatch(candidate_id) is None for candidate_id in shared_ids):
        raise CreditAnalysisError("shared candidate identity is invalid")
    observed_primary: list[str] = []
    observed_pairs: list[list[str]] = []
    observed_membership: dict[str, str] = {}
    observed_primary_ids: list[str] = []
    for task in luna_tasks:
        if task.get("phase") != "luna-primary":
            continue
        if task.get("surface_id") is not None:
            raise CreditAnalysisError("shared Luna primary task has a surface")
        candidates = task.get("candidate_ids")
        pairs = task.get("candidate_pairs")
        if not isinstance(candidates, list) or not all(isinstance(item, str) for item in candidates):
            raise CreditAnalysisError("primary candidate membership is invalid")
        if (
            not isinstance(pairs, list)
            or not pairs
            or not all(
                isinstance(pair, list)
                and len(pair) == 2
                and pair[0] in candidates
                and pair[1] in surface_order
                for pair in pairs
            )
        ):
            raise CreditAnalysisError("primary candidate-surface pairs are invalid")
        observed_primary_ids.append(str(task["task_id"]))
        observed_primary.extend(candidates)
        observed_pairs.extend(pairs)
        observed_membership.update(
            {candidate_id: str(task["task_id"]) for candidate_id in candidates}
        )
    if observed_primary != shared_ids or len(observed_pairs) != len(
        {tuple(pair) for pair in observed_pairs}
    ):
        raise CreditAnalysisError("shared primary coverage is incomplete or duplicated")
    if observed_membership != membership or observed_primary_ids != primary_task_ids:
        raise CreditAnalysisError("shared primary membership is invalid")
    for surface in surfaces:
        surface_id = str(surface["surface_id"])
        expected = surface.get("candidate_ids")
        surface_pairs = [pair[0] for pair in observed_pairs if pair[1] == surface_id]
        if surface_pairs != expected or len(surface_pairs) != len(set(surface_pairs)):
            raise CreditAnalysisError(
                "candidate-surface coverage is incomplete, duplicated, or reordered"
            )
    ordered_ids = [str(task["task_id"]) for task in luna_tasks]
    position = {task_id: index for index, task_id in enumerate(ordered_ids)}
    for task in luna_tasks:
        dependencies = task.get("dependencies")
        if not isinstance(dependencies, list):
            raise CreditAnalysisError("Luna dependencies are invalid")
        for dependency in dependencies:
            if dependency not in position or position[dependency] >= position[str(task["task_id"])]:
                raise CreditAnalysisError("Luna dependency order is malformed")
    projected = manifest.get("projected_luna_calls")
    if projected != len(luna_tasks):
        raise CreditAnalysisError("projected Luna call count is invalid")
    maximum = int(contract["chunking"]["maximum_luna_tasks"])
    if not isinstance(projected, int) or projected < 1 or projected > maximum:
        raise CreditAnalysisError("Luna plan is empty or clearly runaway")
    expected_sol = len(surface_order) + 1
    if manifest.get("projected_sol_calls") != expected_sol:
        raise CreditAnalysisError("projected Sol call count is invalid")
    if manifest.get("projected_semantic_calls") != projected + expected_sol:
        raise CreditAnalysisError("projected semantic call count is invalid")
    if manifest["projected_semantic_calls"] > int(
        contract["chunking"]["maximum_semantic_tasks"]
    ):
        raise CreditAnalysisError("semantic plan is clearly runaway")
    if len(confirmations) != len(surface_order):
        raise CreditAnalysisError("confirmation task count is invalid")


def _orchestration_public_status(state: Mapping[str, Any]) -> dict[str, Any]:
    execution = state.get("execution")
    if not isinstance(execution, Mapping):
        raise CreditAnalysisError("orchestration execution state is invalid")
    task_order = state.get("task_order")
    if not isinstance(task_order, list):
        raise CreditAnalysisError("orchestration task order is invalid")
    completed = sum(
        1
        for task_id in task_order
        if isinstance(execution.get(task_id), Mapping)
        and execution[task_id].get("status") == "complete"
    )
    manifest = state["manifest"]
    return {
        "schema": ORCHESTRATION_STATE_SCHEMA,
        "analysis_id": state["analysis_id"],
        "phase": state["phase"],
        "complete": state["phase"] == "complete",
        "state_path": state["paths"]["state"],
        "manifest_path": manifest["path"],
        "evidence_path": state["evidence"]["path"],
        "final_result_path": (
            state["final_result"]["path"]
            if isinstance(state.get("final_result"), Mapping)
            else None
        ),
        "report_path": (
            state["final_result"]["report_path"]
            if isinstance(state.get("final_result"), Mapping)
            else None
        ),
        "projected_luna_calls": manifest["projected_luna_calls"],
        "projected_sol_calls": manifest["projected_sol_calls"],
        "projected_semantic_calls": manifest["projected_semantic_calls"],
        "shared_primary_chunks": len(manifest["shared_primary_task_ids"]),
        "shared_candidate_count": manifest["shared_candidate_count"],
        "canonical_state_records": manifest["canonical_state"]["record_count"],
        "actual_luna_calls": state["model_attempts"]["luna"],
        "actual_sol_calls": state["model_attempts"]["sol"],
        "accepted_luna_calls": state["model_calls"]["luna"],
        "accepted_sol_calls": state["model_calls"]["sol"],
        "completed_tasks": completed,
        "total_tasks": len(task_order),
        "next_task": next(
            (
                task_id
                for task_id in task_order
                if execution[task_id]["status"] != "complete"
            ),
            None,
        ),
        "surfaces": [
            {
                "surface_id": item["surface_id"],
                "candidate_count": item["candidate_count"],
                "primary_chunks": len(item["primary_task_ids"]),
                "luna_consolidations": len(item["consolidation_task_ids"]),
            }
            for item in manifest["surfaces"]
        ],
    }


ANALYSIS_CHILD_MARKER = "CERATOPS_CREDIT_ANALYSIS_CHILD v1"


def _source_is_analysis_child(rows: Sequence[Mapping[str, Any]]) -> bool:
    """Recognize only an explicit child prompt marker in a user-role row."""

    for row in rows:
        payload = row.get("payload")
        if not isinstance(payload, Mapping) or payload.get("role") != "user":
            continue
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
        if ANALYSIS_CHILD_MARKER in serialized[:4_000]:
            return True
    return False


def _collect_orchestration_evidence(
    *,
    request: Mapping[str, Any],
    contract: Mapping[str, Any],
    ledger: ModuleType,
    analysis_id: str,
) -> tuple[dict[str, Any], str, str, list[tuple[str, str]]]:
    collector_window = request["collector_window"]
    collection_cutoff = dt.datetime.now(dt.timezone.utc).isoformat(
        timespec="microseconds"
    )
    try:
        rows, source_fingerprint = ledger.load_rows_with_fingerprint(
            request["session"]
        )
        if _source_is_analysis_child(rows):
            raise CreditAnalysisError(
                "selected source is a credit-analysis child session"
            )
        path_roots = ledger.review_path_roots(rows)
        collected = ledger.collect_session_evidence_from_rows(
            rows,
            session=request["session"],
            source_fingerprint=source_fingerprint,
            last_runs=collector_window["last_runs"],
            completed_turn_ids=collector_window["completed_turn_ids"],
            pricing_profile=request["pricing"],
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise CreditAnalysisError(f"session collection failed: {exc}") from exc
    if collected.get("collection", {}).get("session_reads") != 1:
        raise CreditAnalysisError("session collector did not report exactly one read")
    if collected.get("collection", {}).get("model_calls", 0) < 1:
        raise CreditAnalysisError("selected completed-run window has no model calls")
    collector_schema = collected.pop("schema", None)
    evidence = {
        **collected,
        "schema": contract["evidence_schema"],
        "collector_schema": collector_schema,
        "analysis_id": analysis_id,
        "source": request["source"],
        "requested_window": request["window"],
        "surface_contract_version": contract["surface_contract_version"],
        "surface_contract_hash": _file_hash(CONTRACT_PATH),
        "analysis_lineage": {
            "controller_analysis_id": analysis_id,
            "source_session": str(request["session"]),
            "source_fingerprint": source_fingerprint,
            "collection_cutoff_utc": collection_cutoff,
            "source_is_analysis_child": False,
            "execution_recollects_session": False,
        },
        "mutation_authority": False,
    }
    fingerprint = _content_hash(evidence)
    evidence["evidence_fingerprint"] = fingerprint
    evidence_path = pathlib.Path(request["evidence_path"])
    _exclusive_json(evidence_path, evidence, "retained evidence")
    return evidence, fingerprint, _file_hash(evidence_path), path_roots


def command_plan_orchestration(
    request_path: pathlib.Path,
    *,
    available_models: set[str] | Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Collect once and freeze a finite complete two-tier analysis plan."""

    contract = _load_contract()
    if contract.get("orchestration_state_schema") != ORCHESTRATION_STATE_SCHEMA:
        raise CreditAnalysisError("orchestration state contract is invalid")
    if contract.get("chunk_manifest_schema") != CHUNK_MANIFEST_SCHEMA:
        raise CreditAnalysisError("chunk manifest contract is invalid")
    models = _validate_orchestration_models(
        contract,
        _codex_model_catalog() if available_models is None else available_models,
    )
    ledger = _load_ledger()
    request = _validate_request(request_path, contract, ledger)
    analysis_id = secrets.token_hex(12)
    evidence, evidence_fingerprint, evidence_sha256, path_roots = (
        _collect_orchestration_evidence(
            request=request,
            contract=contract,
            ledger=ledger,
            analysis_id=analysis_id,
        )
    )
    orchestration_root = pathlib.Path(request["task_root"]) / "orchestration"
    if orchestration_root.exists() or orchestration_root.is_symlink():
        raise CreditAnalysisError("task root already contains orchestration state")
    orchestration_root.mkdir(parents=True)
    canonical_state, canonical_state_record = _collect_canonical_state_snapshot(
        evidence=evidence,
        path_roots=path_roots,
        orchestration_root=orchestration_root,
        ledger=ledger,
    )
    surfaces: list[dict[str, Any]] = []
    confirmation_tasks: list[dict[str, Any]] = []
    surface_order = _surface_order_for_request(request, contract)
    formatted = _format_shared_candidates(
        analysis_id=analysis_id,
        surface_order=surface_order,
        evidence=evidence,
        evidence_path=pathlib.Path(request["evidence_path"]),
        canonical_state=canonical_state,
        contract=contract,
    )
    primary_tasks, shared_membership = _plan_shared_primary_tasks(
        analysis_id=analysis_id,
        records=formatted,
        evidence_path=pathlib.Path(request["evidence_path"]),
        orchestration_root=orchestration_root,
        contract=contract,
    )
    luna_tasks = list(primary_tasks)
    for surface_id in surface_order:
        surface_records = [
            record
            for record in formatted
            if surface_id in record["applicable_surfaces"]
        ]
        planned_luna, confirmation, surface = _plan_surface_tasks(
            analysis_id=analysis_id,
            surface_id=surface_id,
            records=surface_records,
            primary_tasks=primary_tasks,
            shared_membership=shared_membership,
            orchestration_root=orchestration_root,
            contract=contract,
        )
        luna_tasks.extend(planned_luna)
        confirmation_tasks.append(confirmation)
        surfaces.append(surface)
    maximum_luna_tasks = int(contract["chunking"]["maximum_luna_tasks"])
    if len(luna_tasks) > maximum_luna_tasks:
        raise CreditAnalysisError(
            f"projected Luna queue is clearly runaway: {len(luna_tasks)} calls"
        )
    synthesis_task_id = "synthesis"
    synthesis_task = {
        "task_id": synthesis_task_id,
        "phase": "synthesis",
        "stage": "synthesis",
        "surface_id": None,
        "ordinal": 1,
        "depth": 0,
        "dependencies": [task["task_id"] for task in confirmation_tasks],
        "candidate_ids": [],
        "input_sha256": None,
        "artifacts": _task_artifact_paths(orchestration_root, synthesis_task_id),
    }
    semantic_contract = contract["semantic_call_contract"]
    projected_sol = len(confirmation_tasks) + 1
    if request["mode"] == "full-analysis":
        if projected_sol != semantic_contract["full_analysis_sol_calls"]:
            raise CreditAnalysisError("full analysis must project exactly six Sol calls")
        if len(confirmation_tasks) != semantic_contract["surface_confirmation_calls"]:
            raise CreditAnalysisError("full analysis surface confirmation count is invalid")
    projected_semantic = len(luna_tasks) + projected_sol
    maximum_semantic = int(contract["chunking"]["maximum_semantic_tasks"])
    if projected_semantic > maximum_semantic:
        raise CreditAnalysisError(
            "projected semantic queue is clearly runaway: "
            f"{projected_semantic} calls exceeds {maximum_semantic}"
        )
    manifest = {
        "schema": CHUNK_MANIFEST_SCHEMA,
        "analysis_id": analysis_id,
        "action": request["action"],
        "mode": request["mode"],
        "mutation_authority": False,
        "evidence_fingerprint": evidence_fingerprint,
        "source_freeze": evidence["analysis_lineage"],
        "surface_contract_version": contract["surface_contract_version"],
        "surface_order": surface_order,
        "models": models,
        "chunking": contract["chunking"],
        "canonical_state": canonical_state_record,
        "shared_candidate_count": len(formatted),
        "shared_candidate_ids": [record["candidate_id"] for record in formatted],
        "shared_primary_task_ids": [task["task_id"] for task in primary_tasks],
        "shared_primary_membership": shared_membership,
        "surfaces": surfaces,
        "luna_tasks": luna_tasks,
        "confirmation_tasks": confirmation_tasks,
        "synthesis_task": synthesis_task,
        "projected_luna_calls": len(luna_tasks),
        "projected_sol_calls": projected_sol,
        "projected_semantic_calls": projected_semantic,
    }
    _validate_frozen_manifest(manifest, contract)
    manifest_path = orchestration_root / "chunk-manifest.json"
    _exclusive_json(manifest_path, manifest, "chunk manifest")
    manifest_sha256 = _file_hash(manifest_path)
    task_order = [
        *[task["task_id"] for task in luna_tasks],
        *[task["task_id"] for task in confirmation_tasks],
        synthesis_task_id,
    ]
    execution: dict[str, dict[str, Any]] = {
        task_id: {"status": "pending", "attempts": [], "result": None}
        for task_id in task_order
    }
    state = {
        "schema": ORCHESTRATION_STATE_SCHEMA,
        "version": 3,
        "analysis_id": analysis_id,
        "action": request["action"],
        "mode": request["mode"],
        "mutation_authority": False,
        "phase": "planned",
        "surface_contract_version": contract["surface_contract_version"],
        "models": models,
        "source": {
            **request["source"],
            "resolved_session": str(request["session"]),
            "fingerprint": evidence["source_fingerprint"],
            "collection_cutoff_utc": evidence["analysis_lineage"][
                "collection_cutoff_utc"
            ],
            "controller_analysis_id": analysis_id,
            "source_is_analysis_child": False,
            "execution_recollects_session": False,
        },
        "window": {
            "requested": request["window"],
            "resolved": evidence["window"],
            "fingerprint": evidence["window_fingerprint"],
        },
        "evidence": {
            "path": str(request["evidence_path"]),
            "fingerprint": evidence_fingerprint,
            "sha256": evidence_sha256,
            "session_reads": evidence["collection"]["session_reads"],
        },
        "manifest": {
            **manifest,
            "path": str(manifest_path),
            "sha256": manifest_sha256,
        },
        "immutable_artifacts": {
            "request": {
                "path": str(request["request_path"]),
                "sha256": request["request_hash"],
            },
            "surface_contract": {
                "path": str(CONTRACT_PATH),
                "sha256": _file_hash(CONTRACT_PATH),
            },
            "evidence": {
                "path": str(request["evidence_path"]),
                "sha256": evidence_sha256,
            },
            "manifest": {"path": str(manifest_path), "sha256": manifest_sha256},
            "canonical_state": canonical_state_record,
            "pricing_profile": (
                {"path": str(request["pricing"]), "sha256": _file_hash(request["pricing"])}
                if request["pricing"] is not None
                else None
            ),
        },
        "task_order": task_order,
        "execution": execution,
        "model_calls": {"luna": 0, "sol": 0},
        "model_attempts": {"luna": 0, "sol": 0},
        "paths": {
            "state": str(request["state_path"]),
            "orchestration_root": str(orchestration_root),
            "transient": str(orchestration_root / "transient"),
            "final_result": request["paths"]["final_result"],
            "report": str(pathlib.Path(request["task_root"]) / "final-report.md"),
        },
        "cleanup": {
            "owner": "credit-analysis-workflow",
            "trigger": "successful-finalization",
            "transient_root": str(orchestration_root / "transient"),
        },
        "final_result": None,
    }
    pathlib.Path(state["paths"]["transient"]).mkdir()
    _exclusive_json(pathlib.Path(request["state_path"]), state, "orchestration state")
    return _orchestration_public_status(state)


def _manifest_without_runtime_fields(state: Mapping[str, Any]) -> dict[str, Any]:
    manifest = dict(state["manifest"])
    manifest.pop("path", None)
    manifest.pop("sha256", None)
    return manifest


def _verify_attempt_record(
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    attempt: Mapping[str, Any],
    attempt_number: int,
) -> None:
    """Verify persisted child identity and every retained attempt artifact hash."""

    if (
        attempt.get("analysis_id") != state["analysis_id"]
        or attempt.get("task_id") != task["task_id"]
        or attempt.get("phase") != task["phase"]
        or attempt.get("attempt_number") != attempt_number
        or attempt.get("model") != _task_model(state, task)
        or not isinstance(attempt.get("model_invoked"), bool)
        or attempt.get("outcome")
        not in {"accepted", "runner-error", "validation-error"}
    ):
        raise CreditAnalysisError("child attempt identity is invalid")
    artifacts = attempt.get("artifacts")
    expected_labels = {"prompt", "schema", "raw_output", "events", "stderr"}
    if not isinstance(artifacts, Mapping) or set(artifacts) != expected_labels:
        raise CreditAnalysisError("child attempt artifact ledger is invalid")
    root = pathlib.Path(str(state["paths"]["orchestration_root"])).resolve()
    path_fields = {
        "prompt": "prompt_path",
        "schema": "schema_path",
        "raw_output": "raw_output_path",
        "events": "events_path",
        "stderr": "stderr_path",
    }
    for label, path_field in path_fields.items():
        artifact = artifacts[label]
        if artifact is None:
            if label != "raw_output" or attempt.get("outcome") != "runner-error":
                raise CreditAnalysisError("child attempt artifact is unexpectedly absent")
            continue
        if not isinstance(artifact, Mapping) or set(artifact) != {"path", "sha256"}:
            raise CreditAnalysisError("child attempt artifact record is invalid")
        path = pathlib.Path(str(artifact["path"])).resolve(strict=True)
        if (
            path.is_symlink()
            or not path.is_file()
            or not (path == root or path.is_relative_to(root))
            or str(path) != str(attempt.get(path_field))
            or _file_hash(path) != artifact.get("sha256")
        ):
            raise CreditAnalysisError("child attempt artifact changed")


def _verify_canonical_state_index(state: Mapping[str, Any]) -> None:
    """Verify every protected final-state snapshot retained during planning."""

    record = state["immutable_artifacts"]["canonical_state"]
    index_path = pathlib.Path(str(record["path"])).resolve(strict=True)
    index = _read_json(index_path, "canonical-state index")
    records = index.get("records")
    if (
        index.get("schema") != CANONICAL_STATE_SCHEMA
        or not isinstance(records, list)
        or index.get("record_count") != len(records)
        or record.get("record_count") != len(records)
    ):
        raise CreditAnalysisError("canonical-state index is invalid")
    root = index_path.parent.resolve()
    identities: set[str] = set()
    references: set[str] = set()
    for item in records:
        if not isinstance(item, Mapping):
            raise CreditAnalysisError("canonical-state record is invalid")
        item_id = item.get("id")
        reference = item.get("artifact_reference")
        if (
            not isinstance(item_id, str)
            or item_id in identities
            or not isinstance(reference, str)
            or reference in references
        ):
            raise CreditAnalysisError("canonical-state identity is invalid")
        identities.add(item_id)
        references.add(reference)
        snapshot_path = item.get("snapshot_path")
        snapshot_hash = item.get("snapshot_sha256")
        if snapshot_path is None:
            if snapshot_hash is not None:
                raise CreditAnalysisError("canonical-state snapshot hash is orphaned")
            continue
        path = pathlib.Path(str(snapshot_path)).resolve(strict=True)
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.is_relative_to(root)
            or _file_hash(path) != snapshot_hash
        ):
            raise CreditAnalysisError("canonical-state snapshot changed")


def _load_orchestration_state(
    state_path: pathlib.Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    path = state_path.expanduser().resolve(strict=True)
    state = _read_json(path, "orchestration state")
    if state.get("schema") != ORCHESTRATION_STATE_SCHEMA or state.get("version") != 3:
        raise CreditAnalysisError("orchestration state schema is invalid")
    if state.get("mutation_authority") is not False:
        raise CreditAnalysisError("orchestration mutation authority is invalid")
    if state.get("phase") not in {"planned", "executing", "complete"}:
        raise CreditAnalysisError("orchestration phase is invalid")
    if state.get("paths", {}).get("state") != str(path):
        raise CreditAnalysisError("orchestration state path is invalid")
    immutable = state.get("immutable_artifacts")
    if not isinstance(immutable, Mapping):
        raise CreditAnalysisError("orchestration immutable artifacts are invalid")
    for label in (
        "request",
        "surface_contract",
        "evidence",
        "manifest",
        "canonical_state",
    ):
        record = immutable.get(label)
        if not isinstance(record, Mapping):
            raise CreditAnalysisError(f"immutable {label} record is invalid")
        artifact = pathlib.Path(str(record.get("path"))).resolve(strict=True)
        if artifact.is_symlink() or not artifact.is_file():
            raise CreditAnalysisError(f"immutable {label} artifact is invalid")
        if _file_hash(artifact) != record.get("sha256"):
            raise CreditAnalysisError(f"immutable {label} artifact changed")
    _verify_canonical_state_index(state)
    pricing = immutable.get("pricing_profile")
    if pricing is not None:
        if not isinstance(pricing, Mapping):
            raise CreditAnalysisError("immutable pricing record is invalid")
        pricing_path = pathlib.Path(str(pricing.get("path"))).resolve(strict=True)
        if _file_hash(pricing_path) != pricing.get("sha256"):
            raise CreditAnalysisError("immutable pricing profile changed")
    contract = _load_contract()
    manifest_path = pathlib.Path(str(state["manifest"]["path"]))
    manifest = _read_json(manifest_path, "chunk manifest")
    if manifest != _manifest_without_runtime_fields(state):
        raise CreditAnalysisError("orchestration manifest state mismatch")
    _validate_frozen_manifest(manifest, contract)
    evidence_path = pathlib.Path(str(state["evidence"]["path"]))
    evidence = _read_json(evidence_path, "retained evidence")
    if (
        evidence.get("analysis_id") != state.get("analysis_id")
        or evidence.get("evidence_fingerprint") != state["evidence"]["fingerprint"]
        or evidence.get("collection", {}).get("session_reads") != 1
        or evidence.get("analysis_lineage") != state["manifest"]["source_freeze"]
        or state.get("source", {}).get("execution_recollects_session") is not False
    ):
        raise CreditAnalysisError("orchestration evidence identity is invalid")
    task_order = state.get("task_order")
    execution = state.get("execution")
    expected_order = [
        *[task["task_id"] for task in manifest["luna_tasks"]],
        *[task["task_id"] for task in manifest["confirmation_tasks"]],
        manifest["synthesis_task"]["task_id"],
    ]
    if task_order != expected_order or not isinstance(execution, Mapping):
        raise CreditAnalysisError("orchestration task order is invalid")
    if set(execution) != set(expected_order):
        raise CreditAnalysisError("orchestration execution records are invalid")
    for ledger_name in ("model_calls", "model_attempts"):
        ledger = state.get(ledger_name)
        if (
            not isinstance(ledger, Mapping)
            or set(ledger) != {"luna", "sol"}
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in ledger.values()
            )
        ):
            raise CreditAnalysisError(f"orchestration {ledger_name} is invalid")
    if any(
        state["model_calls"][key] > state["model_attempts"][key]
        for key in ("luna", "sol")
    ):
        raise CreditAnalysisError("accepted model calls exceed model attempts")
    frozen_tasks = _task_map(manifest)
    for task_id in expected_order:
        record = execution[task_id]
        if not isinstance(record, Mapping) or record.get("status") not in {
            "pending",
            "complete",
        }:
            raise CreditAnalysisError("orchestration task status is invalid")
        if not isinstance(record.get("attempts"), list):
            raise CreditAnalysisError("orchestration task attempts are invalid")
        for attempt_number, attempt in enumerate(record["attempts"], start=1):
            if not isinstance(attempt, Mapping):
                raise CreditAnalysisError("orchestration task attempt is invalid")
            _verify_attempt_record(
                state,
                frozen_tasks[task_id],
                attempt,
                attempt_number,
            )
        result_record = record.get("result")
        if record.get("status") == "complete":
            if not isinstance(result_record, Mapping):
                raise CreditAnalysisError("completed task result record is invalid")
            task = frozen_tasks[task_id]
            result_path = pathlib.Path(str(result_record.get("path"))).resolve(strict=True)
            expected_result_path = pathlib.Path(str(task["artifacts"]["result"])).resolve()
            if (
                result_path.is_symlink()
                or not result_path.is_file()
                or result_path != expected_result_path
                or result_record.get("analysis_id") != state["analysis_id"]
                or result_record.get("task_id") != task_id
                or result_record.get("phase") != task["phase"]
                or result_record.get("model") != _task_model(state, task)
            ):
                raise CreditAnalysisError("completed task result is missing")
            result_value = _read_json(result_path, f"completed result {task_id}")
            if (
                _file_hash(result_path) != result_record.get("sha256")
                or _content_hash(result_value) != result_record.get("content_hash")
            ):
                raise CreditAnalysisError("completed task result changed")
            for label in ("prompt", "schema"):
                artifact_path = pathlib.Path(str(task["artifacts"][label])).resolve(
                    strict=True
                )
                if _file_hash(artifact_path) != result_record.get(f"{label}_sha256"):
                    raise CreditAnalysisError(f"completed task {label} changed")
            if (
                record["attempts"]
                and record["attempts"][-1].get("outcome") != "accepted"
                and result_record.get("recovered_without_model_call") is not True
            ):
                raise CreditAnalysisError("completed task has no accepted final attempt")
        elif result_record is not None:
            raise CreditAnalysisError("pending task has an accepted result")
        elif any(attempt.get("outcome") == "accepted" for attempt in record["attempts"]):
            raise CreditAnalysisError("pending task has an accepted attempt")
    final_record = state.get("final_result")
    if state["phase"] == "complete":
        if not all(execution[task_id]["status"] == "complete" for task_id in expected_order):
            raise CreditAnalysisError("complete orchestration has pending tasks")
        if not isinstance(final_record, Mapping):
            raise CreditAnalysisError("complete orchestration final record is invalid")
        final_path = pathlib.Path(str(final_record.get("path"))).resolve(strict=True)
        report_path = pathlib.Path(str(final_record.get("report_path"))).resolve(
            strict=True
        )
        if (
            final_path != pathlib.Path(str(state["paths"]["final_result"])).resolve()
            or report_path != pathlib.Path(str(state["paths"]["report"])).resolve()
            or _file_hash(final_path) != final_record.get("sha256")
            or _file_hash(report_path) != final_record.get("report_sha256")
            or _content_hash(_read_json(final_path, "orchestration final result"))
            != final_record.get("content_hash")
        ):
            raise CreditAnalysisError("complete orchestration final artifact changed")
    elif final_record is not None:
        raise CreditAnalysisError("incomplete orchestration has a final record")
    return state, evidence, contract


def _save_orchestration_state(state: Mapping[str, Any]) -> None:
    _atomic_json(pathlib.Path(state["paths"]["state"]), state, "orchestration state")


def command_orchestration_status(state_path: pathlib.Path) -> dict[str, Any]:
    state, _, _ = _load_orchestration_state(state_path)
    return _orchestration_public_status(state)


LUNA_ASSESSMENT_FIELDS = {
    "candidate_ids",
    "surface_id",
    "disposition",
    "reason",
    "evidence_refs",
}
LUNA_FINDING_FIELDS = {
    "id",
    "title",
    "problem_summary",
    "candidate_ids",
    "surface_id",
    "evidence_refs",
    "producer_type",
    "producer_owner",
    "proposed_durable_control",
    "recurrence_likely",
    "savings_justifies_maintenance",
    "material_variant_ids",
}
LUNA_RISK_FIELDS = {
    "id",
    "description",
    "candidate_ids",
    "surface_id",
    "evidence_refs",
    "verification_needed",
    "material_variant_ids",
}
LUNA_TEMPORARY_FIELDS = {
    "id",
    "problem_solved",
    "candidate_ids",
    "surface_id",
    "observed_temporary_control",
    "canonical_owner_hint",
    "evidence_refs",
    "material_variant_ids",
}
LUNA_CHILD_ASSESSMENT_FIELDS = (LUNA_ASSESSMENT_FIELDS - {"surface_id"}) | {
    "provisional_findings",
    "plausible_risks",
    "temporary_control_candidates",
}
LUNA_PRIMARY_CHILD_ASSESSMENT_FIELDS = (
    LUNA_CHILD_ASSESSMENT_FIELDS - {"candidate_ids"}
) | {"candidate_id", "surface_id"}
LUNA_CHILD_FINDING_FIELDS = LUNA_FINDING_FIELDS - {"candidate_ids", "surface_id"}
LUNA_CHILD_RISK_FIELDS = LUNA_RISK_FIELDS - {"candidate_ids", "surface_id"}
LUNA_CHILD_TEMPORARY_FIELDS = LUNA_TEMPORARY_FIELDS - {
    "candidate_ids",
    "surface_id",
}
LUNA_CHILD_RESULT_FIELDS = {
    "schema",
    "analysis_id",
    "task_id",
    "surface_id",
    "stage",
    "input_sha256",
    "candidate_assessments",
    "preserved_variant_ids",
}
LUNA_RESULT_FIELDS = {
    "schema",
    "analysis_id",
    "task_id",
    "surface_id",
    "stage",
    "input_sha256",
    "candidate_assessments",
    "provisional_findings",
    "plausible_risks",
    "temporary_control_candidates",
    "preserved_variant_ids",
}
CONFIRMATION_ASSESSMENT_FIELDS = {
    "candidate_ids",
    "disposition",
    "reason",
    "evidence_refs",
}
CONFIRMATION_FINDING_FIELDS = {
    "id",
    "title",
    "problem_summary",
    "waste_kind",
    "candidate_ids",
    "affected_call_ids",
    "evidence_refs",
    "evidence_narrative",
    "producer_type",
    "producer_owner",
    "proposed_durable_control",
    "implementation_status",
    "targeted_verification",
    "observed_avoidable_call_count",
    "recurrence",
    "confidence",
    "complexity",
    "one_time_implementation_cost",
    "helper_categories",
    "contributing_surfaces",
}
CONFIRMATION_RISK_FIELDS = {
    "id",
    "description",
    "candidate_ids",
    "affected_call_ids",
    "evidence_refs",
    "competing_explanations",
    "missing_fact",
    "verification_needed",
}
CONFIRMATION_CHILD_ASSESSMENT_FIELDS = CONFIRMATION_ASSESSMENT_FIELDS | {
    "confirmed_findings",
    "plausible_risks",
}
CONFIRMATION_CHILD_FINDING_FIELDS = CONFIRMATION_FINDING_FIELDS - {
    "candidate_ids",
    "affected_call_ids",
}
CONFIRMATION_CHILD_RISK_FIELDS = CONFIRMATION_RISK_FIELDS - {
    "candidate_ids",
    "affected_call_ids",
}
TEMPORARY_REVIEW_FIELDS = {
    "id",
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
}
TEMPORARY_CONTRIBUTION_FIELDS = {
    "id",
    "temporary_control_id",
    "owner_key",
    "control_key",
    "candidate_ids",
    "evidence_refs",
    "contribution",
    "material_variant_id",
}
CONFIRMATION_RESULT_FIELDS = {
    "schema",
    "analysis_id",
    "task_id",
    "surface_id",
    "input_sha256",
    "candidate_assessments",
    "confirmed_findings",
    "plausible_risks",
    "temporary_control_reviews",
    "temporary_control_contributions",
    "helper_category_reviews",
}
CONFIRMATION_CHILD_RESULT_FIELDS = CONFIRMATION_RESULT_FIELDS - {
    "confirmed_findings",
    "plausible_risks",
}
SYNTHESIS_RESULT_FIELDS = {
    "schema",
    "analysis_id",
    "task_id",
    "input_sha256",
    "finding_groups",
    "risk_order",
    "temporary_control_merges",
    "call_classifications",
    "producer_groups",
    "analysis_summary",
}


def _closed_result(value: Mapping[str, Any], fields: set[str], label: str) -> None:
    if set(value) != fields:
        missing = sorted(fields - set(value))
        extra = sorted(set(value) - fields)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("unknown " + ", ".join(extra))
        raise CreditAnalysisError(f"{label} fields are invalid: {'; '.join(detail)}")


def _result_strings(value: Any, label: str, *, empty: bool = False) -> list[str]:
    if (
        not isinstance(value, list)
        or (not empty and not value)
        or not all(isinstance(item, str) and item for item in value)
    ):
        qualifier = "string list" if empty else "nonempty string list"
        raise CreditAnalysisError(f"{label} must be a {qualifier}")
    result = list(value)
    if len(result) != len(set(result)):
        raise CreditAnalysisError(f"{label} values must be unique")
    return result


def _result_deduped_strings(
    value: Any, label: str, *, empty: bool = False
) -> list[str]:
    """Normalize only exact duplicate descriptive strings while preserving order."""

    if (
        not isinstance(value, list)
        or (not empty and not value)
        or not all(isinstance(item, str) and item for item in value)
    ):
        qualifier = "string list" if empty else "nonempty string list"
        raise CreditAnalysisError(f"{label} must be a {qualifier}")
    return list(dict.fromkeys(value))


def _result_objects(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise CreditAnalysisError(f"{label} must be an object list")
    return list(value)


def _task_map(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    tasks = [
        *manifest["luna_tasks"],
        *manifest["confirmation_tasks"],
        manifest["synthesis_task"],
    ]
    return {str(task["task_id"]): task for task in tasks}


def _surface_manifest(
    manifest: Mapping[str, Any], surface_id: str
) -> dict[str, Any]:
    for surface in manifest["surfaces"]:
        if surface["surface_id"] == surface_id:
            return surface
    raise CreditAnalysisError(f"surface is absent from manifest: {surface_id}")


def _variant_id(kind: str, item: Mapping[str, Any]) -> str:
    return f"variant.{kind}.{_content_hash(item)[:24]}"


def _luna_variant_ids(result: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for kind, key in (
        ("finding", "provisional_findings"),
        ("risk", "plausible_risks"),
        ("temporary", "temporary_control_candidates"),
    ):
        for item in result[key]:
            variant = _variant_id(kind, item)
            if variant not in values:
                values.append(variant)
    return values


def _allowed_evidence_refs_by_candidate(
    surface_index: Mapping[str, Any],
) -> dict[str, set[str]]:
    dossiers = surface_index.get("verification_dossiers")
    if not isinstance(dossiers, list):
        raise CreditAnalysisError("surface verification dossiers are invalid")
    result: dict[str, set[str]] = {}
    for dossier in dossiers:
        if not isinstance(dossier, Mapping):
            raise CreditAnalysisError("surface verification dossier is invalid")
        candidate_id = dossier.get("candidate_id")
        refs = dossier.get("original_evidence_refs")
        if not isinstance(candidate_id, str) or not isinstance(refs, list):
            raise CreditAnalysisError("surface verification dossier identity is invalid")
        result[candidate_id] = {str(ref) for ref in refs if isinstance(ref, str)}
    return result


def _expanded_assessment_candidates(
    assessments: Sequence[Mapping[str, Any]],
) -> list[str]:
    return [
        candidate_id
        for assessment in assessments
        for candidate_id in assessment["candidate_ids"]
    ]


def _validate_luna_result(
    raw: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    input_sha256: str,
    input_variant_ids: list[str],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    _closed_result(raw, LUNA_CHILD_RESULT_FIELDS, "Luna child result")
    if (
        raw.get("schema") != LUNA_CHILD_RESULT_SCHEMA
        or raw.get("analysis_id") != state["analysis_id"]
        or raw.get("task_id") != task["task_id"]
        or raw.get("surface_id") != task["surface_id"]
        or raw.get("stage") != task["stage"]
        or raw.get("input_sha256") != input_sha256
    ):
        raise CreditAnalysisError("Luna result identity is invalid")
    dispositions = set(contract["luna_dispositions"])
    assessments = _result_objects(raw["candidate_assessments"], "Luna assessments")
    preserved = _result_strings(
        raw["preserved_variant_ids"], "preserved variant IDs", empty=True
    )
    if preserved != input_variant_ids:
        raise CreditAnalysisError("Luna consolidation did not preserve input variants")
    allowed_candidates = set(task["candidate_ids"])
    normalized_assessments: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    temporary: list[dict[str, Any]] = []
    finding_ids: set[str] = set()
    risk_ids: set[str] = set()
    temporary_ids: set[str] = set()
    used_material_variants: list[str] = []
    primary = task["phase"] == "luna-primary"
    if primary and len(assessments) != len(task["candidate_pairs"]):
        raise CreditAnalysisError(
            "primary Luna assessments must align with candidate-surface order"
        )
    for index, assessment in enumerate(assessments, start=1):
        _closed_result(
            assessment,
            (
                LUNA_PRIMARY_CHILD_ASSESSMENT_FIELDS
                if primary
                else LUNA_CHILD_ASSESSMENT_FIELDS
            ),
            f"Luna assessment {index}",
        )
        if primary:
            expected_candidate, expected_surface = task["candidate_pairs"][index - 1]
            if (
                assessment.get("candidate_id") != expected_candidate
                or assessment.get("surface_id") != expected_surface
            ):
                raise CreditAnalysisError(
                    "primary Luna candidate-surface assessment is reordered"
                )
            candidates = [str(expected_candidate)]
            surface_id = str(expected_surface)
        else:
            candidates = _result_strings(
                assessment.get("candidate_ids"),
                f"Luna assessment {index} candidates",
            )
            surface_id = str(task["surface_id"])
        if not set(candidates) <= allowed_candidates:
            raise CreditAnalysisError("Luna assessment references an unknown candidate")
        if surface_id not in state["manifest"]["surface_order"]:
            raise CreditAnalysisError("Luna assessment surface is invalid")
        disposition = assessment.get("disposition")
        if disposition not in dispositions:
            raise CreditAnalysisError("Luna assessment disposition is invalid")
        if not isinstance(assessment.get("reason"), str) or not assessment[
            "reason"
        ].strip():
            raise CreditAnalysisError("Luna assessment reason is missing")
        assessment_refs = _result_deduped_strings(
            assessment.get("evidence_refs"), "Luna assessment evidence"
        )
        nested_findings = _result_objects(
            assessment.get("provisional_findings"), "Luna assessment findings"
        )
        nested_risks = _result_objects(
            assessment.get("plausible_risks"), "Luna assessment risks"
        )
        nested_temporary = _result_objects(
            assessment.get("temporary_control_candidates"),
            "Luna assessment temporary controls",
        )
        if disposition == "provisional-finding-evidence":
            if not nested_findings or nested_risks:
                raise CreditAnalysisError(
                    "provisional finding assessment requires findings only"
                )
        elif disposition == "plausible-risk":
            if not nested_risks or nested_findings:
                raise CreditAnalysisError("risk assessment requires risks only")
        elif nested_findings or nested_risks:
            raise CreditAnalysisError(
                "dismissed or necessary assessment has semantic objects"
            )
        for finding_index, child_finding in enumerate(nested_findings, start=1):
            _closed_result(
                child_finding,
                LUNA_CHILD_FINDING_FIELDS,
                f"Luna finding {index}.{finding_index}",
            )
            finding_id = _identifier(
                child_finding.get("id"), f"Luna finding {index}.{finding_index} ID"
            )
            if finding_id in finding_ids:
                raise CreditAnalysisError("Luna finding ID is duplicated")
            finding_ids.add(finding_id)
            finding_refs = _result_deduped_strings(
                child_finding.get("evidence_refs"), "Luna finding evidence"
            )
            variants = _result_strings(
                child_finding.get("material_variant_ids"),
                "Luna finding material variants",
                empty=True,
            )
            used_material_variants.extend(variants)
            if not isinstance(
                child_finding.get("recurrence_likely"), bool
            ) or not isinstance(
                child_finding.get("savings_justifies_maintenance"), bool
            ):
                raise CreditAnalysisError("Luna finding recurrence inputs are invalid")
            findings.append(
                {
                    **child_finding,
                    "candidate_ids": candidates,
                    "surface_id": surface_id,
                    "evidence_refs": finding_refs,
                }
            )
        for risk_index, child_risk in enumerate(nested_risks, start=1):
            _closed_result(
                child_risk,
                LUNA_CHILD_RISK_FIELDS,
                f"Luna risk {index}.{risk_index}",
            )
            risk_id = _identifier(
                child_risk.get("id"), f"Luna risk {index}.{risk_index} ID"
            )
            if risk_id in risk_ids:
                raise CreditAnalysisError("Luna risk ID is duplicated")
            risk_ids.add(risk_id)
            risk_refs = _result_deduped_strings(
                child_risk.get("evidence_refs"), "Luna risk evidence"
            )
            risk_verification = _result_deduped_strings(
                child_risk.get("verification_needed"), "Luna risk verification"
            )
            variants = _result_strings(
                child_risk.get("material_variant_ids"),
                "Luna risk variants",
                empty=True,
            )
            used_material_variants.extend(variants)
            risks.append(
                {
                    **child_risk,
                    "candidate_ids": candidates,
                    "surface_id": surface_id,
                    "evidence_refs": risk_refs,
                    "verification_needed": risk_verification,
                }
            )
        for temporary_index, child_item in enumerate(nested_temporary, start=1):
            _closed_result(
                child_item,
                LUNA_CHILD_TEMPORARY_FIELDS,
                f"Luna temporary candidate {index}.{temporary_index}",
            )
            item_id = _identifier(child_item.get("id"), "Luna temporary candidate ID")
            if item_id in temporary_ids:
                raise CreditAnalysisError("Luna temporary candidate ID is duplicated")
            temporary_ids.add(item_id)
            temporary_refs = _result_deduped_strings(
                child_item.get("evidence_refs"), "temporary candidate evidence"
            )
            variants = _result_strings(
                child_item.get("material_variant_ids"),
                "temporary material variants",
                empty=True,
            )
            used_material_variants.extend(variants)
            temporary.append(
                {
                    **child_item,
                    "candidate_ids": candidates,
                    "surface_id": surface_id,
                    "evidence_refs": temporary_refs,
                }
            )
        normalized_assessments.append(
            {
                "candidate_ids": candidates,
                "surface_id": surface_id,
                "disposition": disposition,
                "reason": assessment["reason"],
                "evidence_refs": assessment_refs,
            }
        )
    if sorted(used_material_variants) != sorted(input_variant_ids):
        if input_variant_ids:
            raise CreditAnalysisError("Luna consolidation dropped a material variant")
        if used_material_variants:
            raise CreditAnalysisError("primary Luna result invented a material variant")
    if primary:
        observed_pairs = [
            [assessment["candidate_ids"][0], assessment["surface_id"]]
            for assessment in normalized_assessments
        ]
        if observed_pairs != task["candidate_pairs"]:
            raise CreditAnalysisError(
                "Luna candidate-surface coverage is missing, duplicated, or reordered"
            )
    elif _expanded_assessment_candidates(normalized_assessments) != task["candidate_ids"]:
        raise CreditAnalysisError(
            "Luna candidate coverage is missing, duplicated, or reordered"
        )
    return {
        "schema": LUNA_RESULT_SCHEMA,
        "analysis_id": raw["analysis_id"],
        "task_id": raw["task_id"],
        "surface_id": raw["surface_id"],
        "stage": raw["stage"],
        "input_sha256": raw["input_sha256"],
        "candidate_assessments": normalized_assessments,
        "provisional_findings": findings,
        "plausible_risks": risks,
        "temporary_control_candidates": temporary,
        "preserved_variant_ids": preserved,
    }


def _validate_recurrence_inputs(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CreditAnalysisError(f"{label} must be an object")
    required = {
        "calls_saved_per_affected_run",
        "additional_recurring_calls_per_affected_run",
        "affected_similar_run_frequency",
        "affected_similar_run_frequency_range",
        "estimated_calls_saved_per_similar_run",
        "assumptions",
    }
    _closed_result(value, required, label)
    for key in (
        "calls_saved_per_affected_run",
        "additional_recurring_calls_per_affected_run",
        "affected_similar_run_frequency",
        "estimated_calls_saved_per_similar_run",
    ):
        _number(value.get(key), f"{label} {key}")
    frequency_range = value.get("affected_similar_run_frequency_range")
    if (
        not isinstance(frequency_range, list)
        or len(frequency_range) != 2
        or any(not isinstance(item, (int, float)) for item in frequency_range)
        or frequency_range[0] < 0
        or frequency_range[1] < frequency_range[0]
    ):
        raise CreditAnalysisError(f"{label} frequency range is invalid")
    assumptions = _result_deduped_strings(
        value.get("assumptions"), f"{label} assumptions"
    )
    return {**value, "assumptions": assumptions}


def _validate_confirmation_finding(
    finding: Mapping[str, Any],
    *,
    surface_id: str,
    candidate_to_call: Mapping[str, str],
    allowed_refs: Mapping[str, set[str]],
    contract: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    _closed_result(finding, CONFIRMATION_FINDING_FIELDS, label)
    _identifier(finding.get("id"), f"{label} ID")
    candidates = _result_strings(finding.get("candidate_ids"), f"{label} candidates")
    if not set(candidates) <= set(candidate_to_call):
        raise CreditAnalysisError(f"{label} references an unknown candidate")
    expected_calls = list(dict.fromkeys(candidate_to_call[item] for item in candidates))
    calls = _result_strings(finding.get("affected_call_ids"), f"{label} calls")
    if calls != expected_calls:
        raise CreditAnalysisError(f"{label} affected calls do not match candidates")
    evidence_refs = _result_deduped_strings(
        finding.get("evidence_refs"), f"{label} evidence"
    )
    for candidate in candidates:
        if not set(evidence_refs) & allowed_refs[candidate]:
            raise CreditAnalysisError(f"{label} was not verified against original evidence")
    for key in (
        "title",
        "problem_summary",
        "evidence_narrative",
        "producer_owner",
        "proposed_durable_control",
    ):
        if not isinstance(finding.get(key), str) or not finding[key].strip():
            raise CreditAnalysisError(f"{label} {key} is missing")
    if finding.get("waste_kind") not in contract["waste_kinds"]:
        raise CreditAnalysisError(f"{label} waste kind is invalid")
    if finding.get("producer_type") not in contract["producer_types"]:
        raise CreditAnalysisError(f"{label} producer type is invalid")
    if finding.get("implementation_status") not in contract["implementation_statuses"]:
        raise CreditAnalysisError(f"{label} implementation status is invalid")
    if finding.get("complexity") not in contract["complexities"]:
        raise CreditAnalysisError(f"{label} complexity is invalid")
    verification = _result_deduped_strings(
        finding.get("targeted_verification"), f"{label} verification"
    )
    recurrence = _validate_recurrence_inputs(finding.get("recurrence"), f"{label} recurrence")
    observed = finding.get("observed_avoidable_call_count")
    if not isinstance(observed, int) or isinstance(observed, bool) or observed < 0:
        raise CreditAnalysisError(f"{label} observed count is invalid")
    if finding["waste_kind"] == "context-volume":
        if observed != 0 or any(
            recurrence[key] != 0
            for key in (
                "calls_saved_per_affected_run",
                "estimated_calls_saved_per_similar_run",
            )
        ):
            raise CreditAnalysisError("context-volume finding must save zero model calls")
    confidence = finding.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise CreditAnalysisError(f"{label} confidence is invalid")
    cost = finding.get("one_time_implementation_cost")
    if not isinstance(cost, dict) or set(cost) != COST_FIELDS:
        raise CreditAnalysisError(f"{label} implementation cost is invalid")
    _number(cost.get("estimated_model_calls"), f"{label} implementation cost")
    if not isinstance(cost.get("description"), str) or not cost["description"].strip():
        raise CreditAnalysisError(f"{label} implementation cost description is missing")
    helper_categories = _result_deduped_strings(
        finding.get("helper_categories"), f"{label} helper categories", empty=True
    )
    if not set(helper_categories) <= set(contract["helper_categories"]):
        raise CreditAnalysisError(f"{label} helper category is invalid")
    contributing = _result_deduped_strings(
        finding.get("contributing_surfaces"), f"{label} contributing surfaces"
    )
    if surface_id not in contributing or not set(contributing) <= set(contract["surface_order"]):
        raise CreditAnalysisError(f"{label} contributing surfaces are invalid")
    return {
        **finding,
        "evidence_refs": evidence_refs,
        "targeted_verification": verification,
        "recurrence": recurrence,
        "helper_categories": helper_categories,
        "contributing_surfaces": contributing,
    }


def _validate_temporary_review(
    review: Mapping[str, Any],
    *,
    finding_ids: set[str],
    contract: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    _closed_result(review, TEMPORARY_REVIEW_FIELDS, label)
    _identifier(review.get("id"), f"{label} ID")
    for key in (
        "problem_solved",
        "observed_temporary_control",
        "owning_producer",
    ):
        if not isinstance(review.get(key), str) or not review[key].strip():
            raise CreditAnalysisError(f"{label} {key} is missing")
    affected_calls = _result_strings(
        review.get("affected_call_ids"), f"{label} affected calls"
    )
    canonical_refs = _result_deduped_strings(
        review.get("final_canonical_evidence_refs"), f"{label} canonical evidence"
    )
    disposition = review.get("disposition")
    if disposition not in contract["temporary_control_dispositions"]:
        raise CreditAnalysisError(f"{label} disposition is invalid")
    recurrence = review.get("recurrence_inputs")
    savings = review.get("savings_inputs")
    if not isinstance(recurrence, dict) or set(recurrence) != {
        "likely",
        "frequency_range",
        "basis",
    }:
        raise CreditAnalysisError(f"{label} recurrence inputs are invalid")
    if not isinstance(recurrence.get("likely"), bool):
        raise CreditAnalysisError(f"{label} recurrence likelihood is invalid")
    frequency_range = recurrence.get("frequency_range")
    if (
        not isinstance(frequency_range, list)
        or len(frequency_range) != 2
        or any(not isinstance(item, (int, float)) for item in frequency_range)
        or frequency_range[0] < 0
        or frequency_range[1] < frequency_range[0]
    ):
        raise CreditAnalysisError(f"{label} recurrence range is invalid")
    if not isinstance(recurrence.get("basis"), str) or not recurrence["basis"].strip():
        raise CreditAnalysisError(f"{label} recurrence basis is missing")
    if not isinstance(savings, dict) or set(savings) != {
        "expected_calls_saved",
        "maintenance_model_calls",
        "justifies_maintenance",
        "basis",
    }:
        raise CreditAnalysisError(f"{label} savings inputs are invalid")
    _number(savings.get("expected_calls_saved"), f"{label} expected savings")
    _number(savings.get("maintenance_model_calls"), f"{label} maintenance cost")
    if not isinstance(savings.get("justifies_maintenance"), bool):
        raise CreditAnalysisError(f"{label} maintenance gate is invalid")
    if not isinstance(savings.get("basis"), str) or not savings["basis"].strip():
        raise CreditAnalysisError(f"{label} savings basis is missing")
    finding_id = review.get("finding_id")
    no_finding = review.get("no_finding_reason")
    if disposition == "durable-control-missing":
        if recurrence["likely"] is not True or savings["justifies_maintenance"] is not True:
            raise CreditAnalysisError(
                "durable-control-missing requires recurrence and ROI gates"
            )
        if not isinstance(finding_id, str) or finding_id not in finding_ids:
            raise CreditAnalysisError("durable-control-missing must link its finding")
        if no_finding is not None:
            raise CreditAnalysisError("durable-control-missing cannot have no-finding reason")
    else:
        if finding_id is not None:
            raise CreditAnalysisError("non-defect temporary disposition cannot link a finding")
        if not isinstance(no_finding, str) or not no_finding.strip():
            raise CreditAnalysisError("temporary disposition requires a no-finding reason")
    return {
        **review,
        "affected_call_ids": affected_calls,
        "final_canonical_evidence_refs": canonical_refs,
    }


def _validate_confirmation_result(
    raw: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    input_sha256: str,
    selected_candidate_ids: Sequence[str],
    surface_index: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    _closed_result(
        raw, CONFIRMATION_CHILD_RESULT_FIELDS, "confirmation child result"
    )
    if (
        raw.get("schema") != CONFIRMATION_CHILD_RESULT_SCHEMA
        or raw.get("analysis_id") != state["analysis_id"]
        or raw.get("task_id") != task["task_id"]
        or raw.get("surface_id") != task["surface_id"]
        or raw.get("input_sha256") != input_sha256
    ):
        raise CreditAnalysisError("confirmation result identity is invalid")
    allowed_refs = _allowed_evidence_refs_by_candidate(surface_index)
    candidate_to_call = dict(
        zip(
            surface_index["candidate_ids"],
            surface_index["call_ids"],
            strict=True,
        )
    )
    canonical_refs_by_call: dict[str, set[str]] = defaultdict(set)
    for dossier in surface_index["verification_dossiers"]:
        call_id = str(dossier["call_identity"]["call_id"])
        relationships = dossier.get("relationships")
        final_state = (
            relationships.get("final_canonical_state")
            if isinstance(relationships, Mapping)
            else None
        )
        if isinstance(final_state, list):
            canonical_refs_by_call[call_id].update(
                str(item["evidence_ref"])
                for item in final_state
                if isinstance(item, Mapping)
                and isinstance(item.get("evidence_ref"), str)
            )
    assessments = _result_objects(
        raw["candidate_assessments"], "confirmation assessments"
    )
    dispositions = set(contract["confirmation_dispositions"])
    normalized_assessments: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    finding_ids: set[str] = set()
    risk_ids: set[str] = set()
    for index, assessment in enumerate(assessments, start=1):
        _closed_result(
            assessment,
            CONFIRMATION_CHILD_ASSESSMENT_FIELDS,
            f"confirmation assessment {index}",
        )
        candidates = _result_strings(
            assessment.get("candidate_ids"), "confirmation assessment candidates"
        )
        if not set(candidates) <= set(candidate_to_call):
            raise CreditAnalysisError(
                "confirmation assessment references an unknown candidate"
            )
        disposition = assessment.get("disposition")
        if disposition not in dispositions:
            raise CreditAnalysisError("confirmation assessment disposition is invalid")
        if not isinstance(assessment.get("reason"), str) or not assessment[
            "reason"
        ].strip():
            raise CreditAnalysisError("confirmation assessment reason is missing")
        refs = _result_deduped_strings(
            assessment.get("evidence_refs"), "assessment evidence"
        )
        for candidate in candidates:
            if candidate not in allowed_refs or not set(refs) & allowed_refs[candidate]:
                raise CreditAnalysisError(
                    "confirmation assessment was not checked against original evidence"
                )
        nested_findings = _result_objects(
            assessment.get("confirmed_findings"), "assessment confirmed findings"
        )
        nested_risks = _result_objects(
            assessment.get("plausible_risks"), "assessment plausible risks"
        )
        if disposition == "confirmed-finding":
            if not nested_findings or nested_risks:
                raise CreditAnalysisError(
                    "confirmed assessment requires findings only"
                )
        elif disposition == "plausible-risk":
            if not nested_risks or nested_findings:
                raise CreditAnalysisError("risk assessment requires risks only")
        elif nested_findings or nested_risks:
            raise CreditAnalysisError(
                "dismissed or necessary assessment has semantic objects"
            )
        calls = list(dict.fromkeys(candidate_to_call[item] for item in candidates))
        for finding_index, child_finding in enumerate(nested_findings, start=1):
            _closed_result(
                child_finding,
                CONFIRMATION_CHILD_FINDING_FIELDS,
                f"confirmed child finding {index}.{finding_index}",
            )
            validated = _validate_confirmation_finding(
                {
                    **child_finding,
                    "candidate_ids": candidates,
                    "affected_call_ids": calls,
                },
                surface_id=str(task["surface_id"]),
                candidate_to_call=candidate_to_call,
                allowed_refs=allowed_refs,
                contract=contract,
                label=f"confirmed finding {index}.{finding_index}",
            )
            if validated["id"] in finding_ids:
                raise CreditAnalysisError("confirmed finding ID is duplicated")
            finding_ids.add(validated["id"])
            findings.append(validated)
        for risk_index, child_risk in enumerate(nested_risks, start=1):
            _closed_result(
                child_risk,
                CONFIRMATION_CHILD_RISK_FIELDS,
                f"confirmation risk {index}.{risk_index}",
            )
            risk_id = _identifier(child_risk.get("id"), "confirmation risk ID")
            if risk_id in risk_ids:
                raise CreditAnalysisError("confirmation risk ID is duplicated")
            risk_ids.add(risk_id)
            risk_refs = _result_deduped_strings(
                child_risk.get("evidence_refs"), "risk evidence"
            )
            for candidate in candidates:
                if not set(risk_refs) & allowed_refs[candidate]:
                    raise CreditAnalysisError(
                        "confirmation risk lacks original evidence"
                    )
            competing_explanations = _result_deduped_strings(
                child_risk.get("competing_explanations"), "risk explanations"
            )
            risk_verification = _result_deduped_strings(
                child_risk.get("verification_needed"), "risk verification"
            )
            if not isinstance(child_risk.get("missing_fact"), str) or not child_risk[
                "missing_fact"
            ].strip():
                raise CreditAnalysisError("confirmation risk missing fact is absent")
            risks.append(
                {
                    **child_risk,
                    "candidate_ids": candidates,
                    "affected_call_ids": calls,
                    "evidence_refs": risk_refs,
                    "competing_explanations": competing_explanations,
                    "verification_needed": risk_verification,
                }
            )
        normalized_assessments.append(
            {
                "candidate_ids": candidates,
                "disposition": disposition,
                "reason": assessment["reason"],
                "evidence_refs": refs,
            }
        )
    if _expanded_assessment_candidates(normalized_assessments) != list(
        selected_candidate_ids
    ):
        raise CreditAnalysisError(
            "confirmation coverage is missing, duplicated, or reordered"
        )
    reviews = _result_objects(raw["temporary_control_reviews"], "temporary reviews")
    normalized_reviews: list[dict[str, Any]] = []
    review_ids: set[str] = set()
    for index, review in enumerate(reviews, start=1):
        validated = _validate_temporary_review(
            review,
            finding_ids=finding_ids,
            contract=contract,
            label=f"temporary review {index}",
        )
        if validated["id"] in review_ids:
            raise CreditAnalysisError("temporary review ID is duplicated")
        review_refs = set(validated["final_canonical_evidence_refs"])
        for call_id in validated["affected_call_ids"]:
            if not review_refs & canonical_refs_by_call[str(call_id)]:
                raise CreditAnalysisError(
                    "temporary review lacks controller-frozen canonical evidence"
                )
        review_ids.add(validated["id"])
        normalized_reviews.append(validated)
    if task["surface_id"] == "rework-validation":
        required_review_ids = {
            item["id"]
            for item in _primary_temporary_control_inventory(
                state,
                str(task["surface_id"]),
            )
        }
        if not required_review_ids <= review_ids:
            raise CreditAnalysisError(
                "mandatory temporary-control review omitted a Luna candidate"
            )
    elif reviews:
        raise CreditAnalysisError("temporary-control reviews belong to rework-validation")
    contributions = _result_objects(
        raw["temporary_control_contributions"], "temporary contributions"
    )
    normalized_contributions: list[dict[str, Any]] = []
    contribution_ids: set[str] = set()
    for index, contribution in enumerate(contributions, start=1):
        _closed_result(
            contribution,
            TEMPORARY_CONTRIBUTION_FIELDS,
            f"temporary contribution {index}",
        )
        contribution_id = _identifier(contribution.get("id"), "contribution ID")
        if contribution_id in contribution_ids:
            raise CreditAnalysisError("temporary contribution ID is duplicated")
        contribution_ids.add(contribution_id)
        candidates = _result_strings(
            contribution.get("candidate_ids"), "contribution candidates"
        )
        if not set(candidates) <= set(candidate_to_call):
            raise CreditAnalysisError("temporary contribution references unknown candidate")
        contribution_refs = _result_deduped_strings(
            contribution.get("evidence_refs"), "contribution evidence"
        )
        for key in (
            "temporary_control_id",
            "owner_key",
            "control_key",
            "contribution",
            "material_variant_id",
        ):
            if not isinstance(contribution.get(key), str) or not contribution[key].strip():
                raise CreditAnalysisError(f"temporary contribution {key} is missing")
        normalized_contributions.append(
            {**contribution, "evidence_refs": contribution_refs}
        )
    helper_reviews = _result_objects(
        raw["helper_category_reviews"], "helper category reviews"
    )
    if task["surface_id"] == "helper-contracts":
        categories = [item.get("category") for item in helper_reviews]
        if categories != contract["helper_categories"]:
            raise CreditAnalysisError("helper category review is incomplete or reordered")
    elif helper_reviews:
        raise CreditAnalysisError("helper category reviews belong to helper-contracts")
    return {
        "schema": CONFIRMATION_RESULT_SCHEMA,
        "analysis_id": raw["analysis_id"],
        "task_id": raw["task_id"],
        "surface_id": raw["surface_id"],
        "input_sha256": raw["input_sha256"],
        "candidate_assessments": normalized_assessments,
        "confirmed_findings": findings,
        "plausible_risks": risks,
        "temporary_control_reviews": normalized_reviews,
        "temporary_control_contributions": normalized_contributions,
        "helper_category_reviews": helper_reviews,
    }


FINDING_GROUP_FIELDS = {
    "canonical_finding_id",
    "source_finding_ids",
    "primary_source_finding_id",
    "title",
    "problem_summary",
    "owner_key",
    "control_key",
    "contributing_surfaces",
    "savings_source_finding_id",
}
TEMPORARY_MERGE_FIELDS = {
    "merge_id",
    "owner_key",
    "control_key",
    "review_ids",
    "contribution_ids",
    "disposition",
    "finding_id",
    "no_finding_reason",
    "contributing_surfaces",
}
CALL_CLASSIFICATION_FIELDS = {
    "classification",
    "call_ids",
    "primary_finding_id",
    "reason_code",
    "reason",
}
ORCHESTRATION_PRODUCER_GROUP_FIELDS = {
    "id",
    "producer_type",
    "owner",
    "finding_ids",
    "recommended_control",
    "targeted_verification",
}
ANALYSIS_SUMMARY_FIELDS = {
    "confirmed_count",
    "risk_count",
    "necessary_calls",
    "protocol_overhead_calls",
    "reviewed_no_confirmed_waste_calls",
    "unassessed_calls",
    "avoidable_calls",
    "meaningful_input_output_findings",
}


def _accepted_result(
    state: Mapping[str, Any], task_id: str
) -> dict[str, Any]:
    execution = state["execution"][task_id]
    result = execution.get("result")
    if execution.get("status") != "complete" or not isinstance(result, Mapping):
        raise CreditAnalysisError(f"dependency is incomplete: {task_id}")
    return _read_json(pathlib.Path(str(result["path"])), f"result {task_id}")


def _luna_material_variant_inventory(result: Mapping[str, Any]) -> list[str]:
    if result.get("stage") == "primary":
        return _luna_variant_ids(result)
    return _result_strings(
        result.get("preserved_variant_ids"), "consolidated variants", empty=True
    )


def _read_surface_index(
    state: Mapping[str, Any], surface_id: str
) -> dict[str, Any]:
    surface = _surface_manifest(state["manifest"], surface_id)
    path = pathlib.Path(str(surface["index_path"]))
    if _file_hash(path) != surface["index_sha256"]:
        raise CreditAnalysisError("surface evidence index changed")
    value = _read_json(path, f"surface index {surface_id}")
    if (
        value.get("analysis_id") != state["analysis_id"]
        or value.get("surface_id") != surface_id
        or value.get("candidate_ids") != surface["candidate_ids"]
    ):
        raise CreditAnalysisError("surface evidence index identity is invalid")
    return value


def _surface_luna_projection(
    result: Mapping[str, Any], surface_id: str
) -> dict[str, Any]:
    """Project one surface from a shared Luna result without changing evidence."""

    if result.get("schema") != LUNA_RESULT_SCHEMA:
        raise CreditAnalysisError("Luna dependency schema is invalid")
    projected = dict(result)
    projected["surface_id"] = surface_id
    for key in (
        "candidate_assessments",
        "provisional_findings",
        "plausible_risks",
        "temporary_control_candidates",
    ):
        projected[key] = [
            item
            for item in result[key]
            if isinstance(item, Mapping) and item.get("surface_id") == surface_id
        ]
    return projected


def _selected_luna_projection(
    result: Mapping[str, Any], selected: set[str]
) -> dict[str, Any]:
    """Bound a Sol packet to its declared confirmation selection."""

    projected = dict(result)
    assessments: list[dict[str, Any]] = []
    for assessment in result["candidate_assessments"]:
        candidates = [
            candidate
            for candidate in assessment["candidate_ids"]
            if candidate in selected
        ]
        if candidates:
            assessments.append({**assessment, "candidate_ids": candidates})
    projected["candidate_assessments"] = assessments
    for key in (
        "provisional_findings",
        "plausible_risks",
        "temporary_control_candidates",
    ):
        projected[key] = [
            item
            for item in result[key]
            if set(item["candidate_ids"]) & selected
        ]
    return projected


def _write_or_verify_task_input(path: pathlib.Path, payload: Mapping[str, Any]) -> str:
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise CreditAnalysisError("model task input path is invalid")
        existing = _read_json(path, "model task input")
        if existing != payload:
            raise CreditAnalysisError("model task input changed across resume")
    else:
        _exclusive_json(path, payload, "model task input")
    return _file_hash(path)


def _primary_temporary_control_inventory(
    state: Mapping[str, Any], surface_id: str
) -> list[dict[str, Any]]:
    """Retain every primary Luna temporary-control candidate for confirmation."""

    inventory: list[dict[str, Any]] = []
    seen: set[str] = set()
    for task in state["manifest"]["luna_tasks"]:
        if task["phase"] != "luna-primary":
            continue
        result = _accepted_result(state, str(task["task_id"]))
        for item in result["temporary_control_candidates"]:
            if item.get("surface_id") != surface_id:
                continue
            item_id = str(item["id"])
            if item_id in seen:
                raise CreditAnalysisError("Luna temporary-control ID is duplicated")
            seen.add(item_id)
            inventory.append({**item, "source_task_id": task["task_id"]})
    return inventory


def _luna_coverage_inventory(state: Mapping[str, Any]) -> dict[str, Any]:
    """Build the complete compact primary candidate-surface disposition matrix."""

    rows: list[list[str]] = []
    for task in state["manifest"]["luna_tasks"]:
        if task["phase"] != "luna-primary":
            continue
        result = _accepted_result(state, str(task["task_id"]))
        rows.extend(
            [
                str(assessment["candidate_ids"][0]),
                str(assessment["surface_id"]),
                str(assessment["disposition"]),
            ]
            for assessment in result["candidate_assessments"]
        )
    expected = [
        pair
        for task in state["manifest"]["luna_tasks"]
        if task["phase"] == "luna-primary"
        for pair in task["candidate_pairs"]
    ]
    observed = [[row[0], row[1]] for row in rows]
    if observed != expected:
        raise CreditAnalysisError("complete Luna coverage inventory is inconsistent")
    return {
        "fields": ["candidate_id", "surface_id", "disposition"],
        "rows": rows,
        "candidate_surface_pair_count": len(rows),
    }


def _materialize_task_input(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
    task: Mapping[str, Any],
) -> tuple[dict[str, Any], str, list[str]]:
    input_path = pathlib.Path(str(task["artifacts"]["input"]))
    if task["phase"] == "luna-primary":
        payload = _read_json(input_path, "Luna primary input")
        digest = _file_hash(input_path)
        if digest != task["input_sha256"]:
            raise CreditAnalysisError("Luna primary input changed")
        return payload, digest, []
    raw_dependencies = [
        _accepted_result(state, dependency) for dependency in task["dependencies"]
    ]
    dependencies = (
        [
            _surface_luna_projection(result, str(task["surface_id"]))
            for result in raw_dependencies
        ]
        if task["phase"] in {"luna-consolidation", "surface-confirmation"}
        else raw_dependencies
    )
    input_variant_ids: list[str] = []
    if task["phase"] == "luna-consolidation":
        for result in dependencies:
            for variant in _luna_material_variant_inventory(result):
                if variant not in input_variant_ids:
                    input_variant_ids.append(variant)
        payload = {
            "schema": MODEL_TASK_SCHEMA,
            "analysis_id": state["analysis_id"],
            "task_id": task["task_id"],
            "phase": task["phase"],
            "surface_id": task["surface_id"],
            "candidate_ids": task["candidate_ids"],
            "input_variant_ids": input_variant_ids,
            "dependency_results": dependencies,
        }
    elif task["phase"] == "surface-confirmation":
        surface_index = _read_surface_index(state, str(task["surface_id"]))
        selection = _confirmation_selection(
            results=dependencies,
            surface_index=surface_index,
            contract=contract,
        )
        selected = set(selection["selected_candidate_ids"])
        dossiers = [
            dossier
            for dossier in surface_index["verification_dossiers"]
            if dossier["candidate_id"] in selected
        ]
        payload = {
            "schema": MODEL_TASK_SCHEMA,
            "analysis_id": state["analysis_id"],
            "task_id": task["task_id"],
            "phase": task["phase"],
            "surface_id": task["surface_id"],
            "candidate_ids": selection["selected_candidate_ids"],
            "surface_candidate_count": len(task["candidate_ids"]),
            "confirmation_selection": selection,
            "luna_results": [
                _selected_luna_projection(result, selected)
                for result in dependencies
            ],
            "candidate_evidence_map": _confirmation_evidence_map(dossiers),
            "original_evidence_dossiers": dossiers,
            "temporary_control_dispositions": contract[
                "temporary_control_dispositions"
            ],
            "primary_temporary_control_inventory": (
                _primary_temporary_control_inventory(
                    state,
                    str(task["surface_id"]),
                )
                if task["surface_id"] == "rework-validation"
                else []
            ),
            "necessary_reason_codes": contract["necessary_reason_codes"],
            "helper_categories": contract["helper_categories"],
        }
        if _json_chars(payload) >= int(contract["chunking"]["confirmation_packet_chars"]):
            raise CreditAnalysisError(
                f"confirmation packet exceeds the frozen limit: {task['surface_id']}"
            )
    elif task["phase"] == "synthesis":
        payload = {
            "schema": MODEL_TASK_SCHEMA,
            "analysis_id": state["analysis_id"],
            "task_id": task["task_id"],
            "phase": task["phase"],
            "surface_order": state["manifest"]["surface_order"],
            "confirmation_results": dependencies,
            "luna_coverage_inventory": _luna_coverage_inventory(state),
            "call_inventory": evidence["call_inventory"],
            "deterministic_totals": evidence["totals"],
            "pricing": evidence["pricing"],
            "call_classifications": contract["call_classifications"],
            "necessary_reason_codes": contract["necessary_reason_codes"],
            "temporary_control_dispositions": contract[
                "temporary_control_dispositions"
            ],
        }
        if _json_chars(payload) >= int(contract["chunking"]["synthesis_packet_chars"]):
            raise CreditAnalysisError("synthesis packet exceeds the frozen limit")
    else:
        raise CreditAnalysisError(f"unknown model task phase: {task['phase']}")
    digest = _write_or_verify_task_input(input_path, payload)
    return payload, digest, input_variant_ids


def _output_schema_for_task(
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    input_sha256: str,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the exact strict schema also enforced by Python validation."""

    def string() -> dict[str, Any]:
        return {"type": "string", "minLength": 1}

    def number() -> dict[str, Any]:
        return {"type": "number"}

    def integer() -> dict[str, Any]:
        return {"type": "integer"}

    def boolean() -> dict[str, Any]:
        return {"type": "boolean"}

    def nullable_string() -> dict[str, Any]:
        return {"type": ["string", "null"], "minLength": 1}

    def identifier() -> dict[str, Any]:
        return {"type": "string", "pattern": r"^[a-z0-9][a-z0-9._-]*$"}

    def nullable_identifier() -> dict[str, Any]:
        return {
            "type": ["string", "null"],
            "pattern": r"^[a-z0-9][a-z0-9._-]*$",
        }

    def enum_string(values: Sequence[str]) -> dict[str, Any]:
        return {"type": "string", "enum": list(values)}

    def nullable_enum(values: Sequence[str]) -> dict[str, Any]:
        return {"type": ["string", "null"], "enum": [*values, None]}

    def strings(*, nonempty: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {"type": "array", "items": string()}
        if nonempty:
            result["minItems"] = 1
        return result

    def identifiers(*, nonempty: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {"type": "array", "items": identifier()}
        if nonempty:
            result["minItems"] = 1
        return result

    def candidate_identifiers(*, nonempty: bool = False) -> dict[str, Any]:
        values = [str(value) for value in task.get("candidate_ids", [])]
        if task["phase"] == "synthesis":
            return strings(nonempty=nonempty)
        if not values:
            raise CreditAnalysisError(
                f"model task has no typed candidate identifiers: {task['task_id']}"
            )
        prefix = re.escape(
            f"{state['analysis_id']}.c."
        ).replace(r"\-", "-")
        item: dict[str, Any] = {
            "type": "string",
            "pattern": rf"^{prefix}[0-9]{{6}}$",
            "description": (
                "Copy a candidate ID from the supplied candidate list; never place an "
                "evidence reference here."
            ),
        }
        result: dict[str, Any] = {
            "type": "array",
            "items": item,
            "description": (
                "Candidate identifiers only. Values beginning with evidence:// belong "
                "in evidence_refs."
            ),
        }
        if nonempty:
            result["minItems"] = 1
        return result

    def candidate_identifier() -> dict[str, Any]:
        return candidate_identifiers(nonempty=True)["items"]

    def numbers(*, exact_items: int | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {"type": "array", "items": number()}
        if exact_items is not None:
            result["minItems"] = exact_items
            result["maxItems"] = exact_items
        return result

    def closed_object(properties: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": dict(properties),
            "required": list(properties),
            "additionalProperties": False,
        }

    def objects(
        item: Mapping[str, Any],
        *,
        nonempty: bool = False,
        exact_items: int | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"type": "array", "items": dict(item)}
        if exact_items is not None:
            result["minItems"] = exact_items
            result["maxItems"] = exact_items
        elif nonempty:
            result["minItems"] = 1
        return result

    def fixed_string(value: str) -> dict[str, Any]:
        return {"type": "string", "const": value}

    luna_finding = closed_object(
        {
            "id": identifier(),
            "title": string(),
            "problem_summary": string(),
            "evidence_refs": strings(nonempty=True),
            "producer_type": enum_string(contract["producer_types"]),
            "producer_owner": string(),
            "proposed_durable_control": string(),
            "recurrence_likely": boolean(),
            "savings_justifies_maintenance": boolean(),
            "material_variant_ids": identifiers(),
        }
    )
    luna_risk = closed_object(
        {
            "id": identifier(),
            "description": string(),
            "evidence_refs": strings(nonempty=True),
            "verification_needed": strings(nonempty=True),
            "material_variant_ids": identifiers(),
        }
    )
    luna_temporary = closed_object(
        {
            "id": identifier(),
            "problem_solved": string(),
            "observed_temporary_control": string(),
            "canonical_owner_hint": string(),
            "evidence_refs": strings(nonempty=True),
            "material_variant_ids": identifiers(),
        }
    )
    assessment_properties = {
        "candidate_ids": candidate_identifiers(nonempty=True),
        "disposition": enum_string(contract["luna_dispositions"]),
        "reason": string(),
        "evidence_refs": strings(nonempty=True),
        "provisional_findings": objects(luna_finding),
        "plausible_risks": objects(luna_risk),
        "temporary_control_candidates": objects(luna_temporary),
    }
    assessment = closed_object(assessment_properties)
    primary_assessment = closed_object(
        {
            "candidate_id": candidate_identifier(),
            "surface_id": enum_string(
                state.get("manifest", {}).get(
                    "surface_order", contract["surface_order"]
                )
            ),
            **{
                key: value
                for key, value in assessment_properties.items()
                if key != "candidate_ids"
            },
        }
    )

    if task["phase"].startswith("luna-"):
        required = sorted(LUNA_CHILD_RESULT_FIELDS)
        properties: dict[str, Any] = {
            "schema": fixed_string(LUNA_CHILD_RESULT_SCHEMA),
            "analysis_id": fixed_string(str(state["analysis_id"])),
            "task_id": fixed_string(str(task["task_id"])),
            "surface_id": (
                {"type": "null", "const": None}
                if task["phase"] == "luna-primary"
                else fixed_string(str(task["surface_id"]))
            ),
            "stage": fixed_string(str(task["stage"])),
            "input_sha256": fixed_string(input_sha256),
            "candidate_assessments": objects(
                primary_assessment
                if task["phase"] == "luna-primary"
                else assessment,
                exact_items=(
                    len(task["candidate_pairs"])
                    if task["phase"] == "luna-primary"
                    else None
                ),
                nonempty=task["phase"] != "luna-primary",
            ),
            "preserved_variant_ids": identifiers(),
        }
    elif task["phase"] == "surface-confirmation":
        recurrence = closed_object(
            {
                "calls_saved_per_affected_run": number(),
                "additional_recurring_calls_per_affected_run": number(),
                "affected_similar_run_frequency": number(),
                "affected_similar_run_frequency_range": numbers(exact_items=2),
                "estimated_calls_saved_per_similar_run": number(),
                "assumptions": strings(nonempty=True),
            }
        )
        implementation_cost = closed_object(
            {
                "estimated_model_calls": number(),
                "description": string(),
            }
        )
        confirmation_finding = closed_object(
            {
                "id": identifier(),
                "title": string(),
                "problem_summary": string(),
                "waste_kind": enum_string(contract["waste_kinds"]),
                "evidence_refs": strings(nonempty=True),
                "evidence_narrative": string(),
                "producer_type": enum_string(contract["producer_types"]),
                "producer_owner": string(),
                "proposed_durable_control": string(),
                "implementation_status": enum_string(
                    contract["implementation_statuses"]
                ),
                "targeted_verification": strings(nonempty=True),
                "observed_avoidable_call_count": integer(),
                "recurrence": recurrence,
                "confidence": number(),
                "complexity": enum_string(contract["complexities"]),
                "one_time_implementation_cost": implementation_cost,
                "helper_categories": {
                    "type": "array",
                    "items": enum_string(contract["helper_categories"]),
                },
                "contributing_surfaces": strings(nonempty=True),
            }
        )
        confirmation_risk = closed_object(
            {
                "id": identifier(),
                "description": string(),
                "evidence_refs": strings(nonempty=True),
                "competing_explanations": strings(nonempty=True),
                "missing_fact": string(),
                "verification_needed": strings(nonempty=True),
            }
        )
        confirmation_assessment = closed_object(
            {
                "candidate_ids": candidate_identifiers(nonempty=True),
                "disposition": enum_string(contract["confirmation_dispositions"]),
                "reason": string(),
                "evidence_refs": strings(nonempty=True),
                "confirmed_findings": objects(confirmation_finding),
                "plausible_risks": objects(confirmation_risk),
            }
        )
        temporary_recurrence = closed_object(
            {
                "likely": boolean(),
                "frequency_range": numbers(exact_items=2),
                "basis": string(),
            }
        )
        temporary_savings = closed_object(
            {
                "expected_calls_saved": number(),
                "maintenance_model_calls": number(),
                "justifies_maintenance": boolean(),
                "basis": string(),
            }
        )
        temporary_review = closed_object(
            {
                "id": identifier(),
                "problem_solved": string(),
                "affected_call_ids": strings(nonempty=True),
                "observed_temporary_control": string(),
                "final_canonical_evidence_refs": strings(nonempty=True),
                "disposition": enum_string(
                    contract["temporary_control_dispositions"]
                ),
                "owning_producer": string(),
                "recurrence_inputs": temporary_recurrence,
                "savings_inputs": temporary_savings,
                "finding_id": nullable_identifier(),
                "no_finding_reason": nullable_string(),
            }
        )
        temporary_contribution = closed_object(
            {
                "id": identifier(),
                "temporary_control_id": identifier(),
                "owner_key": string(),
                "control_key": string(),
                "candidate_ids": candidate_identifiers(nonempty=True),
                "evidence_refs": strings(nonempty=True),
                "contribution": string(),
                "material_variant_id": identifier(),
            }
        )
        helper_review = closed_object(
            {
                "category": enum_string(contract["helper_categories"]),
                "status": string(),
                "finding_ids": identifiers(),
                "reason": string(),
            }
        )
        required = sorted(CONFIRMATION_CHILD_RESULT_FIELDS)
        properties = {
            "schema": fixed_string(CONFIRMATION_CHILD_RESULT_SCHEMA),
            "analysis_id": fixed_string(str(state["analysis_id"])),
            "task_id": fixed_string(str(task["task_id"])),
            "surface_id": fixed_string(str(task["surface_id"])),
            "input_sha256": fixed_string(input_sha256),
            "candidate_assessments": objects(
                confirmation_assessment, nonempty=True
            ),
            "temporary_control_reviews": objects(temporary_review),
            "temporary_control_contributions": objects(temporary_contribution),
            "helper_category_reviews": objects(helper_review),
        }
    else:
        finding_group = closed_object(
            {
                "canonical_finding_id": identifier(),
                "source_finding_ids": identifiers(nonempty=True),
                "primary_source_finding_id": identifier(),
                "title": string(),
                "problem_summary": string(),
                "owner_key": string(),
                "control_key": string(),
                "contributing_surfaces": strings(nonempty=True),
                "savings_source_finding_id": identifier(),
            }
        )
        temporary_merge = closed_object(
            {
                "merge_id": identifier(),
                "owner_key": string(),
                "control_key": string(),
                "review_ids": identifiers(),
                "contribution_ids": identifiers(),
                "disposition": enum_string(
                    contract["temporary_control_dispositions"]
                ),
                "finding_id": nullable_identifier(),
                "no_finding_reason": nullable_string(),
                "contributing_surfaces": strings(nonempty=True),
            }
        )
        call_classification = closed_object(
            {
                "classification": enum_string(contract["call_classifications"]),
                "call_ids": strings(nonempty=True),
                "primary_finding_id": nullable_identifier(),
                "reason_code": nullable_enum(contract["necessary_reason_codes"]),
                "reason": string(),
            }
        )
        producer_group = closed_object(
            {
                "id": identifier(),
                "producer_type": enum_string(contract["producer_types"]),
                "owner": string(),
                "finding_ids": identifiers(nonempty=True),
                "recommended_control": string(),
                "targeted_verification": strings(nonempty=True),
            }
        )
        analysis_summary = closed_object(
            {
                "confirmed_count": integer(),
                "risk_count": integer(),
                "necessary_calls": integer(),
                "protocol_overhead_calls": integer(),
                "reviewed_no_confirmed_waste_calls": integer(),
                "unassessed_calls": integer(),
                "avoidable_calls": integer(),
                "meaningful_input_output_findings": strings(),
            }
        )
        required = sorted(SYNTHESIS_RESULT_FIELDS)
        properties = {
            "schema": fixed_string(ORCHESTRATION_SYNTHESIS_SCHEMA),
            "analysis_id": fixed_string(str(state["analysis_id"])),
            "task_id": fixed_string(str(task["task_id"])),
            "input_sha256": fixed_string(input_sha256),
            "finding_groups": objects(finding_group),
            "risk_order": identifiers(),
            "temporary_control_merges": objects(temporary_merge),
            "call_classifications": objects(call_classification, nonempty=True),
            "producer_groups": objects(producer_group),
            "analysis_summary": analysis_summary,
        }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _surface_reference_text(surface_id: str, contract: Mapping[str, Any]) -> str:
    reference = next(
        item["reference"] for item in contract["surfaces"] if item["id"] == surface_id
    )
    return (SKILL_DIR / reference).read_text(encoding="utf-8")


def _task_prompt(
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    input_payload: Mapping[str, Any],
    input_sha256: str,
    input_variant_ids: list[str],
    contract: Mapping[str, Any],
) -> str:
    base = (
        f"{ANALYSIS_CHILD_MARKER}\n"
        f"controller_analysis_id={state['analysis_id']}\n"
        f"controller_task_id={task['task_id']}\n\n"
        "You are one analysis-only semantic child in a deterministic credit-analysis "
        "controller. Do not call tools, inspect any path, mutate any file, or perform "
        "bookkeeping. All permitted evidence is embedded below. Return exactly one JSON "
        "object matching the supplied output schema. Do not wrap JSON in Markdown. "
        "Deterministic code validates identity and coverage but never supplies semantic "
        "classifications.\n\n"
    )
    identity = (
        f"Analysis: {state['analysis_id']}\nTask: {task['task_id']}\n"
        f"Phase: {task['phase']}\nInput SHA-256: {input_sha256}\n\n"
    )
    luna_ownership_contract = (
        "Semantic ownership is nested and exclusive: a "
        "`provisional-finding-evidence` assessment has one or more nested "
        "provisional_findings and no plausible_risks; a `plausible-risk` assessment "
        "has one or more nested plausible_risks and no provisional_findings; "
        "`dismissed-candidate` and `necessary-exclusion` assessments have neither. "
        "Nested semantic objects inherit their assessment's candidate assignment; do "
        "not repeat candidate_ids inside them."
    )
    assessment_partition_contract = (
        "`candidate_assessments` must be one ordered partition: concatenating every "
        "assessment's candidate_ids must reproduce the input candidate_ids exactly, "
        "with the same length and order. Each candidate ID appears once total. Never "
        "repeat a candidate in parallel assessments for secondary interpretations; "
        "choose its single disposition and split adjacent candidates when their nested "
        "semantic objects differ. Candidate IDs and evidence references are distinct: "
        "copy candidate_ids only from the input candidate IDs and put every "
        "evidence:// value only in evidence_refs."
    )
    if task["phase"] == "luna-primary":
        surface_contracts = "\n\n".join(
            f"SURFACE `{surface_id}`\n{_surface_reference_text(surface_id, contract)}"
            for surface_id in state.get("manifest", {}).get(
                "surface_order", contract["surface_order"]
            )
        )
        instructions = f"""Primary shared Luna discovery.

Inspect every causally ordered episode once. For each ordered candidate-surface pair,
apply that surface's contract and use exactly one of:
{', '.join(contract['luna_dispositions'])}. Return one candidate_assessments item
per input candidate_pairs row in exact order. Copy its candidate_id and surface_id
into the assessment; never create a pair absent from the input.
Use provisional findings for supported recurring-control evidence, plausible risks
for a decision-blocking unknown, dismissals with concrete reasons, and necessary
exclusions only with concrete evidence. Never use a catch-all necessity reason.
Every assessment must cite original `evidence://` references from its candidate.
Return all material variants. Use globally unique IDs prefixed with the surface.
Primary `preserved_variant_ids` and every item's `material_variant_ids` are empty.
{luna_ownership_contract} Producer types must be one of:
{', '.join(contract['producer_types'])}. Every finding, risk, and temporary-control
object must contain at least one evidence reference. Temporary-control candidates are
nested in the assessment whose candidate and surface assignment they inherit.

{surface_contracts}
"""
    elif task["phase"] == "luna-consolidation":
        instructions = f"""Luna consolidation for `{task['surface_id']}`.

Consolidate without suppressing evidence. Account for every candidate in the exact
input order and preserve every input material variant ID. Each preserved variant ID
must occur exactly once across the material_variant_ids of output findings, risks,
or temporary-control candidates, and the top-level preserved_variant_ids must equal
this ordered list: {json.dumps(input_variant_ids)}. Do not invent a new semantic
disposition merely to shorten the packet.
Group adjacent candidates into one assessment when disposition and reason match; cite
the ordered union of their evidence refs and preserve exact order.
{luna_ownership_contract} Every finding, risk, and temporary-control object must contain
at least one evidence reference. {assessment_partition_contract}
"""
    elif task["phase"] == "surface-confirmation":
        surface = str(task["surface_id"])
        temporary = (
            "Perform the mandatory temporary-control review. Each detected temporary "
            "control receives exactly one disposition and a complete review record. "
            "Every primary_temporary_control_inventory item must have one review whose "
            "id is that temporary-control ID; add distinct IDs for controls first "
            "detected during confirmation. "
            "Only durable-control-missing may link a finding, and only when recurrence "
            "and maintenance ROI are both positive."
            if surface == "rework-validation"
            else "Contribute temporary-control evidence only through temporary_control_contributions; do not create a review."
        )
        helper = (
            "Return exactly one helper_category_reviews record for each mandatory helper category in contract order."
            if surface == "helper-contracts"
            else "Return an empty helper_category_reviews array."
        )
        instructions = f"""Single Sol confirmation for `{surface}`.

Confirm or dismiss every selected Luna material candidate, observable high-signal
candidate, and deterministic ordinary-dismissal audit candidate against the embedded
original evidence. The confirmation_selection records why each candidate is present.
Never rely on Luna summaries alone. Account for selected candidates in exact input
order, each exactly once, using one of:
{', '.join(contract['confirmation_dispositions'])}. Every assessment and every
finding/risk must cite an original evidence reference for each candidate. Preserve
every supported finding. Findings and risks are nested in their owning assessment and
inherit its candidate IDs and affected call IDs; do not repeat those fields inside.
A volume-only finding uses
`context-volume` and zero call savings. Do not classify ordinary model error as
avoidable without a concise durable recurring control. Do not use catch-all
necessity, and leave a genuinely decision-blocking gap as a risk. The evidence map
declares its compact mapping columns in `fields` and its complete ordered values in
`rows`; it is not a semantic classification. Group adjacent candidates into one
assessment when disposition and reason match; cite the ordered union of their evidence
refs and preserve exact expanded order. Semantic ownership is nested and exclusive: a
`confirmed-finding` assessment has one or more nested confirmed_findings and no
plausible_risks; a `plausible-risk` assessment has one or more nested plausible_risks
and no confirmed_findings; `dismissed-candidate` and `necessary-exclusion` assessments
have neither. {assessment_partition_contract}
{temporary} {helper}
"""
        instructions += "\nSurface contract:\n" + _surface_reference_text(surface, contract)
    else:
        instructions = """Single Sol synthesis.

Map every confirmed surface finding into exactly one canonical finding group. Merge
only contributions or findings with the same owning producer/control, preserve all
source finding IDs and contributing surfaces, and select exactly one savings source
per canonical finding. Map every risk once. Merge every temporary-control review and
contribution once by owner/control and assign any finding once. Classify every call
exactly once in original inventory order. Necessary classifications require a
specific supported reason; do not use necessity as a catch-all. `unassessed` is only
for an explicit decision-blocking gap and must not be used merely to avoid review.
Use the complete Luna coverage inventory for ordinary reviewed calls and the Sol
confirmations for selected material, high-signal, and audited candidates.
List every context-volume finding with meaningful input/output/tool volume in
analysis_summary.meaningful_input_output_findings.
"""
    packet = json.dumps(
        input_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return base + identity + instructions + "\n\nINPUT PACKET\n" + packet + "\n"


def _write_or_verify_text(path: pathlib.Path, text_value: str, label: str) -> str:
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise CreditAnalysisError(f"{label} path is invalid")
        if path.read_text(encoding="utf-8") != text_value:
            raise CreditAnalysisError(f"{label} changed across resume")
    else:
        _exclusive_text(path, text_value, label)
    return _file_hash(path)


def _prepare_model_task(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
    task: Mapping[str, Any],
) -> tuple[dict[str, Any], str, pathlib.Path, pathlib.Path, list[str]]:
    input_payload, input_sha256, input_variant_ids = _materialize_task_input(
        state, evidence, contract, task
    )
    schema_task = (
        {**task, "candidate_ids": input_payload["candidate_ids"]}
        if task["phase"] == "surface-confirmation"
        else task
    )
    schema = _output_schema_for_task(
        state=state,
        task=schema_task,
        input_sha256=input_sha256,
        contract=contract,
    )
    schema_path = pathlib.Path(str(task["artifacts"]["schema"]))
    if schema_path.exists():
        if _read_json(schema_path, "model output schema") != schema:
            raise CreditAnalysisError("model output schema changed across resume")
    else:
        _exclusive_json(schema_path, schema, "model output schema")
    prompt = _task_prompt(
        state=state,
        task=task,
        input_payload=input_payload,
        input_sha256=input_sha256,
        input_variant_ids=input_variant_ids,
        contract=contract,
    )
    prompt_path = pathlib.Path(str(task["artifacts"]["prompt"]))
    _write_or_verify_text(prompt_path, prompt, "model prompt")
    return input_payload, input_sha256, prompt_path, schema_path, input_variant_ids


def _confirmation_result_inventory(
    state: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    findings: dict[str, dict[str, Any]] = {}
    risks: dict[str, dict[str, Any]] = {}
    reviews: list[dict[str, Any]] = []
    contributions: list[dict[str, Any]] = []
    for task in state["manifest"]["confirmation_tasks"]:
        result = _accepted_result(state, task["task_id"])
        for finding in result["confirmed_findings"]:
            finding_id = finding["id"]
            if finding_id in findings:
                raise CreditAnalysisError("confirmed finding ID is not globally unique")
            findings[finding_id] = finding
        for risk in result["plausible_risks"]:
            risk_id = risk["id"]
            if risk_id in risks:
                raise CreditAnalysisError("risk ID is not globally unique")
            risks[risk_id] = risk
        reviews.extend(result["temporary_control_reviews"])
        contributions.extend(result["temporary_control_contributions"])
    review_ids = [item["id"] for item in reviews]
    contribution_ids = [item["id"] for item in contributions]
    if len(review_ids) != len(set(review_ids)) or len(contribution_ids) != len(
        set(contribution_ids)
    ):
        raise CreditAnalysisError("temporary-control identity is not globally unique")
    return findings, risks, reviews, contributions


def _validate_synthesis_result(
    raw: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    task: Mapping[str, Any],
    input_sha256: str,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    _closed_result(raw, SYNTHESIS_RESULT_FIELDS, "synthesis result")
    if (
        raw.get("schema") != ORCHESTRATION_SYNTHESIS_SCHEMA
        or raw.get("analysis_id") != state["analysis_id"]
        or raw.get("task_id") != task["task_id"]
        or raw.get("input_sha256") != input_sha256
    ):
        raise CreditAnalysisError("synthesis result identity is invalid")
    findings, risks, reviews, contributions = _confirmation_result_inventory(state)
    groups = _result_objects(raw["finding_groups"], "synthesis finding groups")
    canonical_ids: set[str] = set()
    canonical_sources: dict[str, list[str]] = {}
    source_to_canonical: dict[str, str] = {}
    assigned_sources: list[str] = []
    for index, group in enumerate(groups, start=1):
        _closed_result(group, FINDING_GROUP_FIELDS, f"finding group {index}")
        canonical_id = _identifier(
            group.get("canonical_finding_id"), "canonical finding ID"
        )
        if canonical_id in canonical_ids:
            raise CreditAnalysisError("canonical finding ID is duplicated")
        canonical_ids.add(canonical_id)
        sources = _result_strings(group.get("source_finding_ids"), "source findings")
        if not set(sources) <= set(findings):
            raise CreditAnalysisError("finding group references an unknown source")
        assigned_sources.extend(sources)
        canonical_sources[canonical_id] = sources
        source_to_canonical.update({source: canonical_id for source in sources})
        for field in ("primary_source_finding_id", "savings_source_finding_id"):
            if group.get(field) not in sources:
                raise CreditAnalysisError(f"finding group {field} is invalid")
        for field in ("title", "problem_summary", "owner_key", "control_key"):
            if not isinstance(group.get(field), str) or not group[field].strip():
                raise CreditAnalysisError(f"finding group {field} is missing")
        surfaces = _result_strings(
            group.get("contributing_surfaces"), "finding contributing surfaces"
        )
        expected_surfaces = list(
            dict.fromkeys(
                surface
                for source in sources
                for surface in findings[source]["contributing_surfaces"]
            )
        )
        if surfaces != expected_surfaces:
            raise CreditAnalysisError("finding group dropped a contributing surface")
    if sorted(assigned_sources) != sorted(findings) or len(assigned_sources) != len(
        set(assigned_sources)
    ):
        raise CreditAnalysisError("synthesis did not preserve every confirmed finding")
    risk_order = _result_strings(raw["risk_order"], "risk order", empty=True)
    if set(risk_order) != set(risks) or len(risk_order) != len(risks):
        raise CreditAnalysisError("synthesis risk order is incomplete")
    merges = _result_objects(raw["temporary_control_merges"], "temporary merges")
    assigned_reviews: list[str] = []
    assigned_contributions: list[str] = []
    review_by_id = {item["id"]: item for item in reviews}
    contribution_by_id = {item["id"]: item for item in contributions}
    contribution_surfaces: dict[str, str] = {}
    for confirmation_task in state["manifest"]["confirmation_tasks"]:
        confirmation = _accepted_result(state, confirmation_task["task_id"])
        for contribution in confirmation["temporary_control_contributions"]:
            contribution_surfaces[contribution["id"]] = confirmation["surface_id"]
    merge_keys: set[tuple[str, str]] = set()
    for index, merge in enumerate(merges, start=1):
        _closed_result(merge, TEMPORARY_MERGE_FIELDS, f"temporary merge {index}")
        _identifier(merge.get("merge_id"), "temporary merge ID")
        for field in ("owner_key", "control_key"):
            if not isinstance(merge.get(field), str) or not merge[field].strip():
                raise CreditAnalysisError(f"temporary merge {field} is missing")
        merge_key = (str(merge["owner_key"]), str(merge["control_key"]))
        if merge_key in merge_keys:
            raise CreditAnalysisError("temporary owner/control was split across merges")
        merge_keys.add(merge_key)
        merge_reviews = _result_strings(
            merge.get("review_ids"), "temporary merge review IDs", empty=True
        )
        merge_contributions = _result_strings(
            merge.get("contribution_ids"),
            "temporary merge contribution IDs",
            empty=True,
        )
        if not set(merge_reviews) <= set(review_by_id) or not set(
            merge_contributions
        ) <= set(contribution_by_id):
            raise CreditAnalysisError("temporary merge references an unknown contribution")
        if not merge_reviews and not merge_contributions:
            raise CreditAnalysisError("temporary merge is empty")
        member_keys = {
            (
                str(review_by_id[item]["owning_producer"]),
                str(review_by_id[item]["observed_temporary_control"]),
            )
            for item in merge_reviews
        } | {
            (
                str(contribution_by_id[item]["owner_key"]),
                str(contribution_by_id[item]["control_key"]),
            )
            for item in merge_contributions
        }
        if member_keys != {merge_key}:
            raise CreditAnalysisError("temporary merge crossed owner/control boundaries")
        if merge_reviews and any(
            contribution_by_id[item]["temporary_control_id"] not in merge_reviews
            for item in merge_contributions
        ):
            raise CreditAnalysisError("temporary contribution links a different control")
        assigned_reviews.extend(merge_reviews)
        assigned_contributions.extend(merge_contributions)
        disposition = merge.get("disposition")
        review_dispositions = {
            review_by_id[item]["disposition"] for item in merge_reviews
        }
        if len(review_dispositions) > 1 or (
            review_dispositions and disposition not in review_dispositions
        ):
            raise CreditAnalysisError("temporary merge changed a review disposition")
        if disposition not in contract["temporary_control_dispositions"]:
            raise CreditAnalysisError("temporary merge disposition is invalid")
        finding_id = merge.get("finding_id")
        no_finding = merge.get("no_finding_reason")
        if disposition == "durable-control-missing":
            if finding_id not in canonical_ids or no_finding is not None:
                raise CreditAnalysisError("durable temporary merge must link one finding")
            expected_findings = {
                source_to_canonical[review_by_id[item]["finding_id"]]
                for item in merge_reviews
                if review_by_id[item]["finding_id"] is not None
            }
            if expected_findings != {finding_id}:
                raise CreditAnalysisError("temporary merge assigned savings to another finding")
        else:
            if finding_id is not None or not isinstance(no_finding, str) or not no_finding.strip():
                raise CreditAnalysisError("non-defect temporary merge requires no-finding reason")
        surfaces = _result_strings(
            merge.get("contributing_surfaces"), "temporary merge surfaces"
        )
        expected_merge_surfaces = (
            ({"rework-validation"} if merge_reviews else set())
            | {contribution_surfaces[item] for item in merge_contributions}
        )
        if (
            len(surfaces) != len(set(surfaces))
            or set(surfaces) != expected_merge_surfaces
            or not set(surfaces) <= set(state["manifest"]["surface_order"])
        ):
            raise CreditAnalysisError("temporary merge contributing surface is invalid")
    if sorted(assigned_reviews) != sorted(review_by_id) or len(assigned_reviews) != len(
        set(assigned_reviews)
    ):
        raise CreditAnalysisError("temporary reviews were not merged exactly once")
    if sorted(assigned_contributions) != sorted(contribution_by_id) or len(
        assigned_contributions
    ) != len(set(assigned_contributions)):
        raise CreditAnalysisError("temporary contributions were not merged exactly once")
    classifications = _result_objects(
        raw["call_classifications"], "call classifications"
    )
    classified_calls: list[str] = []
    classification_counts: Counter[str] = Counter()
    protocol_overhead_calls = 0
    for index, classification in enumerate(classifications, start=1):
        _closed_result(
            classification,
            CALL_CLASSIFICATION_FIELDS,
            f"call classification {index}",
        )
        category = classification.get("classification")
        if (
            not isinstance(category, str)
            or category not in contract["call_classifications"]
        ):
            raise CreditAnalysisError("call classification is invalid")
        calls = _result_strings(
            classification.get("call_ids"), "classified call IDs"
        )
        classified_calls.extend(calls)
        classification_counts[str(category)] += len(calls)
        finding_id = classification.get("primary_finding_id")
        reason_code = classification.get("reason_code")
        if category.startswith("avoidable_"):
            if finding_id not in canonical_ids or reason_code is not None:
                raise CreditAnalysisError("avoidable classification lacks a finding")
        elif finding_id is not None:
            raise CreditAnalysisError("non-avoidable classification links a finding")
        if category == "necessary":
            if reason_code not in contract["necessary_reason_codes"]:
                raise CreditAnalysisError("necessary classification reason is invalid")
            if reason_code == "protocol-overhead":
                protocol_overhead_calls += len(calls)
        elif reason_code is not None:
            raise CreditAnalysisError("non-necessary classification has a reason code")
        if not isinstance(classification.get("reason"), str) or not classification[
            "reason"
        ].strip():
            raise CreditAnalysisError("call classification reason is missing")
    if classified_calls != evidence["call_inventory"]:
        raise CreditAnalysisError(
            "call classifications are missing, duplicated, or reordered"
        )
    producer_groups = _result_objects(raw["producer_groups"], "producer groups")
    assigned_canonical: list[str] = []
    for index, producer in enumerate(producer_groups, start=1):
        _closed_result(
            producer,
            ORCHESTRATION_PRODUCER_GROUP_FIELDS,
            f"producer group {index}",
        )
        _identifier(producer.get("id"), "producer group ID")
        if producer.get("producer_type") not in contract["producer_types"]:
            raise CreditAnalysisError("producer group type is invalid")
        linked = _result_strings(producer.get("finding_ids"), "producer findings")
        if not set(linked) <= canonical_ids:
            raise CreditAnalysisError("producer group references an unknown finding")
        assigned_canonical.extend(linked)
        _result_strings(producer.get("targeted_verification"), "producer verification")
    if sorted(assigned_canonical) != sorted(canonical_ids) or len(assigned_canonical) != len(
        set(assigned_canonical)
    ):
        raise CreditAnalysisError("producer groups do not cover canonical findings once")
    summary = raw.get("analysis_summary")
    if not isinstance(summary, dict):
        raise CreditAnalysisError("analysis summary is invalid")
    _closed_result(summary, ANALYSIS_SUMMARY_FIELDS, "analysis summary")
    for field in ANALYSIS_SUMMARY_FIELDS - {"meaningful_input_output_findings"}:
        if not isinstance(summary.get(field), int) or isinstance(summary[field], bool) or summary[
            field
        ] < 0:
            raise CreditAnalysisError(f"analysis summary {field} is invalid")
    meaningful = _result_strings(
        summary.get("meaningful_input_output_findings"),
        "meaningful input/output findings",
        empty=True,
    )
    if not set(meaningful) <= canonical_ids:
        raise CreditAnalysisError("analysis summary references an unknown volume finding")
    if any(
        not any(findings[source]["waste_kind"] == "context-volume" for source in canonical_sources[item])
        for item in meaningful
    ):
        raise CreditAnalysisError("analysis summary volume finding is not context-volume")
    if summary["confirmed_count"] != len(canonical_ids) or summary["risk_count"] != len(
        risk_order
    ):
        raise CreditAnalysisError("analysis summary counts are inconsistent")
    expected_summary_counts = {
        "necessary_calls": classification_counts["necessary"],
        "protocol_overhead_calls": protocol_overhead_calls,
        "reviewed_no_confirmed_waste_calls": classification_counts[
            "reviewed_no_confirmed_waste"
        ],
        "unassessed_calls": classification_counts["unassessed"],
        "avoidable_calls": classification_counts["avoidable_implemented"]
        + classification_counts["avoidable_unimplemented"],
    }
    if any(summary[key] != value for key, value in expected_summary_counts.items()):
        raise CreditAnalysisError("analysis summary classification totals are inconsistent")
    return dict(raw)


def _jsonl_event_summary(path: pathlib.Path) -> dict[str, Any]:
    """Summarize child events without emitting their model-visible payloads."""

    event_types: Counter[str] = Counter()
    usage = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
    }
    malformed = 0
    if not path.exists():
        return {"events": 0, "event_types": {}, "usage": usage, "malformed": 0}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(item, Mapping):
                malformed += 1
                continue
            event_type = item.get("type")
            event_types[str(event_type or "unknown")] += 1
            candidates = [item]
            if isinstance(item.get("usage"), Mapping):
                candidates.append(item["usage"])
            if isinstance(item.get("turn"), Mapping):
                candidates.append(item["turn"])
                if isinstance(item["turn"].get("usage"), Mapping):
                    candidates.append(item["turn"]["usage"])
            for candidate in candidates:
                for key in usage:
                    value = candidate.get(key)
                    if isinstance(value, int) and not isinstance(value, bool):
                        usage[key] = max(usage[key], value)
    return {
        "events": sum(event_types.values()),
        "event_types": dict(sorted(event_types.items())),
        "usage": usage,
        "malformed": malformed,
    }


def _codex_child_command(
    *,
    executable: str,
    model: str,
    schema_path: pathlib.Path,
    raw_output: pathlib.Path,
    orchestration_root: pathlib.Path,
) -> list[str]:
    """Build the current CLI command with global approval policy before `exec`."""

    return [
        executable,
        "--ask-for-approval",
        "never",
        "--config",
        'model_reasoning_effort="max"',
        "exec",
        "--model",
        model,
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--skip-git-repo-check",
        "--output-schema",
        str(schema_path),
        "--color",
        "never",
        "--json",
        "--output-last-message",
        str(raw_output),
        "--cd",
        str(orchestration_root),
        "-",
    ]


def _run_codex_child(
    *,
    analysis_id: str,
    model: str,
    task: Mapping[str, Any],
    prompt_path: pathlib.Path,
    schema_path: pathlib.Path,
    attempt_dir: pathlib.Path,
    orchestration_root: pathlib.Path,
    timeout_seconds: int = 1800,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Launch one explicit, ephemeral, read-only Codex child and wait internally."""

    executable = shutil.which("codex")
    if executable is None:
        raise CreditAnalysisError("Codex CLI is unavailable")
    attempt_dir.mkdir(parents=True, exist_ok=False)
    raw_output = attempt_dir / "last-message.json"
    events_path = attempt_dir / "events.jsonl"
    stderr_path = attempt_dir / "stderr.log"
    command = _codex_child_command(
        executable=executable,
        model=model,
        schema_path=schema_path,
        raw_output=raw_output,
        orchestration_root=orchestration_root,
    )
    started = time.monotonic()
    child_environment = os.environ.copy()
    child_environment["CERATOPS_CREDIT_ANALYSIS_ID"] = analysis_id
    child_environment["CERATOPS_CREDIT_ANALYSIS_TASK_ID"] = str(task["task_id"])
    child_environment["CERATOPS_CREDIT_ANALYSIS_EPHEMERAL"] = "1"
    timed_out = False
    terminated = False
    exit_code: int | None = None
    launch_error: str | None = None
    with prompt_path.open("r", encoding="utf-8") as prompt_handle, events_path.open(
        "x", encoding="utf-8", newline="\n"
    ) as events_handle, stderr_path.open("x", encoding="utf-8", newline="\n") as error_handle:
        try:
            process = subprocess.Popen(
                command,
                cwd=orchestration_root,
                stdin=prompt_handle,
                stdout=events_handle,
                stderr=error_handle,
                text=True,
                env=child_environment,
            )
        except OSError as exc:
            launch_error = f"could not launch Codex child: {exc}"
            error_handle.write(launch_error + "\n")
        else:
            last_notification = started
            while True:
                exit_code = process.poll()
                if exit_code is not None:
                    break
                now = time.monotonic()
                if now - started >= timeout_seconds:
                    timed_out = True
                    process.terminate()
                    terminated = True
                    try:
                        exit_code = process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        exit_code = process.wait(timeout=10)
                    break
                if now - last_notification >= MODEL_PROGRESS_SECONDS:
                    print(
                        f"progress: waiting for {task['task_id']} on {model} "
                        f"({int(now - started)}s)",
                        file=sys.stderr,
                        flush=True,
                    )
                    last_notification = now
                time.sleep(1)
    duration_ms = int((time.monotonic() - started) * 1000)
    event_summary = _jsonl_event_summary(events_path)
    attempt = {
        "runner": "codex-cli",
        "model": model,
        "model_invoked": launch_error is None,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "terminated": terminated,
        "duration_ms": duration_ms,
        "prompt_path": str(prompt_path),
        "schema_path": str(schema_path),
        "raw_output_path": str(raw_output),
        "events_path": str(events_path),
        "stderr_path": str(stderr_path),
        "event_summary": event_summary,
        "error": launch_error,
    }
    if launch_error is not None:
        return None, attempt
    if exit_code != 0:
        detail = ""
        if stderr_path.exists():
            detail = " ".join(stderr_path.read_text(encoding="utf-8").split())[:800]
        attempt["error"] = (
            f"Codex child failed for {task['task_id']} with exit {exit_code}"
            + (f": {detail}" if detail else "")
        )
        return None, attempt
    if not raw_output.is_file() or raw_output.is_symlink():
        attempt["error"] = f"Codex child produced no result: {task['task_id']}"
        return None, attempt
    try:
        value = json.loads(raw_output.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        attempt["error"] = f"Codex child result is not JSON: {task['task_id']}"
        attempt["json_error"] = str(exc)
        return None, attempt
    if not isinstance(value, dict):
        attempt["error"] = f"Codex child result is not an object: {task['task_id']}"
        return None, attempt
    return value, attempt


def _invoke_injected_runner(
    runner: Any,
    *,
    model: str,
    task: Mapping[str, Any],
    prompt_path: pathlib.Path,
    schema_path: pathlib.Path,
    input_payload: Mapping[str, Any],
    input_sha256: str,
    attempt_dir: pathlib.Path,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Invoke one in-process fake runner used by existing behavior tests."""

    if not callable(getattr(runner, "run", None)):
        raise CreditAnalysisError("injected model runner lacks run()")
    attempt_dir.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    error: str | None = None
    try:
        value = runner.run(
            model=model,
            task=dict(task),
            prompt=prompt_path.read_text(encoding="utf-8"),
            schema=_read_json(schema_path, "model output schema"),
            input_payload=dict(input_payload),
            input_sha256=input_sha256,
        )
    except Exception as exc:  # noqa: BLE001 - fake-runner failures exercise resume.
        value = None
        error = f"injected model runner failed: {exc}"
    duration_ms = int((time.monotonic() - started) * 1000)
    raw_path = attempt_dir / "last-message.json"
    if isinstance(value, Mapping):
        _exclusive_json(raw_path, dict(value), "injected runner output")
    elif error is None:
        error = "injected model runner returned a non-object"
    events_path = attempt_dir / "events.jsonl"
    _exclusive_text(
        events_path,
        json.dumps(
            {
                "type": "fake.semantic.completed",
                "model": model,
                "task_id": task["task_id"],
            },
            separators=(",", ":"),
        )
        + "\n",
        "injected runner events",
    )
    stderr_path = attempt_dir / "stderr.log"
    _exclusive_text(
        stderr_path,
        (error + "\n") if error is not None else "",
        "injected runner stderr",
    )
    attempt = {
        "runner": "injected",
        "model": model,
        "model_invoked": True,
        "exit_code": 0,
        "timed_out": False,
        "terminated": False,
        "duration_ms": duration_ms,
        "prompt_path": str(prompt_path),
        "schema_path": str(schema_path),
        "raw_output_path": str(raw_path),
        "events_path": str(events_path),
        "stderr_path": str(stderr_path),
        "event_summary": _jsonl_event_summary(events_path),
        "error": error,
    }
    return (dict(value) if isinstance(value, Mapping) else None), attempt


def _task_model(state: Mapping[str, Any], task: Mapping[str, Any]) -> str:
    """Resolve the explicit model identity for one frozen semantic task."""

    if str(task["phase"]).startswith("luna-"):
        return str(state["models"]["luna"])
    if task["phase"] == "synthesis":
        return str(state["models"]["synthesis"])
    return str(state["models"]["confirmation"])


def _model_counter_key(task: Mapping[str, Any]) -> str:
    """Map a frozen task to the controller's Luna or Sol ledger."""

    return "luna" if str(task["phase"]).startswith("luna-") else "sol"


def _bind_attempt_record(
    attempt: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    input_sha256: str,
    attempt_number: int,
) -> dict[str, Any]:
    """Bind one child attempt to immutable identity and artifact hashes."""

    record = dict(attempt)
    record.update(
        {
            "analysis_id": state["analysis_id"],
            "task_id": task["task_id"],
            "phase": task["phase"],
            "attempt_number": attempt_number,
            "input_sha256": input_sha256,
            "outcome": "runner-error" if attempt.get("error") else "result-produced",
        }
    )
    artifact_paths = {
        "prompt": pathlib.Path(str(record["prompt_path"])),
        "schema": pathlib.Path(str(record["schema_path"])),
        "raw_output": pathlib.Path(str(record["raw_output_path"])),
        "events": pathlib.Path(str(record["events_path"])),
        "stderr": pathlib.Path(str(record["stderr_path"])),
    }
    artifacts: dict[str, dict[str, str] | None] = {}
    for label, path in artifact_paths.items():
        if path.is_file() and not path.is_symlink():
            artifacts[label] = {"path": str(path), "sha256": _file_hash(path)}
        elif label in {"prompt", "schema", "events", "stderr"}:
            raise CreditAnalysisError(f"child attempt {label} artifact is missing")
        else:
            artifacts[label] = None
    record["artifacts"] = artifacts
    return record


def _checkpoint_failed_attempt(
    state: dict[str, Any],
    task: Mapping[str, Any],
    attempt: Mapping[str, Any],
    message: str,
    *,
    outcome: str,
) -> None:
    """Persist a failed semantic attempt before returning its error to the caller."""

    record = dict(attempt)
    record["outcome"] = outcome
    record["error"] = message
    state["execution"][task["task_id"]]["attempts"].append(record)
    _save_orchestration_state(state)


def _validate_task_result(
    raw: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
    task: Mapping[str, Any],
    input_sha256: str,
    input_variant_ids: list[str],
) -> dict[str, Any]:
    if task["phase"].startswith("luna-"):
        return _validate_luna_result(
            raw,
            state=state,
            task=task,
            input_sha256=input_sha256,
            input_variant_ids=input_variant_ids,
            contract=contract,
        )
    if task["phase"] == "surface-confirmation":
        confirmation_input = _read_json(
            pathlib.Path(str(task["artifacts"]["input"])),
            "confirmation task input",
        )
        return _validate_confirmation_result(
            raw,
            state=state,
            task=task,
            input_sha256=input_sha256,
            selected_candidate_ids=confirmation_input["candidate_ids"],
            surface_index=_read_surface_index(state, str(task["surface_id"])),
            contract=contract,
        )
    return _validate_synthesis_result(
        raw,
        state=state,
        evidence=evidence,
        task=task,
        input_sha256=input_sha256,
        contract=contract,
    )


def _accept_or_recover_task(
    *,
    state: dict[str, Any],
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
    task: Mapping[str, Any],
    input_sha256: str,
    input_variant_ids: list[str],
    prompt_path: pathlib.Path,
    schema_path: pathlib.Path,
    raw: Mapping[str, Any] | None,
    attempt: Mapping[str, Any] | None,
) -> bool:
    """Accept one immutable result, recovering a crash window without a new call."""

    result_path = pathlib.Path(str(task["artifacts"]["result"]))
    recovered = raw is None
    if raw is None:
        if not result_path.is_file() or result_path.is_symlink():
            return False
        raw = _read_json(result_path, f"recoverable result {task['task_id']}")
    validated = _validate_task_result(
        raw,
        state=state,
        evidence=evidence,
        contract=contract,
        task=task,
        input_sha256=input_sha256,
        input_variant_ids=input_variant_ids,
    )
    if recovered:
        existing = _read_json(result_path, "recoverable result")
        if existing != validated:
            raise CreditAnalysisError("recoverable task result is noncanonical")
    else:
        _exclusive_json(result_path, validated, "model task result")
    execution = state["execution"][task["task_id"]]
    if attempt is not None:
        accepted_attempt = dict(attempt)
        accepted_attempt["outcome"] = "accepted"
        accepted_attempt["error"] = None
        execution["attempts"].append(accepted_attempt)
    execution["status"] = "complete"
    execution["result"] = {
        "path": str(result_path),
        "sha256": _file_hash(result_path),
        "content_hash": _content_hash(validated),
        "analysis_id": state["analysis_id"],
        "task_id": task["task_id"],
        "phase": task["phase"],
        "model": _task_model(state, task),
        "input_sha256": input_sha256,
        "prompt_sha256": _file_hash(prompt_path),
        "schema_sha256": _file_hash(schema_path),
        "recovered_without_model_call": recovered,
    }
    counter = _model_counter_key(task)
    state["model_calls"][counter] += 1
    if recovered:
        state["model_attempts"][counter] += 1
    _save_orchestration_state(state)
    return True


def _aggregate_finding_volume(
    finding: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, int]:
    calls = {str(call["call_id"]): call for call in _all_calls(evidence)}
    totals = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "tool_argument_chars": 0,
        "tool_result_chars": 0,
    }
    for call_id in finding["affected_call_ids"]:
        call = calls[call_id]
        tokens = call.get("tokens")
        if isinstance(tokens, Mapping):
            for key in (
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
            ):
                value = tokens.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    totals[key] += value
        for item in call.get("tool_results", []):
            if not isinstance(item, Mapping):
                continue
            totals["tool_argument_chars"] += int(item.get("argument_chars") or 0)
            totals["tool_result_chars"] += int(item.get("result_chars") or 0)
    return totals


def _build_orchestration_final(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    synthesis: Mapping[str, Any],
) -> dict[str, Any]:
    findings, risks, reviews, contributions = _confirmation_result_inventory(state)
    canonical_findings: list[dict[str, Any]] = []
    for group in synthesis["finding_groups"]:
        source_ids = group["source_finding_ids"]
        source_records = [findings[item] for item in source_ids]
        primary = dict(findings[group["primary_source_finding_id"]])
        savings = findings[group["savings_source_finding_id"]]
        primary.update(
            {
                "id": group["canonical_finding_id"],
                "title": group["title"],
                "problem_summary": group["problem_summary"],
                "producer_owner": group["owner_key"],
                "proposed_durable_control": group["control_key"],
                "source_finding_ids": source_ids,
                "candidate_ids": list(
                    dict.fromkeys(
                        candidate
                        for source in source_records
                        for candidate in source["candidate_ids"]
                    )
                ),
                "affected_call_ids": list(
                    dict.fromkeys(
                        call
                        for source in source_records
                        for call in source["affected_call_ids"]
                    )
                ),
                "evidence_refs": list(
                    dict.fromkeys(
                        ref
                        for source in source_records
                        for ref in source["evidence_refs"]
                    )
                ),
                "contributing_surfaces": group["contributing_surfaces"],
                "targeted_verification": list(
                    dict.fromkeys(
                        check
                        for source in source_records
                        for check in source["targeted_verification"]
                    )
                ),
                "helper_categories": list(
                    dict.fromkeys(
                        category
                        for source in source_records
                        for category in source["helper_categories"]
                    )
                ),
                "observed_avoidable_call_count": len(
                    {
                        call
                        for source in source_records
                        for call in source["affected_call_ids"]
                    }
                )
                if primary["waste_kind"] == "model-calls"
                else 0,
                "recurrence": savings["recurrence"],
                "one_time_implementation_cost": savings[
                    "one_time_implementation_cost"
                ],
                "savings_assigned_from": group["savings_source_finding_id"],
            }
        )
        primary["volume"] = _aggregate_finding_volume(primary, evidence)
        canonical_findings.append(primary)
    risk_order = synthesis["risk_order"]
    ordered_risks = [risks[risk_id] for risk_id in risk_order]
    classification_totals: Counter[str] = Counter()
    protocol_overhead = 0
    for group in synthesis["call_classifications"]:
        classification_totals[group["classification"]] += len(group["call_ids"])
        if group["reason_code"] == "protocol-overhead":
            protocol_overhead += len(group["call_ids"])
    luna_coverage = _luna_coverage_inventory(state)
    luna_dispositions = Counter(row[2] for row in luna_coverage["rows"])
    return {
        "schema": ORCHESTRATION_FINAL_SCHEMA,
        "analysis_id": state["analysis_id"],
        "action": state["action"],
        "mode": state["mode"],
        "mutation_authority": False,
        "source": state["source"],
        "window": state["window"],
        "evidence": state["evidence"],
        "manifest": {
            "path": state["manifest"]["path"],
            "sha256": state["manifest"]["sha256"],
            "surface_order": state["manifest"]["surface_order"],
            "projected_luna_calls": state["manifest"]["projected_luna_calls"],
            "projected_sol_calls": state["manifest"]["projected_sol_calls"],
            "projected_semantic_calls": state["manifest"][
                "projected_semantic_calls"
            ],
            "shared_primary_chunks": len(
                state["manifest"]["shared_primary_task_ids"]
            ),
            "shared_candidate_count": state["manifest"]["shared_candidate_count"],
            "candidate_surface_pair_count": luna_coverage[
                "candidate_surface_pair_count"
            ],
            "luna_disposition_totals": dict(sorted(luna_dispositions.items())),
            "candidate_coverage": [
                {
                    "surface_id": surface["surface_id"],
                    "candidate_count": surface["candidate_count"],
                    "primary_chunks": len(surface["primary_task_ids"]),
                    "consolidations": len(surface["consolidation_task_ids"]),
                }
                for surface in state["manifest"]["surfaces"]
            ],
        },
        "model_calls": {
            "actual_luna": state["model_attempts"]["luna"],
            "actual_sol": state["model_attempts"]["sol"],
            "accepted_luna": state["model_calls"]["luna"],
            "accepted_sol": state["model_calls"]["sol"],
            "bookkeeping": 0,
        },
        "confirmed_findings": canonical_findings,
        "plausible_risks": ordered_risks,
        "temporary_control_reviews": reviews,
        "temporary_control_contributions": contributions,
        "temporary_control_merges": synthesis["temporary_control_merges"],
        "call_classifications": synthesis["call_classifications"],
        "classification_totals": {
            **{
                category: classification_totals[category]
                for category in (
                    "necessary",
                    "avoidable_implemented",
                    "avoidable_unimplemented",
                    "reviewed_no_confirmed_waste",
                    "unassessed",
                )
            },
            "protocol_overhead": protocol_overhead,
        },
        "producer_groups": synthesis["producer_groups"],
        "analysis_summary": synthesis["analysis_summary"],
        "deterministic_totals": evidence["totals"],
        "pricing": evidence["pricing"],
        "retained_artifacts": {
            "state": state["paths"]["state"],
            "evidence": state["evidence"]["path"],
            "manifest": state["manifest"]["path"],
            "orchestration_root": state["paths"]["orchestration_root"],
        },
    }


def _render_orchestration_report(final: Mapping[str, Any]) -> str:
    findings = final["confirmed_findings"]
    outstanding = [
        finding for finding in findings if finding["implementation_status"] == "unimplemented"
    ]
    implemented = len(findings) - len(outstanding)
    lines = [
        f"Confirmed: {len(findings)}; outstanding: {len(outstanding)}; already addressed: {implemented}",
        "",
        (
            f"Luna calls: {final['model_calls']['actual_luna']} "
            f"(projected {final['manifest']['projected_luna_calls']}); "
            f"Sol calls: {final['model_calls']['actual_sol']} "
            f"(projected {final['manifest']['projected_sol_calls']}); "
            "bookkeeping calls: 0."
        ),
        "",
    ]
    for finding in findings:
        recurrence = finding["recurrence"]
        volume = finding["volume"]
        lines.extend(
            [
                f"## {finding['title']}",
                "",
                f"Problem: {finding['problem_summary']}",
                "",
                (
                    f"Evidence: {len(finding['affected_call_ids'])} affected calls; "
                    f"{volume['input_tokens']} input, {volume['cached_input_tokens']} "
                    f"cached-input, {volume['output_tokens']} output tokens; "
                    f"{volume['tool_argument_chars']} tool-argument and "
                    f"{volume['tool_result_chars']} tool-result characters."
                ),
                "",
                f"Fix: {finding['proposed_durable_control']} Owner: {finding['producer_owner']}.",
                "",
                "Verification: " + "; ".join(finding["targeted_verification"]),
                "",
                (
                    f"Savings: {finding['observed_avoidable_call_count']} observed calls; "
                    f"{recurrence['estimated_calls_saved_per_similar_run']} expected calls "
                    f"per similar run; {finding['one_time_implementation_cost']['estimated_model_calls']} "
                    f"implementation calls; {finding['complexity']} ongoing complexity."
                ),
                "",
            ]
        )
    for risk in final["plausible_risks"]:
        lines.extend(
            [
                f"## Risk: {risk['id']}",
                "",
                f"Observed: {risk['description']}",
                "",
                "Unknown: " + "; ".join(risk["competing_explanations"]),
                "",
                f"Why not confirmed: {risk['missing_fact']}",
                "",
                "How to confirm: " + "; ".join(risk["verification_needed"]),
                "",
            ]
        )
    totals = final["classification_totals"]
    lines.extend(
        [
            "## Call accounting",
            "",
            (
                f"Necessary: {totals['necessary']}; protocol overhead: "
                f"{totals['protocol_overhead']}; avoidable implemented: "
                f"{totals['avoidable_implemented']}; avoidable unimplemented: "
                f"{totals['avoidable_unimplemented']}; reviewed without confirmed waste: "
                f"{totals['reviewed_no_confirmed_waste']}; unassessed: "
                f"{totals['unassessed']}."
            ),
            "",
            f"Retained result: {final['retained_artifacts']['state']}",
            "",
        ]
    )
    return "\n".join(lines)


def _cleanup_orchestration_transient(state: Mapping[str, Any]) -> None:
    cleanup = state.get("cleanup")
    if not isinstance(cleanup, Mapping) or cleanup.get("owner") != "credit-analysis-workflow":
        raise CreditAnalysisError("orchestration cleanup ownership is invalid")
    root = pathlib.Path(str(cleanup.get("transient_root"))).resolve()
    orchestration_root = pathlib.Path(state["paths"]["orchestration_root"]).resolve()
    if root.parent != orchestration_root or root.name != "transient":
        raise CreditAnalysisError("orchestration transient root is invalid")
    if root.is_symlink():
        raise CreditAnalysisError("orchestration transient root is a link")
    if root.exists():
        shutil.rmtree(root)
    if root.exists():
        raise CreditAnalysisError("orchestration transient cleanup failed")


def _finalize_orchestration(
    state: dict[str, Any], evidence: Mapping[str, Any]
) -> None:
    synthesis_task = state["manifest"]["synthesis_task"]
    synthesis = _accepted_result(state, synthesis_task["task_id"])
    final = _build_orchestration_final(state, evidence, synthesis)
    if state["mode"] == "full-analysis":
        if state["model_calls"]["sol"] != 6:
            raise CreditAnalysisError("full analysis did not use exactly six Sol calls")
    if state["model_calls"]["luna"] != state["manifest"]["projected_luna_calls"]:
        raise CreditAnalysisError("actual Luna calls do not match the frozen manifest")
    final_path = pathlib.Path(state["paths"]["final_result"])
    _write_or_verify_json(final_path, final, "orchestration final result")
    report_path = pathlib.Path(state["paths"]["report"])
    report_sha256 = _write_or_verify_text(
        report_path,
        _render_orchestration_report(final),
        "orchestration report",
    )
    state["phase"] = "complete"
    state["final_result"] = {
        "path": str(final_path),
        "sha256": _file_hash(final_path),
        "content_hash": _content_hash(final),
        "report_path": str(report_path),
        "report_sha256": report_sha256,
    }
    _cleanup_orchestration_transient(state)
    _save_orchestration_state(state)


def command_execute_orchestration(
    state_path: pathlib.Path,
    *,
    runner: Any | None = None,
    available_models: set[str] | Mapping[str, Mapping[str, Any]] | None = None,
    task_limit: int | None = None,
) -> dict[str, Any]:
    """Run or resume the finite semantic queue without model-mediated polling."""

    state, evidence, contract = _load_orchestration_state(state_path)
    if state["phase"] == "complete":
        return _orchestration_public_status(state)
    catalog = (
        available_models
        if available_models is not None
        else (
            set(runner.available_models)
            if runner is not None and hasattr(runner, "available_models")
            else _codex_model_catalog()
        )
    )
    models = _validate_orchestration_models(contract, catalog)
    if models != state["models"]:
        raise CreditAnalysisError("available model identity changed after planning")
    if task_limit is not None and (
        not isinstance(task_limit, int) or isinstance(task_limit, bool) or task_limit < 0
    ):
        raise CreditAnalysisError("task_limit must be a nonnegative integer")
    tasks = _task_map(state["manifest"])
    completed_this_run = 0
    state["phase"] = "executing"
    _save_orchestration_state(state)
    for task_id in state["task_order"]:
        execution = state["execution"][task_id]
        if execution["status"] == "complete":
            continue
        if task_limit is not None and completed_this_run >= task_limit:
            break
        task = tasks[task_id]
        input_payload, input_sha256, prompt_path, schema_path, input_variant_ids = (
            _prepare_model_task(state, evidence, contract, task)
        )
        if _accept_or_recover_task(
            state=state,
            evidence=evidence,
            contract=contract,
            task=task,
            input_sha256=input_sha256,
            input_variant_ids=input_variant_ids,
            prompt_path=prompt_path,
            schema_path=schema_path,
            raw=None,
            attempt=None,
        ):
            completed_this_run += 1
            continue
        if task["phase"] == "surface-confirmation":
            incomplete_luna = [
                luna["task_id"]
                for luna in state["manifest"]["luna_tasks"]
                if state["execution"][luna["task_id"]]["status"] != "complete"
            ]
            if incomplete_luna:
                raise CreditAnalysisError("confirmation cannot start before complete Luna coverage")
        model = _task_model(state, task)
        attempt_number = len(execution["attempts"]) + 1
        attempt_dir = pathlib.Path(str(task["artifacts"]["attempts"])) / (
            f"attempt-{attempt_number:03d}"
        )
        if runner is None:
            raw, attempt = _run_codex_child(
                analysis_id=str(state["analysis_id"]),
                model=model,
                task=task,
                prompt_path=prompt_path,
                schema_path=schema_path,
                attempt_dir=attempt_dir,
                orchestration_root=pathlib.Path(state["paths"]["orchestration_root"]),
            )
        else:
            raw, attempt = _invoke_injected_runner(
                runner,
                model=model,
                task=task,
                prompt_path=prompt_path,
                schema_path=schema_path,
                input_payload=input_payload,
                input_sha256=input_sha256,
                attempt_dir=attempt_dir,
            )
        attempt = _bind_attempt_record(
            attempt,
            state=state,
            task=task,
            input_sha256=input_sha256,
            attempt_number=attempt_number,
        )
        if attempt["model_invoked"]:
            state["model_attempts"][_model_counter_key(task)] += 1
        if raw is None:
            message = str(attempt.get("error") or "model task produced no result")
            _checkpoint_failed_attempt(
                state,
                task,
                attempt,
                message,
                outcome="runner-error",
            )
            raise CreditAnalysisError(message)
        try:
            _accept_or_recover_task(
                state=state,
                evidence=evidence,
                contract=contract,
                task=task,
                input_sha256=input_sha256,
                input_variant_ids=input_variant_ids,
                prompt_path=prompt_path,
                schema_path=schema_path,
                raw=raw,
                attempt=attempt,
            )
        except CreditAnalysisError as exc:
            _checkpoint_failed_attempt(
                state,
                task,
                attempt,
                str(exc),
                outcome="validation-error",
            )
            raise
        completed_this_run += 1
    if all(
        state["execution"][task_id]["status"] == "complete"
        for task_id in state["task_order"]
    ):
        _finalize_orchestration(state, evidence)
    else:
        _save_orchestration_state(state)
    return _orchestration_public_status(state)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--request", required=True, type=pathlib.Path)
    execute = commands.add_parser("execute")
    execute.add_argument("--state", required=True, type=pathlib.Path)
    orchestration_status = commands.add_parser("orchestration-status")
    orchestration_status.add_argument("--state", required=True, type=pathlib.Path)
    start = commands.add_parser("start")
    start.add_argument("--request", required=True, type=pathlib.Path)
    submit = commands.add_parser("submit")
    submit.add_argument("--state", required=True, type=pathlib.Path)
    submit.add_argument("--decision", required=True, type=pathlib.Path)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--request", required=True, type=pathlib.Path)
    advance = commands.add_parser("advance")
    advance.add_argument("--state", required=True, type=pathlib.Path)
    advance.add_argument("--result", required=True, type=pathlib.Path)
    status = commands.add_parser("status")
    status.add_argument("--state", required=True, type=pathlib.Path)
    status.add_argument("--packet", action="store_true")
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--state", required=True, type=pathlib.Path)
    finalize.add_argument("--result", required=True, type=pathlib.Path)
    prepare_batch = commands.add_parser("prepare-batch")
    prepare_batch.add_argument("--request", required=True, type=pathlib.Path)
    advance_batch = commands.add_parser("advance-batch")
    advance_batch.add_argument("--state", required=True, type=pathlib.Path)
    advance_batch.add_argument("--result", required=True, type=pathlib.Path)
    status_batch = commands.add_parser("status-batch")
    status_batch.add_argument("--state", required=True, type=pathlib.Path)
    finalize_batch = commands.add_parser("finalize-batch")
    finalize_batch.add_argument("--state", required=True, type=pathlib.Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output: Any
    try:
        if args.command == "plan":
            output = command_plan_orchestration(
                args.request.expanduser().resolve(strict=True)
            )
        elif args.command == "execute":
            output = command_execute_orchestration(args.state)
        elif args.command == "orchestration-status":
            output = command_orchestration_status(args.state)
        elif args.command == "start":
            output = command_start(args.request.expanduser().resolve(strict=True))
        elif args.command == "submit":
            output = command_submit(args.state, args.decision)
        elif args.command == "prepare":
            output = command_prepare(args.request.expanduser().resolve(strict=True))
        elif args.command == "advance":
            output = command_advance(args.state, args.result)
        elif args.command == "status":
            output = _pass_packet(args.state) if args.packet else command_status(args.state)
        elif args.command == "finalize":
            command_finalize(args.state, args.result)
            output = "OK"
        elif args.command == "prepare-batch":
            output = command_prepare_batch(
                args.request.expanduser().resolve(strict=True)
            )
        elif args.command == "advance-batch":
            output = command_advance_batch(args.state, args.result)
        elif args.command == "status-batch":
            output = command_status_batch(args.state)
        else:
            command_finalize_batch(args.state)
            output = "OK"
    except (CreditAnalysisError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if output == "OK":
        print("OK")
    else:
        print(json.dumps(output, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
