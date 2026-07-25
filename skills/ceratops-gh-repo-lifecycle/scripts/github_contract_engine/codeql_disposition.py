"""Validate exact CodeQL evidence before suppression or authorized dismissal.

The evidence document is intentionally small and test-produced. It binds one
live CodeQL alert to one full commit, records a successful source-to-sink
exercise with sentinel credentials, and supplies captured output that proves
the sentinel values were replaced by the contract engine's redaction marker.
Only the dismissal action mutates GitHub, and only with an explicit CLI gate.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from typing import Any

from .format_report import REDACTED, write_json
from .github_api import load_json, run_gh_api


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SENTINEL_PREFIX = "CODEQL_SENTINEL_"
DISMISSAL_REASONS = ("false positive", "won't fix", "used in tests")


class DispositionError(RuntimeError):
    """Raised when live alert state or local evidence is not disposition-safe."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DispositionError(message)


def fetch_alert(repository: str, alert_number: int) -> dict[str, Any]:
    """Fetch the current alert through the package's shared GitHub API client."""

    endpoint = f"/repos/{repository}/code-scanning/alerts/{alert_number}"
    result = run_gh_api("GET", endpoint)
    if not result.ok:
        raise DispositionError(
            f"CodeQL alert read failed: {result.message or result.status}"
        )
    if not isinstance(result.data, dict):
        raise DispositionError("GitHub returned an invalid code scanning alert.")
    return result.data


def _location(value: Any, label: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"Evidence {label} location is missing.")
    path = value.get("path")
    line = value.get("line")
    _require(isinstance(path, str) and bool(path), f"Evidence {label} path is missing.")
    _require(
        isinstance(line, int) and line > 0,
        f"Evidence {label} line must be a positive integer.",
    )
    return value


def validate_evidence(
    evidence: dict[str, Any],
    alert: dict[str, Any],
    *,
    repository: str,
    alert_number: int,
    commit: str,
    disposition: str,
) -> dict[str, Any]:
    """Validate alert identity, executed trace, sentinel input, and safe output."""

    _require(evidence.get("version") == 1, "Evidence version must be 1.")
    _require(
        str(evidence.get("repository", "")).casefold() == repository.casefold(),
        "Evidence repository does not match the requested repository.",
    )
    _require(
        evidence.get("alert_number") == alert_number,
        "Evidence alert number does not match the requested alert.",
    )
    _require(
        evidence.get("commit_sha") == commit,
        "Evidence commit does not match the requested full commit.",
    )
    _require(
        evidence.get("disposition") == disposition,
        "Evidence disposition does not match the requested action.",
    )

    _require(alert.get("number") == alert_number, "Live alert number drifted.")
    tool = alert.get("tool") or {}
    _require(
        isinstance(tool, dict)
        and str(tool.get("name", "")).casefold() == "codeql",
        "The current alert was not produced by CodeQL.",
    )
    rule = alert.get("rule") or {}
    rule_id = rule.get("id") if isinstance(rule, dict) else None
    _require(
        isinstance(rule_id, str) and evidence.get("rule_id") == rule_id,
        "Evidence rule does not match the current CodeQL alert.",
    )
    instance = alert.get("most_recent_instance") or {}
    _require(
        isinstance(instance, dict) and instance.get("state") == "open",
        "The current CodeQL alert instance must still be open for disposition.",
    )
    _require(
        isinstance(instance, dict) and instance.get("commit_sha") == commit,
        "The current alert instance is not tied to the requested commit.",
    )
    alert_location = instance.get("location") or {}
    _require(
        isinstance(alert_location, dict),
        "The current alert instance has no source location.",
    )

    source_to_sink = evidence.get("source_to_sink") or {}
    _require(
        isinstance(source_to_sink, dict)
        and source_to_sink.get("exercised") is True,
        "Evidence must confirm that the reported source-to-sink path executed.",
    )
    trace = source_to_sink.get("trace")
    if not isinstance(trace, list) or len(trace) < 2:
        raise DispositionError(
            "Evidence source-to-sink trace must contain at least source and sink."
        )
    source = _location(trace[0], "source")
    sink = _location(trace[-1], "sink")
    _require(source.get("role") == "source", "Evidence trace must start at source.")
    _require(sink.get("role") == "sink", "Evidence trace must end at sink.")
    _require(
        sink.get("path") == alert_location.get("path")
        and sink.get("line") == alert_location.get("start_line"),
        "Evidence sink does not match the current alert location.",
    )

    execution = evidence.get("execution") or {}
    _require(
        isinstance(execution, dict) and execution.get("exit_code") == 0,
        "Evidence execution must have a successful exit code.",
    )
    command = execution.get("command")
    _require(
        isinstance(command, list)
        and bool(command)
        and all(isinstance(item, str) and item for item in command),
        "Evidence execution command must be a non-empty argument list.",
    )
    sentinels = execution.get("sentinel_credentials")
    if not isinstance(sentinels, dict) or not sentinels:
        raise DispositionError(
            "Evidence execution must declare sentinel credentials."
        )
    raw_sentinel_values = list(sentinels.values())
    if not all(
        isinstance(value, str)
        and value.startswith(SENTINEL_PREFIX)
        and len(value) > len(SENTINEL_PREFIX)
        for value in raw_sentinel_values
    ):
        raise DispositionError(
            f"Every sentinel credential must start with {SENTINEL_PREFIX}."
        )
    sentinel_values = [str(value) for value in raw_sentinel_values]
    _require(
        len(set(sentinel_values)) == len(sentinel_values),
        "Sentinel credential values must be unique.",
    )
    captured_output = execution.get("captured_output")
    if not isinstance(captured_output, str):
        raise DispositionError("Evidence execution must include captured output.")
    leaked = [value for value in sentinel_values if value in captured_output]
    _require(not leaked, "Captured output still contains a sentinel credential.")
    _require(
        REDACTED in captured_output,
        f"Captured output must contain the sanitizer marker {REDACTED}.",
    )

    return {
        "repository": repository,
        "alert_number": alert_number,
        "commit": commit,
        "rule_id": rule_id,
        "source": {"path": source["path"], "line": source["line"]},
        "sink": {"path": sink["path"], "line": sink["line"]},
        "sentinel_count": len(sentinel_values),
        "sanitized": True,
    }


def disposition(args: argparse.Namespace) -> dict[str, Any]:
    """Validate evidence and optionally perform an authorized dismissal."""

    repository = args.repo.strip()
    _require(repository.count("/") == 1, "--repo must use OWNER/REPO.")
    commit = args.commit.lower()
    _require(
        bool(FULL_SHA_RE.fullmatch(commit)),
        "--commit must be a full 40-character Git commit SHA.",
    )
    evidence = load_json(args.evidence)
    _require(isinstance(evidence, dict), "Evidence must be one JSON object.")
    alert = fetch_alert(repository, args.alert_number)
    summary = validate_evidence(
        evidence,
        alert,
        repository=repository,
        alert_number=args.alert_number,
        commit=commit,
        disposition=args.action,
    )

    if args.action == "suppression":
        return {
            "status": "evidence_accepted",
            "action": "suppression",
            "mutated": False,
            "evidence": summary,
        }

    _require(
        args.dismissed_reason in DISMISSAL_REASONS,
        "Dismissal requires a supported --dismissed-reason.",
    )
    _require(
        isinstance(args.dismissed_comment, str)
        and bool(args.dismissed_comment.strip()),
        "Dismissal requires a non-empty --dismissed-comment.",
    )
    if not args.authorize_dismissal:
        return {
            "status": "authorization_required",
            "action": "dismissal",
            "mutated": False,
            "dismissed_reason": args.dismissed_reason,
            "evidence": summary,
        }
    endpoint = (
        f"/repos/{repository}/code-scanning/alerts/{args.alert_number}"
    )
    result = run_gh_api(
        "PATCH",
        endpoint,
        {
            "state": "dismissed",
            "dismissed_reason": args.dismissed_reason,
            "dismissed_comment": args.dismissed_comment,
        },
    )
    if not result.ok:
        raise DispositionError(
            f"CodeQL alert dismissal failed: {result.message or result.status}"
        )
    updated = result.data
    _require(
        isinstance(updated, dict)
        and updated.get("number") == args.alert_number
        and updated.get("state") == "dismissed",
        "GitHub did not verify the alert as dismissed.",
    )
    updated_instance = updated.get("most_recent_instance") or {}
    _require(
        isinstance(updated_instance, dict)
        and updated_instance.get("commit_sha") == commit,
        "Dismissed alert response no longer matches the authorized commit.",
    )
    return {
        "status": "dismissed",
        "action": "dismissal",
        "mutated": True,
        "dismissed_reason": updated.get("dismissed_reason"),
        "evidence": summary,
    }


def build_parser() -> argparse.ArgumentParser:
    """Create the CodeQL disposition parser."""

    parser = argparse.ArgumentParser(
        prog="python -m github_contract_engine codeql-disposition",
        description="Gate CodeQL suppression or dismissal on exact safe evidence.",
    )
    parser.add_argument("--repo", required=True, help="OWNER/REPO")
    parser.add_argument("--alert-number", required=True, type=int)
    parser.add_argument("--commit", required=True, help="full alert-instance SHA")
    parser.add_argument("--evidence", required=True, type=pathlib.Path)
    parser.add_argument(
        "--action", required=True, choices=("suppression", "dismissal")
    )
    parser.add_argument("--dismissed-reason", choices=DISMISSAL_REASONS)
    parser.add_argument("--dismissed-comment")
    parser.add_argument("--authorize-dismissal", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the evidence gate and emit one sanitized compact JSON document."""

    args = build_parser().parse_args(argv)
    try:
        write_json(disposition(args), compact=True)
        return 0
    except (DispositionError, OSError, ValueError, json.JSONDecodeError) as exc:
        write_json({"status": "error", "message": str(exc)}, compact=True)
        return 1
