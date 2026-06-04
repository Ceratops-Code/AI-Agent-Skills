#!/usr/bin/env python3
"""Validate the deterministic GitHub pull-request readiness contract.

This script is intentionally narrow. Repository health, repo contents, and
artifact posture are owned by the other contract validators; this validator
answers the merge-decision contract that needs fresh PR state close to the final
action.

Called by merge, ship, dependency-maintenance, and create/publish workflows when a PR
merge decision is in scope. It reads GitHub PR metadata and local branch state;
it does not mutate the repository or GitHub.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Any

from validator_levels import ERROR, count_by_level


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
ROOT = SKILL_DIR.parent.parent if SKILL_DIR.parent.name == "skills" else SKILL_DIR


class CommandError(RuntimeError):
    """Raised when a required local command fails."""


@dataclass(frozen=True)
class Finding:
    """One machine-readable readiness finding."""

    level: str
    check: str
    message: str
    actual: object | None = None
    expected: object | None = None


def run_command(args: list[str], cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
    """Run a command without shell expansion and keep stdout/stderr separate."""

    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def require_command(args: list[str], cwd: pathlib.Path) -> str:
    """Run a command and return stdout, raising a compact error on failure."""

    completed = run_command(args, cwd)
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "command failed"
        raise CommandError(f"{' '.join(args)}: {stderr}")
    return completed.stdout.strip()


def current_branch(cwd: pathlib.Path) -> str | None:
    """Return the current git branch when the working directory is a checkout."""

    completed = run_command(["git", "branch", "--show-current"], cwd)
    if completed.returncode != 0:
        return None
    branch = completed.stdout.strip()
    return branch or None


def gh_pr_view(selector: str | None, cwd: pathlib.Path) -> dict[str, Any]:
    """Fetch the live PR fields used by the merge-readiness policy."""

    fields = [
        "number",
        "url",
        "state",
        "isDraft",
        "mergeable",
        "reviewDecision",
        "statusCheckRollup",
        "headRefName",
        "baseRefName",
        "autoMergeRequest",
    ]
    args = ["gh", "pr", "view", "--json", ",".join(fields)]
    if selector:
        args.append(selector)
    return json.loads(require_command(args, cwd))


def default_contract_path() -> pathlib.Path:
    """Find the bundled PR readiness contract in source or installed copies."""

    candidates = [
        pathlib.Path.cwd() / "github-pr-readiness-deterministic-contract.json",
        pathlib.Path.cwd() / "skills" / "ceratops-gh-repo-lifecycle" / "references" / "github-pr-readiness-deterministic-contract.json",
        ROOT / "skills" / "ceratops-gh-repo-lifecycle" / "references" / "github-pr-readiness-deterministic-contract.json",
        SKILL_DIR / "references" / "github-pr-readiness-deterministic-contract.json",
        SCRIPT_DIR / "github-pr-readiness-deterministic-contract.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return SKILL_DIR / "references" / "github-pr-readiness-deterministic-contract.json"


def load_contract(path: pathlib.Path) -> dict[str, Any]:
    """Load the PR readiness contract so finding IDs stay contract-backed."""

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def contract_check_ids(contract: dict[str, Any]) -> set[str]:
    """Return deterministic check IDs declared by the PR contract."""

    return {str(check.get("id")) for check in contract.get("checks", []) if check.get("id")}


def add(
    findings: list[Finding],
    level: str,
    check: str,
    message: str,
    *,
    actual: object | None = None,
    expected: object | None = None,
) -> None:
    """Append a finding with consistent field names."""

    findings.append(Finding(level=level, check=check, message=message, actual=actual, expected=expected))


def status_rollup_findings(pr_data: dict[str, Any], findings: list[Finding]) -> None:
    """Classify the visible status checks attached to the PR."""

    raw_rollup = pr_data.get("statusCheckRollup") or []
    if not isinstance(raw_rollup, list):
        add(findings, "WARN", "pr.status_checks", "Could not parse status-check rollup.", actual=type(raw_rollup).__name__)
        return
    if not raw_rollup:
        add(findings, "WARN", "pr.status_checks", "No status checks are attached to this PR.")
        return

    failed: list[str] = []
    pending: list[str] = []
    passed: list[str] = []
    for item in raw_rollup:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("context") or item.get("workflowName") or "unnamed-check")
        conclusion = item.get("conclusion")
        status = item.get("status")
        state = item.get("state")
        if conclusion in {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "NEUTRAL", "STALE"} or state in {"FAILURE", "ERROR"}:
            failed.append(name)
        elif status in {"IN_PROGRESS", "QUEUED", "PENDING", "WAITING"} or state in {"PENDING", "EXPECTED"} or (conclusion is None and state != "SUCCESS"):
            pending.append(name)
        else:
            passed.append(name)

    if failed:
        add(findings, "ERROR", "pr.status_checks", "One or more status checks are failing.", actual=failed)
    elif pending:
        add(findings, "WARN", "pr.status_checks", "Status checks are still pending.", actual=pending)
    else:
        add(findings, "PASS", "pr.status_checks", "All visible status checks are passing.", actual=passed)


def pr_readiness(selector: str | None, cwd: pathlib.Path, *, allow_admin_review_bypass: bool = False) -> tuple[dict[str, object], list[Finding]]:
    """Evaluate the live PR state needed before merge or auto-merge."""

    pr_data = gh_pr_view(selector, cwd)
    findings: list[Finding] = []

    if pr_data.get("state") == "OPEN":
        add(findings, "PASS", "pr.state_open", "PR is open.")
    else:
        add(findings, "ERROR", "pr.state_open", "PR is not open.", actual=pr_data.get("state"), expected="OPEN")

    if pr_data.get("isDraft") is True:
        add(findings, "ERROR", "pr.not_draft", "PR is still marked draft.", actual=True, expected=False)
    else:
        add(findings, "PASS", "pr.not_draft", "PR is ready for review.")

    mergeable = pr_data.get("mergeable")
    if mergeable == "CONFLICTING":
        add(findings, "ERROR", "pr.mergeable", "PR has merge conflicts.", actual=mergeable)
    elif mergeable == "MERGEABLE":
        add(findings, "PASS", "pr.mergeable", "PR is mergeable.", actual=mergeable)
    else:
        add(findings, "WARN", "pr.mergeable", "PR mergeability needs a live re-check.", actual=mergeable)

    review_decision = pr_data.get("reviewDecision")
    if review_decision in {"APPROVED", None, ""}:
        add(findings, "PASS", "pr.review_decision", "No blocking review decision is present.", actual=review_decision)
    elif review_decision == "REVIEW_REQUIRED" and allow_admin_review_bypass:
        add(findings, "WARN", "pr.review_decision", "Required review is bypassable by explicitly authorized admin direct merge.", actual=review_decision, expected="APPROVED or admin bypass")
    elif review_decision == "REVIEW_REQUIRED":
        add(findings, "ERROR", "pr.review_decision", "PR still requires review before merge.", actual=review_decision, expected="APPROVED")
    else:
        add(findings, "ERROR", "pr.review_decision", "PR has a blocking review decision.", actual=review_decision, expected="APPROVED")

    status_rollup_findings(pr_data, findings)

    if pr_data.get("autoMergeRequest"):
        add(findings, "PASS", "pr.auto_merge_request", "Auto-merge is already configured.", actual=True)
    else:
        add(findings, "WARN", "pr.auto_merge_request", "Auto-merge is not configured.", actual=False)

    summary = {
        "number": pr_data.get("number"),
        "url": pr_data.get("url"),
        "base": pr_data.get("baseRefName"),
        "head": pr_data.get("headRefName"),
    }
    return summary, findings


def emit(summary: dict[str, object], findings: list[Finding], *, as_json: bool, contract_path: pathlib.Path) -> int:
    """Print JSON or compact text and return an error status only on ERROR."""

    counts = count_by_level(findings)

    payload = {
        "contract": str(contract_path),
        "summary": summary,
        "counts": counts,
        "findings": [asdict(finding) for finding in findings],
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"summary: {json.dumps(summary, sort_keys=True)}")
        print(f"counts: {json.dumps(counts, sort_keys=True)}")
        for finding in findings:
            print(f"[{finding.level}] {finding.check}: {finding.message}")
            if finding.actual is not None:
                print(f"  actual: {json.dumps(finding.actual, sort_keys=True)}")
            if finding.expected is not None:
                print(f"  expected: {json.dumps(finding.expected, sort_keys=True)}")
    return 1 if counts.get(ERROR, 0) else 0


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""

    parser = argparse.ArgumentParser(description="Validate the live GitHub PR readiness contract before merge.")
    parser.add_argument("--contract", type=pathlib.Path, default=default_contract_path(), help="PR readiness deterministic contract JSON.")
    parser.add_argument("--cwd", type=pathlib.Path, default=pathlib.Path.cwd(), help="Repo working directory used for git and gh context.")
    parser.add_argument("--pr", help="PR number, URL, or branch. Defaults to the PR attached to the current branch.")
    parser.add_argument("--allow-admin-review-bypass", action="store_true", help="Warn instead of error when REVIEW_REQUIRED is the only review blocker for an explicitly authorized admin direct merge.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main() -> int:
    """Parse CLI arguments, evaluate the live PR, and emit the report."""

    parser = build_parser()
    args = parser.parse_args()
    cwd = args.cwd.resolve()
    try:
        contract_path = args.contract.resolve()
        contract = load_contract(contract_path)
        selector = args.pr
        if selector is None:
            selector = current_branch(cwd)
        summary, findings = pr_readiness(selector, cwd, allow_admin_review_bypass=args.allow_admin_review_bypass)
        unknown = sorted({finding.check for finding in findings} - contract_check_ids(contract))
        if unknown:
            add(findings, "ERROR", "contract.unknown_check_ids", "Validator emitted checks missing from the PR readiness contract.", actual=unknown)
        return emit(summary, findings, as_json=args.json, contract_path=contract_path)
    except CommandError as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, sort_keys=True))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
