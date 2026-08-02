#!/usr/bin/env python3
"""Emit a compact, judgment-free model-call ledger from one Codex session.

The ledger groups automatic continuations by turn ID, includes only completed
runs, and fingerprints tool arguments instead of reproducing potentially
sensitive command text. Ordinary mode writes detailed evidence to a
caller-selected file. Closure mode emits the minimum sanitized selected-window
call inventory in one invocation and creates no cleanup artifact. Repeated
``--include-run`` options preserve the existing bounded stdout summaries unless
``--semantic-evidence-output`` writes the selected sanitized actions to a
separate versioned sidecar and emits only selected-run IDs and counts. The
ordinary ledger remains fingerprint-only. Summary mode writes versioned
per-turn usage and structured result evidence while emitting only compact
totals and top-turn rankings. The
same helper validates a caller-owned classification file before reporting,
while the model remains responsible for deciding whether a call was necessary
or avoidable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import re
import sys
import uuid
from collections import Counter
from typing import Any


SCHEMA = "ceratops-model-call-ledger.v1"
SUMMARY_SCHEMA = "ceratops-model-call-ledger-summary.v1"
SEMANTIC_EVIDENCE_SCHEMA = "ceratops-model-call-semantic-evidence.v1"
SEMANTIC_SUMMARY_SCHEMA = "ceratops-model-call-semantic-summary.v1"
CLOSURE_SCHEMA = "ceratops-model-call-ledger-closure.v1"
CLASSIFICATIONS_SCHEMA = "ceratops-model-call-classifications.v1"
CLASSIFIED_SUMMARY_SCHEMA = "ceratops-model-call-classified-summary.v1"
USAGE_EVIDENCE_SCHEMA = "ceratops-model-call-usage-evidence.v1"
USAGE_SUMMARY_SCHEMA = "ceratops-model-call-usage-summary.v1"
PRICING_PROFILE_SCHEMA = "ceratops-model-call-pricing-profile.v1"
DEFAULT_TOP = 5
CLASSIFICATION_CATEGORIES = (
    "necessary",
    "avoidable_implemented",
    "avoidable_unimplemented",
)
TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)
PRICING_FIELDS = (
    "input_per_million_tokens",
    "cached_input_per_million_tokens",
    "output_per_million_tokens",
    "mode_multiplier",
)
WAIT_ACTION_NAMES = frozenset({"wait", "wait_agent", "wait_threads"})
PROCESS_CODE_FIELDS = frozenset(
    {"exit_code", "return_code", "returncode", "process_exit_code"}
)
TIMEOUT_FIELDS = frozenset({"timed_out", "timeout"})
TERMINATION_FIELDS = frozenset({"terminated", "termination"})
ERROR_STATUSES = frozenset({"error", "failed", "failure"})
TIMEOUT_STATUSES = frozenset({"timed_out", "timeout"})
TERMINATION_STATUSES = frozenset(
    {"cancelled", "canceled", "killed", "terminated"}
)
REDACTED = "<redacted>"
USER_HOME = "<user-home>"
LOCAL_PATH = "<local-path>"
SEMANTIC_SUMMARY_LIMIT = 240
SENSITIVE_KEY_RE = re.compile(
    r"(?:^|_)(?:api_?key|authorization|client_?secret|cookie|credentials?|"
    r"password|private_?key|secrets?|tokens?)(?:$|_)",
    re.IGNORECASE,
)
AUTH_VALUE_RE = re.compile(r"\b(bearer|basic)\s+[^\s,;]+", re.IGNORECASE)
CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"(?P<prefix>[\"']?(?:--?|\$env:)?[A-Za-z0-9_-]*"
    r"(?:api[_-]?key|authorization|client[_-]?secret|cookie|credential|"
    r"password|private[_-]?key|secret|token)[A-Za-z0-9_-]*[\"']?"
    r"(?:\s*[:=]\s*|\s+))"
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)",
    re.IGNORECASE,
)
KNOWN_TOKEN_RE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{16,})\b"
)
PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
    re.DOTALL,
)
URL_CREDENTIAL_RE = re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@", re.IGNORECASE)
USER_HOME_RE = re.compile(
    r"(?:[A-Z]:[\\/]+Users[\\/]+[^\\/\s\"']+|"
    r"[\\/]+(?:Users|home)[\\/]+[^\\/\s\"']+)",
    re.IGNORECASE,
)
WINDOWS_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Z]:[\\/])[^\s\"'<>|]+",
    re.IGNORECASE,
)
POSIX_PATH_RE = re.compile(r"(?<![:/A-Za-z0-9])/[^\s\"'<>|]+")
RELATIVE_PATH_RE = re.compile(
    r"(?<![:/A-Za-z0-9])(?:\.{1,2}[\\/])?[A-Za-z0-9_.-]+"
    r"(?:[\\/][A-Za-z0-9_.@-]+)+"
)
PATH_KEY_RE = re.compile(
    r"(?:^|_)(?:cwd|dirs?|directories|files?|paths?)(?:$|_)",
    re.IGNORECASE,
)


class LedgerError(RuntimeError):
    """Report invalid session evidence without exposing raw record contents."""


def positive_int(value: str) -> int:
    """Parse a positive count for the optional completed-run window."""

    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def safe_rate(value: Any, field: str, *, positive: bool = False) -> float:
    """Validate one finite pricing rate without accepting booleans or strings."""

    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise LedgerError(f"pricing field {field} must be a number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0 or (positive and parsed == 0):
        qualifier = "positive finite" if positive else "non-negative finite"
        raise LedgerError(f"pricing field {field} must be {qualifier}")
    return parsed


def load_pricing_profile(path: pathlib.Path) -> dict[str, float | str]:
    """Load one exact versioned credit-rate profile."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LedgerError(f"could not read pricing profile: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LedgerError("pricing profile is not valid JSON") from exc
    if not isinstance(value, dict):
        raise LedgerError("pricing profile must be a JSON object")
    expected = {"schema", *PRICING_FIELDS}
    missing = sorted(expected - value.keys())
    extra = sorted(value.keys() - expected)
    if missing:
        raise LedgerError(f"pricing profile is missing field: {missing[0]}")
    if extra:
        raise LedgerError(f"pricing profile has unsupported field: {extra[0]}")
    if value.get("schema") != PRICING_PROFILE_SCHEMA:
        raise LedgerError(f"pricing profile schema must be {PRICING_PROFILE_SCHEMA}")
    return {
        "schema": PRICING_PROFILE_SCHEMA,
        "input_per_million_tokens": safe_rate(
            value["input_per_million_tokens"],
            "input_per_million_tokens",
        ),
        "cached_input_per_million_tokens": safe_rate(
            value["cached_input_per_million_tokens"],
            "cached_input_per_million_tokens",
        ),
        "output_per_million_tokens": safe_rate(
            value["output_per_million_tokens"],
            "output_per_million_tokens",
        ),
        "mode_multiplier": safe_rate(
            value["mode_multiplier"],
            "mode_multiplier",
            positive=True,
        ),
    }


def percentage(numerator: int, denominator: int) -> float | None:
    """Return one deterministic two-decimal percentage when defined."""

    if denominator <= 0:
        return None
    return round(numerator * 100 / denominator, 2)


def load_rows(path: pathlib.Path) -> list[dict[str, Any]]:
    """Load JSONL records while identifying malformed line numbers."""

    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as session:
            for line_number, line in enumerate(session, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise LedgerError(
                        f"invalid JSON on session line {line_number}"
                    ) from exc
                if not isinstance(row, dict):
                    raise LedgerError(
                        f"session line {line_number} is not a JSON object"
                    )
                rows.append(row)
    except OSError as exc:
        raise LedgerError(f"could not read session: {exc}") from exc
    return rows


def canonical_thread_id(value: str) -> str:
    """Validate a thread ID before using it in a bounded filename lookup."""

    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise LedgerError("thread ID must be a UUID") from exc


def resolve_thread_session(thread_id: str) -> pathlib.Path:
    """Resolve one exact active or archived session below the Codex home."""

    configured_home = os.environ.get("CODEX_HOME")
    codex_home = (
        pathlib.Path(configured_home).expanduser()
        if configured_home
        else pathlib.Path.home() / ".codex"
    )
    canonical_id = canonical_thread_id(thread_id)
    matches: set[pathlib.Path] = set()
    for root_name in ("sessions", "archived_sessions"):
        root = codex_home / root_name
        if not root.is_dir():
            continue
        matches.update(
            candidate.resolve()
            for candidate in root.rglob(f"*{canonical_id}.jsonl")
            if candidate.is_file()
        )
    if not matches:
        raise LedgerError(f"session not found for thread ID: {canonical_id}")
    if len(matches) > 1:
        raise LedgerError(f"multiple sessions found for thread ID: {canonical_id}")
    return matches.pop()


def stable_payload(value: Any) -> str:
    """Serialize tool arguments deterministically for duplicate detection."""

    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value
        return json.dumps(decoded, sort_keys=True, separators=(",", ":"))
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def payload_fingerprint(value: Any) -> str:
    """Hash tool arguments so the ledger does not echo commands or secrets."""

    return hashlib.sha256(stable_payload(value).encode("utf-8")).hexdigest()[:16]


def sensitive_key(value: object) -> bool:
    """Recognize structured argument keys whose values must never be emitted."""

    normalized = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return bool(SENSITIVE_KEY_RE.search(normalized))


def sanitize_text(value: str) -> str:
    """Redact common credential forms and local profile roots before truncation."""

    result = PRIVATE_KEY_RE.sub(REDACTED, value)
    result = USER_HOME_RE.sub(USER_HOME, result)
    result = WINDOWS_PATH_RE.sub(LOCAL_PATH, result)
    result = POSIX_PATH_RE.sub(LOCAL_PATH, result)
    result = RELATIVE_PATH_RE.sub(LOCAL_PATH, result)
    result = URL_CREDENTIAL_RE.sub(rf"\1{REDACTED}@", result)
    result = AUTH_VALUE_RE.sub(
        lambda match: f"{match.group(1)} {REDACTED}", result
    )
    result = KNOWN_TOKEN_RE.sub(REDACTED, result)
    return CREDENTIAL_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group('prefix')}{REDACTED}", result
    )


def sanitize_semantic_value(value: Any, *, key: object | None = None) -> Any:
    """Recursively redact structured tool arguments for opt-in semantic output."""

    if isinstance(value, str):
        if key is not None and PATH_KEY_RE.search(str(key)):
            return LOCAL_PATH
        return sanitize_text(value)
    if isinstance(value, list):
        return [sanitize_semantic_value(item, key=key) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        str(key): (
            REDACTED
            if sensitive_key(key)
            else sanitize_semantic_value(item, key=key)
        )
        for key, item in value.items()
    }


def semantic_summary(value: Any, *, decode_json: bool = True) -> str:
    """Produce one whitespace-normalized bounded summary after full redaction."""

    decoded = value
    if decode_json and isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            pass
    sanitized = sanitize_semantic_value(decoded)
    if isinstance(sanitized, str):
        text = sanitized
    else:
        text = json.dumps(
            sanitized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        )
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= SEMANTIC_SUMMARY_LIMIT:
        return compact
    return compact[: SEMANTIC_SUMMARY_LIMIT - 3] + "..."


def assistant_message_text(payload: dict[str, Any]) -> str:
    """Collect only assistant-authored text from one message response item."""

    content = payload.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text") or item.get("output_text")
        if isinstance(text, str):
            parts.append(text)
    return " ".join(parts)


def semantic_action_from_item(payload: dict[str, Any]) -> dict[str, str] | None:
    """Reduce one response item to an opt-in sanitized semantic action."""

    item_type = payload.get("type")
    if item_type == "message" and payload.get("role") != "user":
        phase = payload.get("phase")
        action = {
            "kind": "message",
            "name": phase if isinstance(phase, str) else "assistant",
        }
        summary = semantic_summary(
            assistant_message_text(payload),
            decode_json=False,
        )
    elif item_type == "function_call":
        name = payload.get("name")
        action = {
            "kind": "tool",
            "name": name if isinstance(name, str) else "unknown",
        }
        summary = semantic_summary(payload.get("arguments"))
    elif item_type == "custom_tool_call":
        name = payload.get("name")
        action = {
            "kind": "tool",
            "name": name if isinstance(name, str) else "unknown",
        }
        summary = semantic_summary(payload.get("input"))
    elif item_type == "tool_search_call":
        action = {"kind": "tool", "name": "tool_search"}
        summary = semantic_summary(payload.get("arguments"))
    else:
        return None
    if summary:
        action["summary"] = summary
    return action


def action_from_item(payload: dict[str, Any]) -> dict[str, str] | None:
    """Reduce one response item to a compact message or tool action."""

    item_type = payload.get("type")
    if item_type == "message" and payload.get("role") != "user":
        phase = payload.get("phase")
        return {
            "kind": "message",
            "name": phase if isinstance(phase, str) else "assistant",
        }
    if item_type == "function_call":
        name = payload.get("name")
        arguments = payload.get("arguments")
    elif item_type == "custom_tool_call":
        name = payload.get("name")
        arguments = payload.get("input")
    elif item_type == "tool_search_call":
        name = "tool_search"
        arguments = payload.get("arguments")
    else:
        return None
    return {
        "kind": "tool",
        "name": name if isinstance(name, str) else "unknown",
        "fingerprint": payload_fingerprint(arguments),
    }


def empty_outcomes() -> dict[str, bool]:
    """Return the closed structured-result signal set for one tool action."""

    return {
        "structured_tool_error": False,
        "nonzero_process_result": False,
        "timeout": False,
        "termination": False,
        "structured_outcome": False,
        "process_result_observed": False,
    }


def scan_structured_signals(
    value: Any,
    signals: dict[str, bool],
    *,
    envelope: bool,
) -> None:
    """Read explicit result fields without interpreting prose result content."""

    if isinstance(value, list):
        for item in value:
            scan_structured_signals(item, signals, envelope=False)
        return
    if not isinstance(value, dict):
        return

    if envelope:
        if "Err" in value:
            signals["structured_outcome"] = True
            signals["structured_tool_error"] = True
        success = value.get("success")
        if isinstance(success, bool):
            signals["structured_outcome"] = True
            signals["structured_tool_error"] |= not success
        status = value.get("status")
        if isinstance(status, str):
            normalized_status = status.casefold()
            signals["structured_outcome"] = True
            signals["structured_tool_error"] |= normalized_status in ERROR_STATUSES
            signals["timeout"] |= normalized_status in TIMEOUT_STATUSES
            signals["termination"] |= normalized_status in TERMINATION_STATUSES

    for key, item in value.items():
        normalized_key = str(key).casefold()
        if normalized_key in {"iserror", "is_error"} and isinstance(item, bool):
            signals["structured_outcome"] = True
            signals["structured_tool_error"] |= item
        elif normalized_key in PROCESS_CODE_FIELDS and (
            isinstance(item, int) and not isinstance(item, bool)
        ):
            signals["structured_outcome"] = True
            signals["process_result_observed"] = True
            signals["nonzero_process_result"] |= item != 0
        elif normalized_key in TIMEOUT_FIELDS and isinstance(item, bool):
            signals["structured_outcome"] = True
            signals["timeout"] |= item
        elif normalized_key in TERMINATION_FIELDS and isinstance(item, bool):
            signals["structured_outcome"] = True
            signals["termination"] |= item
        if isinstance(item, (dict, list)):
            scan_structured_signals(item, signals, envelope=False)


def structured_function_output(payload: dict[str, Any]) -> Any | None:
    """Decode only a complete JSON function result, never prose output text."""

    if payload.get("type") != "function_call_output":
        return None
    output = payload.get("output")
    if isinstance(output, (dict, list)):
        return output
    if not isinstance(output, str):
        return None
    try:
        decoded = json.loads(output)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, (dict, list)) else None


def response_outcomes(payload: dict[str, Any]) -> dict[str, bool]:
    """Collect structured signals exposed directly by one tool-result item."""

    signals = empty_outcomes()
    scan_structured_signals(payload, signals, envelope=True)
    decoded = structured_function_output(payload)
    if decoded is not None:
        scan_structured_signals(decoded, signals, envelope=True)
    return signals


def mcp_outcomes(payload: dict[str, Any]) -> dict[str, bool]:
    """Collect the MCP result envelope and structured process signals."""

    signals = empty_outcomes()
    result = payload.get("result")
    if not isinstance(result, dict):
        return signals
    if "Err" in result:
        signals["structured_outcome"] = True
        signals["structured_tool_error"] = True
    ok = result.get("Ok")
    if not isinstance(ok, dict):
        return signals
    is_error = ok.get("isError")
    if isinstance(is_error, bool):
        signals["structured_outcome"] = True
        signals["structured_tool_error"] |= is_error
    structured = ok.get("structuredContent")
    if isinstance(structured, (dict, list)):
        scan_structured_signals(structured, signals, envelope=False)
    return signals


def patch_outcomes(payload: dict[str, Any]) -> dict[str, bool]:
    """Collect the explicit apply-patch completion signal."""

    signals = empty_outcomes()
    success = payload.get("success")
    if isinstance(success, bool):
        signals["structured_outcome"] = True
        signals["structured_tool_error"] = not success
    return signals


def merge_outcomes(target: dict[str, Any], source: dict[str, bool]) -> None:
    """Merge multiple recorded result events for one top-level tool action."""

    for field, value in source.items():
        target[field] = bool(target.get(field)) or value


def token_usage(payload: dict[str, Any]) -> dict[str, int]:
    """Select non-negative integer usage fields from one token-count event."""

    info = payload.get("info")
    last = info.get("last_token_usage") if isinstance(info, dict) else None
    usage: dict[str, int] = {}
    if not isinstance(last, dict):
        return usage
    for field in TOKEN_FIELDS:
        value = last.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            usage[field] = value
    return usage


def build_ledger(
    rows: list[dict[str, Any]],
    *,
    session: pathlib.Path,
    last_runs: int | None,
) -> dict[str, Any]:
    """Group completed runs and enumerate every non-empty model response."""

    ordered_turns: list[str] = []
    runs: dict[str, dict[str, Any]] = {}
    active_turn: str | None = None
    pending_actions: list[dict[str, str]] = []

    for row in rows:
        row_type = row.get("type")
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue

        if row_type == "turn_context":
            turn_id = payload.get("turn_id")
            active_turn = turn_id if isinstance(turn_id, str) else None
            pending_actions = []
            if active_turn is not None and active_turn not in runs:
                ordered_turns.append(active_turn)
                runs[active_turn] = {
                    "turn_id": active_turn,
                    "started_at": row.get("timestamp"),
                    "completed": False,
                    "calls": [],
                }
            continue

        if active_turn is None or active_turn not in runs:
            continue

        if row_type == "response_item":
            action = action_from_item(payload)
            if action is not None:
                pending_actions.append(action)
            if (
                payload.get("type") == "message"
                and payload.get("role") != "user"
                and payload.get("phase") == "final_answer"
            ):
                runs[active_turn]["completed"] = True
            continue

        if row_type != "event_msg" or payload.get("type") != "token_count":
            continue
        usage = token_usage(payload)
        # Total-only events are delayed context accounting, not model responses.
        if not any(
            usage.get(field, 0) > 0
            for field in ("input_tokens", "output_tokens", "reasoning_output_tokens")
        ):
            pending_actions = []
            continue
        calls = runs[active_turn]["calls"]
        calls.append(
            {
                "index": len(calls) + 1,
                "timestamp": row.get("timestamp"),
                "actions": pending_actions,
                "tokens": usage,
            }
        )
        pending_actions = []

    selected = [
        runs[turn_id]
        for turn_id in ordered_turns
        if runs[turn_id]["completed"]
    ]
    if last_runs is not None:
        selected = selected[-last_runs:]

    selected_fingerprints = Counter(
        (action["name"], action["fingerprint"])
        for run in selected
        for call in run["calls"]
        for action in call["actions"]
        if action["kind"] == "tool"
    )
    totals = {field: 0 for field in TOKEN_FIELDS}
    for run in selected:
        run_totals = {field: 0 for field in TOKEN_FIELDS}
        for call in run["calls"]:
            for field, value in call["tokens"].items():
                run_totals[field] += value
                totals[field] += value
        run["model_calls"] = len(run["calls"])
        run["tokens"] = run_totals
        del run["completed"]

    repeated = [
        {"name": name, "fingerprint": fingerprint, "count": count}
        for (name, fingerprint), count in selected_fingerprints.items()
        if count > 1
    ]
    repeated.sort(
        key=lambda item: (-item["count"], item["name"], item["fingerprint"])
    )

    return {
        "schema": SCHEMA,
        "session": str(session),
        "window": {
            "mode": "last_runs" if last_runs is not None else "full_thread",
            "requested_runs": last_runs,
            "completed_runs": len(selected),
        },
        "totals": {
            "runs": len(selected),
            "model_calls": sum(run["model_calls"] for run in selected),
            **totals,
        },
        "repeated_tool_calls": repeated,
        "runs": selected,
    }


def build_semantic_runs(
    rows: list[dict[str, Any]],
    ledger: dict[str, Any],
    include_runs: list[str],
) -> list[dict[str, Any]]:
    """Build opt-in semantic actions only for requested completed-window runs."""

    if not include_runs:
        return []
    runs_by_id = {run["turn_id"]: run for run in ledger["runs"]}
    requested = list(dict.fromkeys(include_runs))
    unknown = sorted(set(requested) - runs_by_id.keys())
    if unknown:
        raise LedgerError(f"requested run is outside the completed window: {unknown[0]}")

    requested_set = set(requested)
    calls_by_id: dict[str, list[dict[str, Any]]] = {
        turn_id: [] for turn_id in requested
    }
    active_turn: str | None = None
    pending_actions: list[dict[str, str]] = []
    for row in rows:
        row_type = row.get("type")
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        if row_type == "turn_context":
            turn_id = payload.get("turn_id")
            active_turn = turn_id if turn_id in requested_set else None
            pending_actions = []
            continue
        if active_turn is None:
            continue
        if row_type == "response_item":
            action = semantic_action_from_item(payload)
            if action is not None:
                pending_actions.append(action)
            continue
        if row_type != "event_msg" or payload.get("type") != "token_count":
            continue
        usage = token_usage(payload)
        if not any(
            usage.get(field, 0) > 0
            for field in ("input_tokens", "output_tokens", "reasoning_output_tokens")
        ):
            pending_actions = []
            continue
        calls = calls_by_id[active_turn]
        calls.append({"index": len(calls) + 1, "actions": pending_actions})
        pending_actions = []

    result: list[dict[str, Any]] = []
    for turn_id in requested:
        run = runs_by_id[turn_id]
        calls = calls_by_id[turn_id]
        if len(calls) != run["model_calls"]:
            raise LedgerError(f"semantic call count does not match ledger: {turn_id}")
        result.append(
            {
                "turn_id": turn_id,
                "started_at": run["started_at"],
                "model_calls": run["model_calls"],
                "calls": calls,
            }
        )
    return result


def selected_runs_with_semantics(
    ledger: dict[str, Any],
    include_runs: list[str],
    semantic_runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Preserve ordinary selected-run details and add sanitized action summaries."""

    runs_by_id = {run["turn_id"]: run for run in ledger["runs"]}
    semantic_by_id = {run["turn_id"]: run for run in semantic_runs}
    selected: list[dict[str, Any]] = []
    for turn_id in include_runs:
        run = runs_by_id[turn_id]
        semantic_calls = {
            call["index"]: call["actions"]
            for call in semantic_by_id[turn_id]["calls"]
        }
        selected.append(
            {
                **run,
                "calls": [
                    {
                        **call,
                        "semantic_actions": semantic_calls[call["index"]],
                    }
                    for call in run["calls"]
                ],
            }
        )
    return selected


def build_summary(
    ledger: dict[str, Any],
    *,
    evidence_output: pathlib.Path,
) -> dict[str, Any]:
    """Keep ordinary stdout free of selected-run semantic details."""

    runs = ledger["runs"]
    return {
        "schema": SUMMARY_SCHEMA,
        "evidence_schema": ledger["schema"],
        "classification_input": classification_input_contract(),
        "evidence_output": str(evidence_output),
        "window": ledger["window"],
        "totals": ledger["totals"],
        "repeated_tool_calls": ledger["repeated_tool_calls"],
        "runs": [
            {
                "turn_id": run["turn_id"],
                "started_at": run["started_at"],
                "model_calls": run["model_calls"],
                "tokens": run["tokens"],
            }
            for run in runs
        ],
        "selected_runs": [],
    }


def build_semantic_evidence(
    ledger: dict[str, Any],
    include_runs: list[str],
    semantic_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a path-free sidecar for explicitly selected completed runs."""

    return {
        "schema": SEMANTIC_EVIDENCE_SCHEMA,
        "ledger_schema": ledger["schema"],
        "window": ledger["window"],
        "selected_runs": selected_runs_with_semantics(
            ledger,
            list(dict.fromkeys(include_runs)),
            semantic_runs,
        ),
    }


def build_semantic_summary(
    ledger: dict[str, Any],
    semantic_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Emit only the decision-sized receipt for the two written artifacts."""

    selected_runs = semantic_evidence["selected_runs"]
    return {
        "schema": SEMANTIC_SUMMARY_SCHEMA,
        "evidence_schemas": {
            "ledger": ledger["schema"],
            "semantic": semantic_evidence["schema"],
        },
        "written": {"ledger": True, "semantic": True},
        "window": ledger["window"],
        "totals": {
            "selected_runs": len(selected_runs),
            "selected_model_calls": sum(
                run["model_calls"] for run in selected_runs
            ),
        },
        "selected_runs": [
            {
                "turn_id": run["turn_id"],
                "model_calls": run["model_calls"],
            }
            for run in selected_runs
        ],
    }


def build_closure_summary(
    ledger: dict[str, Any],
    semantic_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Emit all completed calls without per-call token or temporary-file noise."""

    result = {
        "schema": CLOSURE_SCHEMA,
        "evidence_schema": ledger["schema"],
        "classification_input": classification_input_contract(),
        "session": ledger["session"],
        "window": ledger["window"],
        "totals": ledger["totals"],
        "repeated_tool_calls": ledger["repeated_tool_calls"],
        "runs": [
            {
                "turn_id": run["turn_id"],
                "started_at": run["started_at"],
                "model_calls": run["model_calls"],
                "tokens": run["tokens"],
                "calls": [
                    {
                        "index": call["index"],
                        "actions": call["actions"],
                    }
                    for call in run["calls"]
                ],
            }
            for run in ledger["runs"]
        ],
    }
    if semantic_runs:
        result["selected_runs"] = semantic_runs
    return result


def call_id_from_payload(payload: dict[str, Any]) -> str | None:
    """Return the opaque result-correlation ID without emitting it."""

    call_id = payload.get("call_id") or payload.get("id")
    return call_id if isinstance(call_id, str) and call_id else None


def estimated_credit_cost(
    tokens: dict[str, int],
    pricing: dict[str, float | str] | None,
) -> float | None:
    """Apply caller-supplied rates without double-charging reasoning output."""

    if pricing is None:
        return None
    input_tokens = tokens.get("input_tokens", 0)
    cached_tokens = tokens.get("cached_input_tokens", 0)
    uncached_tokens = max(input_tokens - cached_tokens, 0)
    raw_cost = (
        uncached_tokens * float(pricing["input_per_million_tokens"])
        + cached_tokens * float(pricing["cached_input_per_million_tokens"])
        + tokens.get("output_tokens", 0)
        * float(pricing["output_per_million_tokens"])
    ) / 1_000_000
    result = raw_cost * float(pricing["mode_multiplier"])
    if not math.isfinite(result):
        raise LedgerError("pricing profile produces a non-finite credit cost")
    return round(result, 12)


def usage_metrics(
    *,
    tokens: dict[str, int],
    model_calls: int,
    duration_ms: int | None,
    actions: int,
    tool_actions: list[dict[str, Any]],
    distinct_calls: int,
    repeated_calls: int,
    retries: int,
    pricing: dict[str, float | str] | None,
) -> dict[str, Any]:
    """Build the common per-turn and thread metric contract."""

    input_tokens = tokens.get("input_tokens", 0)
    cached_tokens = tokens.get("cached_input_tokens", 0)
    output_tokens = tokens.get("output_tokens", 0)
    reasoning_tokens = tokens.get("reasoning_output_tokens", 0)
    total_tokens = tokens.get("total_tokens", 0)
    explicit_failures = sum(
        1 for action in tool_actions if action["explicit_failure"]
    )
    return {
        "model_calls": model_calls,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "uncached_input_tokens": max(input_tokens - cached_tokens, 0),
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
        "input_of_total_pct": percentage(input_tokens, total_tokens),
        "cache_rate_pct": percentage(cached_tokens, input_tokens),
        "output_of_total_pct": percentage(output_tokens, total_tokens),
        "reasoning_of_output_pct": percentage(reasoning_tokens, output_tokens),
        "duration_ms": duration_ms,
        "waits": sum(
            1 for action in tool_actions if action["name"] in WAIT_ACTION_NAMES
        ),
        "actions": actions,
        "tool_actions": len(tool_actions),
        "distinct_calls": distinct_calls,
        "repeated_calls": repeated_calls,
        "retries": retries,
        "explicit_failures": explicit_failures,
        "structured_tool_errors": sum(
            1
            for action in tool_actions
            if action["outcomes"]["structured_tool_error"]
        ),
        "nonzero_process_results": sum(
            1
            for action in tool_actions
            if action["outcomes"]["nonzero_process_result"]
        ),
        "timeouts": sum(
            1 for action in tool_actions if action["outcomes"]["timeout"]
        ),
        "terminations": sum(
            1 for action in tool_actions if action["outcomes"]["termination"]
        ),
        "estimated_credit_cost": estimated_credit_cost(tokens, pricing),
    }


def public_tool_action(action: dict[str, Any]) -> dict[str, Any]:
    """Remove correlation-only state from one sanitized top-level action."""

    if action["structured_outcome"]:
        telemetry = "structured"
    elif action["result_recorded"]:
        telemetry = "unstructured"
    else:
        telemetry = "missing"
    return {
        "index": action["index"],
        "model_call_index": action["model_call_index"],
        "name": action["name"],
        "fingerprint": action["fingerprint"],
        "repeated": action["repeated"],
        "retry": action["retry"],
        "explicit_failure": action["explicit_failure"],
        "result_telemetry": telemetry,
        "process_result_observed": action["process_result_observed"],
        "outcomes": {
            field: action[field]
            for field in (
                "structured_tool_error",
                "nonzero_process_result",
                "timeout",
                "termination",
            )
        },
    }


def build_usage_evidence(
    rows: list[dict[str, Any]],
    ledger: dict[str, Any],
    pricing: dict[str, float | str] | None,
) -> dict[str, Any]:
    """Build sanitized per-turn metrics and structured top-level outcomes."""

    run_states: dict[str, dict[str, Any]] = {}
    for order, run in enumerate(ledger["runs"]):
        run_states[run["turn_id"]] = {
            "order": order,
            "turn_id": run["turn_id"],
            "started_at": run["started_at"],
            "tokens": dict(run["tokens"]),
            "model_calls": run["model_calls"],
            "calls": [
                {
                    "index": call["index"],
                    "tokens": dict(call["tokens"]),
                    "actions": [dict(action) for action in call["actions"]],
                }
                for call in run["calls"]
            ],
            "actions": 0,
            "tool_actions": [],
            "duration_ms": 0,
            "duration_events": 0,
            "next_model_call": 0,
        }

    selected_turns = set(run_states)
    call_actions: dict[str, dict[str, Any]] = {}
    active_turn: str | None = None
    pending_tool_actions: list[dict[str, Any]] = []

    for row in rows:
        row_type = row.get("type")
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue

        if row_type == "turn_context":
            turn_id = payload.get("turn_id")
            active_turn = (
                turn_id
                if isinstance(turn_id, str) and turn_id in selected_turns
                else None
            )
            pending_tool_actions = []
            continue

        if row_type == "event_msg" and payload.get("type") == "task_complete":
            turn_id = payload.get("turn_id")
            duration = payload.get("duration_ms")
            if (
                isinstance(turn_id, str)
                and turn_id in run_states
                and isinstance(duration, int)
                and not isinstance(duration, bool)
                and duration >= 0
            ):
                state = run_states[turn_id]
                state["duration_ms"] += duration
                state["duration_events"] += 1
            continue

        if row_type == "event_msg" and payload.get("type") in {
            "mcp_tool_call_end",
            "patch_apply_end",
        }:
            call_id = call_id_from_payload(payload)
            result_action = call_actions.get(call_id) if call_id else None
            if result_action is None:
                continue
            result_action["result_recorded"] = True
            signals = (
                mcp_outcomes(payload)
                if payload.get("type") == "mcp_tool_call_end"
                else patch_outcomes(payload)
            )
            merge_outcomes(result_action, signals)
            continue

        if row_type == "response_item" and str(payload.get("type", "")).endswith(
            "_output"
        ):
            call_id = call_id_from_payload(payload)
            result_action = call_actions.get(call_id) if call_id else None
            if result_action is not None:
                result_action["result_recorded"] = True
                merge_outcomes(result_action, response_outcomes(payload))
            continue

        if active_turn is None:
            continue
        state = run_states[active_turn]

        if row_type == "response_item":
            compact_action = action_from_item(payload)
            if compact_action is None:
                continue
            state["actions"] += 1
            if compact_action["kind"] != "tool":
                continue
            new_action: dict[str, Any] = {
                "index": len(state["tool_actions"]) + 1,
                "model_call_index": None,
                "name": compact_action["name"],
                "fingerprint": compact_action["fingerprint"],
                "result_recorded": False,
                "repeated": False,
                "retry": False,
                "explicit_failure": False,
                **empty_outcomes(),
            }
            state["tool_actions"].append(new_action)
            pending_tool_actions.append(new_action)
            call_id = call_id_from_payload(payload)
            if call_id is not None:
                call_actions[call_id] = new_action
            continue

        if row_type != "event_msg" or payload.get("type") != "token_count":
            continue
        usage = token_usage(payload)
        if not any(
            usage.get(field, 0) > 0
            for field in ("input_tokens", "output_tokens", "reasoning_output_tokens")
        ):
            pending_tool_actions = []
            continue
        state["next_model_call"] += 1
        for pending_action in pending_tool_actions:
            pending_action["model_call_index"] = state["next_model_call"]
        pending_tool_actions = []

    evidence_runs: list[dict[str, Any]] = []
    all_actions: list[dict[str, Any]] = []
    total_retries = 0
    total_actions = 0
    duration_total = 0
    duration_covered_turns = 0
    for state in run_states.values():
        previous: dict[tuple[str, str], dict[str, Any]] = {}
        for action in state["tool_actions"]:
            action["explicit_failure"] = bool(
                action["structured_tool_error"]
                or action["timeout"]
                or action["termination"]
            )
            signature = (action["name"], action["fingerprint"])
            earlier = previous.get(signature)
            action["repeated"] = earlier is not None
            action["retry"] = bool(earlier and earlier["explicit_failure"])
            previous[signature] = action
        public_actions = [public_tool_action(action) for action in state["tool_actions"]]
        distinct_calls = len(
            {(action["name"], action["fingerprint"]) for action in public_actions}
        )
        repeated_calls = len(public_actions) - distinct_calls
        retries = sum(1 for action in public_actions if action["retry"])
        duration = (
            state["duration_ms"] if state["duration_events"] > 0 else None
        )
        if duration is not None:
            duration_total += duration
            duration_covered_turns += 1
        metrics = usage_metrics(
            tokens=state["tokens"],
            model_calls=state["model_calls"],
            duration_ms=duration,
            actions=state["actions"],
            tool_actions=public_actions,
            distinct_calls=distinct_calls,
            repeated_calls=repeated_calls,
            retries=retries,
            pricing=pricing,
        )
        tool_counts = Counter(action["name"] for action in public_actions)
        evidence_runs.append(
            {
                "turn_id": state["turn_id"],
                "started_at": state["started_at"],
                "totals": metrics,
                "tool_counts": dict(sorted(tool_counts.items())),
                "calls": state["calls"],
                "tool_action_results": public_actions,
            }
        )
        all_actions.extend(public_actions)
        total_retries += retries
        total_actions += state["actions"]

    thread_signatures = {
        (action["name"], action["fingerprint"]) for action in all_actions
    }
    thread_tokens = {
        field: ledger["totals"][field]
        for field in TOKEN_FIELDS
    }
    thread_metrics = usage_metrics(
        tokens=thread_tokens,
        model_calls=ledger["totals"]["model_calls"],
        duration_ms=(duration_total if duration_covered_turns else None),
        actions=total_actions,
        tool_actions=all_actions,
        distinct_calls=len(thread_signatures),
        repeated_calls=len(all_actions) - len(thread_signatures),
        retries=total_retries,
        pricing=pricing,
    )

    result_recorded = sum(1 for action in all_actions if action["result_telemetry"] != "missing")
    structured_results = sum(
        1 for action in all_actions if action["result_telemetry"] == "structured"
    )
    process_results = sum(
        1 for action in all_actions if action["process_result_observed"]
    )
    exec_actions = sum(
        1 for action in all_actions if action["name"] in {"exec", "functions.exec"}
    )
    limitations: list[str] = []
    if exec_actions:
        limitations.append("functions_exec_child_calls_unavailable")
    if result_recorded > structured_results:
        limitations.append("unstructured_tool_result_outcomes")
    if duration_covered_turns < len(evidence_runs):
        limitations.append("turn_duration_unavailable")

    pricing_contract: dict[str, Any]
    if pricing is None:
        pricing_contract = {"provided": False}
    else:
        pricing_contract = {"provided": True, **pricing}

    return {
        "schema": USAGE_EVIDENCE_SCHEMA,
        "window": ledger["window"],
        "pricing": pricing_contract,
        "totals": thread_metrics,
        "runs": evidence_runs,
        "repeated_tool_calls": ledger["repeated_tool_calls"],
        "telemetry": {
            "action_scope": "top_level_response_items",
            "duration_source": "task_complete.duration_ms",
            "retry_definition": "same_turn_repeat_after_explicit_failure",
            "result_signal_source": "structured_result_fields_only",
            "top_level_tool_actions": len(all_actions),
            "result_recorded_actions": result_recorded,
            "structured_outcome_actions": structured_results,
            "unstructured_result_actions": result_recorded - structured_results,
            "missing_result_actions": len(all_actions) - result_recorded,
            "structured_process_result_actions": process_results,
            "duration_covered_turns": duration_covered_turns,
            "duration_total_turns": len(evidence_runs),
            "functions_exec": {
                "outer_actions": exec_actions,
                "child_calls": "unavailable" if exec_actions else "not_observed",
            },
            "nonzero_process_results_are_semantic_failures": False,
            "limitations": limitations,
        },
    }


def build_usage_rankings(
    evidence: dict[str, Any],
    top_n: int,
) -> dict[str, list[dict[str, Any]]]:
    """Rank turns by numeric metrics while preserving selected-order ties."""

    ranking_fields = (
        "total_tokens",
        "uncached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "model_calls",
        "explicit_failures",
        "retries",
        "duration_ms",
        "estimated_credit_cost",
    )
    order = {
        run["turn_id"]: index
        for index, run in enumerate(evidence["runs"])
    }
    rankings: dict[str, list[dict[str, Any]]] = {}
    for field in ranking_fields:
        candidates = [
            (run["turn_id"], run["totals"].get(field))
            for run in evidence["runs"]
            if isinstance(run["totals"].get(field), (int, float))
            and not isinstance(run["totals"].get(field), bool)
            and run["totals"][field] > 0
        ]
        candidates.sort(key=lambda item: (-item[1], order[item[0]]))
        rankings[field] = [
            {"turn_id": turn_id, "value": value}
            for turn_id, value in candidates[:top_n]
        ]
    return rankings


def build_usage_summary(
    evidence: dict[str, Any],
    *,
    top_n: int,
) -> dict[str, Any]:
    """Emit decision-sized totals and rankings without paths or call inventory."""

    limitations = list(evidence["telemetry"]["limitations"])
    if not evidence["pricing"]["provided"]:
        limitations.append("pricing_profile_not_provided")
    return {
        "schema": USAGE_SUMMARY_SCHEMA,
        "evidence_schema": evidence["schema"],
        "evidence_written": True,
        "window": evidence["window"],
        "top_n": top_n,
        "pricing": evidence["pricing"],
        "totals": evidence["totals"],
        "rankings": build_usage_rankings(evidence, top_n),
        "telemetry": {
            "action_scope": evidence["telemetry"]["action_scope"],
            "duration_source": evidence["telemetry"]["duration_source"],
            "retry_definition": evidence["telemetry"]["retry_definition"],
            "result_signal_source": evidence["telemetry"][
                "result_signal_source"
            ],
            "top_level_tool_actions": evidence["telemetry"][
                "top_level_tool_actions"
            ],
            "structured_outcome_actions": evidence["telemetry"][
                "structured_outcome_actions"
            ],
            "unstructured_result_actions": evidence["telemetry"][
                "unstructured_result_actions"
            ],
            "missing_result_actions": evidence["telemetry"][
                "missing_result_actions"
            ],
            "duration_covered_turns": evidence["telemetry"][
                "duration_covered_turns"
            ],
            "duration_total_turns": evidence["telemetry"][
                "duration_total_turns"
            ],
            "functions_exec": evidence["telemetry"]["functions_exec"],
            "nonzero_process_results_are_semantic_failures": False,
            "limitations": limitations,
        },
    }


def classification_input_contract() -> dict[str, Any]:
    """Describe the compact caller-owned classification file shape."""

    return {
        "schema": CLASSIFICATIONS_SCHEMA,
        "categories": list(CLASSIFICATION_CATEGORIES),
        "shape": {
            "schema": CLASSIFICATIONS_SCHEMA,
            "session": "<exact ledger session>",
            "runs": [
                {
                    "turn_id": "<selected turn ID>",
                    "groups": [
                        {
                            "category": "<category>",
                            "control": "<required for avoidable categories>",
                            "indices": [1],
                        }
                    ],
                }
            ],
        },
    }


def load_classifications(path: pathlib.Path) -> dict[str, Any]:
    """Load caller judgment without accepting malformed or partial JSON."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LedgerError(f"could not read classifications: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LedgerError("classifications are not valid JSON") from exc
    if not isinstance(value, dict):
        raise LedgerError("classifications must be a JSON object")
    return value


def build_classified_summary(
    ledger: dict[str, Any],
    classifications: dict[str, Any],
) -> dict[str, Any]:
    """Require every selected call to have exactly one supported classification."""

    if classifications.get("schema") != CLASSIFICATIONS_SCHEMA:
        raise LedgerError(
            f"classifications schema must be {CLASSIFICATIONS_SCHEMA}"
        )
    try:
        classified_session = pathlib.Path(
            str(classifications.get("session") or "")
        ).expanduser().resolve(strict=True)
        ledger_session = pathlib.Path(ledger["session"]).resolve(strict=True)
    except OSError as exc:
        raise LedgerError(f"could not resolve classified session: {exc}") from exc
    if classified_session != ledger_session:
        raise LedgerError("classifications session does not match the ledger")

    raw_runs = classifications.get("runs")
    if not isinstance(raw_runs, list):
        raise LedgerError("classifications must contain a runs list")
    classified_runs: dict[str, dict[str, Any]] = {}
    for raw_run in raw_runs:
        if not isinstance(raw_run, dict):
            raise LedgerError("each classified run must be an object")
        turn_id = raw_run.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id:
            raise LedgerError("each classified run needs a turn_id")
        if turn_id in classified_runs:
            raise LedgerError(f"duplicate classified run: {turn_id}")
        classified_runs[turn_id] = raw_run

    ledger_runs = {run["turn_id"]: run for run in ledger["runs"]}
    missing_runs = sorted(ledger_runs.keys() - classified_runs.keys())
    extra_runs = sorted(classified_runs.keys() - ledger_runs.keys())
    if missing_runs:
        raise LedgerError(f"missing classified run: {missing_runs[0]}")
    if extra_runs:
        raise LedgerError(f"classified run is outside the window: {extra_runs[0]}")

    totals: Counter[str] = Counter()
    control_totals: Counter[tuple[str, str]] = Counter()
    summarized_runs: list[dict[str, Any]] = []
    for turn_id, ledger_run in ledger_runs.items():
        raw_groups = classified_runs[turn_id].get("groups")
        if not isinstance(raw_groups, list) or not raw_groups:
            raise LedgerError(f"classified run has no groups: {turn_id}")
        assigned: dict[int, str] = {}
        category_counts: Counter[str] = Counter()
        for group in raw_groups:
            if not isinstance(group, dict):
                raise LedgerError(f"classification group is not an object: {turn_id}")
            category = group.get("category")
            if category not in CLASSIFICATION_CATEGORIES:
                raise LedgerError(
                    f"unsupported classification category in run: {turn_id}"
                )
            control = group.get("control")
            control_name: str | None = None
            if category == "necessary":
                if control not in (None, ""):
                    raise LedgerError(
                        f"necessary calls must not name a control: {turn_id}"
                    )
            elif not isinstance(control, str) or not control.strip():
                raise LedgerError(
                    f"avoidable calls must name their controlling fix: {turn_id}"
                )
            else:
                control_name = control.strip()
            raw_indices = group.get("indices")
            if not isinstance(raw_indices, list) or not raw_indices:
                raise LedgerError(
                    f"classification group has no call indices: {turn_id}"
                )
            for index in raw_indices:
                if (
                    not isinstance(index, int)
                    or isinstance(index, bool)
                    or index < 1
                    or index > ledger_run["model_calls"]
                ):
                    raise LedgerError(
                        f"classified call index is outside run {turn_id}"
                    )
                if index in assigned:
                    raise LedgerError(
                        f"call {index} is classified more than once in run {turn_id}"
                    )
                assigned[index] = category
                category_counts[category] += 1
                totals[category] += 1
                if category != "necessary":
                    assert control_name is not None
                    control_totals[(category, control_name)] += 1

        expected = set(range(1, ledger_run["model_calls"] + 1))
        missing_calls = sorted(expected - assigned.keys())
        if missing_calls:
            raise LedgerError(
                f"call {missing_calls[0]} is unclassified in run {turn_id}"
            )
        summarized_runs.append(
            {
                "turn_id": turn_id,
                "started_at": ledger_run["started_at"],
                "model_calls": ledger_run["model_calls"],
                "necessary": category_counts["necessary"],
                "avoidable_with_implemented_fix": category_counts[
                    "avoidable_implemented"
                ],
                "avoidable_with_unimplemented_fix": category_counts[
                    "avoidable_unimplemented"
                ],
            }
        )

    model_calls = ledger["totals"]["model_calls"]
    classified_calls = sum(totals.values())
    if classified_calls != model_calls:
        raise LedgerError(
            f"classified call total {classified_calls} does not match {model_calls}"
        )
    return {
        "schema": CLASSIFIED_SUMMARY_SCHEMA,
        "evidence_schema": ledger["schema"],
        "classification_schema": CLASSIFICATIONS_SCHEMA,
        "session": ledger["session"],
        "window": ledger["window"],
        "totals": {
            "model_calls": model_calls,
            "necessary": totals["necessary"],
            "avoidable_with_implemented_fix": totals[
                "avoidable_implemented"
            ],
            "avoidable_with_unimplemented_fix": totals[
                "avoidable_unimplemented"
            ],
            **{
                field: ledger["totals"][field]
                for field in TOKEN_FIELDS
            },
        },
        "runs": summarized_runs,
        "controls": [
            {"category": category, "control": control, "model_calls": count}
            for (category, control), count in sorted(control_totals.items())
        ],
    }


def write_evidence(path: pathlib.Path, ledger: dict[str, Any]) -> None:
    """Write sanitized call evidence only to the caller-authorized path."""

    if not path.parent.is_dir():
        raise LedgerError(f"evidence output directory does not exist: {path.parent}")
    try:
        path.write_text(
            json.dumps(ledger, separators=(",", ":")) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as exc:
        raise LedgerError(f"could not write evidence output: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    """Build the public deterministic evidence and summary command."""

    parser = argparse.ArgumentParser(
        description=(
            "Write model-call evidence, emit one artifact-free closure inventory, "
            "or write detailed usage evidence with a compact summary."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--session", type=pathlib.Path)
    source.add_argument("--thread-id")
    parser.add_argument("--evidence-output", type=pathlib.Path)
    parser.add_argument(
        "--semantic-evidence-output",
        type=pathlib.Path,
        help=(
            "write versioned sanitized evidence for explicitly selected runs "
            "and keep semantic action bodies out of stdout"
        ),
    )
    parser.add_argument(
        "--classifications",
        type=pathlib.Path,
        help=(
            "validate one caller-owned classification file against the exact "
            "selected session window"
        ),
    )
    parser.add_argument("--last-runs", type=positive_int)
    parser.add_argument(
        "--include-run",
        action="append",
        default=[],
        help=(
            "add bounded sanitized action summaries for one completed run; "
            "repeat for additional runs"
        ),
    )
    parser.add_argument(
        "--closure",
        action="store_true",
        help=(
            "emit selected completed calls without creating an evidence "
            "artifact"
        ),
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help=(
            "write versioned sanitized usage evidence and emit compact totals "
            "and top-turn rankings"
        ),
    )
    parser.add_argument(
        "--top",
        type=positive_int,
        help=f"number of turns per summary ranking (default: {DEFAULT_TOP})",
    )
    parser.add_argument(
        "--pricing-profile",
        type=pathlib.Path,
        help=(
            "optional versioned input, cached-input, output, and mode credit rates"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one preserved ledger mode or the additive compact usage summary."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.summary and args.closure:
            raise LedgerError("--summary does not accept --closure")
        if args.summary:
            if args.classifications is not None:
                raise LedgerError("--summary does not accept --classifications")
            if args.include_run:
                raise LedgerError("--summary does not accept --include-run")
            if args.semantic_evidence_output is not None:
                raise LedgerError(
                    "--summary does not accept --semantic-evidence-output"
                )
            if args.evidence_output is None:
                raise LedgerError("--summary requires --evidence-output")
        elif args.classifications is not None:
            if args.evidence_output is not None:
                raise LedgerError(
                    "--classifications does not accept --evidence-output"
                )
            if args.include_run:
                raise LedgerError(
                    "--classifications validates every completed run"
                )
            if args.semantic_evidence_output is not None:
                raise LedgerError(
                    "--classifications does not accept --semantic-evidence-output"
                )
        elif args.closure:
            if args.evidence_output is not None:
                raise LedgerError("--closure does not accept --evidence-output")
            if args.semantic_evidence_output is not None:
                raise LedgerError(
                    "--closure does not accept --semantic-evidence-output"
                )
        else:
            if args.thread_id is not None:
                raise LedgerError("--thread-id requires --closure")
            if args.evidence_output is None:
                raise LedgerError("ordinary mode requires --evidence-output")
            if args.semantic_evidence_output is not None and not args.include_run:
                raise LedgerError(
                    "--semantic-evidence-output requires --include-run"
                )
            if args.include_run and args.semantic_evidence_output is None:
                raise LedgerError(
                    "--include-run requires --semantic-evidence-output"
                )

        if not args.summary and args.top is not None:
            raise LedgerError("--top requires --summary")
        if not args.summary and args.pricing_profile is not None:
            raise LedgerError("--pricing-profile requires --summary")

        if args.thread_id is not None:
            session = resolve_thread_session(args.thread_id)
        else:
            if args.session is None:
                raise LedgerError("session path is required")
            session = args.session.expanduser().resolve(strict=True)
        rows = load_rows(session)
        ledger = build_ledger(
            rows,
            session=session,
            last_runs=args.last_runs,
        )
        semantic_runs = build_semantic_runs(rows, ledger, args.include_run)
        if args.classifications is not None:
            classification_path = args.classifications.expanduser().resolve(
                strict=True
            )
            result = build_classified_summary(
                ledger,
                load_classifications(classification_path),
            )
        elif args.closure:
            result = build_closure_summary(ledger, semantic_runs)
        elif args.summary:
            if args.evidence_output is None:
                raise LedgerError("--summary requires --evidence-output")
            evidence_output = args.evidence_output.expanduser().resolve()
            if evidence_output == session:
                raise LedgerError("evidence output must not overwrite the session")
            pricing: dict[str, float | str] | None = None
            if args.pricing_profile is not None:
                pricing_path = args.pricing_profile.expanduser().resolve(strict=True)
                if evidence_output == pricing_path:
                    raise LedgerError(
                        "evidence output must not overwrite the pricing profile"
                    )
                pricing = load_pricing_profile(pricing_path)
            evidence = build_usage_evidence(rows, ledger, pricing)
            result = build_usage_summary(
                evidence,
                top_n=args.top or DEFAULT_TOP,
            )
            write_evidence(evidence_output, evidence)
        else:
            if args.evidence_output is None:
                raise LedgerError("ordinary mode requires --evidence-output")
            evidence_output = args.evidence_output.expanduser().resolve()
            if evidence_output == session:
                raise LedgerError("evidence output must not overwrite the session")
            if args.semantic_evidence_output is None:
                result = build_summary(
                    ledger,
                    evidence_output=evidence_output,
                )
                write_evidence(evidence_output, ledger)
            else:
                semantic_output = (
                    args.semantic_evidence_output.expanduser().resolve()
                )
                if semantic_output == session:
                    raise LedgerError(
                        "semantic evidence output must not overwrite the session"
                    )
                if semantic_output == evidence_output:
                    raise LedgerError(
                        "semantic evidence output must differ from evidence output"
                    )
                if not evidence_output.parent.is_dir():
                    raise LedgerError(
                        "evidence output directory does not exist: "
                        f"{evidence_output.parent}"
                    )
                if not semantic_output.parent.is_dir():
                    raise LedgerError(
                        "semantic evidence output directory does not exist: "
                        f"{semantic_output.parent}"
                    )
                semantic_evidence = build_semantic_evidence(
                    ledger,
                    args.include_run,
                    semantic_runs,
                )
                result = build_semantic_summary(ledger, semantic_evidence)
                write_evidence(evidence_output, ledger)
                write_evidence(semantic_output, semantic_evidence)
    except (LedgerError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
