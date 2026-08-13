#!/usr/bin/env python3
"""Ship ``release/local``, publish its release, deploy locally, and clean.

The GitHub helper retains ownership of publication, gates, exact-head merge,
and synchronization. This wrapper adds separately owned, checkpointed remote
release publication and local deployment phases plus the required late
selected-work recheck and cleanup.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
from typing import Any

from github_pr_workflow import ship as github_ship

SCRIPT_ROOT = pathlib.Path(__file__).resolve().parent
DEPLOY_RUNNER = SCRIPT_ROOT / "run-deploy-operation.py"
RELEASE_RUNNER = SCRIPT_ROOT / "run-release-operation.py"
PENDING_MANAGER = SCRIPT_ROOT / "manage-pending-work.py"
DEFAULT_DEPLOY_CONTRACT = pathlib.Path("deploy/deploy.yml")
DEFAULT_RELEASE_CONTRACT = pathlib.Path("release/release.yml")
RELEASE_BRANCH = "release/local"


class RepositoryShipError(RuntimeError):
    """Raised when a delegated lifecycle phase does not complete."""

    def __init__(
        self,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.payload = {"status": "error", "message": message, **(payload or {})}


def _inside(path: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _contract_preflight(
    repo_root: pathlib.Path,
    contract: pathlib.Path,
    default_contract: pathlib.Path,
    operation: str,
    *,
    label: str,
    default_selection: bool,
    absent_reason: str,
) -> dict[str, Any] | None:
    """Validate one selected contract or classify its absent default as no-op."""

    selected = (
        contract if contract.is_absolute() else repo_root / contract
    ).resolve()
    default = (repo_root / default_contract).resolve()
    if not _inside(selected, repo_root):
        raise RepositoryShipError(
            f"{label} contract must be a file inside the repository."
        )
    if selected.exists():
        if not selected.is_file():
            raise RepositoryShipError(
                f"{label} contract must be a file inside the repository."
            )
        return None
    if selected != default or not default_selection:
        raise RepositoryShipError(
            f"Selected {label.lower()} contract does not exist before shipping."
        )
    return {
        "status": "no_op",
        "operation": operation,
        "steps": [],
        "reason": absent_reason,
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


def _operation_checkpoint_directory(repo_root: pathlib.Path) -> pathlib.Path:
    """Return the repository-owned directory for completed operations."""

    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--git-common-dir"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = result.stdout.strip().splitlines()
    if result.returncode or not lines:
        raise RepositoryShipError("Could not resolve the repository Git directory.")
    common_dir = pathlib.Path(lines[0])
    if not common_dir.is_absolute():
        common_dir = repo_root / common_dir
    return common_dir.resolve() / "codex" / "repository-lifecycle" / "operations"


def _operation_checkpoint_path(
    repo_root: pathlib.Path, target_commit: str, phase: str
) -> pathlib.Path:
    """Return one exact-target record independent of optional cleanup scope."""

    suffixes = {
        "release_publication": ".release-publication.json",
        "deployment": ".deployment.json",
    }
    try:
        suffix = suffixes[phase]
    except KeyError as exc:
        raise RepositoryShipError(f"Unknown checkpoint phase: {phase}") from exc
    normalized_commit = target_commit.lower()
    if github_ship.FULL_SHA_RE.fullmatch(normalized_commit) is None:
        raise RepositoryShipError("Operation checkpoint requires a full commit SHA.")
    return _operation_checkpoint_directory(repo_root) / f"{normalized_commit}{suffix}"


def _operation_checkpoint_temporary_path(path: pathlib.Path) -> pathlib.Path:
    """Return one exact helper-owned atomic operation-checkpoint sibling."""

    return path.with_suffix(path.suffix + ".tmp")


def _remove_completed_operation_checkpoint(path: pathlib.Path) -> None:
    """Remove completed operation state and only its atomic-write sibling."""

    temporary = _operation_checkpoint_temporary_path(path)
    try:
        temporary.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise RepositoryShipError(
            f"Could not remove completed operation checkpoint {path}: {exc}"
        ) from exc
    if (
        temporary.exists()
        or temporary.is_symlink()
        or path.exists()
        or path.is_symlink()
    ):
        raise RepositoryShipError(
            f"Completed operation checkpoint cleanup left an artifact: {path}"
        )


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
    sources = value.get("sources") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or value.get("version") != github_ship.PENDING_WORK_SCOPE_VERSION
        or not isinstance(sources, list)
        or not sources
    ):
        raise RepositoryShipError("Pending-work scope has invalid sources.")
    branches: list[str] = []
    for source in sources:
        if (
            not isinstance(source, dict)
            or set(source) != {"branch", "commit", "state"}
            or not isinstance(source.get("branch"), str)
            or not source["branch"]
            or not isinstance(source.get("commit"), str)
            or github_ship.FULL_SHA_RE.fullmatch(source["commit"].lower()) is None
            or source.get("state") not in github_ship.PENDING_SOURCE_STATES
        ):
            raise RepositoryShipError("Pending-work scope has invalid sources.")
        branches.append(source["branch"])
    if len(branches) != len(set(branches)):
        raise RepositoryShipError("Pending-work scope has duplicate sources.")

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


def _operation_identity(
    repo_root: pathlib.Path,
    *,
    phase: str,
    target_branch: str,
    target_commit: str,
    synchronized_commit: str,
    contract: pathlib.Path,
    operation: str,
) -> dict[str, object]:
    """Bind reusable phase evidence to one exact synchronized release."""

    resolved_contract = (
        contract if contract.is_absolute() else repo_root / contract
    ).resolve(strict=True)
    return {
        "version": 1,
        "phase": phase,
        "target_branch": target_branch,
        "target_commit": target_commit,
        "synchronized_commit": synchronized_commit,
        "contract": str(resolved_contract),
        "operation": operation,
    }


def _read_operation_checkpoint(
    path: pathlib.Path,
    identity: dict[str, object],
) -> dict[str, Any] | None:
    """Reuse only structurally valid evidence for the exact current phase."""

    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RepositoryShipError(
            f"Could not read operation checkpoint {path}: {exc}"
        ) from exc
    if (
        not isinstance(value, dict)
        or set(value) != {*identity, "result"}
        or value.get("version") != 1
        or any(
            not isinstance(value.get(key), str)
            for key in (
                "phase",
                "target_branch",
                "target_commit",
                "synchronized_commit",
                "contract",
                "operation",
            )
        )
        or not isinstance(value.get("result"), dict)
    ):
        raise RepositoryShipError("Operation checkpoint has invalid structure.")
    if any(value.get(key) != expected for key, expected in identity.items()):
        return None
    return dict(value["result"])


def _write_operation_checkpoint(
    path: pathlib.Path,
    identity: dict[str, object],
    result: dict[str, Any],
) -> None:
    """Atomically persist one completed phase before later side effects."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _operation_checkpoint_temporary_path(path)
    temporary.write_text(
        json.dumps(
            {**identity, "result": result},
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _ship_command(
    args: argparse.Namespace,
    repo_root: pathlib.Path,
    pending_scope: pathlib.Path | None,
    target_commit: str | None,
) -> list[str]:
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
    if target_commit:
        command.extend(("--commit", target_commit))
    if args.title:
        command.extend(("--title", args.title))
    if args.body:
        command.extend(("--body", args.body))
    review_request = getattr(args, "review_replies_request", None)
    if review_request is not None:
        command.extend(("--review-replies-request", str(review_request)))
    if args.delete_branch:
        command.append("--delete-branch")
    if args.reusable_head:
        command.append("--reusable-head")
    if pending_scope is None:
        command.append("--no-pending-work-check")
    else:
        command.extend(
            (
                "--pending-work-check",
                "--pending-work-scope",
                str(pending_scope),
            )
        )
    return command


def _prepare_pending_command(
    *,
    repo_root: pathlib.Path,
    target_branch: str,
    target_commit: str | None,
) -> list[str]:
    """Build canonical optional-scope preparation before remote mutation."""

    command = [
        sys.executable,
        str(PENDING_MANAGER),
        "--repo-root",
        str(repo_root),
        "prepare",
        "--target-branch",
        target_branch,
    ]
    if target_commit:
        command.extend(("--target-commit", target_commit))
    return command


def _prepared_scope(result: dict[str, Any]) -> pathlib.Path | None:
    """Normalize the pending manager's compact optional-scope result."""

    if result.get("status") != "ready":
        raise RepositoryShipError(
            "Pending-work preparation returned an invalid status."
        )
    value = result.get("pending_work_scope")
    if not isinstance(value, str):
        raise RepositoryShipError("Pending-work preparation lacks its scope result.")
    return pathlib.Path(value).resolve() if value else None


def _prepared_target_commit(
    result: dict[str, Any],
    pending_scope: pathlib.Path | None,
    explicit_commit: str | None,
) -> str | None:
    """Select the retained scope commit without requiring manual repetition."""

    normalized_explicit = explicit_commit.lower() if explicit_commit else None
    if pending_scope is None:
        return normalized_explicit
    recorded = result.get("target_commit")
    if recorded is None and normalized_explicit is not None:
        return normalized_explicit
    if (
        not isinstance(recorded, str)
        or len(recorded) != 40
        or any(character not in "0123456789abcdef" for character in recorded)
    ):
        raise RepositoryShipError(
            "Pending-work preparation lacks its recorded target commit."
        )
    if normalized_explicit is not None and normalized_explicit != recorded:
        raise RepositoryShipError(
            "Explicit commit does not match the retained pending-work scope."
        )
    return recorded


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
    """Run complete shipping, release publication, deployment, and cleanup."""

    if args.head_branch != RELEASE_BRANCH:
        raise RepositoryShipError(f"Head branch must be {RELEASE_BRANCH}.")
    repo_root = args.repo_root.expanduser().resolve(strict=True)
    release_publication: dict[str, Any] | None = _contract_preflight(
        repo_root,
        args.release_contract,
        DEFAULT_RELEASE_CONTRACT,
        args.release_operation,
        label="Release",
        default_selection=(
            args.release_preflight_operation == "preflight"
            and args.release_operation == "publish"
        ),
        absent_reason="release_contract_absent",
    )
    deployment: dict[str, Any] | None = _contract_preflight(
        repo_root,
        args.deploy_contract,
        DEFAULT_DEPLOY_CONTRACT,
        args.deploy_operation,
        label="Deployment",
        default_selection=args.deploy_operation == "deploy",
        absent_reason="deployment_contract_absent",
    )
    if release_publication is None:
        preflight_code, preflight = _run_json(
            [
                sys.executable,
                str(RELEASE_RUNNER),
                "--repo-root",
                str(repo_root),
                "--contract",
                str(args.release_contract),
                "--operation",
                args.release_preflight_operation,
            ]
        )
        if preflight_code:
            raise RepositoryShipError(
                str(preflight.get("message", "Release preflight failed.")),
                {
                    **preflight,
                    "phase": "release_preflight",
                    "remote_mutation": False,
                },
            )
    prepare_code, prepared = _run_json(
        _prepare_pending_command(
            repo_root=repo_root,
            target_branch=args.head_branch,
            target_commit=args.commit,
        )
    )
    if prepare_code == 2:
        return prepared
    if prepare_code:
        raise RepositoryShipError(
            str(prepared.get("message", "Pending-work preparation failed.")),
            prepared,
        )
    pending_scope = _prepared_scope(prepared)
    prepared_target_commit = _prepared_target_commit(
        prepared,
        pending_scope,
        args.commit,
    )
    _require_cleanup_safe_caller(repo_root, pending_scope)
    ship_code, shipped = _run_json(
        _ship_command(
            args,
            repo_root,
            pending_scope,
            prepared_target_commit,
        )
    )
    if ship_code == 2:
        return shipped
    if ship_code:
        raise RepositoryShipError(
            str(shipped.get("message", "Shipping failed.")),
            shipped,
        )
    if shipped.get("status") not in {"shipped", "already_shipped"}:
        raise RepositoryShipError("GitHub ship returned a non-terminal result.")
    target_commit = shipped.get("commit")
    synchronized_head = shipped.get("synchronized_head")
    if not isinstance(target_commit, str) or not isinstance(synchronized_head, str):
        raise RepositoryShipError("Shipping result lacks exact commit identity.")
    if (
        prepared_target_commit is not None
        and target_commit.lower() != prepared_target_commit
    ):
        raise RepositoryShipError(
            "Shipping result does not match the prepared target commit."
        )

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
                str(checked.get("message", "Late pending-work check failed.")),
                checked,
            )
        pending_scope = _prepared_scope(checked)

    release_checkpoint: pathlib.Path | None = None
    release_identity: dict[str, object] | None = None
    if release_publication is None:
        release_checkpoint = _operation_checkpoint_path(
            repo_root, target_commit, "release_publication"
        )
        release_identity = _operation_identity(
            repo_root,
            phase="release_publication",
            target_branch=args.head_branch,
            target_commit=target_commit,
            synchronized_commit=synchronized_head,
            contract=args.release_contract,
            operation=args.release_operation,
        )
        release_publication = _read_operation_checkpoint(
            release_checkpoint,
            release_identity,
        )
    if release_publication is None:
        release_code, release_publication = _run_json(
            [
                sys.executable,
                str(RELEASE_RUNNER),
                "--repo-root",
                str(repo_root),
                "--contract",
                str(args.release_contract),
                "--operation",
                args.release_operation,
            ]
        )
        if release_code:
            raise RepositoryShipError(
                str(
                    release_publication.get(
                        "message", "Release publication failed."
                    )
                ),
                {
                    **release_publication,
                    "phase": "release_publication",
                    "remote_mutation": True,
                },
            )
        if release_checkpoint is not None and release_identity is not None:
            _write_operation_checkpoint(
                release_checkpoint,
                release_identity,
                release_publication,
            )

    deployment_checkpoint: pathlib.Path | None = None
    deployment_identity: dict[str, object] | None = None
    if deployment is None:
        deployment_checkpoint = _operation_checkpoint_path(
            repo_root, target_commit, "deployment"
        )
        deployment_identity = _operation_identity(
            repo_root,
            phase="deployment",
            target_branch=args.head_branch,
            target_commit=target_commit,
            synchronized_commit=synchronized_head,
            contract=args.deploy_contract,
            operation=args.deploy_operation,
        )
        deployment = _read_operation_checkpoint(
            deployment_checkpoint,
            deployment_identity,
        )
    if deployment is None:
        deploy_code, deployment = _run_json(
            [
                sys.executable,
                str(DEPLOY_RUNNER),
                "--repo-root",
                str(repo_root),
                "--contract",
                str(args.deploy_contract),
                "--operation",
                args.deploy_operation,
                "--if-declared",
            ]
        )
        if deploy_code:
            raise RepositoryShipError(
                str(deployment.get("message", "Deployment failed.")),
                {
                    **deployment,
                    "phase": "deployment",
                    "remote_mutation": True,
                },
            )
        if deployment_checkpoint is not None and deployment_identity is not None:
            _write_operation_checkpoint(
                deployment_checkpoint,
                deployment_identity,
                deployment,
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
                "phase": "post_operations",
                "repository": shipped.get("repository"),
                "commit": target_commit,
                "pr": shipped.get("pr"),
                "url": shipped.get("url"),
                "release_publication": release_publication,
                "deployment": deployment,
                "remote_mutation": True,
            }
        if finalize_code:
            raise RepositoryShipError(
                str(finalized.get("message", "Selected-work cleanup failed.")),
                finalized,
            )
    for checkpoint in (release_checkpoint, deployment_checkpoint):
        if checkpoint is not None:
            _remove_completed_operation_checkpoint(checkpoint)

    return {
        "status": shipped["status"],
        "repository": shipped.get("repository"),
        "commit": target_commit,
        "pr": shipped.get("pr"),
        "url": shipped.get("url"),
        "merge_commit": shipped.get("merge_commit"),
        "synchronized_head": synchronized_head,
        "release_publication": release_publication,
        "deployment": deployment,
        "finalization": finalized,
    }


def build_parser() -> argparse.ArgumentParser:
    """Create the complete repository ship parser."""

    parser = argparse.ArgumentParser(
        description=(
            "Ship, publish the remote release, deploy locally, and finalize."
        )
    )
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--repo")
    parser.add_argument(
        "--head-branch",
        required=True,
        help="must be release/local",
    )
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
    parser.add_argument("--delete-branch", action="store_true")
    parser.add_argument("--reusable-head", action="store_true")
    parser.add_argument(
        "--release-contract",
        type=pathlib.Path,
        default=DEFAULT_RELEASE_CONTRACT,
        help=(
            "Repository release-publication contract. An absent default "
            "release/release.yml makes publication an explicit no-op."
        ),
    )
    parser.add_argument("--release-preflight-operation", default="preflight")
    parser.add_argument("--release-operation", default="publish")
    parser.add_argument(
        "--deploy-contract",
        type=pathlib.Path,
        default=DEFAULT_DEPLOY_CONTRACT,
        help=(
            "Repository deployment contract. An absent default deploy/deploy.yml "
            "makes deploy an explicit no-op."
        ),
    )
    parser.add_argument("--deploy-operation", default="deploy")
    parser.add_argument("--ci-wait-seconds", type=int, default=900)
    parser.add_argument("--review-wait-seconds", type=int, default=260)
    parser.add_argument("--review-replies-request", type=pathlib.Path)
    parser.add_argument("--interval-seconds", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the complete workflow and emit one compact result."""

    args = build_parser().parse_args(argv)
    try:
        result = ship_repository(args)
    except RepositoryShipError as exc:
        print(
            json.dumps(exc.payload, separators=(",", ":")),
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError) as exc:
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
