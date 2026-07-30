#!/usr/bin/env python3
"""Record, recheck, and finalize one selected repository work scope.

Scope files live under the repository's common Git directory and name only the
source branches approved for one integration target. Unrelated branches and
worktrees are never enumerated. Finalization removes only clean selected
worktrees under the repository's expected worktree root and merged branches.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
from typing import Any

from github_pr_workflow import ship
from github_pr_workflow.command import (
    CommandError,
    require_output,
    require_success,
    run_command,
)


class PendingWorkError(RuntimeError):
    """Raised when selected-scope persistence or cleanup is unsafe."""


def _git(repo_root: pathlib.Path, *args: str) -> list[str]:
    return ["git", "-C", str(repo_root), *args]


def _inside(path: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _common_git_dir(repo_root: pathlib.Path) -> pathlib.Path:
    raw = require_output(
        _git(repo_root, "rev-parse", "--git-common-dir"), cwd=repo_root
    ).splitlines()[0]
    path = pathlib.Path(raw)
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _scope_path(repo_root: pathlib.Path, target_branch: str) -> pathlib.Path:
    digest = hashlib.sha256(target_branch.encode("utf-8")).hexdigest()
    return (
        _common_git_dir(repo_root)
        / "codex"
        / "repository-lifecycle"
        / "promotions"
        / f"sha256-{digest}.json"
    )


def _read_scope(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PendingWorkError(f"Could not read pending-work scope {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PendingWorkError("Pending-work scope must be an object.")
    return value


def _write_scope(path: pathlib.Path, scope: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(scope, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _validated_scope(
    repo_root: pathlib.Path,
    path: pathlib.Path,
    *,
    target_branch: str,
    target_commit: str,
) -> dict[str, Any]:
    expected_path = _scope_path(repo_root, target_branch)
    if path.resolve() != expected_path:
        raise PendingWorkError(
            "Pending-work manager accepts only its generated scope path."
        )
    args = argparse.Namespace(
        pending_work_check=True,
        pending_work_scope=path,
        head_branch=target_branch,
    )
    _, scope = ship._load_pending_work_scope(args, repo_root, target_commit)
    if scope is None:
        raise PendingWorkError("Pending-work scope unexpectedly disabled its check.")
    return scope


def _validate_branch(repo_root: pathlib.Path, branch: str) -> None:
    result = run_command(
        ["git", "check-ref-format", "--branch", branch],
        cwd=repo_root,
    )
    if result.returncode:
        raise PendingWorkError(f"Invalid source branch: {branch!r}")


def record_scope(
    repo_root: pathlib.Path,
    *,
    target_branch: str,
    target_commit: str,
    source_branches: list[str],
) -> dict[str, object]:
    """Atomically advance one integration target's selected source scope."""

    if not source_branches:
        raise PendingWorkError("At least one source branch is required.")
    _validate_branch(repo_root, target_branch)
    if ship.FULL_SHA_RE.fullmatch(target_commit) is None:
        raise PendingWorkError("Target commit must be a full Git SHA.")
    if len(set(source_branches)) != len(source_branches):
        raise PendingWorkError("Source branches must be unique.")
    if target_branch in source_branches:
        raise PendingWorkError("The target branch cannot be a source branch.")
    for branch in source_branches:
        _validate_branch(repo_root, branch)
    require_success(
        _git(repo_root, "cat-file", "-e", f"{target_commit}^{{commit}}"),
        cwd=repo_root,
    )
    target_head = require_output(
        _git(repo_root, "rev-parse", f"refs/heads/{target_branch}"),
        cwd=repo_root,
    ).splitlines()[0]
    if target_head != target_commit:
        raise PendingWorkError(
            "Target branch does not point at the recorded target commit."
        )

    requested_scope = {
        "version": 1,
        "target_branch": target_branch,
        "target_commit": target_commit,
        "source_branches": sorted(source_branches),
    }
    findings = ship._pending_work_findings(repo_root, requested_scope)
    if findings:
        return {
            "status": "pending_work",
            "remote_mutation": False,
            "findings": findings,
        }

    path = _scope_path(repo_root, target_branch)
    retained: list[str] = []
    if path.is_file():
        existing = _read_scope(path)
        if (
            set(existing)
            != {
                "version",
                "target_branch",
                "target_commit",
                "source_branches",
            }
            or
            existing.get("version") != 1
            or existing.get("target_branch") != target_branch
            or not isinstance(existing.get("source_branches"), list)
            or not existing["source_branches"]
            or len(set(existing["source_branches"]))
            != len(existing["source_branches"])
            or any(
                not isinstance(value, str) or not value
                for value in existing["source_branches"]
            )
        ):
            raise PendingWorkError("Existing pending-work scope has incompatible identity.")
        retained = list(existing["source_branches"])
        for branch in retained:
            _validate_branch(repo_root, branch)
    merged = sorted(set(retained) | set(source_branches))
    scope = {
        "version": 1,
        "target_branch": target_branch,
        "target_commit": target_commit,
        "source_branches": merged,
    }
    _write_scope(path, scope)
    _validated_scope(
        repo_root,
        path,
        target_branch=target_branch,
        target_commit=target_commit,
    )
    return {
        "status": "ready",
        "target_branch": target_branch,
        "target_commit": target_commit,
        "source_branches": merged,
        "pending_work_scope": str(path),
    }


def check_scope(
    repo_root: pathlib.Path,
    path: pathlib.Path,
    *,
    target_branch: str,
    target_commit: str,
) -> dict[str, object]:
    """Recheck every branch named by one exact persisted scope."""

    scope = _validated_scope(
        repo_root,
        path,
        target_branch=target_branch,
        target_commit=target_commit,
    )
    findings = ship._pending_work_findings(repo_root, scope)
    if findings:
        return {
            "status": "pending_work",
            "remote_mutation": False,
            "findings": findings,
            "pending_work_scope": str(path.resolve()),
        }
    return {
        "status": "ready",
        "source_branches": scope["source_branches"],
        "pending_work_scope": str(path.resolve()),
    }


def _selected_worktree(repo_root: pathlib.Path, branch: str) -> pathlib.Path | None:
    raw = require_output(
        _git(
            repo_root,
            "for-each-ref",
            "--format=%(worktreepath)",
            f"refs/heads/{branch}",
        ),
        cwd=repo_root,
    ).strip()
    return pathlib.Path(raw).resolve() if raw else None


def _remove_selected_worktree(
    repo_root: pathlib.Path,
    branch: str,
    path: pathlib.Path,
    expected_root: pathlib.Path,
) -> None:
    if not _inside(path, expected_root) or path == expected_root:
        raise PendingWorkError(
            f"Selected worktree is outside the expected root: {branch}"
        )
    attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if path.is_symlink() or attributes & reparse_flag:
        raise PendingWorkError(f"Selected worktree is a reparse point: {branch}")
    require_success(
        _git(repo_root, "worktree", "remove", str(path)),
        cwd=repo_root,
    )
    if path.exists():
        resolved = path.resolve()
        if not _inside(resolved, expected_root) or resolved == expected_root:
            raise PendingWorkError(
                f"Residual worktree is outside the expected root: {branch}"
            )
        shutil.rmtree(resolved)


def finalize_scope(
    repo_root: pathlib.Path,
    path: pathlib.Path,
    *,
    target_branch: str,
    target_commit: str,
    current_branch: str,
    current_commit: str,
) -> dict[str, object]:
    """Late-recheck and remove only clean, merged selected source work."""

    checked = check_scope(
        repo_root,
        path,
        target_branch=target_branch,
        target_commit=target_commit,
    )
    if checked["status"] != "ready":
        return checked
    if require_output(
        _git(repo_root, "branch", "--show-current"), cwd=repo_root
    ).strip() != current_branch:
        raise PendingWorkError("Repository is not on the synchronized base branch.")
    if require_output(
        _git(repo_root, "rev-parse", "HEAD"), cwd=repo_root
    ).splitlines()[0] != current_commit:
        raise PendingWorkError("Repository is not at the synchronized base commit.")
    if require_output(
        _git(repo_root, "status", "--porcelain"), cwd=repo_root
    ).strip():
        raise PendingWorkError("Repository is dirty after synchronization.")

    scope = _read_scope(path)
    expected_root = (repo_root.parent / "worktrees" / repo_root.name).resolve()
    removed: list[str] = []
    for branch in scope["source_branches"]:
        if branch in {current_branch, target_branch}:
            raise PendingWorkError("Pending-work scope contains a protected branch.")
        worktree = _selected_worktree(repo_root, branch)
        if worktree is not None:
            _remove_selected_worktree(repo_root, branch, worktree, expected_root)
        require_success(
            _git(repo_root, "branch", "-d", branch),
            cwd=repo_root,
        )
        removed.append(branch)
    path.unlink()
    return {
        "status": "finalized",
        "removed": removed,
        "pending_work_scope": "",
    }


def build_parser() -> argparse.ArgumentParser:
    """Create the selected-scope manager parser."""

    parser = argparse.ArgumentParser(description="Manage selected pending repository work.")
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser("record")
    record.add_argument("--target-branch", required=True)
    record.add_argument("--target-commit", required=True)
    record.add_argument("--source-branch", action="append", required=True)

    check = subparsers.add_parser("check")
    check.add_argument("--scope", required=True, type=pathlib.Path)
    check.add_argument("--target-branch", required=True)
    check.add_argument("--target-commit", required=True)

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--scope", required=True, type=pathlib.Path)
    finalize.add_argument("--target-branch", required=True)
    finalize.add_argument("--target-commit", required=True)
    finalize.add_argument("--current-branch", required=True)
    finalize.add_argument("--current-commit", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute one scope operation and emit one compact result."""

    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.expanduser().resolve()
    if hasattr(args, "scope"):
        args.scope = (
            args.scope
            if args.scope.is_absolute()
            else repo_root / args.scope
        ).resolve()
    try:
        if args.command == "record":
            result = record_scope(
                repo_root,
                target_branch=args.target_branch,
                target_commit=args.target_commit.lower(),
                source_branches=args.source_branch,
            )
        elif args.command == "check":
            result = check_scope(
                repo_root,
                args.scope,
                target_branch=args.target_branch,
                target_commit=args.target_commit.lower(),
            )
        else:
            result = finalize_scope(
                repo_root,
                args.scope,
                target_branch=args.target_branch,
                target_commit=args.target_commit.lower(),
                current_branch=args.current_branch,
                current_commit=args.current_commit.lower(),
            )
    except (
        PendingWorkError,
        ship.ShipError,
        CommandError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        print(
            json.dumps(
                {"status": "error", "message": str(exc)},
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 2 if result.get("status") == "pending_work" else 0


if __name__ == "__main__":
    raise SystemExit(main())
