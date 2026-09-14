"""Bounded structured command results shared by SDLC commands and handoffs."""

from __future__ import annotations

import json
from typing import Any

STEP_RESULT_BYTES = 65536
STEP_RESULT_DEPTH = 64


def _unique_result_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous JSON members rather than silently replace receipt values."""

    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate result member.")
        value[key] = item
    return value


def capture_step_result(stdout: str, *, require_identity: bool = True) -> dict[str, Any]:
    """Retain a whole JSON receipt without forwarding logs or interpreting success.

    Successful output requires nonempty schema/status strings; a failed command
    may preserve any complete JSON object from either stream. Parsing never
    scans log fragments. Oversized output gets a
    content-free omission marker; malformed and ordinary output stay suppressed.
    Container depth is bounded so downstream checkpoint readers can decode it.
    Capture cannot turn a completed side effect into a retryable failure.
    """

    if len(stdout.encode("utf-8")) > STEP_RESULT_BYTES:
        return {"result_omitted": "stdout_limit"}
    try:
        value = json.loads(stdout, object_pairs_hook=_unique_result_object)
        if not isinstance(value, dict) or (require_identity and not all(
            isinstance(value.get(key), str) and value[key].strip()
            for key in ("schema", "status")
        )):
            return {}
        pending: list[tuple[dict[str, Any] | list[Any], int]] = [(value, 1)]
        while pending:
            container, depth = pending.pop()
            if depth > STEP_RESULT_DEPTH:
                return {}
            children = container.values() if isinstance(container, dict) else container
            pending.extend(
                (child, depth + 1)
                for child in children
                if isinstance(child, (dict, list))
            )
        # Reject non-finite numbers, including exponent overflow, at every depth.
        json.dumps(value, allow_nan=False)
    except (ValueError, RecursionError):
        return {}
    return {"result": value}
