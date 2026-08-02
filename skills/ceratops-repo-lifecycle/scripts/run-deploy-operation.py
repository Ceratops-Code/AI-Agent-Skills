#!/usr/bin/env python3
"""Validate and execute one named repository deployment operation.

The contract contains argv arrays, never shell text, and may declare one agent
handoff that this helper returns without executing. Every working directory
must resolve inside the selected repository. Explicit parameters are strict;
lifecycle context is used only when declared. Successful commands emit no
captured output; failures retain only a bounded tail for diagnosis.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import Any, cast

import jsonschema
import yaml


SCRIPT_ROOT = pathlib.Path(__file__).resolve().parent
SCHEMA = (
    SCRIPT_ROOT.parent
    / "references"
    / "schemas"
    / "deploy-contract.schema.json"
)
DEFAULT_CONTRACT = pathlib.Path("deploy/deploy.yml")
PARAMETER_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PLACEHOLDER_RE = re.compile(r"^\{(?P<name>[a-z][a-z0-9_]*)\}$")


class DeployError(RuntimeError):
    """Raised when a contract or operation violates a deployment boundary."""


def _inside(path: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _read_contract(
    repo_root: pathlib.Path, contract_path: pathlib.Path
) -> Mapping[str, Any]:
    resolved = (
        contract_path
        if contract_path.is_absolute()
        else repo_root / contract_path
    ).resolve(strict=True)
    if not resolved.is_file() or not _inside(resolved, repo_root):
        raise DeployError("Deployment contract must be a file inside the repository.")
    try:
        value = yaml.safe_load(resolved.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(value)
    except (
        OSError,
        yaml.YAMLError,
        json.JSONDecodeError,
        jsonschema.ValidationError,
        jsonschema.SchemaError,
    ) as exc:
        raise DeployError(f"Invalid deployment contract: {exc}") from exc
    if not isinstance(value, Mapping):
        raise DeployError("Deployment contract must be a mapping.")
    return value


def _operation_steps(
    contract: Mapping[str, Any], operation: str
) -> tuple[Mapping[str, Any], Sequence[Mapping[str, Any]]]:
    operations = contract.get("operations")
    if not isinstance(operations, Mapping) or operation not in operations:
        raise DeployError(f"Deployment operation is not declared: {operation}")
    selected = operations[operation]
    if not isinstance(selected, Mapping):
        raise DeployError(f"Deployment operation is invalid: {operation}")
    steps = selected.get("steps", [])
    if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes)):
        raise DeployError(f"Deployment operation has no valid steps: {operation}")
    return selected, steps


def _parameters(values: Sequence[str]) -> dict[str, str]:
    """Parse unique nonempty ``name=value`` operation parameters."""

    result: dict[str, str] = {}
    for value in values:
        name, separator, parameter = value.partition("=")
        if (
            not separator
            or PARAMETER_NAME_RE.fullmatch(name) is None
            or not parameter
        ):
            raise DeployError("Deployment parameters must use name=value.")
        if name in result:
            raise DeployError(f"Duplicate deployment parameter: {name}")
        result[name] = parameter
    return result


def _expanded_argv(
    argv: Sequence[str], parameters: Mapping[str, str]
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
            raise DeployError(f"Missing deployment parameter: {name}")
        expanded.append(parameters[name])
    return expanded


def _working_directory(
    repo_root: pathlib.Path, step: Mapping[str, Any]
) -> pathlib.Path:
    raw = step.get("cwd", ".")
    if not isinstance(raw, str):
        raise DeployError("Deployment step cwd must be text.")
    cwd = (repo_root / raw).resolve(strict=True)
    if not cwd.is_dir() or not _inside(cwd, repo_root):
        raise DeployError("Deployment step cwd must be a directory inside the repository.")
    return cwd


def _failure_tail(result: subprocess.CompletedProcess[str]) -> str:
    output = (result.stderr or result.stdout or "").splitlines()
    return "\n".join(output[-8:])


def run_operation(
    repo_root: pathlib.Path,
    operation: str,
    contract_path: pathlib.Path = DEFAULT_CONTRACT,
    parameters: Mapping[str, str] | None = None,
    parameters_if_declared: Mapping[str, str] | None = None,
    *,
    if_declared: bool = False,
) -> dict[str, object]:
    """Run one operation with strict parameters and conditional caller context."""

    root = repo_root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise DeployError("Repository root is not a directory.")
    contract = _read_contract(root, contract_path)
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
    selected, steps = _operation_steps(contract, operation)
    expected = selected.get("parameters", [])
    if (
        not isinstance(expected, Sequence)
        or isinstance(expected, (str, bytes))
        or not all(isinstance(value, str) for value in expected)
    ):
        raise DeployError(f"Deployment operation has invalid parameters: {operation}")
    declared = set(expected)
    supplied = dict(parameters or {})
    conditional = dict(parameters_if_declared or {})
    duplicated = sorted(set(supplied) & set(conditional))
    if duplicated:
        raise DeployError(
            "Deployment parameter supplied more than once: "
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
        raise DeployError("Deployment parameter mismatch: " + "; ".join(detail))
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
            raise DeployError(f"Deployment operation has an invalid step: {operation}")
        prepared.append(
            (
                step_id,
                _expanded_argv(cast(Sequence[str], argv), supplied),
                _working_directory(root, step),
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
            raise DeployError(f"Deployment step could not start: {step_id}: {exc}") from exc
        if completed_process.returncode != 0:
            tail = _failure_tail(completed_process)
            suffix = f"\n{tail}" if tail else ""
            raise DeployError(f"Deployment step failed: {step_id}{suffix}")
        completed.append(step_id)
    operation_result: dict[str, object] = {
        "status": "deployed",
        "operation": operation,
        "steps": completed,
    }
    handoff = selected.get("handoff")
    if isinstance(handoff, str):
        operation_result["handoff"] = handoff
    return operation_result


def build_parser() -> argparse.ArgumentParser:
    """Create the deterministic deployment-operation parser."""

    parser = argparse.ArgumentParser(
        description="Execute one operation from deploy/deploy.yml."
    )
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--contract", type=pathlib.Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--parameter", action="append", default=[])
    parser.add_argument("--parameter-if-declared", action="append", default=[])
    parser.add_argument(
        "--if-declared",
        action="store_true",
        help="Return an explicit no-op when the selected operation is absent.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute one operation and emit one compact result."""

    args = build_parser().parse_args(argv)
    try:
        result = run_operation(
            args.repo_root,
            args.operation,
            args.contract,
            _parameters(args.parameter),
            _parameters(args.parameter_if_declared),
            if_declared=args.if_declared,
        )
    except (DeployError, OSError, ValueError) as exc:
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


if __name__ == "__main__":
    raise SystemExit(main())
