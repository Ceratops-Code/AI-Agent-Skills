"""Discover and normalize producer-neutral persistent descendant threads.

Only structured tool-result records may establish lineage. The resulting
records carry identity and provenance; tool-result payloads themselves are not
added to semantic evidence by this module.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .single_surface_analysis import _content_hash

_CHILD_SESSION_ARRAY_RE = re.compile(
    r'"child_session_ids"\s*:\s*(\[[^\]]*\])', re.DOTALL
)
_THREAD_ID_RE = re.compile(r'"threadId"\s*:\s*"([^"\\]+)"')
_NATIVE_THREAD_TOOLS = frozenset({"create_thread", "fork_thread"})


def _completed_tool_call_ids(evidence: Mapping[str, Any]) -> set[str]:
    """Return raw tool-call identities retained for completed source runs."""

    model_review = evidence.get("model_review")
    records = model_review.get("records") if isinstance(model_review, Mapping) else None
    if not isinstance(records, list):
        return set()
    return {
        call_id
        for record in records
        if isinstance(record, Mapping)
        and isinstance((call_id := record.get("call_id")), str)
        and call_id
    }


def _native_thread_tool(name: Any) -> bool:
    """Recognize Codex tools whose successful result identifies a new thread."""

    if not isinstance(name, str) or not name:
        return False
    leaf = re.split(r"__|[./]", name)[-1]
    return leaf in _NATIVE_THREAD_TOOLS


def _ids_from_structured_result(
    value: Any,
    *,
    allow_native_thread_id: bool,
    depth: int = 0,
) -> list[tuple[str, str]]:
    """Extract exact child identities from one structured tool result."""

    if depth > 12:
        return []
    found: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "child_session_ids" and isinstance(item, Sequence) and not isinstance(
                item, (str, bytes)
            ):
                found.extend(
                    (session_id, "child-session-ids")
                    for session_id in item
                    if isinstance(session_id, str) and session_id
                )
            elif (
                allow_native_thread_id
                and key == "threadId"
                and isinstance(item, str)
                and item
            ):
                found.append((item, "native-thread-tool"))
            found.extend(
                _ids_from_structured_result(
                    item,
                    allow_native_thread_id=allow_native_thread_id,
                    depth=depth + 1,
                )
            )
        return found
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            found.extend(
                _ids_from_structured_result(
                    item,
                    allow_native_thread_id=allow_native_thread_id,
                    depth=depth + 1,
                )
            )
        return found
    if not isinstance(value, str) or not value:
        return found
    stripped = value.strip()
    if stripped.startswith(("{", "[")):
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, (Mapping, list)):
            found.extend(
                _ids_from_structured_result(
                    decoded,
                    allow_native_thread_id=allow_native_thread_id,
                    depth=depth + 1,
                )
            )
    for match in _CHILD_SESSION_ARRAY_RE.finditer(value):
        try:
            child_ids = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(child_ids, list):
            found.extend(
                (session_id, "child-session-ids")
                for session_id in child_ids
                if isinstance(session_id, str) and session_id
            )
    if allow_native_thread_id:
        found.extend(
            (match.group(1), "native-thread-tool")
            for match in _THREAD_ID_RE.finditer(value)
        )
    return found


def _persistent_descendant_references(
    rows: Sequence[Mapping[str, Any]],
    *,
    parent_session_id: str,
    lineage_depth: int,
    completed_call_ids: set[str],
) -> list[dict[str, Any]]:
    """Find persistent children exposed by frozen structured tool results."""

    call_tools: dict[str, str] = {}
    for row in rows:
        if row.get("type") != "response_item":
            continue
        payload = row.get("payload")
        if not isinstance(payload, Mapping):
            continue
        call_id = payload.get("call_id") or payload.get("id")
        name = payload.get("name") or payload.get("tool")
        if isinstance(call_id, str) and isinstance(name, str):
            call_tools[call_id] = name

    references: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_result(
        value: Any,
        *,
        source_call_id: str | None,
        tool_name: Any,
    ) -> None:
        if source_call_id is None or source_call_id not in completed_call_ids:
            return
        allow_native = _native_thread_tool(tool_name)
        for session_id, discovery_kind in _ids_from_structured_result(
            value,
            allow_native_thread_id=allow_native,
        ):
            if session_id in seen:
                continue
            seen.add(session_id)
            references.append(
                {
                    "session_id": session_id,
                    "parent_session_id": parent_session_id,
                    "lineage_depth": lineage_depth,
                    "source_call_id": source_call_id,
                    "discovery_kind": discovery_kind,
                }
            )

    for row in rows:
        payload = row.get("payload")
        if not isinstance(payload, Mapping):
            continue
        if row.get("type") == "response_item":
            item_type = payload.get("type")
            call_id = payload.get("call_id") or payload.get("id")
            if not isinstance(item_type, str) or not item_type.endswith("_output"):
                continue
            add_result(
                {
                    key: item
                    for key, item in payload.items()
                    if key not in {"call_id", "id", "type"}
                },
                source_call_id=call_id if isinstance(call_id, str) else None,
                tool_name=call_tools.get(call_id) if isinstance(call_id, str) else None,
            )
            continue
        if row.get("type") != "event_msg" or payload.get("type") != "mcp_tool_call_end":
            continue
        invocation = payload.get("invocation")
        call_id = payload.get("call_id")
        tool_name = (
            invocation.get("tool")
            if isinstance(invocation, Mapping)
            else call_tools.get(call_id) if isinstance(call_id, str) else None
        )
        add_result(
            payload.get("result"),
            source_call_id=call_id if isinstance(call_id, str) else None,
            tool_name=tool_name,
        )
    return references


def _session_identity(
    rows: Sequence[Mapping[str, Any]],
    *,
    fallback: str,
) -> str:
    """Return retained session metadata identity without requiring UUID syntax."""

    for row in rows:
        if row.get("type") != "session_meta":
            continue
        payload = row.get("payload")
        if not isinstance(payload, Mapping):
            continue
        value = payload.get("id") or payload.get("session_id")
        if isinstance(value, str) and value:
            return value
    return fallback


def _namespace_descendant_evidence(
    evidence: Mapping[str, Any],
    *,
    session_id: str,
    parent_session_id: str,
    lineage_depth: int,
    source_cwd: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Give one descendant session collision-free ordinary-run identities."""

    value = json.loads(json.dumps(evidence, ensure_ascii=False, default=str))
    prefix = f"thread.{hashlib.sha256(session_id.encode('utf-8')).hexdigest()[:12]}"
    turn_ids = {
        str(run["turn_id"]): f"{prefix}:{run['turn_id']}"
        for run in value.get("runs", [])
    }
    message_ids = {
        str(message["message_id"]): f"{prefix}:{message['message_id']}"
        for run in value.get("runs", [])
        for message in run.get("user_messages", [])
    }
    call_ids = {
        str(call["call_id"]): f"{prefix}:{call['call_id']}"
        for run in value.get("runs", [])
        for call in run.get("calls", [])
    }
    review_ids = {
        str(record["record_id"]): f"{prefix}:{record['record_id']}"
        for record in value.get("model_review", {}).get("records", [])
    }
    for run in value.get("runs", []):
        original_turn_id = str(run["turn_id"])
        run["turn_id"] = turn_ids[original_turn_id]
        run["source_session_id"] = session_id
        run["source_parent_session_id"] = parent_session_id
        run["source_lineage_depth"] = lineage_depth
        run["source_cwd"] = source_cwd
        for message in run.get("user_messages", []):
            message["message_id"] = message_ids[str(message["message_id"])]
        for call in run.get("calls", []):
            call["call_id"] = call_ids[str(call["call_id"])]
            call["turn_id"] = turn_ids[str(call["turn_id"])]
            call["user_message_ids"] = [
                message_ids[str(message_id)]
                for message_id in call.get("user_message_ids", [])
            ]
            call["model_review_record_ids"] = [
                review_ids[str(record_id)]
                for record_id in call.get("model_review_record_ids", [])
            ]
    model_review = value.get("model_review", {})
    for record in model_review.get("records", []):
        record["record_id"] = review_ids[str(record["record_id"])]
        if record.get("turn_id") is not None:
            record["turn_id"] = turn_ids[str(record["turn_id"])]
    model_review["global_record_ids"] = [
        review_ids[str(record_id)]
        for record_id in model_review.get("global_record_ids", [])
    ]
    model_review["call_record_ids"] = {
        turn_ids[str(turn_id)]: {
            str(index): [review_ids[str(record_id)] for record_id in record_ids]
            for index, record_ids in calls.items()
        }
        for turn_id, calls in model_review.get("call_record_ids", {}).items()
    }
    value["call_inventory"] = [
        call_ids[str(call_id)] for call_id in value.get("call_inventory", [])
    ]
    coverage = value.get("semantic_coverage", {})
    coverage["run_ids"] = [
        turn_ids[str(turn_id)] for turn_id in coverage.get("run_ids", [])
    ]
    value["thread_source"] = {
        "session_id": session_id,
        "parent_session_id": parent_session_id,
        "lineage_depth": lineage_depth,
        "source_cwd": source_cwd,
    }
    return value, turn_ids


def _merge_numeric_totals(values: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate deterministic usage totals across independently read sessions."""

    percentage_keys = {
        "input_of_total_pct",
        "cache_rate_pct",
        "output_of_total_pct",
        "reasoning_of_output_pct",
    }
    result: dict[str, Any] = {}
    for key in values[0]:
        if key in percentage_keys:
            continue
        items = [value.get(key) for value in values]
        if all(item is None for item in items):
            result[key] = None
        elif all(
            item is None
            or isinstance(item, (int, float)) and not isinstance(item, bool)
            for item in items
        ):
            result[key] = sum(item for item in items if item is not None)
        else:
            result[key] = items[0]
    input_tokens = int(result.get("input_tokens") or 0)
    cached_tokens = int(result.get("cached_input_tokens") or 0)
    output_tokens = int(result.get("output_tokens") or 0)
    reasoning_tokens = int(result.get("reasoning_output_tokens") or 0)
    total_tokens = int(result.get("total_tokens") or input_tokens + output_tokens)
    result.update(
        {
            "input_of_total_pct": round(100 * input_tokens / total_tokens, 2)
            if total_tokens
            else 0.0,
            "cache_rate_pct": round(100 * cached_tokens / input_tokens, 2)
            if input_tokens
            else 0.0,
            "output_of_total_pct": round(100 * output_tokens / total_tokens, 2)
            if total_tokens
            else 0.0,
            "reasoning_of_output_pct": round(
                100 * reasoning_tokens / output_tokens, 2
            )
            if output_tokens
            else 0.0,
        }
    )
    return result


def _merge_thread_evidence(
    primary: Mapping[str, Any],
    descendants: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Merge namespaced descendants into one ordinary frozen run inventory."""

    merged = json.loads(json.dumps(primary, ensure_ascii=False, default=str))
    if not descendants:
        return merged
    all_values = [merged, *descendants]
    merged["runs"] = [run for value in all_values for run in value.get("runs", [])]
    merged["call_inventory"] = [
        call_id for value in all_values for call_id in value.get("call_inventory", [])
    ]
    merged["collection"] = {
        key: sum(int(value.get("collection", {}).get(key) or 0) for value in all_values)
        for key in (
            "session_reads",
            "completed_runs",
            "model_calls",
            "user_messages",
            "model_review_records",
        )
    }
    merged["semantic_coverage"] = {
        "mode": "complete",
        "threshold_percent": 100,
        "run_ids": [str(run["turn_id"]) for run in merged["runs"]],
        "covered_calls": len(merged["call_inventory"]),
        "total_calls": len(merged["call_inventory"]),
        "covered_percent": 100.0,
    }
    merged["totals"] = _merge_numeric_totals(
        [value["totals"] for value in all_values]
    )
    repeated: dict[tuple[str, str], dict[str, Any]] = {}
    for value in all_values:
        for group in value.get("repeated_tool_calls", []):
            key = (str(group.get("name")), str(group.get("fingerprint")))
            if key not in repeated:
                repeated[key] = dict(group)
            else:
                repeated[key]["count"] = int(repeated[key].get("count") or 0) + int(
                    group.get("count") or 0
                )
    merged["repeated_tool_calls"] = list(repeated.values())
    reviews = [value["model_review"] for value in all_values]
    merged_review = merged["model_review"]
    merged_review["records"] = [
        record for review in reviews for record in review.get("records", [])
    ]
    merged_review["global_record_ids"] = [
        record_id
        for review in reviews
        for record_id in review.get("global_record_ids", [])
    ]
    merged_review["call_record_ids"] = {
        str(turn_id): calls
        for review in reviews
        for turn_id, calls in review.get("call_record_ids", {}).items()
    }
    canonical: dict[str, Any] = {}
    for review in reviews:
        for item in review.get("canonical_path_references", []):
            canonical.setdefault(
                json.dumps(item, sort_keys=True, separators=(",", ":")), item
            )
    merged_review["canonical_path_references"] = list(canonical.values())
    merged["source_fingerprint"] = _content_hash(
        [value.get("source_fingerprint") for value in all_values]
    )
    merged["window_fingerprint"] = _content_hash(
        [value.get("window_fingerprint") for value in all_values]
    )
    return merged


__all__ = (
    "_completed_tool_call_ids",
    "_merge_thread_evidence",
    "_namespace_descendant_evidence",
    "_persistent_descendant_references",
    "_session_identity",
)
