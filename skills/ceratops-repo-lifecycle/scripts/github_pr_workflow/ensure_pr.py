"""Push one prepared branch and ensure its open GitHub PR matches local HEAD."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from collections.abc import Mapping
from typing import Any

from .command import CommandError, require_output, require_success


class EnsurePrError(RuntimeError):
    """Raised when a prepared branch cannot be published safely."""


def _git(repo_root: pathlib.Path, *args: str) -> list[str]:
    return ["git", "-C", str(repo_root), *args]


def _open_pr(args: argparse.Namespace) -> dict[str, Any] | None:
    raw = require_output(
        [
            "gh",
            "pr",
            "list",
            "--head",
            args.head_branch,
            "--base",
            args.base_branch,
            "--state",
            "open",
            "--limit",
            "1",
            "--json",
            "number,url,headRefOid,changedFiles,state,isDraft,statusCheckRollup",
        ],
        cwd=args.repo_root,
    )
    value = json.loads(raw or "[]")
    if not isinstance(value, list):
        raise EnsurePrError("gh pr list returned a non-list response")
    if not value:
        return None
    item = value[0]
    if not isinstance(item, dict):
        raise EnsurePrError("gh pr list returned an invalid PR record")
    return item


def wait_for_pr_head(
    args: argparse.Namespace,
    expected_head: str,
    *,
    max_attempts: int = 6,
    delay_seconds: float = 2,
) -> dict[str, Any]:
    """Bound GitHub propagation retries without hiding durable head drift."""

    last_pr: dict[str, Any] | None = None
    for attempt in range(1, max_attempts + 1):
        last_pr = _open_pr(args)
        if last_pr is not None and last_pr.get("headRefOid") == expected_head:
            return last_pr
        if attempt < max_attempts:
            time.sleep(delay_seconds)
    if last_pr is None:
        raise EnsurePrError(
            f"Open PR for {args.head_branch!r} was not observed after {max_attempts} attempts."
        )
    raise EnsurePrError(
        f"Open PR head {last_pr.get('headRefOid')!r} did not match local head "
        f"{expected_head!r} after {max_attempts} attempts."
    )


def _check_summary(value: object) -> dict[str, int]:
    summary: dict[str, int] = {}
    if not isinstance(value, list):
        return summary
    for check in value:
        state = "UNKNOWN"
        if isinstance(check, Mapping):
            for field in ("conclusion", "status", "state"):
                candidate = check.get(field)
                if isinstance(candidate, str) and candidate.strip():
                    state = candidate
                    break
        summary[state] = summary.get(state, 0) + 1
    return summary


def ensure_pr(args: argparse.Namespace) -> dict[str, object]:
    """Verify, push, create or update, and observe one prepared branch PR."""

    repo_root = args.repo_root.expanduser().resolve(strict=True)
    args.repo_root = repo_root
    status = require_output(_git(repo_root, "status", "--porcelain"), cwd=repo_root)
    if status:
        raise EnsurePrError("Refusing to publish because the worktree is dirty.")
    current_branch = require_output(
        _git(repo_root, "branch", "--show-current"), cwd=repo_root
    ).strip()
    if current_branch != args.head_branch:
        raise EnsurePrError(
            f"Expected active branch {args.head_branch!r}, got {current_branch!r}."
        )
    local_head = require_output(
        _git(repo_root, "rev-parse", "HEAD"), cwd=repo_root
    ).splitlines()[0].strip()
    ahead_raw = require_output(
        _git(repo_root, "rev-list", "--count", f"{args.base_branch}..HEAD"),
        cwd=repo_root,
    )
    if int(ahead_raw.splitlines()[0]) <= 0:
        raise EnsurePrError(
            f"Branch {args.head_branch!r} is not ahead of {args.base_branch!r}."
        )

    require_success(
        _git(
            repo_root,
            "push",
            "-u",
            args.remote_name,
            f"{args.head_branch}:{args.head_branch}",
        ),
        cwd=repo_root,
    )
    pr = _open_pr(args)
    if pr is None:
        title = args.title or "Ship staged skill release"
        body = args.body or "Staged skill lifecycle release branch."
        require_success(
            [
                "gh",
                "pr",
                "create",
                "--base",
                args.base_branch,
                "--head",
                args.head_branch,
                "--title",
                title,
                "--body",
                body,
            ],
            cwd=repo_root,
        )
    elif args.title or args.body:
        command = ["gh", "pr", "edit", str(pr["number"])]
        if args.title:
            command.extend(("--title", args.title))
        if args.body:
            command.extend(("--body", args.body))
        require_success(command, cwd=repo_root)

    pr = wait_for_pr_head(args, local_head)
    return {
        "status": "pr_ready",
        "pr": pr.get("number"),
        "url": pr.get("url"),
        "head": pr.get("headRefOid"),
        "changed_files": pr.get("changedFiles"),
        "state": pr.get("state"),
        "draft": pr.get("isDraft"),
        "checks": _check_summary(pr.get("statusCheckRollup")),
    }


def build_parser() -> argparse.ArgumentParser:
    """Create the ensure-pr parser for prepared local branches."""

    parser = argparse.ArgumentParser(
        prog="python -m github_pr_workflow ensure-pr",
        description="Push a prepared branch and create or update its open PR.",
    )
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--head-branch", required=True)
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--remote-name", default="origin")
    parser.add_argument("--title")
    parser.add_argument("--body")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run ensure-pr and emit exactly one compact JSON result."""

    args = build_parser().parse_args(argv)
    try:
        print(json.dumps(ensure_pr(args), separators=(",", ":"), ensure_ascii=True))
        return 0
    except (CommandError, EnsurePrError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"status": "error", "message": str(exc)},
                separators=(",", ":"),
                ensure_ascii=True,
            ),
            file=sys.stderr,
        )
        return 1
