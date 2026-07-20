"""Safely fast-forward local main and align explicitly named reusable branches."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

from .command import CommandError, require_output, require_success


class SyncError(RuntimeError):
    """Raised when local sync safety conditions are not satisfied."""


def _git(repo_root: pathlib.Path, *args: str) -> list[str]:
    return ["git", "-C", str(repo_root), *args]


def _assert_clean(repo_root: pathlib.Path, phase: str) -> None:
    status = require_output(_git(repo_root, "status", "--porcelain"), cwd=repo_root)
    if status:
        raise SyncError(f"Refusing to sync because the worktree is dirty {phase}.")


def sync_main(args: argparse.Namespace) -> dict[str, Any]:
    """Fetch, fast-forward main, and force only explicitly named local branches."""

    repo_root = args.repo_root.expanduser().resolve(strict=True)
    if not repo_root.is_dir():
        raise SyncError(f"repository root is not a directory: {repo_root}")
    _assert_clean(repo_root, "before syncing main")
    require_success(_git(repo_root, "fetch", "--prune", args.remote_name), cwd=repo_root)
    require_success(_git(repo_root, "switch", args.main_branch), cwd=repo_root)
    require_success(
        _git(
            repo_root,
            "merge",
            "--ff-only",
            f"{args.remote_name}/{args.main_branch}",
        ),
        cwd=repo_root,
    )
    _assert_clean(repo_root, f"after fast-forwarding {args.main_branch}")

    aligned: list[str] = []
    for branch in args.align_branch:
        if not branch.strip():
            raise SyncError("--align-branch entries must not be empty.")
        if branch == args.main_branch:
            raise SyncError("--align-branch must not include the main branch.")
        require_success(
            _git(repo_root, "branch", "-f", branch, args.main_branch), cwd=repo_root
        )
        aligned.append(branch)
    head = require_output(
        _git(repo_root, "rev-parse", args.main_branch), cwd=repo_root
    ).splitlines()[0]
    return {
        "status": "synced",
        "main": args.main_branch,
        "remote": args.remote_name,
        "head": head.strip(),
        "aligned_branches": aligned,
    }


def build_parser() -> argparse.ArgumentParser:
    """Create the sync command parser with the former helper's options."""

    parser = argparse.ArgumentParser(
        prog="python -m github_pr_workflow sync",
        description="Fast-forward local main and optionally align reusable branches."
    )
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--main-branch", default="main")
    parser.add_argument("--remote-name", default="origin")
    parser.add_argument("--align-branch", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run local synchronization and emit one compact JSON result."""

    args = build_parser().parse_args(argv)
    try:
        print(json.dumps(sync_main(args), separators=(",", ":"), ensure_ascii=True))
        return 0
    except (CommandError, SyncError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "error", "message": str(exc)},
                separators=(",", ":"),
                ensure_ascii=True,
            ),
            file=sys.stderr,
        )
        return 1
