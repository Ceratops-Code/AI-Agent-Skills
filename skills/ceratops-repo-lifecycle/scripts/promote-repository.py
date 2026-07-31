#!/usr/bin/env python3
"""Fast-forward selected task branches into one reusable local release branch.

The helper owns only generic Git promotion and selected-scope recording.
Repository-specific validation or installation runs through a named operation
from ``deploy/deploy.yml`` when explicitly selected.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from typing import Any

from github_pr_workflow.command import (
    CommandError,
    require_output,
    require_success,
    run_command,
)


SCRIPT_ROOT = pathlib.Path(__file__).resolve().parent
PENDING_MANAGER = SCRIPT_ROOT / "manage-pending-work.py"
DEPLOY_RUNNER = SCRIPT_ROOT / "run-deploy-operation.py"


class PromotionError(RuntimeError):
    """Raised when a local promotion invariant is not satisfied."""


def _git(repo_root: pathlib.Path, *args: str) -> list[str]:
    return ["git", "-C", str(repo_root), *args]


def _clean(repo_root: pathlib.Path, phase: str) -> None:
    if require_output(
        _git(repo_root, "status", "--porcelain"), cwd=repo_root
    ).strip():
        raise PromotionError(f"Repository is dirty {phase}.")


def _ref_exists(repo_root: pathlib.Path, ref: str) -> bool:
    result = run_command(
        _git(repo_root, "show-ref", "--verify", "--quiet", ref),
        cwd=repo_root,
    )
    if result.returncode not in {0, 1}:
        raise PromotionError(f"Could not inspect Git ref: {ref}")
    return result.returncode == 0


def _branch_head(repo_root: pathlib.Path, branch: str) -> str:
    return require_output(
        _git(repo_root, "rev-parse", f"{branch}^{{commit}}"),
        cwd=repo_root,
    ).splitlines()[0]


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


def _preflight_sources(repo_root: pathlib.Path, branches: list[str]) -> None:
    for branch in branches:
        require_success(
            ["git", "check-ref-format", "--branch", branch],
            cwd=repo_root,
        )
        if not _ref_exists(repo_root, f"refs/heads/{branch}"):
            raise PromotionError(f"Source branch does not exist: {branch}")
        worktree = _selected_worktree(repo_root, branch)
        if worktree is None:
            continue
        status = require_output(
            _git(worktree, "status", "--porcelain"),
            cwd=repo_root,
        ).strip()
        if status:
            raise PromotionError(f"Source worktree is dirty: {branch}")


def _run_json(command: list[str], cwd: pathlib.Path) -> tuple[int, dict[str, Any]]:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    raw = result.stdout.strip() if result.stdout.strip() else result.stderr.strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PromotionError("Lifecycle helper returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise PromotionError("Lifecycle helper returned a non-object result.")
    return result.returncode, payload


def promote(args: argparse.Namespace) -> dict[str, object]:
    """Prepare a release branch, record selected work, and optionally deploy."""

    repo_root = args.repo_root.expanduser().resolve(strict=True)
    if not repo_root.is_dir():
        raise PromotionError("Repository root is not a directory.")
    branches = list(dict.fromkeys(args.source_branch or []))
    if len(branches) != len(args.source_branch or []):
        raise PromotionError("Source branches must be unique.")
    if args.prepare_release_only:
        if branches or args.run_operation is not None or args.no_run_operation:
            raise PromotionError(
                "Prepare-only cannot select source branches or deployment."
            )
        current_branch = require_output(
            _git(repo_root, "branch", "--show-current"),
            cwd=repo_root,
        ).strip()
        if current_branch != args.main_branch:
            raise PromotionError(
                f"Prepare-only requires branch {args.main_branch}, "
                f"got {current_branch or 'detached HEAD'}."
            )
    else:
        if not branches:
            raise PromotionError("Promotion requires at least one source branch.")
        if args.run_operation is None and not args.no_run_operation:
            raise PromotionError("Promotion requires an explicit deployment choice.")
        if args.release_branch in branches or args.main_branch in branches:
            raise PromotionError("Source branches cannot be release or main.")
    _clean(repo_root, "before promotion")
    if not args.prepare_release_only:
        _preflight_sources(repo_root, branches)
    require_success(
        _git(repo_root, "remote", "get-url", args.remote_name),
        cwd=repo_root,
    )
    require_success(
        _git(repo_root, "fetch", "--prune", args.remote_name),
        cwd=repo_root,
    )
    remote_main = f"{args.remote_name}/{args.main_branch}"
    if not _ref_exists(repo_root, f"refs/heads/{args.main_branch}"):
        raise PromotionError(f"Local main branch does not exist: {args.main_branch}")
    if not _ref_exists(
        repo_root,
        f"refs/remotes/{args.remote_name}/{args.main_branch}",
    ):
        raise PromotionError(f"Remote main branch does not exist: {remote_main}")
    require_success(
        _git(repo_root, "switch", args.main_branch),
        cwd=repo_root,
    )
    require_success(
        _git(repo_root, "merge", "--ff-only", remote_main),
        cwd=repo_root,
    )
    if _ref_exists(repo_root, f"refs/heads/{args.release_branch}"):
        require_success(
            _git(repo_root, "switch", args.release_branch),
            cwd=repo_root,
        )
    else:
        require_success(
            _git(
                repo_root,
                "switch",
                "-c",
                args.release_branch,
                args.main_branch,
            ),
            cwd=repo_root,
        )
    _clean(repo_root, f"after preparing {args.release_branch}")
    release_start = _branch_head(repo_root, args.release_branch)

    if args.prepare_release_only:
        return {
            "status": "prepared",
            "release_branch": args.release_branch,
            "head": release_start,
        }

    merged: list[str] = []
    for branch in branches:
        ancestor = run_command(
            _git(repo_root, "merge-base", "--is-ancestor", "HEAD", branch),
            cwd=repo_root,
        )
        if ancestor.returncode == 1:
            raise PromotionError(
                f"Source branch must be rebased onto {args.release_branch}: {branch}"
            )
        if ancestor.returncode:
            raise PromotionError(f"Could not compare source branch: {branch}")
        base = require_output(
            _git(repo_root, "merge-base", "HEAD", branch),
            cwd=repo_root,
        ).splitlines()[0]
        require_success(
            _git(repo_root, "diff", "--check", base, branch),
            cwd=repo_root,
        )
        require_success(
            _git(repo_root, "merge", "--ff-only", branch),
            cwd=repo_root,
        )
        _clean(repo_root, f"after promoting {branch}")
        merged.append(branch)

    target_commit = _branch_head(repo_root, args.release_branch)
    record_command = [
        sys.executable,
        str(PENDING_MANAGER),
        "--repo-root",
        str(repo_root),
        "record",
        "--target-branch",
        args.release_branch,
        "--target-commit",
        target_commit,
    ]
    for branch in merged:
        record_command.extend(("--source-branch", branch))
    record_code, record = _run_json(record_command, SCRIPT_ROOT)
    if record_code == 2:
        return record
    if record_code:
        raise PromotionError(str(record.get("message", "Scope recording failed.")))

    operation: dict[str, Any] | None = None
    if args.run_operation is not None:
        operation_command = [
            sys.executable,
            str(DEPLOY_RUNNER),
            "--repo-root",
            str(repo_root),
            "--contract",
            str(args.deploy_contract),
            "--operation",
            args.run_operation,
        ]
        if args.run_operation == "after_promote":
            operation_command.extend(
                (
                    "--parameter-if-declared",
                    f"base_revision={release_start}",
                )
            )
        operation_code, operation = _run_json(
            operation_command,
            SCRIPT_ROOT,
        )
        if operation_code:
            raise PromotionError(str(operation.get("message", "Deployment failed.")))

    _clean(repo_root, "before reporting ready state")
    return {
        "status": "ready",
        "release_branch": args.release_branch,
        "head": target_commit,
        "release_start": release_start,
        "merged_branches": merged,
        "pending_work_scope": record["pending_work_scope"],
        "operation": operation,
    }


def build_parser() -> argparse.ArgumentParser:
    """Create the promotion parser."""

    parser = argparse.ArgumentParser(
        description="Promote selected branches into a local release branch."
    )
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--source-branch", action="append")
    parser.add_argument("--main-branch", default="main")
    parser.add_argument("--release-branch", default="release/local")
    parser.add_argument("--remote-name", default="origin")
    parser.add_argument(
        "--prepare-release-only",
        action="store_true",
        help="Prepare the release branch from a clean main checkout and stop.",
    )
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--run-operation")
    operation.add_argument(
        "--no-run-operation",
        action="store_true",
        help="Promote without running a deployment operation.",
    )
    parser.add_argument(
        "--deploy-contract",
        type=pathlib.Path,
        default=pathlib.Path("deploy/deploy.yml"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run promotion and emit one compact result."""

    args = build_parser().parse_args(argv)
    try:
        result = promote(args)
    except (
        CommandError,
        PromotionError,
        OSError,
        ValueError,
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
