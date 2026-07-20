"""Orchestrate validated GitHub PR merge and live result verification."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Any

from github_contract_engine.levels import ERROR, count_by_level

from . import codex_review, readiness
from .command import CommandError, require_output, require_success


class WorkflowError(RuntimeError):
    """Raised when a merge safety gate or live verification fails."""


def _validate_readiness(
    pr: str,
    repo_root: pathlib.Path,
    *,
    allow_admin_review_bypass: bool,
) -> None:
    contract_path = readiness.default_contract_path().resolve()
    _, findings = readiness.validate_readiness(
        pr,
        repo_root,
        contract_path,
        allow_admin_review_bypass=allow_admin_review_bypass,
    )
    counts = count_by_level(findings)
    if counts.get(ERROR, 0):
        failures = [
            f"{finding.check}: {finding.message}"
            for finding in findings
            if finding.level == ERROR
        ]
        raise WorkflowError("PR readiness failed: " + "; ".join(failures[:8]))


def _merge_working_directory(repo: str | None, repo_root: pathlib.Path) -> pathlib.Path:
    codex_home = os.environ.get("CODEX_HOME")
    if repo and codex_home:
        candidate = pathlib.Path(codex_home).expanduser()
        if candidate.is_dir():
            return candidate.resolve()
    return repo_root


def merge_pr(args: argparse.Namespace) -> dict[str, Any]:
    """Run readiness, review wait, merge mutation, and live verification."""

    repo_root = args.repo_root.expanduser().resolve(strict=True)
    if not repo_root.is_dir():
        raise WorkflowError(f"repository root is not a directory: {repo_root}")

    _validate_readiness(
        args.pr,
        repo_root,
        allow_admin_review_bypass=args.admin,
    )
    review = codex_review.wait_for_codex_threads(
        args.pr,
        args.repo,
        wait_seconds=args.wait_seconds,
        interval_seconds=args.interval_seconds,
        authors=codex_review.DEFAULT_CODEX_AUTHORS,
        cwd=repo_root,
    )
    if review["active_codex_thread_count"]:
        raise WorkflowError(
            f"Codex review gate found {review['active_codex_thread_count']} active thread(s)."
        )

    # The PR head and checks can change during the review wait.
    _validate_readiness(
        args.pr,
        repo_root,
        allow_admin_review_bypass=args.admin,
    )

    gh_args = ["gh", "pr", "merge", args.pr, f"--{args.merge_method}"]
    if args.admin:
        gh_args.append("--admin")
    if args.auto:
        gh_args.append("--auto")
    if args.delete_branch:
        gh_args.append("--delete-branch")
    if args.repo:
        gh_args.extend(["--repo", args.repo])
    working_directory = _merge_working_directory(args.repo, repo_root)
    require_success(gh_args, cwd=working_directory)

    view_args = [
        "gh",
        "pr",
        "view",
        args.pr,
        "--json",
        "number,url,state,mergedAt,mergeCommit",
    ]
    if args.repo:
        view_args.extend(["--repo", args.repo])
    pr_state = json.loads(require_output(view_args, cwd=working_directory))
    if not args.auto and pr_state.get("state") != "MERGED":
        raise WorkflowError(
            f"PR merge was not verified; live state is {pr_state.get('state')}."
        )
    merge_commit = pr_state.get("mergeCommit")
    return {
        "status": (
            "merged" if pr_state.get("state") == "MERGED" else "auto_merge_enabled"
        ),
        "pr": pr_state.get("number"),
        "url": pr_state.get("url"),
        "state": pr_state.get("state"),
        "merged_at": pr_state.get("mergedAt"),
        "merge_commit": (
            merge_commit.get("oid") if isinstance(merge_commit, dict) else None
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    """Create the merge command parser with the former helper's options."""

    parser = argparse.ArgumentParser(
        prog="python -m github_pr_workflow merge",
        description="Validate, merge, and live-verify one GitHub pull request."
    )
    parser.add_argument("--pr", required=True)
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--repo")
    parser.add_argument(
        "--merge-method", choices=("merge", "squash", "rebase"), default="merge"
    )
    parser.add_argument("--admin", action="store_true")
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--delete-branch", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=260)
    parser.add_argument("--interval-seconds", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run merge orchestration and emit exactly one compact JSON result."""

    args = build_parser().parse_args(argv)
    try:
        print(json.dumps(merge_pr(args), separators=(",", ":"), ensure_ascii=True))
        return 0
    except (
        CommandError,
        WorkflowError,
        readiness.CommandError,
        codex_review.CommandError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(
            json.dumps(
                {"status": "error", "message": str(exc)},
                separators=(",", ":"),
                ensure_ascii=True,
            ),
            file=sys.stderr,
        )
        return 1
