#!/usr/bin/env python3
"""Run the complete repository-owned local validation sequence.

``--evidence-file`` selects first-failure evidence. Child output is suppressed
on success and written in full only for the first failed check. A successful
run removes stale evidence at that exact path and prunes only the dedicated
default evidence directory when empty. Commands use argv lists, and managed
runtime installation remains outside this aggregate. Tests delegate to
``scripts/run-tests.py --all`` with a complete failure-diagnostic destination;
CI may use ``--without-tests`` only when a separate explicit invocation of that
same runner owns the job's test phase.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import platform
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

COMMAND_NOT_FOUND_EXIT_CODE = 127
MAX_FORWARDED_PYTEST_FAILURES = 10
PYTEST_IDENTITY_BYTES = 400
PYTEST_LOCATION_BYTES = 500
PYTEST_FAILURE_EXCERPT_BYTES = 800


@dataclass(frozen=True)
class Check:
    """Describe one ordered validation command and its reporting identity."""

    name: str
    command: tuple[str, ...]
    cwd: pathlib.Path
    platform: str | None = None


@dataclass(frozen=True)
class Failure:
    """Describe one failed check without retaining its full diagnostic streams."""

    check: str
    platform: str | None
    exit_code: int
    evidence_file: pathlib.Path
    evidence_error: str | None = None
    details: dict[str, object] | None = None


ProcessRunner = Callable[
    [Sequence[str], pathlib.Path], subprocess.CompletedProcess[str]
]


def require_repository_python(repo_root: pathlib.Path) -> None:
    """Reject a mismatched interpreter before any checks or child side effects.

    The standard project requirement is also consumed by uv local setup and CI.
    Use packaging's PEP 440 parser rather than maintaining a version grammar.
    This check does not install or switch Python or modify the environment.
    """

    from packaging.specifiers import SpecifierSet
    from packaging.version import Version

    metadata = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata.get("project")
    requirement = project.get("requires-python") if isinstance(project, dict) else None
    if not isinstance(requirement, str) or not requirement.strip():
        raise ValueError("pyproject.toml must declare project.requires-python")
    version = Version(platform.python_version())
    if version not in SpecifierSet(requirement):
        raise ValueError(
            f"Python {version} does not satisfy project.requires-python={requirement!r}; "
            "use the interpreter selected by uv python find --system"
        )


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
    test_diagnostic_file: pathlib.Path | None = None,
    include_tests: bool = True,
) -> tuple[Check, ...]:
    """Build the single canonical repository-validation sequence."""

    python = python_executable or sys.executable
    npm = npm_executable or ("npm.cmd" if sys.platform == "win32" else "npm")
    pytest_diagnostic = test_diagnostic_file or (
        repo_root / "build" / "test-diagnostics" / "pytest-failure.json"
    )
    checks: tuple[Check, ...] = (
        Check("markdown-lint", (npm, "run", "lint:markdown"), repo_root),
        Check(
            "yaml-lint",
            (python, "-m", "yamllint", "."),
            repo_root,
        ),
        Check(
            "ruff",
            (
                python,
                "-m",
                "ruff",
                "check",
                "scripts",
                "tools",
                "skills/ceratops-repo-lifecycle/references/templates/"
                "deploy-skills-template.py",
            ),
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
    )
    if include_tests:
        checks += (
            Check(
                "pytest",
                (
                    python,
                    "scripts/run-tests.py",
                    "--all",
                    "--diagnostic-output",
                    str(pytest_diagnostic),
                ),
                repo_root,
            ),
        )
    return checks


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


def _utf8_prefix(value: str, limit: int) -> str:
    """Return a valid UTF-8 prefix whose encoded representation fits ``limit``."""

    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    if limit <= 3:
        return "." * limit
    prefix = encoded[: limit - 3].decode("utf-8", errors="ignore").rstrip()
    return prefix + "..."


def _nonnegative_int(value: object) -> int | None:
    """Accept JSON integers suitable for bounded count fields."""

    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def pytest_failure_details(stdout: str) -> dict[str, object] | None:
    """Allowlist bounded actionable details from the repository test runner."""

    try:
        child_payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(child_payload, Mapping):
        return None
    if child_payload.get("status") != "pytest-failed":
        return None
    pytest_payload = child_payload.get("pytest")
    if not isinstance(pytest_payload, Mapping):
        return None

    failures: list[dict[str, object]] = []
    raw_failures = pytest_payload.get("failures")
    if isinstance(raw_failures, list):
        for raw_failure in raw_failures[:MAX_FORWARDED_PYTEST_FAILURES]:
            if not isinstance(raw_failure, Mapping):
                continue
            identity = raw_failure.get("test")
            if not isinstance(identity, str) or not identity:
                continue
            location = raw_failure.get("source_location")
            excerpt = raw_failure.get("excerpt")
            failures.append(
                {
                    "test": _utf8_prefix(identity, PYTEST_IDENTITY_BYTES),
                    "source_location": (
                        _utf8_prefix(location, PYTEST_LOCATION_BYTES)
                        if isinstance(location, str)
                        else None
                    ),
                    "excerpt": (
                        _utf8_prefix(excerpt, PYTEST_FAILURE_EXCERPT_BYTES)
                        if isinstance(excerpt, str)
                        else ""
                    ),
                }
            )

    reported_count = _nonnegative_int(pytest_payload.get("failure_count"))
    failure_count = max(len(failures), reported_count or 0)
    details: dict[str, object] = {
        "failure_count": failure_count,
        "omitted_failure_count": max(0, failure_count - len(failures)),
        "failures": failures,
    }

    raw_diagnostic = pytest_payload.get("diagnostic")
    if isinstance(raw_diagnostic, Mapping):
        diagnostic: dict[str, object] = {}
        byte_count = _nonnegative_int(raw_diagnostic.get("bytes"))
        if byte_count is not None:
            diagnostic["bytes"] = byte_count
        for key, limit in (("path", 2_000), ("sha256", 128), ("error", 1_000)):
            value = raw_diagnostic.get(key)
            if isinstance(value, str):
                diagnostic[key] = _utf8_prefix(value, limit)
        if diagnostic:
            details["diagnostic"] = diagnostic
    return details


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
            details=(
                pytest_failure_details(result.stdout)
                if check.name == "pytest"
                else None
            ),
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
    if failure.details is not None:
        payload.update(failure.details)
    return payload


def cleanup_evidence(
    evidence_file: pathlib.Path,
    *,
    prune_default_parent: bool,
) -> None:
    """Remove stale failure evidence after success and only its owned directory."""

    evidence_file.unlink(missing_ok=True)
    evidence_file.with_name(f".{evidence_file.name}.tmp").unlink(missing_ok=True)
    if prune_default_parent:
        try:
            evidence_file.parent.rmdir()
        except FileNotFoundError:
            pass
        except OSError:
            if not evidence_file.parent.is_dir() or any(
                evidence_file.parent.iterdir()
            ):
                return
            raise


def main(
    argv: Sequence[str] | None = None,
    *,
    process_runner: ProcessRunner = run_process,
) -> int:
    """Resolve caller paths, execute validation, and emit one bounded result."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--evidence-file", type=pathlib.Path)
    parser.add_argument("--without-tests", action="store_true")
    parsed, unexpected = parser.parse_known_args(arguments)
    evidence_file = (
        parsed.evidence_file.expanduser().resolve()
        if parsed.evidence_file
        else repo_root
        / "build"
        / "deploy-validation"
        / "repository-validation.log"
    )
    if unexpected:
        payload: dict[str, object] = {
            "check": "configuration",
            "exit_code": 2,
            "evidence_file": str(evidence_file),
        }
        payload["unexpected_arguments"] = unexpected
        print(json.dumps(payload, separators=(",", ":"), ensure_ascii=True))
        return 2

    failure: Failure | None
    try:
        require_repository_python(repo_root)
    except (ImportError, OSError, ValueError) as exc:
        reason = _utf8_prefix(str(exc), 2_000)
        check = Check("python-requirement", (sys.executable, __file__, *arguments), repo_root)
        evidence_error = None
        try:
            write_evidence(
                evidence_file,
                check,
                subprocess.CompletedProcess(check.command, 2, "", reason),
            )
        except OSError as evidence_exc:
            evidence_error = _utf8_prefix(str(evidence_exc), 1_000)
        failure = Failure(
            check=check.name,
            platform=None,
            exit_code=2,
            evidence_file=evidence_file,
            evidence_error=evidence_error,
            details={"reason": reason},
        )
    else:
        failure = run_checks(
            build_checks(repo_root, include_tests=not parsed.without_tests),
            evidence_file,
            process_runner=process_runner,
        )
    if failure is None:
        try:
            cleanup_evidence(
                evidence_file,
                prune_default_parent=parsed.evidence_file is None,
            )
        except OSError as exc:
            print(
                json.dumps(
                    {
                        "check": "evidence-cleanup",
                        "exit_code": 1,
                        "evidence_file": str(evidence_file),
                        "cleanup_error": f"{type(exc).__name__}: {exc}",
                    },
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
            )
            return 1
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
