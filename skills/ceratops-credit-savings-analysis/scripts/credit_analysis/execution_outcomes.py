"""Interpret execution outcomes at known transport boundaries.

Printed stdout, stderr, examples, and nested application data are opaque. Only
result envelopes, explicit process fields, and exact runtime failure headers
can establish execution signals. Nonzero exit codes remain observable process
results, not automatic semantic failures: predicates and handled domain results
may legitimately return nonzero. Reviews still decide whether work was wasteful.

The module performs no I/O, persists no state, and launches no model calls.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from typing import Any

PROCESS_CODE_FIELDS = frozenset(
    {"exit_code", "return_code", "returncode", "process_exit_code"}
)
TIMEOUT_FIELDS = frozenset({"timed_out", "timeout"})
TERMINATION_FIELDS = frozenset({"terminated", "termination"})
ERROR_STATUSES = frozenset({"error", "failed", "failure"})
TIMEOUT_STATUSES = frozenset({"timed_out", "timeout"})
TERMINATION_STATUSES = frozenset({"cancelled", "canceled", "killed", "terminated"})
OUTCOME_FLAGS = (
    "structured_tool_error",
    "nonzero_process_result",
    "timeout",
    "termination",
)
RESULT_TYPES = frozenset(
    {
        "function_call_output",
        "custom_tool_call_output",
        "mcp_tool_call_end",
        "patch_apply_end",
    }
)
TEXT_BLOCK_TYPES = frozenset({"text", "input_text", "output_text"})
RUNTIME_FAILURE_HEADER = re.compile(
    r"\AScript (?P<kind>failed|timed out)\r?\n"
    r"Wall time[^\r\n]*\r?\nOutput:",
    re.IGNORECASE,
)


def empty_outcomes() -> dict[str, Any]:
    """Return the collector's existing closed signal shape."""
    return {
        "structured_tool_error": False,
        "nonzero_process_result": False,
        "timeout": False,
        "termination": False,
        "structured_outcome": False,
        "process_result_observed": False,
        "process_exit_codes": [],
    }


def _output_items(value: Any, depth: int) -> Iterator[Mapping[str, Any]]:
    """Decode tool-return blocks, never strings inside a process result."""
    if depth > 24:
        return
    if isinstance(value, str):
        header = RUNTIME_FAILURE_HEADER.match(value)
        if header:
            yield {
                "status": "timeout"
                if header["kind"].casefold() == "timed out"
                else "failed",
                # The header establishes failure; retain its diagnostics for
                # the collector's bounded, redacted excerpt.
                "_runtime_header": value,
            }
            return
        try:
            decoded = json.loads(value)
        except (ValueError, RecursionError):
            return
        yield from _result_envelopes(decoded, depth + 1)
    elif isinstance(value, list):
        for item in value:
            if (
                isinstance(item, Mapping)
                and isinstance(item.get("type"), str)
                and item["type"] in TEXT_BLOCK_TYPES
            ):
                yield from _output_items(item.get("text"), depth + 1)
            else:
                yield from _result_envelopes(item, depth + 1)
    else:
        yield from _result_envelopes(value, depth + 1)


def _result_envelopes(value: Any, depth: int = 0) -> Iterator[Mapping[str, Any]]:
    """Follow supported result wrappers; arbitrary mapping keys are never walked."""
    if depth > 24:
        return
    if isinstance(value, list):
        for item in value:
            yield from _result_envelopes(item, depth + 1)
        return
    if not isinstance(value, Mapping):
        return
    kind = value.get("type")
    if not isinstance(kind, str):
        kind = None
    if kind in {"response_item", "event_msg"}:
        payload = value.get("payload")
        if (
            isinstance(payload, Mapping)
            and isinstance(payload.get("type"), str)
            and payload["type"] in RESULT_TYPES
        ):
            yield from _result_envelopes(payload, depth + 1)
        return
    if kind == "mcp_tool_call_end":
        result = value.get("result")
        if isinstance(result, Mapping):
            if "Err" in result:
                yield {"isError": True, "error": result["Err"]}
            elif isinstance(result.get("Ok"), Mapping):
                yield from _result_envelopes(result["Ok"], depth + 1)
        return
    if kind == "patch_apply_end":
        yield value
        return
    if kind in {"function_call_output", "custom_tool_call_output"}:
        yield value
        yield from _output_items(value.get("output"), depth + 1)
        return
    # Desktop history stores output blocks under a ctco identity without type.
    if str(value.get("id", "")).startswith("ctco_") and "output" in value:
        yield value
        yield from _output_items(value["output"], depth + 1)
        return
    if "structured_outcome" in value and isinstance(
        value["structured_outcome"], Mapping
    ):
        yield from _result_envelopes(value["structured_outcome"], depth + 1)
        return
    # Canonical collector records carry flags and codes separately from content.
    if isinstance(value.get("outcomes"), Mapping):
        yield {
            **value["outcomes"],
            "process_exit_codes": value.get("process_exit_codes", []),
            "process_result_observed": value.get("process_result_observed", False),
        }
        return
    # Promise.allSettled and the indexed wrappers emitted by functions.exec.
    if value.get("status") == "fulfilled" and "value" in value:
        yield from _result_envelopes(value["value"], depth + 1)
        return
    if value.get("status") == "rejected" and "reason" in value:
        yield {"isError": True, "error": value["reason"]}
        return
    if ("i" in value or "label" in value) and "r" in value:
        yield from _result_envelopes(value["r"], depth + 1)
        return
    if value.get("schema") == "ceratops-command-probe-result.v1":
        # The probe's own success verdict includes legitimate predicate exit 1.
        yield {"success": value.get("ok")}
        return
    if "Ok" in value or "Err" in value:
        if "Err" in value:
            yield {"isError": True, "error": value["Err"]}
        else:
            yield from _result_envelopes(value["Ok"], depth + 1)
        return
    keys = {str(key).casefold() for key in value}
    markers = (
        PROCESS_CODE_FIELDS
        | TIMEOUT_FIELDS
        | TERMINATION_FIELDS
        | {
            "iserror",
            "is_error",
            "success",
            "status",
            "process_exit_codes",
            "structured_tool_error",
            "nonzero_process_result",
            "explicit_failure",
            "structuredcontent",
        }
    )
    if keys & markers:
        yield value
        # MCP structuredContent is an explicitly designated result envelope.
        # Its content blocks and a process's output/stdout/stderr stay opaque.
        if isinstance(value.get("structuredContent"), (Mapping, list)):
            yield from _result_envelopes(value["structuredContent"], depth + 1)


def _envelope_outcomes(value: Mapping[str, Any]) -> dict[str, Any]:
    signals = empty_outcomes()
    fields = {str(key).casefold(): item for key, item in value.items()}
    for key in PROCESS_CODE_FIELDS:
        code = fields.get(key)
        if isinstance(code, int) and not isinstance(code, bool):
            signals["process_exit_codes"].append(code)
    codes = fields.get("process_exit_codes")
    if isinstance(codes, list):
        signals["process_exit_codes"].extend(
            code
            for code in codes
            if isinstance(code, int) and not isinstance(code, bool)
        )
    if signals["process_exit_codes"]:
        signals["process_result_observed"] = True
        signals["structured_outcome"] = True
        signals["nonzero_process_result"] = any(
            code != 0 for code in signals["process_exit_codes"]
        )
    for key in OUTCOME_FLAGS:
        if isinstance(fields.get(key), bool):
            signals[key] |= fields[key]
            signals["structured_outcome"] = True
    for key in ("iserror", "is_error", "explicit_failure"):
        if isinstance(fields.get(key), bool):
            signals["structured_tool_error"] |= fields[key]
            signals["structured_outcome"] = True
    if isinstance(fields.get("success"), bool):
        signals["structured_tool_error"] |= not fields["success"]
        signals["structured_outcome"] = True
    for key in TIMEOUT_FIELDS:
        if isinstance(fields.get(key), bool):
            signals["timeout"] |= fields[key]
            signals["structured_outcome"] = True
    for key in TERMINATION_FIELDS:
        if isinstance(fields.get(key), bool):
            signals["termination"] |= fields[key]
            signals["structured_outcome"] = True
    status = fields.get("status")
    if isinstance(status, str):
        status = status.casefold()
        if status in ERROR_STATUSES | TIMEOUT_STATUSES | TERMINATION_STATUSES:
            signals["structured_tool_error"] |= status in ERROR_STATUSES
            signals["timeout"] |= status in TIMEOUT_STATUSES
            signals["termination"] |= status in TERMINATION_STATUSES
            signals["structured_outcome"] = True
    if "_runtime_header" in value:
        signals["structured_outcome"] = False
    return signals


def merge_outcomes(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    """Merge multiple result events without changing their process-code history."""
    for field in empty_outcomes():
        value = source.get(field)
        if field == "process_exit_codes":
            target[field].extend(value or [])
        else:
            target[field] = bool(target.get(field)) or bool(value)


def response_outcomes(payload: Any) -> dict[str, Any]:
    """Collect facts only at supported result boundaries."""
    signals = empty_outcomes()
    for envelope in _result_envelopes(payload):
        merge_outcomes(signals, _envelope_outcomes(envelope))
    return signals


def has_failure_telemetry(value: Any) -> bool:
    """Require a tool error, timeout, or termination rather than printed content."""
    signals = response_outcomes(value)
    return bool(
        signals["structured_tool_error"] or signals["timeout"] or signals["termination"]
    )


def has_nonzero_process_result(value: Any) -> bool:
    """Keep nonzero process results reviewable without declaring semantic failure."""
    return bool(response_outcomes(value)["nonzero_process_result"])


def structured_outcome(value: Any) -> dict[str, Any] | None:
    """Project the same normalized facts into retained model-input evidence."""
    signals = response_outcomes(value)
    if not (
        signals["structured_outcome"]
        or signals["process_result_observed"]
        or has_failure_telemetry(value)
    ):
        return None
    return {
        "outcomes": {key: signals[key] for key in OUTCOME_FLAGS},
        "process_exit_codes": list(dict.fromkeys(signals["process_exit_codes"])),
    }


def failure_details(value: Any) -> list[str]:
    """Select diagnostic text only from the result that actually reports failure."""
    details = []
    for envelope in _result_envelopes(value):
        signals = _envelope_outcomes(envelope)
        if not (
            signals["structured_tool_error"]
            or signals["timeout"]
            or signals["termination"]
            or signals["nonzero_process_result"]
        ):
            continue
        selected = []
        for key in ("_runtime_header", "error", "stderr"):
            detail = envelope.get(key)
            if isinstance(detail, str) and detail.strip():
                selected.append(detail)
        if not selected:
            if signals["timeout"]:
                selected.append("Command timed out")
            elif signals["termination"]:
                selected.append("Command terminated")
            elif signals["structured_tool_error"]:
                selected.append("Tool reported failure")
            else:
                selected.append(
                    "Process exit code: "
                    + str(
                        next(
                            code for code in signals["process_exit_codes"] if code != 0
                        )
                    )
                )
        details.extend(selected)
    return details


def failure_family(reason: str, action: Mapping[str, Any]) -> tuple[str | None, bool]:
    """Describe established failure; diagnostic wording cannot establish one."""
    failed = bool(
        action["structured_tool_error"] or action["timeout"] or action["termination"]
    )
    if not failed:
        code = next((code for code in action["process_exit_codes"] if code != 0), None)
        return (f"exit_code_{code}", False) if code is not None else (None, False)
    direct = reason.casefold()
    if "pretooluse" in direct and "reject" in direct:
        return "pre_tool_use_rejection", True
    families = (
        ("empty pipe element", "powershell_empty_pipe"),
        ("convertfrom-json", "powershell_json_parse"),
        ("invalid json primitive", "powershell_json_parse"),
        ("unicodeencodeerror", "python_output_encoding"),
        ("missing required system tool", "missing_system_tool"),
        ("selection must produce exactly one", "ambiguous_selection"),
        ("the following arguments are required", "missing_cli_argument"),
    )
    for marker, family in families:
        if marker in direct:
            return family, True
    if "windows-shell-sanity.py" in direct and any(
        marker in direct
        for marker in (
            "foreach_pipeline",
            "select_object_",
            "json_pipeline_contract",
            "python_non_ascii_output",
            "blocking_count",
        )
    ):
        return "windows_shell_sanity_block", True
    if "tool" in direct and "rejected" in direct:
        return "tool_rejected", True
    if action["timeout"]:
        return "command_timeout", True
    if action["termination"]:
        return "termination", True
    return "structured_tool_error", True
