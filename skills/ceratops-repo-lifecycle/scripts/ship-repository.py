#!/usr/bin/env python3
"""Ship one integration branch, deploy synchronized main, and clean its scope.

The GitHub helper retains ownership of publication, gates, exact-head merge,
and synchronization. This wrapper adds the repository lifecycle's deterministic
post-sync operation plus the required late selected-work recheck and cleanup.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
from typing import Any


SCRIPT_ROOT = pathlib.Path(__file__).resolve().parent
DEPLOY_RUNNER = SCRIPT_ROOT / "run-deploy-operation.py"
PENDING_MANAGER = SCRIPT_ROOT / "manage-pending-work.py"
DEFAULT_DEPLOY_CONTRACT = pathlib.Path("deploy/deploy.yml")


class RepositoryShipError(RuntimeError):
    """Raised when a delegated lifecycle phase does not complete."""


def _inside(path: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _deployment_preflight(
    repo_root: pathlib.Path,
    contract: pathlib.Path,
    operation: str,
) -> dict[str, Any] | None:
    """Classify an absent default after-ship contract before remote mutation."""

    selected = (
        contract if contract.is_absolute() else repo_root / contract
    ).resolve()
    default = (repo_root / DEFAULT_DEPLOY_CONTRACT).resolve()
    if not _inside(selected, repo_root):
        raise RepositoryShipError(
            "Deployment contract must be a file inside the repository."
        )
    if selected.exists():
        if not selected.is_file():
            raise RepositoryShipError(
                "Deployment contract must be a file inside the repository."
            )
        return None
    if selected != default or operation != "after_ship":
        raise RepositoryShipError(
            "Selected deployment contract does not exist before shipping."
        )
    return {
        "status": "no_op",
        "operation": operation,
        "steps": [],
        "reason": "deployment_contract_absent",
    }


def _run_json(
    command: list[str], *, cwd: pathlib.Path = SCRIPT_ROOT
) -> tuple[int, dict[str, Any]]:
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
        raise RepositoryShipError("Lifecycle helper returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise RepositoryShipError("Lifecycle helper returned a non-object result.")
    return result.returncode, payload


def _run_finalization(
    command: list[str], *, repo_root: pathlib.Path
) -> tuple[int, dict[str, Any]]:
    """Run cleanup outside any selected worktree that it may remove.

    Windows will not delete a directory used as a process working directory, so
    both this wrapper and the cleanup child must leave the selected worktree.
    """

    previous_cwd = pathlib.Path.cwd().resolve()
    os.chdir(repo_root)
    try:
        return _run_json(command, cwd=repo_root)
    finally:
        if previous_cwd.exists():
            os.chdir(previous_cwd)


def _deployment_checkpoint_path(scope: pathlib.Path) -> pathlib.Path:
    """Return the scope-owned completed-deployment record path."""

    return scope.with_suffix(".after-ship.json")


def _resolve_pending_scope(
    repo_root: pathlib.Path, scope: pathlib.Path | None
) -> pathlib.Path | None:
    """Bind a caller-relative scope to the repository for every ship phase."""

    if scope is None:
        return None
    return (scope if scope.is_absolute() else repo_root / scope).resolve()


def _branch_worktree(repo_root: pathlib.Path, branch: str) -> pathlib.Path | None:
    """Return the registered worktree for one selected source branch."""

    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "for-each-ref",
            "--format=%(worktreepath)",
            f"refs/heads/{branch}",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RepositoryShipError(f"Could not locate selected branch {branch!r}.")
    raw = result.stdout.strip()
    return pathlib.Path(raw).resolve() if raw else None


def _require_cleanup_safe_caller(
    repo_root: pathlib.Path, scope: pathlib.Path | None
) -> None:
    """Block publication when the parent shell pins a selected worktree.

    A child process cannot change its parent shell's working directory. On
    Windows that shell would prevent finalization from deleting the worktree.
    """

    if scope is None:
        return
    try:
        value = json.loads(scope.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RepositoryShipError(f"Could not read pending-work scope: {exc}") from exc
    branches = value.get("source_branches") if isinstance(value, dict) else None
    if not isinstance(branches, list) or not all(
        isinstance(branch, str) and branch for branch in branches
    ):
        raise RepositoryShipError("Pending-work scope has invalid source branches.")

    caller = pathlib.Path.cwd().resolve()
    for branch in branches:
        worktree = _branch_worktree(repo_root, branch)
        if worktree is None:
            continue
        try:
            caller.relative_to(worktree)
        except ValueError:
            continue
        raise RepositoryShipError(
            "Run ship-repository.py from outside selected worktree "
            f"{branch!r} so finalization can remove it."
        )


def _deployment_identity(
    repo_root: pathlib.Path,
    *,
    target_branch: str,
    target_commit: str,
    contract: pathlib.Path,
    operation: str,
) -> dict[str, object]:
    """Bind reusable deployment evidence to one exact release operation."""

    resolved_contract = (
        contract if contract.is_absolute() else repo_root / contract
    ).resolve(strict=True)
    return {
        "version": 1,
        "target_branch": target_branch,
        "target_commit": target_commit,
        "contract": str(resolved_contract),
        "operation": operation,
    }


def _read_deployment_checkpoint(
    path: pathlib.Path,
    identity: dict[str, object],
) -> dict[str, Any] | None:
    """Reuse only structurally valid evidence for the exact current release."""

    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RepositoryShipError(
            f"Could not read deployment checkpoint {path}: {exc}"
        ) from exc
    if (
        not isinstance(value, dict)
        or set(value) != {*identity, "deployment"}
        or value.get("version") != 1
        or any(
            not isinstance(value.get(key), str)
            for key in ("target_branch", "target_commit", "contract", "operation")
        )
        or not isinstance(value.get("deployment"), dict)
    ):
        raise RepositoryShipError("Deployment checkpoint has invalid structure.")
    if any(value.get(key) != expected for key, expected in identity.items()):
        return None
    return dict(value["deployment"])


def _write_deployment_checkpoint(
    path: pathlib.Path,
    identity: dict[str, object],
    deployment: dict[str, Any],
) -> None:
    """Atomically persist completed deployment before selected-work cleanup."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {**identity, "deployment": deployment},
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


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
    pending_scope = _resolve_pending_scope(repo_root, args.pending_work_scope)
    args.pending_work_scope = pending_scope
    _require_cleanup_safe_caller(repo_root, pending_scope)
    deployment_preflight = _deployment_preflight(
        repo_root,
        args.deploy_contract,
        args.deploy_operation,
    )
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

    checkpoint_path: pathlib.Path | None = None
    deployment_identity: dict[str, object] | None = None
    deployed: dict[str, Any] | None = deployment_preflight
    if pending_scope is not None and deployed is None:
        checkpoint_path = _deployment_checkpoint_path(pending_scope)
        deployment_identity = _deployment_identity(
            repo_root,
            target_branch=args.head_branch,
            target_commit=target_commit,
            contract=args.deploy_contract,
            operation=args.deploy_operation,
        )
        deployed = _read_deployment_checkpoint(
            checkpoint_path,
            deployment_identity,
        )
    if deployed is None:
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
            raise RepositoryShipError(
                str(deployed.get("message", "Deployment failed."))
            )
        if checkpoint_path is not None and deployment_identity is not None:
            _write_deployment_checkpoint(
                checkpoint_path,
                deployment_identity,
                deployed,
            )

    finalized: dict[str, Any] | None = None
    if pending_scope is not None:
        finalize_code, finalized = _run_finalization(
            _pending_command(
                "finalize",
                repo_root=repo_root,
                scope=pending_scope,
                target_branch=args.head_branch,
                target_commit=target_commit,
                current_branch=args.base_branch,
                current_commit=synchronized_head,
            ),
            repo_root=repo_root,
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
        if checkpoint_path is not None:
            checkpoint_path.unlink(missing_ok=True)

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
        default=DEFAULT_DEPLOY_CONTRACT,
        help=(
            "Repository deployment contract. An absent default deploy/deploy.yml "
            "makes after_ship an explicit no-op."
        ),
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
