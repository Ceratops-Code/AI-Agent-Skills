"""Run declared update checks and carry their evidence to the workflow.

The workflow owns path validation and temporary check cleanup. Processes run
without a shell; check failures retain evidence for the caller-selected file.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence

MAX_CAPTURE = 32_000
MAX_COMPACT_DETAIL = 1_000
MAX_FAILURE_OUTPUT = 4_000


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


def _pytest_failures(report: pathlib.Path) -> tuple[list[dict[str, str]], str | None]:
    """Retain pytest's native identities, messages, and tracebacks before cleanup.

    JUnit classname/name pairs are identities, not reconstructed node IDs: file
    locations and dotted class names cannot losslessly recover every node ID.
    Raw terminal capture may be truncated, so it is not our failure inventory.
    """
    try:
        root = ET.parse(report).getroot()
    except FileNotFoundError:
        return [], "pytest failure report is missing"
    except (OSError, ET.ParseError) as exc:
        return [], f"pytest failure report is unreadable: {exc}"
    if root.tag not in {"testsuite", "testsuites"}:
        return [], "pytest failure report has an unexpected root"
    failures = []
    for case in root.iter("testcase"):
        identity = "::".join(
            part for part in (case.get("classname"), case.get("name")) if part
        ) or "unidentified test"
        for failure in case:
            if failure.tag in {"failure", "error"}:
                failures.append({
                    "test": identity,
                    "kind": failure.tag,
                    "message": failure.get("message", ""),
                    "detail": "".join(failure.itertext()),
                })
    return failures, None


def _compact_failure_output(value: str, *, tail: bool = False) -> str:
    """Bound direct diagnostics, explicitly referring to retained full evidence."""
    value = " ".join(value.split())
    marker = "[output omitted; full details in evidence]"
    if len(value) <= MAX_FAILURE_OUTPUT:
        return value
    size = MAX_FAILURE_OUTPUT - len(marker) - 1
    return f"{marker} {value[-size:]}" if tail else f"{value[:size]} {marker}"


def _pytest_failure_message(
    result: subprocess.CompletedProcess[str], evidence: dict[str, object],
    failures: list[dict[str, str]], report_error: str | None,
) -> str:
    """Report the same run's failures; unavailable reports use the terminal tail."""
    prefix = f"pytest check failed (exit {result.returncode})"
    if failures:
        messages = []
        for failure in failures:
            message = failure["message"] or failure["detail"]
            if message in {"collection failure", "internal error"}:
                detail_lines = failure["detail"].strip().splitlines()
                if detail_lines:
                    message += ": " + detail_lines[-1]
            messages.append(f"{failure['test']} [{failure['kind']}]: {message}")
        return f"{prefix}, {len(failures)} reported: " + _compact_failure_output(
            "; ".join(messages)
        )
    diagnostic = "\n".join(
        stream.strip() for stream in (result.stderr, result.stdout) if stream.strip()
    )
    # A startup/internal error may never create XML. Preserve the full fallback
    # separately, since the legacy stdout/stderr evidence fields are bounded.
    evidence["failure_diagnostic"] = diagnostic
    reason = report_error or "pytest reported no failed test details"
    if diagnostic:
        return f"{prefix}: {reason}; " + _compact_failure_output(diagnostic, tail=True)
    return f"{prefix}: {reason}; no terminal diagnostic was emitted"


def _run_check(
    repo_root: pathlib.Path,
    check: Mapping[str, object],
    environment: Mapping[str, str],
    *,
    resolve_target: Callable[[pathlib.Path, str], pathlib.Path],
    search_applicability: Callable[[Mapping[str, object]], str],
) -> dict[str, object]:
    kind = check.get("kind")
    if kind == "pytest":
        nodes = check.get("nodes")
        if not isinstance(nodes, list) or not all(isinstance(node, str) for node in nodes):
            raise UpdateExecutionError("state pytest check is invalid")
        # check_environment owns this unique directory on success and failure.
        report = pathlib.Path(tempfile.mkdtemp(
            prefix="pytest-report-", dir=environment["TMPDIR"],
        )) / "results.xml"
        argv = [
            sys.executable, "-m", "pytest", "-q", *nodes,
            f"--junitxml={report}",
        ]
        selection: dict[str, object] = {"nodes": nodes}
    elif kind == "command":
        raw_argv = check.get("argv")
        if not isinstance(raw_argv, list) or not all(
            isinstance(item, str) for item in raw_argv
        ):
            raise UpdateExecutionError("state command check is invalid")
        argv = [str(item) for item in raw_argv]
        selection = {"argv": argv}
    if kind in {"pytest", "command"}:
        result = _run(argv, cwd=repo_root, environment=environment)
        evidence = {
            "kind": kind,
            **selection,
            "returncode": result.returncode,
            "stdout": _bounded(result.stdout),
            "stderr": _bounded(result.stderr),
            "reused": False,
        }
        if kind == "pytest":
            failures, report_error = _pytest_failures(report)
            evidence["failures"] = failures
            if report_error:
                evidence["report_error"] = report_error
        if result.returncode:
            message = (
                _pytest_failure_message(result, evidence, failures, report_error)
                if kind == "pytest" else f"command check failed with {result.returncode}"
            )
            raise CheckFailure(message, evidence)
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
