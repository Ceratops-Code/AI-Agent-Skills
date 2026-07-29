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


def _branch_worktrees(repo_root: pathlib.Path) -> dict[str, pathlib.Path]:
    """Map each checked-out local branch to the worktree that owns it."""

    output = require_output(
        _git(repo_root, "worktree", "list", "--porcelain", "-z"),
        cwd=repo_root,
    )
    worktrees: dict[str, pathlib.Path] = {}
    current_path: pathlib.Path | None = None
    for field in output.split("\0"):
        if not field:
            current_path = None
            continue
        key, _, value = field.partition(" ")
        if key == "worktree":
            current_path = pathlib.Path(value).resolve(strict=False)
        elif key == "branch" and current_path is not None:
            branch = value.removeprefix("refs/heads/")
            existing = worktrees.get(branch)
            if existing is not None and existing != current_path:
                raise SyncError(
                    f"Branch {branch!r} is checked out in multiple worktrees."
                )
            worktrees[branch] = current_path
    return worktrees


def _required_worktree(
    worktrees: dict[str, pathlib.Path],
    branch: str,
) -> pathlib.Path | None:
    """Strictly resolve a selected branch owner without touching unrelated entries."""

    worktree = worktrees.get(branch)
    if worktree is None:
        return None
    try:
        resolved = worktree.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SyncError(
            f"Required worktree for branch {branch!r} is unavailable: {worktree}"
        ) from exc
    if not resolved.is_dir():
        raise SyncError(
            f"Required worktree for branch {branch!r} is not a directory: {resolved}"
        )
    return resolved


def sync_main(args: argparse.Namespace) -> dict[str, Any]:
    """Sync main in its owning worktree and align explicitly named branches."""

    repo_root = args.repo_root.expanduser().resolve(strict=True)
    if not repo_root.is_dir():
        raise SyncError(f"repository root is not a directory: {repo_root}")
    worktrees = _branch_worktrees(repo_root)
    for branch in args.align_branch:
        if not branch.strip():
            raise SyncError("--align-branch entries must not be empty.")
        if branch == args.main_branch:
            raise SyncError("--align-branch must not include the main branch.")

    main_worktree = _required_worktree(worktrees, args.main_branch)
    checked_worktrees = [repo_root]
    for branch in args.align_branch:
        branch_worktree = _required_worktree(worktrees, branch)
        if branch_worktree is not None:
            worktrees[branch] = branch_worktree
        if branch_worktree is not None and branch_worktree not in checked_worktrees:
            checked_worktrees.append(branch_worktree)
    if main_worktree is not None and main_worktree not in checked_worktrees:
        checked_worktrees.append(main_worktree)
    for worktree in checked_worktrees:
        _assert_clean(worktree, f"before synchronization in {worktree}")

    require_success(_git(repo_root, "fetch", "--prune", args.remote_name), cwd=repo_root)
    if main_worktree is None:
        require_success(_git(repo_root, "switch", args.main_branch), cwd=repo_root)
        main_worktree = repo_root
        worktrees = {
            branch: worktree
            for branch, worktree in worktrees.items()
            if worktree != repo_root
        }
        worktrees[args.main_branch] = repo_root
    require_success(
        _git(
            main_worktree,
            "merge",
            "--ff-only",
            f"{args.remote_name}/{args.main_branch}",
        ),
        cwd=main_worktree,
    )
    _assert_clean(main_worktree, f"after fast-forwarding {args.main_branch}")

    aligned: list[str] = []
    for branch in args.align_branch:
        branch_worktree = worktrees.get(branch)
        if branch_worktree is None:
            require_success(
                _git(repo_root, "branch", "-f", branch, args.main_branch),
                cwd=repo_root,
            )
        else:
            require_success(
                _git(
                    branch_worktree,
                    "switch",
                    "-C",
                    branch,
                    args.main_branch,
                ),
                cwd=branch_worktree,
            )
            _assert_clean(branch_worktree, f"after aligning {branch}")
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
