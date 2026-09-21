"""Run declared update checks and carry their evidence to the workflow.

The workflow owns path validation and temporary check cleanup. Processes run
without a shell; check failures retain evidence for the caller-selected file.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence

MAX_CAPTURE = 32_000


class UpdateExecutionError(RuntimeError):
    """One compact request, baseline, check, or evidence failure."""


def _run(
    arguments: Sequence[str],
    *,
    cwd: pathlib.Path,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one declared process without shell interpretation."""

    try:
        return subprocess.run(
            list(arguments),
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise UpdateExecutionError(
            f"could not start {arguments[0]}: {exc}"
        ) from exc


def _bounded(value: str) -> str:
    return value if len(value) <= MAX_CAPTURE else value[:MAX_CAPTURE] + "\n[truncated]"


def validate_non_test_command(arguments: Sequence[str]) -> None:
    """Reject direct test entrypoints, preserving arguments to ordinary scripts.

    Unwrap the supported Python/uv launch forms, rather than banning words in
    argument payloads. This is workflow validation, not a sandbox for arbitrary
    caller-authored programs; declared commands must perform non-test checks.
    """
    argv = list(arguments)
    name = pathlib.PureWindowsPath(argv[0]).name.lower()
    if name in {"uv", "uv.exe"} and "run" in argv:
        argv = argv[argv.index("run") + 1:]
        value_options = {"--python", "--project", "--directory", "--with", "--with-editable", "--with-requirements", "--package"}
        while argv and argv[0].startswith("-"):
            option = argv.pop(0)
            if option in value_options and argv:
                argv.pop(0)
        if not argv:
            return
        name = pathlib.PureWindowsPath(argv[0]).name.lower()
    if re.fullmatch(r"(?:python(?:[0-9.]+)?|py)(?:\.exe)?", name):
        argv = argv[1:]
        while argv and argv[0].startswith("-"):
            option = argv.pop(0)
            if option in {"-c", "--help", "--version"}:
                return
            if option == "-m":
                break
            if option in {"-W", "-X"} and argv:
                argv.pop(0)
        if not argv:
            return
        name = pathlib.PureWindowsPath(argv[0]).name.lower()
    if name in {"pytest", "pytest.exe", "py.test", "py.test.exe", "unittest", "run-tests.py", "run-tests", "tox", "tox.exe", "nox", "nox.exe"}:
        raise UpdateExecutionError("test-runner commands belong to repository SDLC tests")


def _run_check(
    repo_root: pathlib.Path,
    check: Mapping[str, object],
    environment: Mapping[str, str],
    *,
    resolve_target: Callable[[pathlib.Path, str], pathlib.Path],
    search_applicability: Callable[[Mapping[str, object]], str],
) -> dict[str, object]:
    kind = check.get("kind")
    if kind == "command":
        raw_argv = check.get("argv")
        if not isinstance(raw_argv, list) or not all(
            isinstance(item, str) for item in raw_argv
        ):
            raise UpdateExecutionError("state command check is invalid")
        argv = [str(item) for item in raw_argv]
        validate_non_test_command(argv)
        selection = {"argv": argv}
        result = _run(argv, cwd=repo_root, environment=environment)
        evidence = {
            "kind": kind,
            **selection,
            "returncode": result.returncode,
            "stdout": _bounded(result.stdout),
            "stderr": _bounded(result.stderr),
            "reused": False,
        }
        if result.returncode:
            raise CheckFailure(f"command check failed with {result.returncode}", evidence)
        return evidence
    if kind != "search":
        raise UpdateExecutionError("state check kind is invalid")
    pattern = check.get("pattern")
    paths = check.get("paths")
    expected = check.get("expected_matches")
    if (
        not isinstance(pattern, str)
        or not isinstance(paths, list)
        or not all(isinstance(path, str) for path in paths)
        or not isinstance(expected, int)
        or isinstance(expected, bool)
    ):
        raise UpdateExecutionError("state search check is invalid")
    regex = re.compile(pattern)
    applicability_sha256 = search_applicability(check)
    matches = 0
    for path in paths:
        target = resolve_target(repo_root, path)
        if target.is_symlink() or not target.is_file():
            raise UpdateExecutionError(f"search path does not exist: {path}")
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise UpdateExecutionError(f"search path is unreadable: {path}: {exc}") from exc
        matches += sum(1 for _ in regex.finditer(text))
    final_applicability_sha256 = search_applicability(check)
    evidence = {
        "kind": kind,
        "pattern": pattern,
        "paths": paths,
        "expected_matches": expected,
        "actual_matches": matches,
        "returncode": 0 if matches == expected else 1,
        "applicability_sha256": applicability_sha256,
        "reused": False,
    }
    if applicability_sha256 != final_applicability_sha256:
        evidence["returncode"] = 1
        raise CheckFailure("search inputs changed while check was running", evidence)
    if matches != expected:
        raise CheckFailure(
            f"search expected {expected} matches, found {matches}", evidence
        )
    return evidence


class CheckFailure(UpdateExecutionError):
    """A check failure that carries its detailed evidence record."""

    def __init__(self, message: str, evidence: dict[str, object]) -> None:
        super().__init__(message)
        self.evidence = evidence
