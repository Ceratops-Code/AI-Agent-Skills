#!/usr/bin/env python3
"""Execute repository-owned SDLC capabilities with exact argv and local check barriers.

YAML locations identify operations; their category distinguishes validation from
mutation. Lifecycle callers own timing and choose operation IDs. This runner
prepares the whole batch, runs repository and selected-deliverable validation
and tests before mutation, and stops on failure. CI never dispatches skill
handoffs. Skill callers resolve installed action bindings, keeping implementations
out of repository declarations. Prerequisites remain setup annotations.
Successful steps may return bounded schema-tagged JSON results; their domain
status is preserved separately from command completion and checkpointed by callers.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
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
from github_pr_workflow.command import failure_excerpt
from sdlc_handoffs import execute_handoff
from sdlc_results import capture_step_result

DEFAULT_CONTRACT = pathlib.Path("sdlc/sdlc.yml")
PARAMETER_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PLACEHOLDER_RE = re.compile(r"^\{(?P<name>[a-z][a-z0-9_]*)\}$")
FAILURE_TAIL_LINES = 8
FAILURE_TAIL_CHARS = 4096
FAILED_STATUSES = frozenset({"operation_failed", "validation_failed", "tests_failed", "state_changed", "handoff_required", "error"})


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
    handoff_mode: str = "legacy"


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
    *, context: str = "skill",
) -> list[PreparedOperation]:
    """Validate all selected commands, parameters and cwd values before execution."""

    if context not in {"skill", "ci", "return"}:
        raise OperationError("Unknown SDLC execution context")
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
                selected.get("no-op"),
                context if contract.get("version", 2) >= 3 or context == "ci" else "legacy",
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

    Version 3 keeps every applicable gate even with an explicit order. Historical
    versions preserve their selection behavior. Categories own gate semantics.
    """

    contract = read_repository_contract(repo_root, contract_path)
    current = contract.get("version", 2) >= 3
    if explicit is not None:
        for operation in explicit:
            if operation_category(operation) not in {"validate", "tests"}:
                raise OperationError("Validation selections must name validate or tests entries.")
        if not current:
            return list(explicit)
    selected_deliverables = {
        operation.split(".")[1]
        for operation in (*selected_operations, *(explicit or ()))
        if operation.startswith("deliverables.")
    }
    entries = operation_entries(contract)
    automatic = [
        operation for operation in entries
        if operation_category(operation) in {"validate", "tests"}
        and (
            operation.startswith("repository.")
            or operation.split(".")[1] in selected_deliverables
            or (current and not selected_deliverables)
        )
    ]
    # In the current format an explicit selection can order checks, but cannot
    # bypass a selected deliverable's tests or repository-level prerequisites.
    return list(dict.fromkeys([*(explicit or []), *automatic]))


def _bounded_tail(value: str | None) -> list[str]:
    return (value or "")[-FAILURE_TAIL_CHARS:].splitlines()[-FAILURE_TAIL_LINES:]


def execute_prepared_operation(prepared: PreparedOperation) -> dict[str, object]:
    """Run one operation in its declared caller context and retain gate failures."""

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
    if prepared.handoff and prepared.handoff_mode == "ci" and not prepared.steps:
        return {**base, "status": "deferred_handoff", "handoff": prepared.handoff}
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
            argv = list(step.argv)
            # CreateProcess does not apply PATHEXT to bare npm/pnpm commands.
            # Resolve a bare executable while leaving repository-relative paths
            # bound to the declared cwd and preserving shell-free arguments.
            if os.name == "nt" and not any(separator in argv[0] for separator in ("/", "\\")):
                argv[0] = shutil.which(argv[0]) or argv[0]
            result = subprocess.run(
                argv,
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
            child_results = {}
            for stream, output in (("stdout", stdout), ("stderr", stderr)):
                captured = capture_step_result(output, require_identity=False)
                if "result_omitted" in captured:
                    captured["result_omitted"] = "output_limit"
                if captured:
                    child_results[stream] = captured
            return {
                **base,
                "status": "validation_failed"
                if prepared.category == "validate"
                else "tests_failed" if prepared.category == "tests" else "operation_failed",
                "message": f"SDLC step failed: {prepared.operation} step {step.position}",
                "steps": completed,
                "failed_step": step.position,
                "diagnostic": {
                    "exit_code": code,
                    "message": failure_excerpt("\n".join((stderr, stdout)))
                    or (f"Command exited with code {code}." if code is not None
                        else "Command could not start."),
                    "stdout_tail": _bounded_tail(stdout),
                    "stderr_tail": _bounded_tail(stderr),
                    **({"child_results": child_results} if child_results else {}),
                },
            }
        completed.append(step.position)
        captured = capture_step_result(stdout)
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
        if prepared.handoff_mode == "skill":
            if prepared.commit and prepared.category in {"deploy-local", "publish"}:
                try:
                    require_clean_commit(prepared.repo_root, prepared.commit)
                except OperationError as exc:
                    return {**base, "status": "state_changed", "message": str(exc)}
            result_value.update(execute_handoff(prepared.handoff, prepared.repo_root))
            if result_value["status"] == "completed":
                result_value["handoff_completed"] = True
            if repository_commit(prepared.repo_root) != prepared.commit:
                result_value.update(status="state_changed", message="HEAD changed during the skill action")
        elif prepared.handoff_mode == "return":
            result_value["status"] = "handoff_required"
        elif prepared.handoff_mode == "ci":
            result_value["status"] = "deferred_handoff"
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
        if result["status"] != "deferred_handoff":
            completed.append(operation.operation)
    return {
        "status": "completed",
        "completed_operations": completed,
        "pending_operations": [],
        "results": results,
        **({"deferred_handoffs": [item for item in results if item["status"] == "deferred_handoff"]} if any(item["status"] == "deferred_handoff" for item in results) else {}),
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
        help="Ordered validate/tests locations; v3 retains every applicable gate.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run selected validation and tests without deployment or publication.",
    )
    parser.add_argument("--parameter", action="append", default=[])
    parser.add_argument("--parameter-if-declared", action="append", default=[])
    parser.add_argument("--if-declared", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--ci", action="store_true", help="Execute commands only; never dispatch skill handoffs.")
    parser.add_argument("--tests", action="store_true", help="Run only selected SDLC tests.")
    parser.add_argument("--return-handoffs", action="store_true", help="Return pending skill routes without dispatch.")
    parser.add_argument("--evidence-file", type=pathlib.Path)
    parser.add_argument(
        "--commit", help="Require this exact clean Git commit before and after checks."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = args.repo_root.expanduser().resolve(strict=True)
        context = "ci" if args.ci else "return" if args.return_handoffs else "skill"
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
            args.sdlc_contract, context=context,
        )
        if any(item.category in {"deploy-local", "publish"} for item in prepared):
            commit = repository_commit(root)
            if commit:
                require_clean_commit(root, commit)
                args.commit = args.commit or commit
        requires_validation = args.validate or args.tests or any(
            item.category in {"deploy-local", "publish"} for item in prepared
        )
        validations = (
            prepare_operations(
                root,
                [
                    OperationRequest(
                        operation,
                        parameters=parameters if args.validate or args.tests else None,
                        parameters_if_declared=conditional
                        if args.validate or args.tests
                        else {**conditional, **parameters},
                    )
                    for operation in validation_operations(
                        root,
                        args.operation,
                        args.validation_operation,
                        args.sdlc_contract,
                    )
                    if not args.tests or operation_category(operation) == "tests"
                ],
                args.sdlc_contract, context=context,
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
                    if not (args.validate or args.tests)
                    else checks["pending_operations"],
                    "results": checks["results"]
                    if args.validate or args.tests
                    else [checks["results"][-1]],
                }
            else:
                if args.commit:
                    require_clean_commit(root, args.commit)
                result = (
                    checks if args.validate or args.tests else execute_prepared_operations(prepared)
                )
                advisory_checks = [
                    item for item in checks["results"] if item.get("handoff") and not item.get("handoff_completed")
                ]
                if advisory_checks and not (args.validate or args.tests):
                    result["validation_handoffs"] = advisory_checks
    except (OperationError, OSError, ValueError) as exc:
        result = {"status": "error", "message": str(exc)[:4096]}
    failed = result.get("status") in FAILED_STATUSES
    if args.evidence_file:
        if failed:
            args.evidence_file.parent.mkdir(parents=True, exist_ok=True)
            args.evidence_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        else:
            args.evidence_file.unlink(missing_ok=True)
    print(
        json.dumps(result, separators=(",", ":")),
        file=sys.stderr if failed else sys.stdout,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
