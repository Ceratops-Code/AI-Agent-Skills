"""Execute one schema-validated repository-owned operation without a shell.

Release publication and local deployment use separate contracts and wrappers,
but share the safety mechanics here: exact argv arrays, strict parameters,
repository-bounded working directories, compact results, and bounded failure
evidence. Callers supply the contract identity and success status so this
module never conflates remote publication with local deployment.
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
from typing import Any, cast

from ceratops_repo_compatibility_engine.deploy_contract_validation import (
    DeployContractError,
    load_contract,
)

PARAMETER_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PLACEHOLDER_RE = re.compile(r"^\{(?P<name>[a-z][a-z0-9_]*)\}$")


@dataclass(frozen=True)
class OperationProfile:
    """Describe one contract type without weakening shared execution rules."""

    label: str
    default_contract: pathlib.Path
    schema: pathlib.Path
    default_success_status: str
    operation_statuses: Mapping[str, str]


class OperationError(RuntimeError):
    """Raised when a contract or operation violates its repository boundary."""


def _inside(path: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _read_contract(
    repo_root: pathlib.Path,
    contract_path: pathlib.Path,
    profile: OperationProfile,
) -> Mapping[str, Any]:
    resolved = (
        contract_path if contract_path.is_absolute() else repo_root / contract_path
    ).resolve(strict=True)
    if not resolved.is_file() or not _inside(resolved, repo_root):
        raise OperationError(
            f"{profile.label} contract must be a file inside the repository."
        )
    try:
        return load_contract(resolved, schema_path=profile.schema)
    except DeployContractError as exc:
        raise OperationError(
            f"Invalid {profile.label.lower()} contract: {exc}"
        ) from exc


def _operation_steps(
    contract: Mapping[str, Any],
    operation: str,
    profile: OperationProfile,
) -> tuple[Mapping[str, Any], Sequence[Mapping[str, Any]]]:
    operations = contract.get("operations")
    if not isinstance(operations, Mapping) or operation not in operations:
        raise OperationError(f"{profile.label} operation is not declared: {operation}")
    selected = operations[operation]
    if not isinstance(selected, Mapping):
        raise OperationError(f"{profile.label} operation is invalid: {operation}")
    steps = selected.get("steps", [])
    if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes)):
        raise OperationError(
            f"{profile.label} operation has no valid steps: {operation}"
        )
    return selected, steps


def parse_parameters(values: Sequence[str], profile: OperationProfile) -> dict[str, str]:
    """Parse unique nonempty ``name=value`` operation parameters."""

    result: dict[str, str] = {}
    for value in values:
        name, separator, parameter = value.partition("=")
        if (
            not separator
            or PARAMETER_NAME_RE.fullmatch(name) is None
            or not parameter
        ):
            raise OperationError(
                f"{profile.label} parameters must use name=value."
            )
        if name in result:
            raise OperationError(
                f"Duplicate {profile.label.lower()} parameter: {name}"
            )
        result[name] = parameter
    return result


def _expanded_argv(
    argv: Sequence[str],
    parameters: Mapping[str, str],
    profile: OperationProfile,
) -> list[str]:
    """Replace only whole-argument declared placeholders."""

    expanded: list[str] = []
    for value in argv:
        match = PLACEHOLDER_RE.fullmatch(value)
        if match is None:
            expanded.append(value)
            continue
        name = match.group("name")
        if name not in parameters:
            raise OperationError(
                f"Missing {profile.label.lower()} parameter: {name}"
            )
        expanded.append(parameters[name])
    return expanded


def _working_directory(
    repo_root: pathlib.Path,
    step: Mapping[str, Any],
    profile: OperationProfile,
) -> pathlib.Path:
    raw = step.get("cwd", ".")
    if not isinstance(raw, str):
        raise OperationError(f"{profile.label} step cwd must be text.")
    cwd = (repo_root / raw).resolve(strict=True)
    if not cwd.is_dir() or not _inside(cwd, repo_root):
        raise OperationError(
            f"{profile.label} step cwd must be a directory inside the repository."
        )
    return cwd


def _failure_tail(result: subprocess.CompletedProcess[str]) -> str:
    output = (result.stderr or result.stdout or "").splitlines()
    return "\n".join(output[-8:])


def run_operation(
    repo_root: pathlib.Path,
    operation: str,
    profile: OperationProfile,
    contract_path: pathlib.Path | None = None,
    parameters: Mapping[str, str] | None = None,
    parameters_if_declared: Mapping[str, str] | None = None,
    *,
    if_declared: bool = False,
) -> dict[str, object]:
    """Run one declared operation and return its contract-specific result."""

    root = repo_root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise OperationError("Repository root is not a directory.")
    selected_contract = contract_path or profile.default_contract
    contract = _read_contract(root, selected_contract, profile)
    operations = contract.get("operations")
    if (
        if_declared
        and isinstance(operations, Mapping)
        and operation not in operations
    ):
        return {
            "status": "no_op",
            "operation": operation,
            "steps": [],
            "reason": "operation_not_declared",
        }
    selected, steps = _operation_steps(contract, operation, profile)
    expected = selected.get("parameters", [])
    if (
        not isinstance(expected, Sequence)
        or isinstance(expected, (str, bytes))
        or not all(isinstance(value, str) for value in expected)
    ):
        raise OperationError(
            f"{profile.label} operation has invalid parameters: {operation}"
        )
    declared = set(expected)
    supplied = dict(parameters or {})
    conditional = dict(parameters_if_declared or {})
    duplicated = sorted(set(supplied) & set(conditional))
    if duplicated:
        raise OperationError(
            f"{profile.label} parameter supplied more than once: "
            + ", ".join(duplicated)
        )
    supplied.update(
        (name, value) for name, value in conditional.items() if name in declared
    )
    missing = sorted(declared - set(supplied))
    extra = sorted(set(parameters or {}) - declared)
    if missing or extra:
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("unexpected " + ", ".join(extra))
        raise OperationError(
            f"{profile.label} parameter mismatch: " + "; ".join(detail)
        )

    prepared: list[tuple[str, list[str], pathlib.Path]] = []
    for step in steps:
        step_id = step.get("id")
        argv = step.get("run")
        if (
            not isinstance(step_id, str)
            or not isinstance(argv, Sequence)
            or isinstance(argv, (str, bytes))
            or not all(isinstance(value, str) and value for value in argv)
        ):
            raise OperationError(
                f"{profile.label} operation has an invalid step: {operation}"
            )
        prepared.append(
            (
                step_id,
                _expanded_argv(cast(Sequence[str], argv), supplied, profile),
                _working_directory(root, step, profile),
            )
        )

    completed: list[str] = []
    for step_id, argv, working_directory in prepared:
        try:
            completed_process = subprocess.run(
                argv,
                cwd=working_directory,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise OperationError(
                f"{profile.label} step could not start: {step_id}: {exc}"
            ) from exc
        if completed_process.returncode != 0:
            tail = _failure_tail(completed_process)
            suffix = f"\n{tail}" if tail else ""
            raise OperationError(
                f"{profile.label} step failed: {step_id}{suffix}"
            )
        completed.append(step_id)

    result: dict[str, object] = {
        "status": profile.operation_statuses.get(
            operation, profile.default_success_status
        ),
        "operation": operation,
        "steps": completed,
    }
    handoff = selected.get("handoff")
    if isinstance(handoff, str):
        result["handoff"] = handoff
    return result


def build_parser(profile: OperationProfile) -> argparse.ArgumentParser:
    """Create the parser for one contract-specific executable wrapper."""

    parser = argparse.ArgumentParser(
        description=(
            f"Execute one operation from {profile.default_contract.as_posix()}."
        )
    )
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument(
        "--contract", type=pathlib.Path, default=profile.default_contract
    )
    parser.add_argument("--operation", required=True)
    parser.add_argument("--parameter", action="append", default=[])
    parser.add_argument("--parameter-if-declared", action="append", default=[])
    parser.add_argument(
        "--if-declared",
        action="store_true",
        help="Return an explicit no-op when the selected operation is absent.",
    )
    return parser


def operation_main(
    profile: OperationProfile,
    argv: list[str] | None = None,
) -> int:
    """Execute one profile and emit only its compact machine result."""

    args = build_parser(profile).parse_args(argv)
    try:
        result = run_operation(
            args.repo_root,
            args.operation,
            profile,
            args.contract,
            parse_parameters(args.parameter, profile),
            parse_parameters(args.parameter_if_declared, profile),
            if_declared=args.if_declared,
        )
    except (OperationError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "error", "message": str(exc)},
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0
