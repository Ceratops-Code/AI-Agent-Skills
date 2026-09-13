#!/usr/bin/env python3
"""Execute repository-owned SDLC capabilities with exact argv and local check barriers.

YAML locations identify operations; their category distinguishes validation from
mutation. Lifecycle callers own timing and choose operation IDs. This runner
prepares the whole batch, runs repository and selected-deliverable validations
before deployment/publication, and stops on failure. Handoffs and prerequisites
are advisory data, never executable prose or completion receipts.
Successful steps may return bounded schema-tagged JSON results; their domain
status is preserved separately from command completion and checkpointed by callers.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ceratops_repo_compatibility_engine.sdlc_contract_validation import (
    SdlcContractError,
    load_contract,
    operation_entries,
)
from ceratops_repo_compatibility_engine.sdlc_contract_validation import (
    operation_category as contract_operation_category,
)

DEFAULT_CONTRACT = pathlib.Path("sdlc/sdlc.yml")
PARAMETER_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PLACEHOLDER_RE = re.compile(r"^\{(?P<name>[a-z][a-z0-9_]*)\}$")
FAILURE_TAIL_LINES = 8
FAILURE_TAIL_CHARS = 4096
STEP_RESULT_BYTES = 65536
STEP_RESULT_DEPTH = 64
FAILED_STATUSES = frozenset({"operation_failed", "validation_failed", "state_changed"})


@dataclass(frozen=True)
class OperationRequest:
    """Select one YAML location and its exact parameter policy."""

    operation: str
    parameters: Mapping[str, str] | None = None
    parameters_if_declared: Mapping[str, str] | None = None
    if_declared: bool = False


@dataclass(frozen=True)
class PreparedStep:
    """One bounded command identified by its v1 step ID or v2 YAML position."""

    position: int | str
    argv: tuple[str, ...]
    cwd: pathlib.Path


@dataclass(frozen=True)
class PreparedOperation:
    """A validated operation bound to the commit observed during preparation."""

    repo_root: pathlib.Path
    operation: str
    category: str
    commit: str | None
    steps: tuple[PreparedStep, ...]
    handoff: str | None
    prerequisites: Mapping[str, Any]
    no_op_reason: str | None = None


class OperationError(RuntimeError):
    """A malformed selection or unsafe repository boundary."""


def operation_category(operation: str) -> str:
    """Validate a complete YAML location and return its structural category."""

    try:
        return contract_operation_category(operation)
    except SdlcContractError as exc:
        raise OperationError(str(exc)) from exc


def read_repository_contract(
    repo_root: pathlib.Path,
    contract_path: pathlib.Path | None = None,
) -> Mapping[str, Any]:
    """Read only a repository-bounded contract; an absent default is empty."""

    selected = contract_path or DEFAULT_CONTRACT
    lexical = repo_root / selected
    resolved = lexical.resolve()
    if not resolved.is_relative_to(repo_root) or lexical.is_symlink():
        raise OperationError("SDLC contract must be a file inside the repository.")
    if not resolved.exists() and selected == DEFAULT_CONTRACT:
        return {"version": 2, "kind": "ceratops-sdlc"}
    if not resolved.is_file():
        raise OperationError("Selected SDLC contract must be a repository file.")
    try:
        return load_contract(resolved)
    except SdlcContractError as exc:
        raise OperationError(f"Invalid SDLC contract: {exc}") from exc


def parse_parameters(values: Sequence[str]) -> dict[str, str]:
    """Parse unique nonempty name=value parameters without shell expansion."""

    result: dict[str, str] = {}
    for value in values:
        name, separator, parameter = value.partition("=")
        if not separator or PARAMETER_NAME_RE.fullmatch(name) is None or not parameter:
            raise OperationError("SDLC parameters must use name=value.")
        if name in result:
            raise OperationError(f"Duplicate SDLC parameter: {name}")
        result[name] = parameter
    return result


def _parameters(
    selected: Mapping[str, Any],
    request: OperationRequest,
) -> dict[str, str]:
    declared = set(selected.get("parameters", []))
    supplied = dict(request.parameters or {})
    conditional = dict(request.parameters_if_declared or {})
    duplicated = sorted(set(supplied) & set(conditional))
    if duplicated:
        raise OperationError(
            "Parameter supplied more than once: " + ", ".join(duplicated)
        )
    supplied.update(
        (name, value) for name, value in conditional.items() if name in declared
    )
    missing = sorted(declared - set(supplied))
    extra = sorted(set(request.parameters or {}) - declared)
    if missing or extra:
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("unexpected " + ", ".join(extra))
        raise OperationError("SDLC parameter mismatch: " + "; ".join(detail))
    return supplied


def _expanded_argv(
    argv: Sequence[str], parameters: Mapping[str, str]
) -> tuple[str, ...]:
    """Substitute only whole-argument declared placeholders."""

    expanded: list[str] = []
    for value in argv:
        match = PLACEHOLDER_RE.fullmatch(value)
        if match is None:
            expanded.append(value)
            continue
        name = match.group("name")
        if name not in parameters:
            raise OperationError(f"Missing SDLC parameter: {name}")
        expanded.append(parameters[name])
    return tuple(expanded)


def _working_directory(repo_root: pathlib.Path, raw: str) -> pathlib.Path:
    cwd = (repo_root / raw).resolve(strict=True)
    if not cwd.is_dir() or not cwd.is_relative_to(repo_root):
        raise OperationError("SDLC step cwd must be a directory inside the repository.")
    return cwd


def repository_commit(repo_root: pathlib.Path) -> str | None:
    """Return HEAD for a Git worktree, or None for standalone capability use."""

    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def require_clean_commit(repo_root: pathlib.Path, commit: str) -> None:
    """Prevent a checked commit from authorizing different or uncommitted content."""

    if repository_commit(repo_root) != commit:
        raise OperationError(
            "Repository HEAD changed; validate the new commit before continuing."
        )
    result = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode or result.stdout.strip():
        raise OperationError(
            "Repository must be clean at the checked commit before continuing."
        )


def prepare_operations(
    repo_root: pathlib.Path,
    requests: Sequence[OperationRequest],
    contract_path: pathlib.Path | None = None,
) -> list[PreparedOperation]:
    """Validate all selected commands, parameters and cwd values before execution."""

    root = repo_root.expanduser().resolve(strict=True)
    contract = read_repository_contract(root, contract_path)
    entries = operation_entries(contract)
    requirements = contract.get("repository", {}).get("prerequisites", {})
    commit = repository_commit(root)
    prepared: list[PreparedOperation] = []
    for request in requests:
        category = operation_category(request.operation)
        selected = entries.get(request.operation)
        if selected is None:
            absent_v1_section = (
                contract.get("version") == 1
                and request.operation.split(".")[0] in {"deploy", "release"}
                and request.operation.split(".")[0] not in contract
            )
            if not request.if_declared and not absent_v1_section:
                raise OperationError(
                    f"SDLC operation is not declared: {request.operation}"
                )
            prepared.append(
                PreparedOperation(
                    root,
                    request.operation,
                    category,
                    commit,
                    (),
                    None,
                    {},
                    "contract_section_not_declared"
                    if absent_v1_section else "operation_not_declared",
                )
            )
            continue
        parameters = _parameters(selected, request)
        steps = tuple(
            PreparedStep(
                step.get("id", position),
                _expanded_argv(step["run"], parameters),
                _working_directory(root, step.get("cwd", ".")),
            )
            for position, step in enumerate(selected.get("steps", []), start=1)
        )
        prepared.append(
            PreparedOperation(
                root,
                request.operation,
                category,
                commit,
                steps,
                selected.get("handoff"),
                {
                    name: requirements[name]
                    for name in selected.get("prerequisites", [])
                },
            )
        )
    return prepared


def validation_operations(
    repo_root: pathlib.Path,
    selected_operations: Sequence[str] = (),
    explicit: Sequence[str] | None = None,
    contract_path: pathlib.Path | None = None,
) -> list[str]:
    """Select repository checks and checks of selected deliverables, in YAML order.

    An explicit ordered list replaces discovery for this invocation. No operation
    name or script path has a special validation meaning; only the category does.
    """

    if explicit is not None:
        for operation in explicit:
            if operation_category(operation) != "validate":
                raise OperationError(
                    "Validation selections must name validate entries."
                )
        return list(explicit)
    selected_deliverables = {
        operation.split(".")[1]
        for operation in selected_operations
        if operation.startswith("deliverables.")
    }
    entries = operation_entries(read_repository_contract(repo_root, contract_path))
    return [
        operation
        for operation in entries
        if operation_category(operation) == "validate"
        and (
            operation.startswith("repository.")
            or operation.split(".")[1] in selected_deliverables
        )
    ]


def _bounded_tail(value: str | None) -> list[str]:
    return (value or "")[-FAILURE_TAIL_CHARS:].splitlines()[-FAILURE_TAIL_LINES:]


def _unique_result_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous JSON members rather than silently replace receipt values."""

    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate result member.")
        value[key] = item
    return value


def _step_result(stdout: str) -> dict[str, Any]:
    """Retain a whole JSON receipt without forwarding logs or interpreting success.

    Only a complete object with nonempty schema/status strings is a result.
    Parsing never scans log fragments or reads stderr. Oversized output gets a
    content-free omission marker; malformed and ordinary output stay suppressed.
    Container depth is bounded so downstream checkpoint readers can decode it.
    Capture cannot turn a completed side effect into a retryable failure.
    """

    if len(stdout.encode("utf-8")) > STEP_RESULT_BYTES:
        return {"result_omitted": "stdout_limit"}
    try:
        value = json.loads(stdout, object_pairs_hook=_unique_result_object)
        if not isinstance(value, dict) or not all(
            isinstance(value.get(key), str) and value[key].strip()
            for key in ("schema", "status")
        ):
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


def execute_prepared_operation(prepared: PreparedOperation) -> dict[str, object]:
    """Run one prepared operation; never infer that an advisory handoff completed."""

    base: dict[str, object] = {
        "operation": prepared.operation,
        "commit": prepared.commit,
        "steps": [],
    }
    if prepared.no_op_reason is not None:
        return {**base, "status": "no_op", "reason": prepared.no_op_reason}
    if repository_commit(prepared.repo_root) != prepared.commit:
        return {
            **base,
            "status": "state_changed",
            "message": "HEAD changed after preparation.",
        }
    completed: list[int | str] = []
    step_results: list[dict[str, Any]] = []
    for step in prepared.steps:
        if prepared.commit and prepared.category in {"deploy-local", "publish"}:
            try:
                require_clean_commit(prepared.repo_root, prepared.commit)
            except OperationError as exc:
                return {
                    **base,
                    "steps": completed,
                    "status": "state_changed",
                    "message": str(exc),
                }
        try:
            result = subprocess.run(
                list(step.argv),
                cwd=step.cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            code, stdout, stderr = result.returncode, result.stdout, result.stderr
        except OSError as exc:
            code, stdout, stderr = None, "", str(exc)
        if code != 0:
            return {
                **base,
                "status": "validation_failed"
                if prepared.category == "validate"
                else "operation_failed",
                "message": f"SDLC step failed: {prepared.operation} step {step.position}",
                "steps": completed,
                "failed_step": step.position,
                "diagnostic": {
                    "exit_code": code,
                    "stdout_tail": _bounded_tail(stdout),
                    "stderr_tail": _bounded_tail(stderr),
                },
            }
        completed.append(step.position)
        captured = _step_result(stdout)
        if captured:
            step_results.append({"step": step.position, **captured})
            # The shared list also preserves earlier receipts on later failures
            # or commit drift, before any subsequent side effect is attempted.
            base["step_results"] = step_results
        if repository_commit(prepared.repo_root) != prepared.commit:
            return {
                **base,
                "steps": completed,
                "status": "state_changed",
                "message": "HEAD changed during operation; prepare and validate the new commit.",
            }
    result_value = {
        **base,
        "status": "completed" if prepared.steps else "advisory",
        "steps": completed,
    }
    if prepared.handoff:
        result_value["handoff"] = prepared.handoff
    if prepared.prerequisites:
        result_value["prerequisites"] = dict(prepared.prerequisites)
    return result_value


def execute_prepared_operations(
    prepared: Sequence[PreparedOperation],
) -> dict[str, Any]:
    """Run in order, stopping at the first failure with a bounded pending ledger."""

    results: list[dict[str, object]] = []
    completed: list[str] = []
    for index, operation in enumerate(prepared):
        result = execute_prepared_operation(operation)
        results.append(result)
        if result["status"] in FAILED_STATUSES:
            return {
                **result,
                "completed_operations": completed,
                "pending_operations": [item.operation for item in prepared[index:]],
                "results": results,
            }
        completed.append(operation.operation)
    return {
        "status": "completed",
        "completed_operations": completed,
        "pending_operations": [],
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--sdlc-contract", type=pathlib.Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--operation",
        action="append",
        default=[],
        help="Complete YAML location; repeat in execution order.",
    )
    parser.add_argument(
        "--validation-operation",
        action="append",
        help="Complete validate location; repeats replace automatic discovery.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run selected validation without deployment or publication.",
    )
    parser.add_argument("--parameter", action="append", default=[])
    parser.add_argument("--parameter-if-declared", action="append", default=[])
    parser.add_argument("--if-declared", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--commit", help="Require this exact clean Git commit before and after checks."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = args.repo_root.expanduser().resolve(strict=True)
        parameters = parse_parameters(args.parameter)
        conditional = parse_parameters(args.parameter_if_declared)
        if args.commit:
            require_clean_commit(root, args.commit)
        prepared = prepare_operations(
            root,
            [
                OperationRequest(operation, parameters, conditional, args.if_declared)
                for operation in args.operation
            ],
            args.sdlc_contract,
        )
        if any(item.category in {"deploy-local", "publish"} for item in prepared):
            commit = repository_commit(root)
            if commit:
                require_clean_commit(root, commit)
                args.commit = args.commit or commit
        requires_validation = args.validate or any(
            item.category in {"deploy-local", "publish"} for item in prepared
        )
        validations = (
            prepare_operations(
                root,
                [
                    OperationRequest(
                        operation,
                        parameters=parameters if args.validate else None,
                        parameters_if_declared=conditional
                        if args.validate
                        else {**conditional, **parameters},
                    )
                    for operation in validation_operations(
                        root,
                        args.operation,
                        args.validation_operation,
                        args.sdlc_contract,
                    )
                ],
                args.sdlc_contract,
            )
            if requires_validation
            else []
        )
        if args.prepare_only:
            result: dict[str, Any] = {
                "status": "prepared",
                "operations": args.operation,
            }
            requirements = {
                name: data
                for item in [*validations, *prepared]
                for name, data in item.prerequisites.items()
            }
            if requirements:
                result["prerequisites"] = requirements
        else:
            checks = execute_prepared_operations(validations)
            if checks["status"] in FAILED_STATUSES:
                result = {
                    **checks,
                    "completed_operations": [],
                    "pending_operations": args.operation
                    if not args.validate
                    else checks["pending_operations"],
                    "results": checks["results"]
                    if args.validate
                    else [checks["results"][-1]],
                }
            else:
                if args.commit:
                    require_clean_commit(root, args.commit)
                result = (
                    checks if args.validate else execute_prepared_operations(prepared)
                )
                advisory_checks = [
                    item for item in checks["results"] if item.get("handoff")
                ]
                if advisory_checks and not args.validate:
                    result["validation_handoffs"] = advisory_checks
    except (OperationError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "error", "message": str(exc)[:4096]}, separators=(",", ":")
            ),
            file=sys.stderr,
        )
        return 1
    failed = result.get("status") in FAILED_STATUSES
    print(
        json.dumps(result, separators=(",", ":")),
        file=sys.stderr if failed else sys.stdout,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
