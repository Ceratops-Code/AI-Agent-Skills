#!/usr/bin/env python3
"""Emit one compact non-destructive snapshot for named closure targets.

The caller owns target selection. This helper never discovers unrelated
branches or worktrees, never cleans caller data, and refreshes a remote only
when that remote is named explicitly.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from typing import Any


SCHEMA = "ceratops-closure-snapshot.v1"


class SnapshotError(RuntimeError):
    """Report one actionable closure-snapshot failure."""


def resolve_directory(path: pathlib.Path, label: str) -> pathlib.Path:
    """Resolve one required directory without widening the caller's scope."""

    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise SnapshotError(f"{label} is unavailable: {path}") from exc
    if not resolved.is_dir():
        raise SnapshotError(f"{label} is not a directory: {resolved}")
    return resolved


def validate_name(value: str, label: str) -> str:
    """Reject empty or option-like Git names before invoking Git."""

    candidate = value.strip()
    if (
        not candidate
        or candidate.startswith("-")
        or any(ch.isspace() for ch in candidate)
    ):
        raise SnapshotError(f"{label} is invalid: {value}")
    return candidate


def run_git(
    repo: pathlib.Path,
    *arguments: str,
    allowed_codes: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[str]:
    """Run Git without a shell and keep failures compact."""

    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise SnapshotError(f"git timed out: {arguments[0]}") from exc
    if result.returncode not in allowed_codes:
        detail = (result.stderr or result.stdout).strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise SnapshotError(f"git failed: {arguments[0]}{suffix}")
    return result


def git_text(repo: pathlib.Path, *arguments: str) -> str:
    """Return trimmed Git stdout for one successful command."""

    return run_git(repo, *arguments).stdout.strip()


def git_clean(repo: pathlib.Path) -> bool:
    """Report tracked and untracked worktree cleanliness."""

    return not git_text(repo, "status", "--porcelain=v1", "--untracked-files=normal")


def git_head(repo: pathlib.Path, ref: str = "HEAD") -> str:
    """Resolve one commit without allowing the ref to become an option."""

    validate_name(ref, "Git ref")
    return git_text(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")


def divergence(repo: pathlib.Path, upstream: str, local: str) -> dict[str, int]:
    """Return ahead/behind counts for two validated commit references."""

    validate_name(upstream, "release upstream")
    validate_name(local, "release branch")
    output = git_text(repo, "rev-list", "--left-right", "--count", f"{upstream}...{local}")
    parts = output.split()
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise SnapshotError("git returned invalid release divergence")
    return {"ahead": int(parts[1]), "behind": int(parts[0])}


def branch_tracking(repo: pathlib.Path, branch: str) -> dict[str, Any]:
    """Report current-branch upstream divergence or why it is unavailable."""

    if not branch:
        return {"status": "detached"}
    upstream_result = run_git(
        repo,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
        allowed_codes=(0, 128),
    )
    if upstream_result.returncode != 0:
        return {"status": "unavailable"}
    upstream = validate_name(upstream_result.stdout, "current branch upstream")
    return {
        "status": "tracked",
        "ref": upstream,
        **divergence(repo, upstream, branch),
    }


def registered_worktree(repo: pathlib.Path, branch: str) -> pathlib.Path:
    """Resolve the exact worktree registered for one named local branch."""

    validate_name(branch, "task branch")
    raw = git_text(
        repo,
        "for-each-ref",
        "--format=%(worktreepath)",
        f"refs/heads/{branch}",
    )
    lines = [line for line in raw.splitlines() if line.strip()]
    if len(lines) != 1:
        raise SnapshotError(f"task branch must have one registered worktree: {branch}")
    return pathlib.Path(lines[0]).resolve(strict=True)


def is_ancestor(repo: pathlib.Path, ancestor: str, descendant: str) -> bool:
    """Check one exact ancestry relationship without changing refs."""

    result = run_git(
        repo,
        "merge-base",
        "--is-ancestor",
        ancestor,
        descendant,
        allowed_codes=(0, 1),
    )
    return result.returncode == 0


def temp_snapshot(path: pathlib.Path) -> dict[str, Any]:
    """Count files below one explicitly named temporary root."""

    resolved = path.expanduser().resolve()
    if not resolved.exists():
        return {"path": str(resolved), "exists": False, "files": 0}
    if not resolved.is_dir():
        raise SnapshotError(f"temp root is not a directory: {resolved}")
    return {
        "path": str(resolved),
        "exists": True,
        "files": sum(1 for candidate in resolved.rglob("*") if candidate.is_file()),
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the explicit closure-target command."""

    parser = argparse.ArgumentParser(
        description="Emit one compact non-destructive closure snapshot."
    )
    parser.add_argument("--repo", required=True, type=pathlib.Path)
    parser.add_argument("--fetch-remote")
    parser.add_argument("--release-branch")
    parser.add_argument("--release-upstream")
    parser.add_argument("--task-worktree", type=pathlib.Path)
    parser.add_argument("--task-branch")
    parser.add_argument("--temp-root", type=pathlib.Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Validate declared targets, collect their state once, and emit JSON."""

    args = build_parser().parse_args(argv)
    try:
        if bool(args.release_branch) != bool(args.release_upstream):
            raise SnapshotError(
                "--release-branch and --release-upstream must be provided together"
            )
        if bool(args.task_worktree) != bool(args.task_branch):
            raise SnapshotError(
                "--task-worktree and --task-branch must be provided together"
            )
        if args.task_branch and not args.release_branch:
            raise SnapshotError("task worktree checks require --release-branch")

        repo = resolve_directory(args.repo, "repo")
        repository_root = pathlib.Path(
            git_text(repo, "rev-parse", "--show-toplevel")
        ).resolve(strict=True)
        if repository_root != repo:
            raise SnapshotError(f"repo must be the Git worktree root: {repository_root}")

        if args.fetch_remote:
            remote = validate_name(args.fetch_remote, "fetch remote")
            git_text(repo, "remote", "get-url", remote)
            run_git(repo, "fetch", "--prune", remote)

        current_branch = git_text(repo, "branch", "--show-current")
        result: dict[str, Any] = {
            "schema": SCHEMA,
            "repo": {
                "path": str(repo),
                "branch": current_branch,
                "head": git_head(repo),
                "clean": git_clean(repo),
                "tracking": branch_tracking(repo, current_branch),
            },
        }

        if args.release_branch:
            release_branch = validate_name(args.release_branch, "release branch")
            release_upstream = validate_name(
                args.release_upstream, "release upstream"
            )
            release_head = git_head(repo, release_branch)
            git_head(repo, release_upstream)
            result["release"] = {
                "branch": release_branch,
                "head": release_head,
                "upstream": release_upstream,
                **divergence(repo, release_upstream, release_branch),
            }

        if args.task_worktree:
            task_worktree = resolve_directory(args.task_worktree, "task worktree")
            task_branch = validate_name(args.task_branch, "task branch")
            if registered_worktree(repo, task_branch) != task_worktree:
                raise SnapshotError(
                    f"task worktree does not match branch {task_branch}: {task_worktree}"
                )
            actual_branch = git_text(task_worktree, "branch", "--show-current")
            if actual_branch != task_branch:
                raise SnapshotError(
                    f"task worktree branch mismatch: expected {task_branch}, got {actual_branch}"
                )
            task_head = git_head(task_worktree)
            result["task"] = {
                "path": str(task_worktree),
                "branch": task_branch,
                "head": task_head,
                "clean": git_clean(task_worktree),
                "staged_in_release": is_ancestor(
                    repo, task_head, args.release_branch
                ),
            }

        if args.temp_root:
            result["temp"] = temp_snapshot(args.temp_root)
    except (OSError, SnapshotError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
