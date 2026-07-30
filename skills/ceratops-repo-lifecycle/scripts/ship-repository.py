#!/usr/bin/env python3
"""Ship one integration branch, deploy synchronized main, and clean its scope.

The GitHub helper retains ownership of publication, gates, exact-head merge,
and synchronization. This wrapper adds the repository lifecycle's deterministic
post-sync operation plus the required late selected-work recheck and cleanup.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from typing import Any


SCRIPT_ROOT = pathlib.Path(__file__).resolve().parent
DEPLOY_RUNNER = SCRIPT_ROOT / "run-deploy-operation.py"
PENDING_MANAGER = SCRIPT_ROOT / "manage-pending-work.py"


class RepositoryShipError(RuntimeError):
    """Raised when a delegated lifecycle phase does not complete."""


def _run_json(command: list[str]) -> tuple[int, dict[str, Any]]:
    result = subprocess.run(
        command,
        cwd=SCRIPT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    raw = result.stdout.strip() if result.stdout.strip() else result.stderr.strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RepositoryShipError("Lifecycle helper returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise RepositoryShipError("Lifecycle helper returned a non-object result.")
    return result.returncode, payload


def _ship_command(args: argparse.Namespace, repo_root: pathlib.Path) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "github_pr_workflow",
        "ship",
        "--repo-root",
        str(repo_root),
        "--head-branch",
        args.head_branch,
        "--base-branch",
        args.base_branch,
        "--remote-name",
        args.remote_name,
        "--merge-method",
        args.merge_method,
        "--ci-wait-seconds",
        str(args.ci_wait_seconds),
        "--review-wait-seconds",
        str(args.review_wait_seconds),
        "--interval-seconds",
        str(args.interval_seconds),
    ]
    if args.repo:
        command.extend(("--repo", args.repo))
    if args.commit:
        command.extend(("--commit", args.commit))
    if args.title:
        command.extend(("--title", args.title))
    if args.body:
        command.extend(("--body", args.body))
    if args.delete_branch:
        command.append("--delete-branch")
    if args.reusable_head:
        command.append("--reusable-head")
    if args.pending_work_scope is None:
        command.append("--no-pending-work-check")
    else:
        command.extend(
            (
                "--pending-work-check",
                "--pending-work-scope",
                str(args.pending_work_scope),
            )
        )
    return command


def _pending_command(
    action: str,
    *,
    repo_root: pathlib.Path,
    scope: pathlib.Path,
    target_branch: str,
    target_commit: str,
    current_branch: str | None = None,
    current_commit: str | None = None,
) -> list[str]:
    command = [
        sys.executable,
        str(PENDING_MANAGER),
        "--repo-root",
        str(repo_root),
        action,
        "--scope",
        str(scope),
        "--target-branch",
        target_branch,
        "--target-commit",
        target_commit,
    ]
    if action == "finalize":
        if current_branch is None or current_commit is None:
            raise RepositoryShipError("Finalization requires synchronized identity.")
        command.extend(
            (
                "--current-branch",
                current_branch,
                "--current-commit",
                current_commit,
            )
        )
    return command


def ship_repository(args: argparse.Namespace) -> dict[str, object]:
    """Run the complete repository shipping and deployment workflow."""

    repo_root = args.repo_root.expanduser().resolve(strict=True)
    ship_code, shipped = _run_json(_ship_command(args, repo_root))
    if ship_code == 2:
        return shipped
    if ship_code:
        raise RepositoryShipError(str(shipped.get("message", "Shipping failed.")))
    if shipped.get("status") not in {"shipped", "already_shipped"}:
        raise RepositoryShipError("GitHub ship returned a non-terminal result.")
    target_commit = shipped.get("commit")
    synchronized_head = shipped.get("synchronized_head")
    if not isinstance(target_commit, str) or not isinstance(synchronized_head, str):
        raise RepositoryShipError("Shipping result lacks exact commit identity.")

    pending_scope = args.pending_work_scope
    if pending_scope is not None:
        check_code, checked = _run_json(
            _pending_command(
                "check",
                repo_root=repo_root,
                scope=pending_scope,
                target_branch=args.head_branch,
                target_commit=target_commit,
            )
        )
        if check_code == 2:
            return {
                **checked,
                "phase": "post_sync",
                "repository": shipped.get("repository"),
                "commit": target_commit,
                "pr": shipped.get("pr"),
                "url": shipped.get("url"),
                "remote_mutation": True,
            }
        if check_code:
            raise RepositoryShipError(
                str(checked.get("message", "Late pending-work check failed."))
            )

    deploy_code, deployed = _run_json(
        [
            sys.executable,
            str(DEPLOY_RUNNER),
            "--repo-root",
            str(repo_root),
            "--contract",
            str(args.deploy_contract),
            "--operation",
            args.deploy_operation,
        ]
    )
    if deploy_code:
        raise RepositoryShipError(str(deployed.get("message", "Deployment failed.")))

    finalized: dict[str, Any] | None = None
    if pending_scope is not None:
        finalize_code, finalized = _run_json(
            _pending_command(
                "finalize",
                repo_root=repo_root,
                scope=pending_scope,
                target_branch=args.head_branch,
                target_commit=target_commit,
                current_branch=args.base_branch,
                current_commit=synchronized_head,
            )
        )
        if finalize_code == 2:
            return {
                **finalized,
                "phase": "post_deploy",
                "repository": shipped.get("repository"),
                "commit": target_commit,
                "pr": shipped.get("pr"),
                "url": shipped.get("url"),
                "deployment": deployed,
                "remote_mutation": True,
            }
        if finalize_code:
            raise RepositoryShipError(
                str(finalized.get("message", "Selected-work cleanup failed."))
            )

    return {
        "status": shipped["status"],
        "repository": shipped.get("repository"),
        "commit": target_commit,
        "pr": shipped.get("pr"),
        "url": shipped.get("url"),
        "merge_commit": shipped.get("merge_commit"),
        "synchronized_head": synchronized_head,
        "deployment": deployed,
        "finalization": finalized,
    }


def build_parser() -> argparse.ArgumentParser:
    """Create the complete repository ship parser."""

    parser = argparse.ArgumentParser(
        description="Ship, deploy, and finalize one repository release."
    )
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--repo")
    parser.add_argument("--head-branch", required=True)
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--remote-name", default="origin")
    parser.add_argument("--commit")
    parser.add_argument("--title")
    parser.add_argument("--body")
    parser.add_argument(
        "--merge-method",
        choices=("merge", "squash", "rebase"),
        default="merge",
    )
    pending = parser.add_mutually_exclusive_group(required=True)
    pending.add_argument("--pending-work-scope", type=pathlib.Path)
    pending.add_argument("--no-pending-work-check", action="store_true")
    parser.add_argument("--delete-branch", action="store_true")
    parser.add_argument("--reusable-head", action="store_true")
    parser.add_argument(
        "--deploy-contract",
        type=pathlib.Path,
        default=pathlib.Path("deploy/deploy.yml"),
    )
    parser.add_argument("--deploy-operation", default="after_ship")
    parser.add_argument("--ci-wait-seconds", type=int, default=900)
    parser.add_argument("--review-wait-seconds", type=int, default=260)
    parser.add_argument("--interval-seconds", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the complete workflow and emit one compact result."""

    args = build_parser().parse_args(argv)
    try:
        result = ship_repository(args)
    except (RepositoryShipError, OSError, ValueError) as exc:
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
