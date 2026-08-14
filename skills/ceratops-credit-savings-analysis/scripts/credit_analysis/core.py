#!/usr/bin/env python3
"""Own resumable single-thread and per-thread-batch credit analyses.

The primary workflow collects one selected session once, freezes shared causal
episodes and a finite shared Luna manifest, launches explicitly modeled
analysis-only Codex children, validates complete input coverage, runs one Sol
adjudication across every public surface, and retains
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
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from types import ModuleType
from typing import Any

PACKAGE_DIR = pathlib.Path(__file__).resolve().parent
SCRIPT_DIR = PACKAGE_DIR.parent
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
CANONICAL_STATE_SCHEMA = "ceratops-credit-analysis-canonical-state.v1"
HOLISTIC_STATE_SCHEMA = "ceratops-credit-analysis-orchestration-state.v4"
HOLISTIC_MANIFEST_SCHEMA = "ceratops-credit-analysis-chunk-manifest.v4"
HOLISTIC_LUNA_RESULT_SCHEMA = "ceratops-credit-analysis-luna-result.v4"
HOLISTIC_SOL_RESULT_SCHEMA = "ceratops-credit-analysis-adjudication-result.v1"
HOLISTIC_SOL_TRANSPORT_SCHEMA = "ceratops-credit-analysis-sol-transport.v1"
HOLISTIC_FINAL_SCHEMA = "ceratops-credit-analysis-orchestration-final.v4"
HOLISTIC_EVIDENCE_SCHEMA = "ceratops-credit-analysis-formatted-evidence.v4"
HOLISTIC_TASK_SCHEMA = "ceratops-credit-analysis-model-task.v4"
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


def _validate_canonical_task_directory(path: pathlib.Path, label: str) -> None:
    """Require ``<repo-parent>/tmp/<repo-name>/<thread-name>`` topology.

    The sibling repository marker binds the caller-selected cleanup root to a
    concrete repository name. This check runs before creating a missing final
    component so malformed callers cannot create controller state elsewhere.
    """

    repository_name = path.parent.name
    temp_root = path.parent.parent
    repository_root = temp_root.parent / repository_name
    if temp_root.name.casefold() != "tmp" or not repository_name:
        raise CreditAnalysisError(
            f"{label} must match <repo-parent>/tmp/<repo-name>/<thread-name>"
        )
    try:
        resolved_repository = repository_root.resolve(strict=True)
    except OSError as exc:
        raise CreditAnalysisError(
            f"{label} has no matching sibling repository: {repository_root}"
        ) from exc
    git_marker = resolved_repository / ".git"
    if (
        repository_root.is_symlink()
        or not resolved_repository.is_dir()
        or git_marker.is_symlink()
        or not (git_marker.is_file() or git_marker.is_dir())
    ):
        raise CreditAnalysisError(
            f"{label} has no matching real Git repository: {repository_root}"
        )


def _validate_task_directory_scope(
    path: pathlib.Path,
    label: str,
    canonical_boundary: pathlib.Path | None,
) -> None:
    """Validate a public canonical root or one helper-owned nested child root."""

    if canonical_boundary is None:
        _validate_canonical_task_directory(path, label)
        return
    boundary = _existing_directory(str(canonical_boundary), f"{label} boundary")
    _validate_canonical_task_directory(boundary, f"{label} boundary")
    try:
        path.relative_to(boundary)
    except ValueError as exc:
        raise CreditAnalysisError(
            f"{label} must be inside its canonical task root"
        ) from exc


def _task_directory(
    value: Any,
    label: str,
    *,
    canonical_boundary: pathlib.Path | None = None,
) -> pathlib.Path:
    """Return the caller-selected directory, creating only its final component."""

    if not isinstance(value, str) or not value:
        raise CreditAnalysisError(f"{label} must be nonempty text")
    requested = pathlib.Path(value).expanduser()
    if requested.exists() or requested.is_symlink():
        existing = _existing_directory(value, label)
        _validate_task_directory_scope(existing, label, canonical_boundary)
        return existing
    if requested.name in {"", ".", ".."}:
        raise CreditAnalysisError(f"{label} must name a child directory")
    try:
        parent = requested.parent.resolve(strict=True)
    except OSError as exc:
        raise CreditAnalysisError(f"{label} parent does not exist: {value}") from exc
    if requested.parent.is_symlink() or not parent.is_dir():
        raise CreditAnalysisError(f"{label} parent must be a real directory")
    path = parent / requested.name
    _validate_task_directory_scope(path, label, canonical_boundary)
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
        "orchestration_state_schema": HOLISTIC_STATE_SCHEMA,
        "chunk_manifest_schema": HOLISTIC_MANIFEST_SCHEMA,
        "luna_result_schema": HOLISTIC_LUNA_RESULT_SCHEMA,
        "adjudication_result_schema": HOLISTIC_SOL_RESULT_SCHEMA,
        "orchestration_final_schema": HOLISTIC_FINAL_SCHEMA,
    }
    if any(contract.get(key) != value for key, value in orchestration_schemas.items()):
        raise CreditAnalysisError("orchestration schema contract is invalid")
    models = contract.get("models")
    if (
        not isinstance(models, Mapping)
        or set(models) != {"luna", "sol"}
        or not all(isinstance(value, str) and value for value in models.values())
    ):
        raise CreditAnalysisError("orchestration model contract is invalid")
    if contract.get("model_reasoning_effort") != {"luna": "medium", "sol": "max"}:
        raise CreditAnalysisError("orchestration reasoning effort contract is invalid")
    semantic_calls = contract.get("semantic_call_contract")
    if semantic_calls != {
        "normal_luna_calls": 1,
        "sol_calls": 1,
        "bookkeeping_calls": 0,
    }:
        raise CreditAnalysisError("semantic call contract is invalid")
    context_budget = contract.get("context_budget")
    context_budget_keys = {
        "characters_per_token",
        "hidden_prompt_reserve_tokens",
        "safety_margin_tokens",
        "luna_output_reserve_tokens",
        "sol_output_reserve_tokens",
        "minimum_evidence_tokens",
    }
    if (
        not isinstance(context_budget, Mapping)
        or set(context_budget) != context_budget_keys
        or not isinstance(context_budget["characters_per_token"], (int, float))
        or isinstance(context_budget["characters_per_token"], bool)
        or context_budget["characters_per_token"] <= 0
        or any(
            not isinstance(context_budget[key], int)
            or isinstance(context_budget[key], bool)
            or context_budget[key] < 1
            for key in context_budget_keys - {"characters_per_token"}
        )
    ):
        raise CreditAnalysisError("orchestration context budget is invalid")
    chunking = contract.get("chunking")
    chunking_keys = {
        "large_payload_inline_chars",
        "compact_text_chars",
        "sol_evidence_chars_per_candidate",
    }
    if (
        not isinstance(chunking, Mapping)
        or set(chunking) != chunking_keys
        or any(
            not isinstance(chunking[key], int)
            or isinstance(chunking[key], bool)
            or chunking[key] < 1
            for key in chunking_keys
        )
    ):
        raise CreditAnalysisError("orchestration chunking contract is invalid")
    coverage = contract.get("coverage")
    if (
        not isinstance(coverage, Mapping)
        or set(coverage) != {"maximum_unassessed_fraction"}
        or not isinstance(coverage["maximum_unassessed_fraction"], (int, float))
        or isinstance(coverage["maximum_unassessed_fraction"], bool)
        or not 0 <= coverage["maximum_unassessed_fraction"] < 1
    ):
        raise CreditAnalysisError("orchestration coverage contract is invalid")
    if contract.get("luna_candidate_kinds") != [
        "provisional-finding",
        "plausible-risk",
        "temporary-control",
    ] or contract.get("adjudication_dispositions") != [
        "confirmed-finding",
        "plausible-risk",
        "dismissed-candidate",
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
    *,
    task_root_boundary: pathlib.Path | None = None,
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
    task_root = _task_directory(
        request.get("task_temp_root"),
        "task_temp_root",
        canonical_boundary=task_root_boundary,
    )
    state_path = task_root / "state.json"
    evidence_path = _new_file(request.get("evidence_output"), "evidence output")
    try:
        evidence_path.relative_to(task_root)
    except ValueError as exc:
        raise CreditAnalysisError(
            "evidence output must be inside task_temp_root"
        ) from exc
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

__all__ = (
    "ACTION_REFERENCE_RE",
    "Any",
    "BATCH_COMPLETED_FIELDS",
    "BATCH_INDEX_SCHEMA",
    "BATCH_ITEM_FIELDS",
    "BATCH_REQUEST_FIELDS",
    "BATCH_SELECTOR_FIELDS",
    "BATCH_STATE_FIELDS",
    "BATCH_STATE_SCHEMA",
    "BATCH_STATE_VERSION",
    "BATCH_SUMMARY_ACCEPTED_FIELDS",
    "BATCH_SUMMARY_GROUP_FIELDS",
    "BATCH_SUMMARY_GROUP_FIELD_ORDER",
    "BATCH_SUMMARY_RESULT_FIELDS",
    "BATCH_SUMMARY_RESULT_FIELD_ORDER",
    "BATCH_SUMMARY_STATE_FIELDS",
    "CALL_SELECTOR_FIELDS",
    "CANONICAL_STATE_SCHEMA",
    "CLASSIFICATION_GROUP_FIELDS",
    "COMPLETED_FIELDS",
    "CONTEXT_SCHEMA",
    "CONTRACT_PATH",
    "COST_FIELDS",
    "Counter",
    "CreditAnalysisError",
    "DECISION_EXCLUSION_FIELDS",
    "DECISION_FINDING_FIELDS",
    "DECISION_RECURRENCE_FIELDS",
    "DECISION_RISK_FIELDS",
    "DISMISSAL_FIELDS",
    "DISPOSITION_FIELDS",
    "EVIDENCE_NARRATIVE_LIMIT",
    "EXCLUSION_FIELDS",
    "FINAL_PACKET_SCHEMA",
    "FINDING_FIELDS",
    "HELPER_REVIEW_FIELDS",
    "HOLISTIC_EVIDENCE_SCHEMA",
    "HOLISTIC_FINAL_SCHEMA",
    "HOLISTIC_LUNA_RESULT_SCHEMA",
    "HOLISTIC_MANIFEST_SCHEMA",
    "HOLISTIC_SOL_RESULT_SCHEMA",
    "HOLISTIC_SOL_TRANSPORT_SCHEMA",
    "HOLISTIC_STATE_SCHEMA",
    "HOLISTIC_TASK_SCHEMA",
    "IDENTIFIER_RE",
    "INDEX_SCHEMA",
    "LEDGER_PATH",
    "MODEL_PROGRESS_SECONDS",
    "Mapping",
    "ModuleType",
    "PACKAGE_DIR",
    "PASS_PACKET_CHAR_LIMIT",
    "PASS_PACKET_SCHEMA",
    "PRODUCER_GROUP_FIELDS",
    "PROJECT_SELECTOR_FIELDS",
    "READ_SEARCH_TOKENS",
    "RECURRENCE_FIELDS",
    "REMEDIATION_FIELDS",
    "REQUEST_FIELDS",
    "RISK_FIELDS",
    "SCRIPT_DIR",
    "SECONDARY_FIELDS",
    "SKILL_DIR",
    "SOURCE_ALLOWED_FIELDS",
    "STATE_FIELDS",
    "STATE_SCHEMA",
    "STATE_VERSION",
    "SURFACE_DECISION_FIELDS",
    "SURFACE_DECISION_SCHEMA",
    "SURFACE_PACKET_BUDGETS",
    "SURFACE_RESULT_FIELDS",
    "SYNTHESIS_ASSESSMENT_FIELDS",
    "SYNTHESIS_DECISION_FIELDS",
    "SYNTHESIS_DECISION_SCHEMA",
    "SYNTHESIS_FIELDS",
    "Sequence",
    "WINDOW_FIELDS",
    "_accept_result",
    "_accepted_payloads",
    "_action_title",
    "_all_calls",
    "_allowed_fields",
    "_append_index",
    "_assemble_surface_decision",
    "_assemble_synthesis_decision",
    "_atomic_json",
    "_atomic_write",
    "_bounded_value",
    "_budgeted_values",
    "_build_full_final",
    "_build_standalone_final",
    "_call_signal_score",
    "_candidate_cluster_partition",
    "_candidate_clusters",
    "_candidate_ids",
    "_canonical_bytes",
    "_cleanup_transients",
    "_closed",
    "_cluster_representative",
    "_cluster_token_totals",
    "_cluster_tool_totals",
    "_compact_call",
    "_compact_synthesis_cluster",
    "_content_hash",
    "_decision_finding",
    "_decision_recurrence",
    "_decision_risk",
    "_detail_packet_calls",
    "_evidence_ref",
    "_exclusive_json",
    "_existing_directory",
    "_existing_file",
    "_expand_decision_selectors",
    "_file_hash",
    "_final_packet",
    "_finding_inventory",
    "_finding_presentation_key",
    "_finding_savings",
    "_group_standalone_findings",
    "_helper_decision_metadata",
    "_idempotent_resubmission",
    "_identifier",
    "_initialize_analysis",
    "_json_chars",
    "_load_contract",
    "_load_ledger",
    "_load_state",
    "_model_review_records_for_calls",
    "_new_file",
    "_number",
    "_objects",
    "_observable_call_signature",
    "_open_pending",
    "_packet_call",
    "_pass_packet",
    "_persist_final_result",
    "_positive_integers",
    "_protocol_budget",
    "_public_status",
    "_public_surface_results",
    "_read_index",
    "_read_json",
    "_recover_indexed_pending",
    "_render_final_report",
    "_request_source",
    "_request_window",
    "_run_outcome_calls",
    "_save_state",
    "_size_band",
    "_strings",
    "_surface_cluster_summary",
    "_surface_decision_contract",
    "_surface_pass_packet",
    "_synthesis_remaining_calls",
    "_task_directory",
    "_truncate_text",
    "_user_messages_for_calls",
    "_validate_evidence_refs",
    "_validate_finding",
    "_validate_recurrence",
    "_validate_request",
    "_validate_surface_result",
    "_validate_synthesis",
    "_validated_classification_groups",
    "_verify_completed",
    "_volume_hotspot_ids",
    "_write_final_result",
    "argparse",
    "command_advance",
    "command_finalize",
    "command_prepare",
    "command_start",
    "command_status",
    "command_submit",
    "defaultdict",
    "dt",
    "hashlib",
    "importlib",
    "json",
    "math",
    "os",
    "pathlib",
    "re",
    "secrets",
    "shutil",
    "signal",
    "subprocess",
    "sys",
    "tempfile",
    "time",
)
