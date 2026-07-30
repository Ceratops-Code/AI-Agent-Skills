#!/usr/bin/env python3
"""Validate and execute one named repository deployment operation.

The contract contains argv arrays, never shell text. Every working directory
must resolve inside the selected repository. Successful commands emit no
captured output; failures retain only a bounded tail for diagnosis.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import Any

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
) -> Sequence[Mapping[str, Any]]:
    operations = contract.get("operations")
    if not isinstance(operations, Mapping) or operation not in operations:
        raise DeployError(f"Deployment operation is not declared: {operation}")
    selected = operations[operation]
    if not isinstance(selected, Mapping):
        raise DeployError(f"Deployment operation is invalid: {operation}")
    steps = selected.get("steps")
    if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes)):
        raise DeployError(f"Deployment operation has no valid steps: {operation}")
    return steps


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
) -> dict[str, object]:
    """Run one declared operation and return its compact structured result."""

    root = repo_root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise DeployError("Repository root is not a directory.")
    contract = _read_contract(root, contract_path)
    completed: list[str] = []
    for step in _operation_steps(contract, operation):
        step_id = step.get("id")
        argv = step.get("run")
        if (
            not isinstance(step_id, str)
            or not isinstance(argv, Sequence)
            or isinstance(argv, (str, bytes))
            or not all(isinstance(value, str) and value for value in argv)
        ):
            raise DeployError(f"Deployment operation has an invalid step: {operation}")
        try:
            result = subprocess.run(
                list(argv),
                cwd=_working_directory(root, step),
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise DeployError(f"Deployment step could not start: {step_id}: {exc}") from exc
        if result.returncode != 0:
            tail = _failure_tail(result)
            suffix = f"\n{tail}" if tail else ""
            raise DeployError(f"Deployment step failed: {step_id}{suffix}")
        completed.append(step_id)
    return {
        "status": "deployed",
        "operation": operation,
        "steps": completed,
    }


def build_parser() -> argparse.ArgumentParser:
    """Create the deterministic deployment-operation parser."""

    parser = argparse.ArgumentParser(
        description="Execute one operation from deploy/deploy.yml."
    )
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--contract", type=pathlib.Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--operation", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute one operation and emit one compact result."""

    args = build_parser().parse_args(argv)
    try:
        result = run_operation(args.repo_root, args.operation, args.contract)
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
