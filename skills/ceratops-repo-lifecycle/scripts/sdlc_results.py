"""Bounded structured command results shared by SDLC commands and handoffs."""

from __future__ import annotations

import json
import pathlib
from functools import lru_cache
from typing import Any

import jsonschema

STEP_RESULT_BYTES = 65536
STEP_RESULT_DEPTH = 64
OPERATION_RESULT_SCHEMA = (
    pathlib.Path(__file__).resolve().parents[1]
    / "references"
    / "schemas"
    / "operation-result.v1.schema.json"
)


class StepResultError(ValueError):
    """A declared operation result is missing or violates its contract."""


def _unique_result_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous JSON members rather than silently replace receipt values."""

    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate result member.")
        value[key] = item
    return value


@lru_cache(maxsize=1)
def _operation_result_validator() -> jsonschema.Draft202012Validator:
    """Load the installed canonical operation-result schema once per process."""

    try:
        schema = json.loads(OPERATION_RESULT_SCHEMA.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        jsonschema.SchemaError,
    ) as exc:
        raise StepResultError(f"Operation-result schema is invalid: {exc}") from exc
    return jsonschema.Draft202012Validator(schema)


def _raise_required(message: str, expected_schema: str | None) -> None:
    if expected_schema is not None:
        raise StepResultError(message)


def capture_step_result(
    stdout: str,
    *,
    require_identity: bool = True,
    expected_schema: str | None = None,
    expected_stage: str | None = None,
) -> dict[str, Any]:
    """Retain a whole JSON receipt without forwarding logs or interpreting success.

    Successful output requires nonempty schema/status strings; a failed command
    may preserve any complete JSON object from either stream. Parsing never
    scans log fragments. Oversized output gets a
    content-free omission marker; malformed and ordinary output stay suppressed.
    Container depth is bounded so downstream checkpoint readers can decode it.
    When an SDLC action declares ``result-schema``, malformed or absent output
    raises ``StepResultError``. The caller must retain command completion and
    must not replay a side effect merely to recover its result.
    """

    if len(stdout.encode("utf-8")) > STEP_RESULT_BYTES:
        _raise_required("Required operation result exceeds the stdout limit.", expected_schema)
        return {"result_omitted": "stdout_limit"}
    try:
        value = json.loads(stdout, object_pairs_hook=_unique_result_object)
        if not isinstance(value, dict) or (require_identity and not all(
            isinstance(value.get(key), str) and value[key].strip()
            for key in ("schema", "status")
        )):
            _raise_required("Required operation result is not one complete JSON object.", expected_schema)
            return {}
        pending: list[tuple[dict[str, Any] | list[Any], int]] = [(value, 1)]
        while pending:
            container, depth = pending.pop()
            if depth > STEP_RESULT_DEPTH:
                _raise_required("Required operation result exceeds the nesting limit.", expected_schema)
                return {}
            children = container.values() if isinstance(container, dict) else container
            pending.extend(
                (child, depth + 1)
                for child in children
                if isinstance(child, (dict, list))
            )
        # Reject non-finite numbers, including exponent overflow, at every depth.
        json.dumps(value, allow_nan=False)
    except StepResultError:
        raise
    except (ValueError, RecursionError) as exc:
        _raise_required(f"Required operation result is invalid JSON: {exc}", expected_schema)
        return {}
    if expected_schema is not None:
        errors = list(_operation_result_validator().iter_errors(value))
        if errors:
            error = jsonschema.exceptions.best_match(errors) or errors[0]
            location = ".".join(str(part) for part in error.absolute_path)
            suffix = f" at {location}" if location else ""
            raise StepResultError(
                f"Required operation result violates the canonical schema{suffix}: "
                f"{error.message}"[:1024]
            )
        if value.get("schema") != expected_schema:
            raise StepResultError(
                "Required operation result schema differs from the SDLC declaration."
            )
        if expected_stage is not None and value.get("stage") != expected_stage:
            raise StepResultError(
                "Required repository-stage result differs from the selected SDLC stage."
            )
        if value.get("status") != "passed":
            raise StepResultError(
                "A successful SDLC command must emit a passed terminal result."
            )
    return {"result": value}
