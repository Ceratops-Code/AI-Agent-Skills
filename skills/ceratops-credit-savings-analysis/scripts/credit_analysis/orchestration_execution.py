"""Finite reviewer queue, corrective attempts, and single-owner checkpoints.

Workers invoke already prepared children and retain attempt artifacts. Only the
calling controller validates responses and mutates orchestration state.
"""
from __future__ import annotations

import concurrent.futures
import copy
import json
import pathlib
from typing import Any, Mapping

from . import luna_sol_analysis as analysis
from .model_response_contract import (
    apply_response_correction,
    correction_response_schema,
    project_response_correction,
    response_correction_scope,
)
from .single_thread_analysis import CreditAnalysisError


def _order_omissions(state: dict[str, Any]) -> None:
    order = {task_id: index for index, task_id in enumerate(state["task_order"])}
    state["omissions"].sort(key=lambda item: order.get(item.get("task_id"), -1))


def _checkpoint_state(state: dict[str, Any]) -> None:
    """Publish only from the controller; preserve manifest presentation order."""
    _order_omissions(state)
    analysis._holistic_sync_child_lineage(state)
    analysis._holistic_save_state(state)


def _schema_rejection(attempt: Mapping[str, Any]) -> str | None:
    """Read permanent API schema failures from retained, integrity-bound events.

    CLI startup diagnostics may hide the actual API error. Only error events with
    the provider's exact code stop the batch; ordinary model failures retain their
    existing handling. Reusing this check on resume prevents a paid retry against
    the same rejected request. Already running siblings still finish and checkpoint.
    """
    artifact = attempt.get("artifacts", {}).get("events")
    if not isinstance(artifact, Mapping):
        return None
    path = pathlib.Path(str(artifact["path"]))
    if path.is_symlink() or not path.is_file() or analysis._file_hash(path) != artifact["sha256"]:
        raise CreditAnalysisError("failed attempt events changed")
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, Mapping) or event.get("type") not in {"error", "turn.failed"}:
                continue
            detail = event.get("error", event)
            if not isinstance(detail, Mapping):
                continue
            message = detail.get("message")
            if isinstance(message, str):
                try:
                    decoded = json.loads(message)
                except json.JSONDecodeError:
                    decoded = None
                if isinstance(decoded, Mapping):
                    detail = decoded
            detail = detail.get("error", detail)
            if isinstance(detail, Mapping) and detail.get("code") == "invalid_json_schema":
                return (
                    "API rejected response schema (invalid_json_schema): "
                    + str(detail.get("message") or "schema is unsupported")
                    + "; repair the schema and start a new analysis"
                )
    return None


def _prior_rejection(
    state: Mapping[str, Any], task: Mapping[str, Any], input_sha: str,
    *, oldest: bool = False,
) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    """Resolve the newest retained rejection for this exact immutable input."""
    attempts = state["execution"][task["task_id"]]["attempts"]
    for attempt in attempts if oldest else reversed(attempts):
        if attempt.get("outcome") != "validation-error" or attempt.get("input_sha256") != input_sha:
            continue
        artifact = attempt.get("artifacts", {}).get("raw_output")
        if not isinstance(artifact, Mapping):
            raise CreditAnalysisError("corrective retry has no retained prior response")
        path = pathlib.Path(str(artifact["path"]))
        if path.is_symlink() or not path.is_file() or analysis._file_hash(path) != artifact["sha256"]:
            raise CreditAnalysisError("corrective retry prior response changed")
        if not isinstance(attempt.get("error"), str) or not attempt["error"]:
            raise CreditAnalysisError("corrective retry has no exact validation error")
        return attempt, analysis._read_json(path, "corrective retry prior response")
    return None


def _current_response_schema(
    state: Mapping[str, Any], task: Mapping[str, Any], digest: str,
) -> dict[str, Any]:
    """Bind today's structural enforcement to the run's frozen contract and aliases."""
    contract = analysis._read_json(
        pathlib.Path(state["immutable_artifacts"]["surface_contract"]["path"]),
        "frozen response contract",
    )
    if task["phase"] in {"luna-discovery", "sol-direct-evidence"}:
        return analysis._holistic_luna_schema(
            state=state, task=task, input_sha256=digest, contract=contract,
        )
    aliases = analysis._holistic_read_sol_aliases(task, digest)
    return analysis._holistic_sol_schema(
        state=state, task=task, input_sha256=digest, contract=contract,
        luna_candidate_ids=list(aliases["aliases"]["luna_candidates"].values()),
        alias_record=aliases,
    )


def _corrective_prompt(
    *, state: Mapping[str, Any], task: dict[str, Any], input_sha: str,
    prompt_path: pathlib.Path, schema_path: pathlib.Path, attempt_number: int,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Retain complete feedback without trimming evidence or expanding call limits.

    The controller retains retry prompts with immutable attempt evidence until
    the caller removes the analysis root, including across interrupted runs.
    A request that cannot fit the proven byte envelope stops before child launch.
    """
    rejected = _prior_rejection(state, task, input_sha, oldest=True)
    if rejected is None:
        return prompt_path, schema_path
    attempt, prior = rejected
    instructions = (
        "Correct the retained response against the supplied output schema and exact "
        "validation errors. Preserve the complete admitted call/candidate coverage, "
        "evidence references, accepted sibling results, and every unaffected judgment. "
        "Keep valid identifiers unchanged; repair an invalid finding identifier and all "
        "its references consistently without changing the finding. Only the diagnosed "
        "invalid_recurrence_finding_ids may have recurrence inputs and assumptions "
        "reconsidered against the same supplied evidence. For diagnosed "
        "conflicting_call_finding_ids, reconsider only their conflicting call "
        "judgments against that evidence or withdraw the inconsistent finding; "
        "preserve calls supported by unaffected findings. Correct a supported estimate "
        "or withdraw the unsupported finding, remove its dependent links, and explain "
        "the withdrawal in its retained candidate decision. Keep linked existing risks. "
        "Retain temporary-control reviews with a null finding_id and explicit "
        "no_finding_reason; remove only merges for withdrawn findings. Leave affected "
        "calls unassessed when no retained finding supports their avoidability. "
        "Preserve every other finding, estimate and call judgment. Do not invent "
        "savings to pass validation. Return only the permitted edits in the correction "
        "schema; the controller copies every protected field from the retained response. "
        "A withdrawal reason is copied to its dependent decisions and reviews; the "
        "controller removes its links and marks unsupported orphan calls unassessed."
    )
    if task["phase"] == "luna-discovery":
        task["output_byte_limit"] = max(1_000, int(task["output_byte_limit"]) * 9 // 10)
        instructions += f" Keep the complete result within {task['output_byte_limit']} UTF-8 bytes."
    response_schema = _current_response_schema(state, task, input_sha)
    schema = correction_response_schema(prior, response_schema)
    feedback = {"instructions": instructions, "prior_attempt": attempt["attempt_number"],
                "validation_errors": [attempt["error"]], "prior_response": prior,
                "correction_scope": response_correction_scope(prior, response_schema)}
    latest = _prior_rejection(state, task, input_sha)
    if latest is not None and latest[0]["attempt_number"] != attempt["attempt_number"]:
        feedback["rejected_response"] = latest[1]
        feedback["validation_errors"] = [latest[0]["error"]]
    prompt = prompt_path.read_text(encoding="utf-8") + "\nCorrection request:\n" + json.dumps(
        feedback, ensure_ascii=False, separators=(",", ":"),
    ) + "\n"
    role = analysis._holistic_role(task)
    size = len(prompt.encode("utf-8")) + analysis._json_bytes(schema)
    if size > int(state["model_specs"][role]["input_byte_budget"]):
        raise CreditAnalysisError("corrective retry exceeds its proven UTF-8 byte envelope; retained response was not truncated")
    target = prompt_path.with_name(f"{prompt_path.stem}.retry-{attempt_number:03d}{prompt_path.suffix}")
    if schema != analysis._read_json(schema_path, "frozen response schema"):
        schema_path = schema_path.with_name(f"{schema_path.stem}.retry-{attempt_number:03d}{schema_path.suffix}")
        analysis._write_or_verify_json(schema_path, schema, "corrective response schema")
    analysis._write_or_verify_text(target, prompt, "corrective retry prompt")
    return target, schema_path


def _corrected_response(
    state: Mapping[str, Any], task: Mapping[str, Any], digest: str,
    raw: Mapping[str, Any], attempt: Mapping[str, Any], *, retained: bool = False,
) -> Mapping[str, Any]:
    """Reconstruct edits before validation or size checks, without changing evidence.

    A frozen full-response retry can be projected only during retained recovery,
    after checking its original schema and output artifacts. Newly invoked retries
    must use the edit contract. The first rejection always owns protected values.
    """
    rejected = _prior_rejection(state, task, digest, oldest=True)
    result = raw
    if rejected is not None and attempt["attempt_number"] != rejected[0]["attempt_number"]:
        _, prior = rejected
        response_schema = _current_response_schema(state, task, digest)
        if retained:
            values = {}
            for name in ("schema", "raw_output"):
                artifact = attempt["artifacts"][name]
                path = pathlib.Path(artifact["path"])
                if path.is_symlink() or not path.is_file() or analysis._file_hash(path) != artifact["sha256"]:
                    raise CreditAnalysisError(f"retained corrective {name} changed")
                values[name] = analysis._read_json(path, f"retained corrective {name}")
            if values["raw_output"] != raw:
                raise CreditAnalysisError("retained corrective response does not match its attempt")
            if "baseline_sha256" not in values["schema"].get("properties", {}):
                result = project_response_correction(prior, raw, correction_response_schema(prior, response_schema))
        result = apply_response_correction(prior, result, response_schema)
    if (task["phase"] == "luna-discovery" and analysis._json_bytes(result)
            > int(attempt.get("output_byte_limit") or task["output_byte_limit"])):
        raise CreditAnalysisError("Luna result exceeds its output byte target")
    return result


def _diagnosed_luna_retry(error: CreditAnalysisError) -> bool:
    """Retry only a concrete result-size or output-contract failure."""

    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "byte target",
            "schema",
            "fields are invalid",
            "identity changed",
            "coverage attestation",
            "invalid type",
            "must be an",
            "must be text",
            "must be numeric",
            "must be boolean",
            "outside the frozen contract",
            "too many items",
            "too few items",
        )
    )


def _holistic_model_attempt(
    *,
    runner: Any | None,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    payload: Mapping[str, Any],
    input_sha: str,
    prompt_path: pathlib.Path,
    schema_path: pathlib.Path,
    attempt_number: int,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Invoke one already-prepared task; callers own durable state updates."""

    role = analysis._holistic_role(task)
    model = str(state["model_specs"][role]["model"])
    effort = str(state["model_specs"][role]["reasoning_effort"])
    runtime_task = {**task, "reasoning_effort": effort}
    prompt_path, schema_path = _corrective_prompt(
        state=state,
        task=runtime_task,
        input_sha=input_sha,
        prompt_path=prompt_path,
        schema_path=schema_path,
        attempt_number=attempt_number,
    )
    attempt_dir = (
        pathlib.Path(str(task["artifacts"]["attempts"]))
        / f"attempt-{attempt_number:03d}"
    )
    if runner is None:
        raw, attempt = analysis._run_codex_child(
            analysis_id=str(state["analysis_id"]),
            model=model,
            reasoning_effort=effort,
            task=runtime_task,
            prompt_path=prompt_path,
            schema_path=schema_path,
            attempt_dir=attempt_dir,
            execution_cwd=pathlib.Path(str(task["execution_cwd"])),
        )
    else:
        raw, attempt = analysis._invoke_injected_runner(
            runner,
            model=model,
            task=runtime_task,
            prompt_path=prompt_path,
            schema_path=schema_path,
            input_payload=payload,
            input_sha256=input_sha,
            attempt_dir=attempt_dir,
        )
    return raw, {
        **attempt,
        "reasoning_effort": effort,
        "output_byte_limit": runtime_task.get("output_byte_limit"),
    }


def _omit_luna_task(
    state: dict[str, Any],
    task: Mapping[str, Any],
    *,
    reason: str,
    error: str | None = None,
) -> None:
    execution = state["execution"][task["task_id"]]
    execution["status"] = "omitted"
    output_bytes = 0
    for attempt in reversed(execution["attempts"]):
        raw_artifact = attempt.get("artifacts", {}).get("raw_output")
        if not isinstance(raw_artifact, Mapping):
            continue
        raw_path = pathlib.Path(str(raw_artifact.get("path")))
        if raw_path.is_file() and not raw_path.is_symlink():
            output_bytes = raw_path.stat().st_size
            break
    omission = {
        "stage": "luna",
        "reason": reason,
        "task_id": task["task_id"],
        "turn_id": task["turn_id"],
        "run_window_ordinal": task["run_window_ordinal"],
        "run_window_count": task["run_window_count"],
        "candidate_ids": list(task["candidate_ids"]),
        "record_count": len(task["candidate_ids"]),
        "candidate_count": len(task["candidate_ids"]),
        "evidence_bytes": int(task["evidence_bytes"]),
        "input_bytes": int(task["input_bytes"]),
        "output_bytes": output_bytes,
    }
    if error:
        omission["error"] = error
    if not any(
        item.get("task_id") == task["task_id"]
        for item in state["omissions"]
        if isinstance(item, Mapping)
    ):
        state["omissions"].append(omission)
        _order_omissions(state)


def _omit_sol_task(
    state: dict[str, Any],
    task: Mapping[str, Any],
    *,
    reason: str,
    error: str | None = None,
) -> None:
    """Retain exact inventory for one non-final Sol task that cannot be accepted."""

    if task["phase"] == "sol-final":
        raise CreditAnalysisError("the final Sol result cannot be omitted")
    execution = state["execution"][task["task_id"]]
    execution["status"] = "omitted"
    output_bytes = 0
    for attempt in reversed(execution["attempts"]):
        raw_artifact = attempt.get("artifacts", {}).get("raw_output")
        if not isinstance(raw_artifact, Mapping):
            continue
        raw_path = pathlib.Path(str(raw_artifact.get("path")))
        if raw_path.is_file() and not raw_path.is_symlink():
            output_bytes = raw_path.stat().st_size
            break
    source_record_ids = list(task.get("candidate_ids", []))
    candidate_ids = list(
        task.get("luna_candidate_ids", source_record_ids)
    )
    call_ids = list(task.get("call_ids", []))
    if not call_ids:
        call_ids = list(
            dict.fromkeys(
                call_id
                for window in task.get("audit_windows", [])
                for call_id in window.get("call_ids", [])
            )
        )
    input_path = pathlib.Path(str(task["artifacts"]["input"]))
    input_bytes = (
        input_path.stat().st_size
        if input_path.is_file() and not input_path.is_symlink()
        else 0
    )
    omission: dict[str, Any] = {
        "stage": task["phase"],
        "reason": reason,
        "task_id": task["task_id"],
        "turn_ids": list(task.get("turn_ids", [])),
        "candidate_ids": candidate_ids,
        "source_record_ids": source_record_ids,
        "call_ids": call_ids,
        "record_count": len(source_record_ids),
        "candidate_count": len(candidate_ids),
        "evidence_bytes": int(task.get("routing_bytes") or input_bytes),
        "input_bytes": input_bytes,
        "output_bytes": output_bytes,
        "attempt_count": len(execution["attempts"]),
    }
    if error:
        omission["error"] = error
    if not any(
        item.get("task_id") == task["task_id"]
        for item in state["omissions"]
        if isinstance(item, Mapping)
    ):
        state["omissions"].append(omission)
        _order_omissions(state)


def _consume_attempt(
    future: Any,
    completed_item: tuple[Any, ...],
    *,
    state: dict[str, Any],
    contract: Mapping[str, Any],
    compact: Mapping[str, Any],
    luna_attempt_limit: int,
) -> int:
    """Validate and publish one finished worker on the controller thread."""

    task, _, digest, prompt_path, schema_path, candidate_ids, attempt_number = completed_item
    raw, attempt = future.result()
    attempt = analysis._bind_attempt_record(
        attempt,
        state=state,
        task=task,
        input_sha256=digest,
        attempt_number=attempt_number,
    )
    role = analysis._holistic_role(task)
    if attempt["model_invoked"]:
        state["model_attempts"][role] += 1
    execution = state["execution"][task["task_id"]]
    if raw is None:
        schema_error = _schema_rejection(attempt)
        if schema_error is not None:
            attempt["error"] = schema_error
        execution["attempts"].append(
            {**attempt, "outcome": "runner-error"}
        )
        if schema_error is not None:
            raise CreditAnalysisError(schema_error)
        if task["phase"] == "luna-discovery":
            _omit_luna_task(
                state,
                task,
                reason="luna-runner-error",
                error=str(attempt.get("error") or "no result"),
            )
            return 1
        analysis._holistic_sync_child_lineage(state)
        analysis._holistic_save_state(state)
        raise CreditAnalysisError(
                str(
                    attempt.get("error")
                    or "model task produced no result"
                )
        )
    try:
        raw = _corrected_response(state, task, digest, raw, attempt)
        validated = analysis._validate_holistic_task_result(
            raw,
            state=state,
            task=task,
            input_sha256=digest,
            contract=contract,
            compact=compact,
            luna_candidate_ids=candidate_ids,
        )
    except CreditAnalysisError as error:
        execution["attempts"].append(
            {
                **attempt,
                "outcome": "validation-error",
                "error": str(error),
            }
        )
        can_retry_luna = (
            task["phase"] == "luna-discovery"
            and _diagnosed_luna_retry(error)
            and len(execution["attempts"]) == 1
            and state["model_attempts"]["luna"] < luna_attempt_limit
        )
        can_retry_sol = (
            task["phase"].startswith("sol-")
            and analysis._can_retry_sol_validation(
                state, contract, task
            )
        )
        if can_retry_luna or can_retry_sol:
            return 0
        if task["phase"] == "luna-discovery":
            _omit_luna_task(
                state,
                task,
                reason="luna-invalid-output",
                error=str(error),
            )
            return 1
        if task["phase"] != "sol-final":
            _omit_sol_task(
                state,
                task,
                reason="sol-invalid-output",
                error=str(error),
            )
            return 1
        analysis._holistic_sync_child_lineage(state)
        analysis._holistic_save_state(state)
        raise
    analysis._holistic_accept_result(
        state=state,
        task=task,
        validated=validated,
        input_sha256=digest,
        prompt_path=prompt_path,
        schema_path=schema_path,
        attempt=attempt,
        recovered=False,
    )
    return 1


def command_execute_orchestration(
    state_path: pathlib.Path,
    *,
    runner: Any | None = None,
    available_models: set[str] | Mapping[str, Mapping[str, Any]] | None = None,
    task_limit: int | None = None,
    expected_request_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Execute run parts and independent Sol stages with bounded concurrency."""

    state, evidence, contract, compact = analysis._holistic_read_state(state_path)
    if expected_request_path is not None:
        expected_request = expected_request_path.expanduser().resolve(strict=True)
        planned_request = pathlib.Path(
            str(state["immutable_artifacts"]["request"]["path"])
        ).resolve(strict=True)
        if planned_request != expected_request:
            raise CreditAnalysisError(
                "request does not own the existing orchestration state"
            )
    for execution in state["execution"].values():
        for attempt in execution["attempts"]:
            if attempt.get("outcome") == "runner-error":
                schema_error = _schema_rejection(attempt)
                if schema_error is not None:
                    raise CreditAnalysisError(schema_error)
    if state["phase"] == "complete":
        return analysis._holistic_public_status(state)
    catalog = (
        available_models
        if available_models is not None
        else (
            runner.available_models
            if runner is not None and hasattr(runner, "available_models")
            else analysis._codex_model_catalog()
        )
    )
    current_specs = analysis._holistic_model_specs(contract, catalog)
    for role in ("luna", "sol"):
        planned = state["model_specs"][role]
        current = current_specs[role]
        if (
            current["model"] != planned["model"]
            or current["reasoning_effort"] != planned["reasoning_effort"]
            or current["effective_context_tokens"]
            < planned["effective_context_tokens"]
        ):
            raise CreditAnalysisError(
                f"{role} model capability changed after planning"
            )
    if task_limit is not None and (
        not isinstance(task_limit, int)
        or isinstance(task_limit, bool)
        or task_limit < 0
    ):
        raise CreditAnalysisError("task_limit must be a nonnegative integer")

    tasks = analysis._holistic_task_map(state["manifest"])
    task_budget = task_limit
    progressed = 0
    luna_attempt_limit = int(
        contract["semantic_call_contract"]["luna_max_attempts"]
    )
    sol_retry_limit = int(
        contract["semantic_call_contract"][
            "sol_max_validation_retries_per_task"
        ]
    )
    state["phase"] = "executing"
    analysis._holistic_save_state(state)

    while True:
        luna_tasks = state["manifest"]["luna_tasks"]
        pending_luna = [
            task
            for task in luna_tasks
            if state["execution"][task["task_id"]]["status"] == "pending"
        ]
        remaining_attempts = luna_attempt_limit - int(
            state["model_attempts"]["luna"]
        )
        if remaining_attempts <= 0:
            for task in pending_luna:
                _omit_luna_task(state, task, reason="luna-attempt-cap")
            pending_luna = []
            analysis._holistic_save_state(state)

        luna_terminal = all(
            state["execution"][task["task_id"]]["status"]
            in {"complete", "omitted"}
            for task in luna_tasks
        )
        if luna_terminal and state.get("routing") is None:
            analysis._freeze_sol_routing(state, compact, contract)
            tasks = analysis._holistic_task_map(state["manifest"])

        sol_omission_changed = False
        for base_task in state["manifest"]["sol_tasks"]:
            execution = state["execution"][base_task["task_id"]]
            if execution["status"] != "pending":
                continue
            rejected = analysis._sol_validation_error_count(execution)
            if not rejected:
                continue
            task = analysis._holistic_runtime_task(state, base_task)
            if task["phase"] == "sol-final":
                # Revalidate frozen output before enforcing limits on new calls.
                continue
            if rejected > sol_retry_limit:
                _omit_sol_task(
                    state,
                    task,
                    reason="sol-invalid-output",
                    error=str(execution["attempts"][-1].get("error") or "invalid result"),
                )
                progressed += 1
                sol_omission_changed = True
                continue
        if sol_omission_changed:
            analysis._holistic_save_state(state)

        if state.get("routing") is not None:
            analysis._freeze_focused_review(state, compact, contract)

        ready: list[dict[str, Any]] = []
        for task_id in state["task_order"]:
            execution = state["execution"][task_id]
            if execution["status"] != "pending":
                continue
            base_task = tasks[task_id]
            if any(
                state["execution"][dependency]["status"]
                not in {"complete", "skipped", "omitted"}
                for dependency in base_task["dependencies"]
            ):
                continue
            if base_task["phase"].startswith("sol-") and state.get("routing") is None:
                continue
            ready.append(analysis._holistic_runtime_task(state, base_task))

        if not ready:
            break
        phase = ready[0]["phase"]
        if phase == "luna-discovery":
            ready = [task for task in ready if task["phase"] == phase]
            concurrency = int(
                contract["semantic_call_contract"]["luna_max_concurrency"]
            )
            ready = ready[: min(concurrency, max(0, remaining_attempts))]
        elif phase in {"sol-adjudication", "sol-direct-evidence"}:
            ready = [
                task
                for task in ready
                if task["phase"] in {"sol-adjudication", "sol-direct-evidence"}
            ]
            concurrency = len(ready)
        else:
            ready = [ready[0]]
            concurrency = 1
        if task_budget is not None:
            remaining_tasks = task_budget - progressed
            if remaining_tasks <= 0:
                break
            ready = ready[:remaining_tasks]
        if not ready:
            break

        prepared: list[
            tuple[
                dict[str, Any],
                dict[str, Any],
                str,
                pathlib.Path,
                pathlib.Path,
                list[str],
            ]
        ] = []
        for task in ready:
            payload, digest, prompt_path, schema_path, candidate_ids = (
                analysis._holistic_prepare_task(
                    state, evidence, contract, compact, task
                )
            )
            result_path = pathlib.Path(str(task["artifacts"]["result"]))
            if result_path.is_file() and not result_path.is_symlink():
                validated = analysis._validate_holistic_task_result(
                    analysis._read_json(result_path, "recoverable holistic result"),
                    state=state,
                    task=task,
                    input_sha256=digest,
                    contract=contract,
                    compact=compact,
                    luna_candidate_ids=candidate_ids,
                )
                analysis._holistic_accept_result(
                    state=state,
                    task=task,
                    validated=validated,
                    input_sha256=digest,
                    prompt_path=prompt_path,
                    schema_path=schema_path,
                    attempt=None,
                    recovered=True,
                )
                progressed += 1
                continue
            recoverable_attempt = _prior_rejection(state, task, digest)
            recovery_error: CreditAnalysisError | None = None
            if recoverable_attempt is not None:
                try:
                    recoverable = _corrected_response(state, task, digest, recoverable_attempt[1], recoverable_attempt[0], retained=True)
                    validated = analysis._validate_holistic_task_result(
                        recoverable,
                        state=state,
                        task=task,
                        input_sha256=digest,
                        contract=contract,
                        compact=compact,
                        luna_candidate_ids=candidate_ids,
                    )
                except CreditAnalysisError as error:
                    recovery_error = error
                else:
                    analysis._holistic_accept_result(
                        state=state,
                        task=task,
                        validated=validated,
                        input_sha256=digest,
                        prompt_path=prompt_path,
                        schema_path=schema_path,
                        attempt=None,
                        recovered=True,
                    )
                    progressed += 1
                    continue
            if task["phase"] == "sol-final":
                if analysis._sol_validation_error_count(state["execution"][task["task_id"]]) > sol_retry_limit:
                    raise CreditAnalysisError(
                        "final Sol failed validation after its automatic retry"
                        + (f"; retained response revalidation: {recovery_error}" if recovery_error else "")
                    )
                if analysis._sol_attempt_capacity(state, contract, task) == 0:
                    raise CreditAnalysisError(
                        "Sol attempt ceiling leaves no final result capacity"
                    )
            raw: Mapping[str, Any] | None
            unrecorded = analysis._holistic_unrecorded_attempt(
                state,
                task,
                digest,
                prompt_path,
                schema_path,
            )
            if unrecorded is not None:
                raw, attempt = unrecorded
                role = analysis._holistic_role(task)
                state["model_attempts"][role] += 1
                execution = state["execution"][task["task_id"]]
                try:
                    raw = _corrected_response(state, task, digest, raw, attempt, retained=True)
                    validated = analysis._validate_holistic_task_result(
                        raw,
                        state=state,
                        task=task,
                        input_sha256=digest,
                        contract=contract,
                        compact=compact,
                        luna_candidate_ids=candidate_ids,
                    )
                except CreditAnalysisError as error:
                    execution["attempts"].append(
                        {
                            **attempt,
                            "outcome": "validation-error",
                            "error": str(error),
                        }
                    )
                    can_retry_luna = (
                        task["phase"] == "luna-discovery"
                        and _diagnosed_luna_retry(error)
                        and len(execution["attempts"]) == 1
                        and state["model_attempts"]["luna"] < luna_attempt_limit
                    )
                    can_retry_sol = (
                        task["phase"].startswith("sol-")
                        and analysis._can_retry_sol_validation(
                            state, contract, task
                        )
                    )
                    if not can_retry_luna and not can_retry_sol:
                        if task["phase"] == "luna-discovery":
                            _omit_luna_task(
                                state,
                                task,
                                reason="luna-invalid-output",
                                error=str(error),
                            )
                            progressed += 1
                            continue
                        if task["phase"] != "sol-final":
                            _omit_sol_task(
                                state,
                                task,
                                reason="sol-invalid-output",
                                error=str(error),
                            )
                            progressed += 1
                            continue
                        analysis._holistic_sync_child_lineage(state)
                        analysis._holistic_save_state(state)
                        raise
                    analysis._holistic_sync_child_lineage(state)
                    analysis._holistic_save_state(state)
                    continue
                else:
                    analysis._holistic_accept_result(
                        state=state,
                        task=task,
                        validated=validated,
                        input_sha256=digest,
                        prompt_path=prompt_path,
                        schema_path=schema_path,
                        attempt=attempt,
                        recovered=True,
                    )
                    progressed += 1
                    continue
            prepared.append(
                (task, payload, digest, prompt_path, schema_path, candidate_ids)
            )
        if phase.startswith("sol-"):
            # Reuse retained results before spending any remaining launch budget.
            analysis._validate_sol_call_budget(state, contract)
            launch_capacity = analysis._sol_attempt_capacity(state, contract, ready[0])
            deferred = prepared[launch_capacity:]
            prepared = prepared[:launch_capacity]
            for task, *_ in deferred:
                execution = state["execution"][task["task_id"]]
                if task["phase"] != "sol-final" and analysis._sol_validation_error_count(
                    execution
                ):
                    _omit_sol_task(
                        state,
                        task,
                        reason="sol-retry-capacity",
                        error=str(execution["attempts"][-1].get("error") or "invalid result"),
                    )
                    progressed += 1
            if deferred:
                analysis._holistic_save_state(state)
            if not prepared and any(
                state["execution"][item[0]["task_id"]]["status"] == "pending"
                for item in deferred
            ):
                raise CreditAnalysisError(
                    "Sol attempt ceiling leaves no "
                    + ("final result" if phase == "sol-final" else "first-stage")
                    + " capacity"
                )
        if not prepared:
            continue

        futures: dict[Any, tuple[Any, ...]] = {}
        failures: list[tuple[int, BaseException]] = []
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, min(concurrency, len(prepared)))
        ) as executor:
            for prepared_item in prepared:
                task, payload, digest, prompt_path, schema_path, _ = prepared_item
                attempt_number = len(state["execution"][task["task_id"]]["attempts"]) + 1
                # Workers never observe another completion's mutable controller state.
                future = executor.submit(
                    _holistic_model_attempt,
                    runner=runner,
                    state=copy.deepcopy(state),
                    task=copy.deepcopy(task),
                    payload=copy.deepcopy(payload),
                    input_sha=digest,
                    prompt_path=prompt_path,
                    schema_path=schema_path,
                    attempt_number=attempt_number,
                )
                futures[future] = (*prepared_item, attempt_number)
            pending = set(futures)
            while pending:
                try:
                    for future in concurrent.futures.as_completed(pending):
                        pending.remove(future)
                        completed_item = futures[future]
                        task = completed_item[0]
                        try:
                            progressed += _consume_attempt(
                                future, completed_item, state=state, contract=contract,
                                compact=compact, luna_attempt_limit=luna_attempt_limit,
                            )
                        except BaseException as error:
                            # Drain paid-for siblings even after a failure or interruption.
                            # Incomplete artifacts remain owned and block unsafe replay.
                            failures.append((int(task["ordinal"]), error))
                        finally:
                            if state["execution"][task["task_id"]]["status"] != "complete":
                                _checkpoint_state(state)
                except KeyboardInterrupt as error:
                    failures.append((-1, error))
        _checkpoint_state(state)
        if failures:
            raise min(failures, key=lambda item: item[0])[1]

    if all(
        state["execution"][task_id]["status"]
        in {"complete", "skipped", "omitted"}
        for task_id in state["task_order"]
    ):
        analysis._finalize_holistic(state, evidence, compact)
    else:
        analysis._holistic_save_state(state)
    return analysis._holistic_public_status(state)
