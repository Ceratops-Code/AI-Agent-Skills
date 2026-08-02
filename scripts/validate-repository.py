#!/usr/bin/env python3
"""Run the complete local and CI repository validation sequence.

The caller may select an evidence path through
``REPOSITORY_VALIDATION_EVIDENCE_FILE``. Child commands never inherit the
terminal: their output is suppressed on success and written in full only for
the first failed check. Commands use argv lists so paths containing spaces are
not reparsed by a shell. Managed runtime installation is intentionally outside
this aggregate repository validator.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass


EVIDENCE_FILE_ENV = "REPOSITORY_VALIDATION_EVIDENCE_FILE"
COMMAND_NOT_FOUND_EXIT_CODE = 127


@dataclass(frozen=True)
class Check:
    """Describe one ordered validation command and its reporting identity."""

    name: str
    command: tuple[str, ...]
    cwd: pathlib.Path
    platform: str | None = None


@dataclass(frozen=True)
class Failure:
    """Describe one failed check without retaining its diagnostic output."""

    check: str
    platform: str | None
    exit_code: int
    evidence_file: pathlib.Path
    evidence_error: str | None = None


ProcessRunner = Callable[
    [Sequence[str], pathlib.Path], subprocess.CompletedProcess[str]
]


def run_process(
    command: Sequence[str], cwd: pathlib.Path
) -> subprocess.CompletedProcess[str]:
    """Run one child without a shell and capture all diagnostic output."""

    return subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def build_checks(
    repo_root: pathlib.Path,
    *,
    python_executable: str | None = None,
    npm_executable: str | None = None,
) -> tuple[Check, ...]:
    """Build the single canonical repository-validation sequence."""

    python = python_executable or sys.executable
    npm = npm_executable or ("npm.cmd" if sys.platform == "win32" else "npm")
    lifecycle_scripts = (
        repo_root / "skills" / "ceratops-repo-lifecycle" / "scripts"
    )
    source_validator = (
        repo_root
        / "skills"
        / "ceratops-skill-lifecycle"
        / "scripts"
        / "skills-consistency-source-validator.py"
    )

    return (
        Check("markdown-lint", (npm, "run", "lint:markdown"), repo_root),
        Check(
            "yaml-lint",
            (python, "-m", "yamllint", "."),
            repo_root,
        ),
        Check(
            "mypy",
            (python, "-m", "mypy", "--platform", "linux"),
            repo_root,
            "linux",
        ),
        Check(
            "mypy",
            (python, "-m", "mypy", "--platform", "win32"),
            repo_root,
            "win32",
        ),
        Check("pytest", (python, "-m", "pytest", "-q"), repo_root),
        Check(
            "source-contract-validator",
            (python, str(source_validator), "--mode", "full"),
            repo_root,
        ),
        Check(
            "repo-lifecycle-promote-help",
            (python, "promote-repository.py", "--help"),
            lifecycle_scripts,
        ),
        Check(
            "repo-lifecycle-pending-work-help",
            (python, "manage-pending-work.py", "--help"),
            lifecycle_scripts,
        ),
        Check(
            "repo-lifecycle-deploy-operation-help",
            (python, "run-deploy-operation.py", "--help"),
            lifecycle_scripts,
        ),
        Check(
            "repo-lifecycle-ship-help",
            (python, "ship-repository.py", "--help"),
            lifecycle_scripts,
        ),
        Check(
            "repo-lifecycle-pr-ship-help",
            (python, "-m", "github_pr_workflow", "ship", "--help"),
            lifecycle_scripts,
        ),
        Check(
            "repo-lifecycle-codeql-disposition-help",
            (
                python,
                "-m",
                "github_contract_engine",
                "codeql-disposition",
                "--help",
            ),
            lifecycle_scripts,
        ),
    )


def evidence_text(
    check: Check, result: subprocess.CompletedProcess[str]
) -> str:
    """Render complete failed-child diagnostics for the selected evidence file."""

    lines = [
        f"check: {check.name}",
        f"exit_code: {result.returncode}",
        f"cwd: {check.cwd}",
        "command: "
        + json.dumps(list(check.command), separators=(",", ":"), ensure_ascii=True),
    ]
    if check.platform is not None:
        lines.insert(1, f"platform: {check.platform}")
    lines.extend(("stdout:", result.stdout or "", "stderr:", result.stderr or ""))
    return "\n".join(lines) + "\n"


def write_evidence(
    evidence_file: pathlib.Path,
    check: Check,
    result: subprocess.CompletedProcess[str],
) -> None:
    """Write one failure atomically enough for a caller-owned temporary path."""

    evidence_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = evidence_file.with_name(f".{evidence_file.name}.tmp")
    temporary.write_text(
        evidence_text(check, result), encoding="utf-8", newline="\n"
    )
    temporary.replace(evidence_file)


def run_checks(
    checks: Sequence[Check],
    evidence_file: pathlib.Path,
    *,
    process_runner: ProcessRunner = run_process,
) -> Failure | None:
    """Run checks in order and return immediately after the first failure."""

    for check in checks:
        try:
            result = process_runner(check.command, check.cwd)
        except OSError as exc:
            result = subprocess.CompletedProcess(
                list(check.command),
                COMMAND_NOT_FOUND_EXIT_CODE,
                "",
                f"{type(exc).__name__}: {exc}",
            )
        if result.returncode == 0:
            continue

        evidence_error = None
        try:
            write_evidence(evidence_file, check, result)
        except OSError as exc:
            evidence_error = f"{type(exc).__name__}: {exc}"
        return Failure(
            check=check.name,
            platform=check.platform,
            exit_code=result.returncode,
            evidence_file=evidence_file,
            evidence_error=evidence_error,
        )
    return None


def failure_payload(failure: Failure) -> dict[str, object]:
    """Return the compact caller-facing failure contract."""

    payload: dict[str, object] = {"check": failure.check}
    if failure.platform is not None:
        payload["platform"] = failure.platform
    payload["exit_code"] = failure.exit_code
    payload["evidence_file"] = str(failure.evidence_file)
    if failure.evidence_error is not None:
        payload["evidence_error"] = failure.evidence_error
    return payload


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    process_runner: ProcessRunner = run_process,
) -> int:
    """Resolve caller paths, execute validation, and emit one bounded result."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    environment = os.environ if environ is None else environ
    evidence_value = environment.get(EVIDENCE_FILE_ENV)
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    evidence_file = (
        pathlib.Path(evidence_value).expanduser().resolve()
        if evidence_value
        else repo_root
        / "build"
        / "deploy-validation"
        / "repository-validation.log"
    )
    if arguments:
        payload: dict[str, object] = {
            "check": "configuration",
            "exit_code": 2,
            "evidence_file": str(evidence_file),
        }
        payload["unexpected_arguments"] = arguments
        print(json.dumps(payload, separators=(",", ":"), ensure_ascii=True))
        return 2

    failure = run_checks(
        build_checks(repo_root),
        evidence_file,
        process_runner=process_runner,
    )
    if failure is None:
        print("OK")
        return 0

    print(
        json.dumps(
            failure_payload(failure), separators=(",", ":"), ensure_ascii=True
        )
    )
    return failure.exit_code if failure.exit_code > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
