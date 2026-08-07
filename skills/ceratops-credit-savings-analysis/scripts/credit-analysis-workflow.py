#!/usr/bin/env python3
"""Own one resumable, analysis-only credit-savings workflow.

The controller validates a closed request, invokes the reusable ledger
collector exactly once, fingerprints one retained evidence bundle, opens a
versioned fixed queue, and persists accepted passes as immutable files plus an
append-only index. It makes no model calls and no semantic findings. Surface
judgment belongs to the pending action reference; synthesis is an internal
model-gated phase. All state writes are atomic, stdout is decision-sized, and
successful finalization deletes only recorded controller-owned context and
pending-result files.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import pathlib
import re
import secrets
import sys
import tempfile
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
INDEX_SCHEMA = "ceratops-credit-analysis-index-record.v1"
STATE_VERSION = 1
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
SOURCE_FIELDS = {"thread_id", "session"}
WINDOW_FIELDS = {"mode", "last_runs", "turn_ids"}
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
    "affected_call_ids",
    "evidence_refs",
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
    "call_classifications",
    "secondary_call_mappings",
    "producer_groups",
}
DISPOSITION_FIELDS = {"finding_id", "primary_call_ids", "secondary_call_ids"}
CLASSIFICATION_FIELDS = {
    "call_id",
    "classification",
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
    if internal != [{"id": "synthesis", "public": False}]:
        raise CreditAnalysisError("synthesis must be the only internal phase")
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
    return contract


def _request_source(
    raw: Any,
    ledger: ModuleType,
) -> tuple[dict[str, Any], pathlib.Path]:
    if not isinstance(raw, dict):
        raise CreditAnalysisError("source must be an object")
    _closed(raw, SOURCE_FIELDS, "source")
    thread_id = raw.get("thread_id")
    session = raw.get("session")
    selected = sum(
        1
        for value in (thread_id, session)
        if isinstance(value, str) and value
    )
    if selected != 1 or any(value not in (None, "") and not isinstance(value, str) for value in (thread_id, session)):
        raise CreditAnalysisError("source must name exactly one thread ID or session")
    try:
        if isinstance(thread_id, str) and thread_id:
            resolved = ledger.resolve_thread_session(thread_id)
            descriptor = {"kind": "thread_id", "value": thread_id}
        else:
            resolved = pathlib.Path(str(session)).expanduser().resolve(strict=True)
            descriptor = {"kind": "session", "value": str(resolved)}
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
    task_root = _existing_directory(request.get("task_temp_root"), "task_temp_root")
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
                _compact_call(call, semantic=False) for call in _all_calls(evidence)
            ],
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
        focused_runs = set(evidence["focused_semantic_context"]["run_ids"])
        candidate_set = set(candidates)
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


def command_prepare(request_path: pathlib.Path) -> dict[str, Any]:
    contract = _load_contract()
    ledger = _load_ledger()
    request = _validate_request(request_path, contract, ledger)
    analysis_id = secrets.token_hex(12)
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
    if (
        not isinstance(observed, int)
        or isinstance(observed, bool)
        or observed != len(affected)
    ):
        raise CreditAnalysisError(f"finding {finding_id} avoidable count must match its calls")
    recurrence = _validate_recurrence(raw.get("recurrence"), f"finding {finding_id} recurrence")
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
        "affected_call_ids": affected,
        "evidence_refs": refs,
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
        if set(primary + secondary) != set(findings[finding_id]["affected_call_ids"]):
            raise CreditAnalysisError(f"finding {finding_id} call mapping drops surface evidence")
        normalized = {
            "finding_id": finding_id,
            "primary_call_ids": primary,
            "secondary_call_ids": secondary,
        }
        dispositions.append(normalized)
        disposition_by_id[finding_id] = normalized
    if set(disposition_by_id) != set(findings):
        raise CreditAnalysisError("synthesis lacks a disposition for an accepted finding")

    classifications: list[dict[str, Any]] = []
    classification_by_call: dict[str, dict[str, Any]] = {}
    for raw in _objects(result.get("call_classifications"), "call classifications"):
        _closed(raw, CLASSIFICATION_FIELDS, "call classification")
        call_id = raw.get("call_id")
        category = raw.get("classification")
        finding_id = raw.get("primary_finding_id")
        reason_code = raw.get("reason_code")
        reason = raw.get("reason")
        if (
            not isinstance(call_id, str)
            or call_id not in known_calls
            or call_id in classification_by_call
        ):
            raise CreditAnalysisError(f"call classification is duplicate or unknown: {call_id}")
        if category not in contract["call_classifications"]:
            raise CreditAnalysisError(f"call classification category is invalid: {call_id}")
        if not isinstance(reason, str) or not reason.strip():
            raise CreditAnalysisError(f"call classification reason is required: {call_id}")
        if category == "necessary":
            if finding_id is not None or reason_code not in contract["necessary_reason_codes"]:
                raise CreditAnalysisError(f"necessary classification is invalid: {call_id}")
        else:
            if (
                not isinstance(finding_id, str)
                or finding_id not in findings
                or reason_code is not None
            ):
                raise CreditAnalysisError(f"avoidable classification is invalid: {call_id}")
            if call_id not in disposition_by_id[finding_id]["primary_call_ids"]:
                raise CreditAnalysisError(f"primary finding mapping disagrees: {call_id}")
            expected_category = (
                "avoidable_implemented"
                if findings[finding_id]["implementation_status"] == "implemented"
                else "avoidable_unimplemented"
            )
            if category != expected_category:
                raise CreditAnalysisError(f"implementation classification disagrees: {call_id}")
        normalized = {
            "call_id": call_id,
            "classification": category,
            "primary_finding_id": finding_id,
            "reason_code": reason_code,
            "reason": reason.strip(),
        }
        classifications.append(normalized)
        classification_by_call[call_id] = normalized
    if [item["call_id"] for item in classifications] != list(evidence["call_inventory"]):
        raise CreditAnalysisError("every model call must be classified exactly once in inventory order")

    primary_by_finding: dict[str, set[str]] = defaultdict(set)
    for item in classifications:
        finding_id = item["primary_finding_id"]
        if isinstance(finding_id, str):
            primary_by_finding[finding_id].add(item["call_id"])
    for finding_id, disposition in disposition_by_id.items():
        if primary_by_finding[finding_id] != set(disposition["primary_call_ids"]):
            raise CreditAnalysisError(f"finding primary calls are multiply or inconsistently assigned: {finding_id}")
        for call_id in disposition["secondary_call_ids"]:
            if classification_by_call[call_id]["classification"] == "necessary":
                raise CreditAnalysisError(f"secondary avoidable evidence is classified necessary: {call_id}")

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
        "call_classifications": classifications,
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
        for call_id in finding["affected_call_ids"]
    }
    findings = [
        {
            **finding,
            "source_surface": surface["surface_id"],
            "deduplicated_avoidable_call_count": len(
                set(finding["affected_call_ids"])
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
    classifications = synthesis["call_classifications"]
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
        _verify_completed(state)
        final_result = _build_full_final(state, evidence, contract)
    else:
        if state.get("pending") is not None or state["current_index"] != len(state["queue"]):
            raise CreditAnalysisError("standalone surface has not been accepted")
        accepted_path = pathlib.Path(state["completed"][-1]["path"]).resolve()
        if result_file.resolve() != accepted_path:
            raise CreditAnalysisError("standalone finalization requires its accepted result path")
        if _content_hash(_read_json(result_file, "accepted surface result")) != state["completed"][-1]["content_hash"]:
            raise CreditAnalysisError("standalone accepted result changed")
        final_result = _build_standalone_final(state, evidence, contract)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--request", required=True, type=pathlib.Path)
    advance = commands.add_parser("advance")
    advance.add_argument("--state", required=True, type=pathlib.Path)
    advance.add_argument("--result", required=True, type=pathlib.Path)
    status = commands.add_parser("status")
    status.add_argument("--state", required=True, type=pathlib.Path)
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--state", required=True, type=pathlib.Path)
    finalize.add_argument("--result", required=True, type=pathlib.Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            output: Any = command_prepare(args.request.expanduser().resolve(strict=True))
        elif args.command == "advance":
            output = command_advance(args.state, args.result)
        elif args.command == "status":
            output = command_status(args.state)
        else:
            command_finalize(args.state, args.result)
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
