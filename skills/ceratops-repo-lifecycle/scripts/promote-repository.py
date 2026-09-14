#!/usr/bin/env python3
"""Promote selected task branches into reusable ``release/local``.

When release has advanced, the helper may rebase a clean, unpublished,
linear-history source in its existing worktree. Failed attempts restore and
verify the exact source snapshot before blocking. Repository validation runs from the SDLC validate entries after assembling
the release and before local deployment. Composed shipping repeats validation
at its own boundary and owns post-merge publication, deployment, and cleanup.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from github_pr_workflow.command import (
    CommandError,
    require_output,
    require_success,
    run_command,
)
from repository_operation import OperationError, operation_category

SCRIPT_ROOT = pathlib.Path(__file__).resolve().parent
PENDING_MANAGER = SCRIPT_ROOT / "manage-pending-work.py"
OPERATION_RUNNER = SCRIPT_ROOT / "repository_operation.py"
SHIP_REPOSITORY = SCRIPT_ROOT / "ship-repository.py"
RELEASE_BRANCH = "release/local"
DEFAULT_SDLC_CONTRACT = pathlib.Path("sdlc/sdlc.yml")


class PromotionError(RuntimeError):
    """Raised when a local promotion invariant is not satisfied."""

    def __init__(
        self,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.payload = payload


@dataclass(frozen=True)
class SourceState:
    """Immutable preflight identity for one selected source branch."""

    head: str
    worktree: pathlib.Path | None


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


def _preflight_sources(
    repo_root: pathlib.Path, branches: list[str]
) -> dict[str, SourceState]:
    """Validate and snapshot selected branches before release preparation."""

    states: dict[str, SourceState] = {}
    for branch in branches:
        require_success(
            ["git", "check-ref-format", "--branch", branch],
            cwd=repo_root,
        )
        if not _ref_exists(repo_root, f"refs/heads/{branch}"):
            raise PromotionError(f"Source branch does not exist: {branch}")
        worktree = _selected_worktree(repo_root, branch)
        if worktree is None:
            states[branch] = SourceState(
                head=_branch_head(repo_root, branch),
                worktree=None,
            )
            continue
        if _worktree_status(worktree, repo_root):
            raise PromotionError(f"Source worktree is dirty: {branch}")
        states[branch] = SourceState(
            head=_branch_head(repo_root, branch),
            worktree=worktree,
        )
    return states


def _worktree_status(worktree: pathlib.Path, repo_root: pathlib.Path) -> str:
    """Return porcelain state for one known worktree."""

    return require_output(
        _git(worktree, "status", "--porcelain"),
        cwd=repo_root,
    ).strip()


def _command_detail(result: subprocess.CompletedProcess[str]) -> str:
    """Return one bounded single-line command diagnostic."""

    raw = result.stderr.strip() or result.stdout.strip()
    detail = " ".join(raw.split()) if raw else f"exit {result.returncode}"
    return detail if len(detail) <= 500 else detail[:500] + " [truncated]"


def _branch_is_published(
    repo_root: pathlib.Path,
    branch: str,
    head: str,
) -> bool:
    """Return whether rebasing could rewrite a published branch history."""

    upstream = run_command(
        _git(
            repo_root,
            "for-each-ref",
            "--format=%(upstream)",
            f"refs/heads/{branch}",
        ),
        cwd=repo_root,
    )
    if upstream.returncode:
        raise PromotionError(f"Could not inspect source upstream: {branch}")
    if upstream.stdout.strip():
        return True

    remote_refs = run_command(
        _git(repo_root, "for-each-ref", "--format=%(refname)", "refs/remotes"),
        cwd=repo_root,
    )
    if remote_refs.returncode:
        raise PromotionError(f"Could not inspect remote branches for: {branch}")
    suffix = f"/{branch}"
    if any(ref.endswith(suffix) for ref in remote_refs.stdout.splitlines()):
        return True

    containing = run_command(
        _git(
            repo_root,
            "for-each-ref",
            "--format=%(refname)",
            "--contains",
            head,
            "refs/remotes",
        ),
        cwd=repo_root,
    )
    if containing.returncode:
        raise PromotionError(f"Could not inspect published commits for: {branch}")
    return bool(containing.stdout.strip())


def _rebase_in_progress(
    worktree: pathlib.Path,
    repo_root: pathlib.Path,
) -> bool:
    """Return whether Git records an active rebase in the selected worktree."""

    for state_name in ("rebase-merge", "rebase-apply"):
        result = run_command(
            _git(worktree, "rev-parse", "--git-path", state_name),
            cwd=repo_root,
        )
        if result.returncode:
            raise PromotionError("Could not inspect automatic rebase state.")
        state_path = pathlib.Path(result.stdout.strip())
        if not state_path.is_absolute():
            state_path = worktree / state_path
        if state_path.exists():
            return True
    return False


def _restore_source_after_rebase(
    repo_root: pathlib.Path,
    branch: str,
    state: SourceState,
) -> str | None:
    """Restore the exact clean source snapshot after an unsuccessful rebase."""

    worktree = state.worktree
    if worktree is None:
        return "source worktree disappeared"
    in_progress = _rebase_in_progress(worktree, repo_root)
    current = run_command(
        _git(worktree, "branch", "--show-current"),
        cwd=repo_root,
    )
    if current.returncode:
        return "could not read the source worktree branch"
    if not in_progress and current.stdout.strip() != branch:
        return "source worktree no longer has the selected branch checked out"
    if in_progress:
        aborted = run_command(
            _git(worktree, "rebase", "--abort"),
            cwd=repo_root,
        )
        if aborted.returncode:
            return f"git rebase --abort failed: {_command_detail(aborted)}"

    current = run_command(
        _git(worktree, "branch", "--show-current"),
        cwd=repo_root,
    )
    if current.returncode or current.stdout.strip() != branch:
        return "source branch was not restored after abort"

    head = _branch_head(repo_root, branch)
    status = _worktree_status(worktree, repo_root)
    if head != state.head or status:
        reset = run_command(
            _git(worktree, "reset", "--hard", state.head),
            cwd=repo_root,
        )
        if reset.returncode:
            return f"git reset --hard failed: {_command_detail(reset)}"

    restored_head = _branch_head(repo_root, branch)
    restored_status = _worktree_status(worktree, repo_root)
    if _rebase_in_progress(worktree, repo_root):
        return "rebase state remains after rollback"
    if restored_head != state.head:
        return f"restored head is {restored_head}, expected {state.head}"
    if restored_status:
        count = len(restored_status.splitlines())
        return f"restored worktree has {count} status entries"
    return None


def _conflicting_paths(
    worktree: pathlib.Path,
    repo_root: pathlib.Path,
) -> list[str]:
    """Return sorted unmerged paths from an unsuccessful rebase."""

    result = run_command(
        _git(worktree, "diff", "--name-only", "--diff-filter=U"),
        cwd=repo_root,
    )
    if result.returncode:
        return []
    return sorted({line for line in result.stdout.splitlines() if line})


def _automatic_rebase(
    repo_root: pathlib.Path,
    release_head: str,
    branch: str,
    merge_base: str,
    state: SourceState,
) -> dict[str, str]:
    """Rebase one eligible source and compensate every unsuccessful attempt."""

    worktree = state.worktree
    assert worktree is not None
    result = run_command(
        _git(
            worktree,
            "rebase",
            "--no-autostash",
            "--no-gpg-sign",
            "--onto",
            release_head,
            merge_base,
            branch,
        ),
        cwd=repo_root,
    )
    if result.returncode:
        conflicts = _conflicting_paths(worktree, repo_root)
        rollback_error = _restore_source_after_rebase(repo_root, branch, state)
        if rollback_error is not None:
            raise PromotionError(
                f"Automatic rebase and rollback failed for {branch}: "
                f"{rollback_error}"
            )
        if conflicts:
            raise PromotionError(
                f"Automatic rebase conflicted for {branch}; original head "
                f"{state.head} restored; conflicting paths: {', '.join(conflicts)}"
            )
        raise PromotionError(
            f"Automatic rebase failed for {branch}; original head {state.head} "
            f"restored: {_command_detail(result)}"
        )

    new_head = _branch_head(repo_root, branch)
    validation_error: str | None = None
    if _worktree_status(worktree, repo_root):
        validation_error = "rebased worktree is dirty"
    else:
        ancestor = run_command(
            _git(repo_root, "merge-base", "--is-ancestor", release_head, branch),
            cwd=repo_root,
        )
        if ancestor.returncode:
            validation_error = "release head is not an ancestor after rebase"
    if validation_error is None:
        checked = run_command(
            _git(repo_root, "diff", "--check", release_head, branch),
            cwd=repo_root,
        )
        if checked.returncode:
            validation_error = f"git diff --check failed: {_command_detail(checked)}"
    if validation_error is not None:
        rollback_error = _restore_source_after_rebase(repo_root, branch, state)
        if rollback_error is not None:
            raise PromotionError(
                f"Automatic rebase validation and rollback failed for {branch}: "
                f"{validation_error}; {rollback_error}"
            )
        raise PromotionError(
            f"Automatic rebase validation failed for {branch}; original head "
            f"{state.head} restored: {validation_error}"
        )
    return {
        "branch": branch,
        "old_head": state.head,
        "new_head": new_head,
        "onto": release_head,
    }


def _prepare_source_for_fast_forward(
    repo_root: pathlib.Path,
    release_head: str,
    branch: str,
    state: SourceState,
) -> dict[str, str] | None:
    """Validate ancestry or perform the one eligible automatic rebase."""

    if _branch_head(repo_root, branch) != state.head:
        raise PromotionError(f"Source branch changed after preflight: {branch}")
    ancestor = run_command(
        _git(repo_root, "merge-base", "--is-ancestor", release_head, branch),
        cwd=repo_root,
    )
    if ancestor.returncode == 0:
        require_success(
            _git(repo_root, "diff", "--check", release_head, branch),
            cwd=repo_root,
        )
        return None
    if ancestor.returncode != 1:
        raise PromotionError(f"Could not compare source branch: {branch}")

    contained = run_command(
        _git(repo_root, "merge-base", "--is-ancestor", state.head, release_head),
        cwd=repo_root,
    )
    if contained.returncode == 0:
        # Re-promoting included work must not rewrite its published history.
        return None
    if contained.returncode != 1:
        raise PromotionError(f"Could not compare source branch: {branch}")

    worktree = state.worktree
    if worktree is None or not worktree.is_dir():
        raise PromotionError(
            f"Automatic rebase requires an existing source worktree: {branch}"
        )
    current = require_output(
        _git(worktree, "branch", "--show-current"),
        cwd=repo_root,
    ).strip()
    if current != branch:
        raise PromotionError(
            f"Automatic rebase requires the source branch checked out in its "
            f"worktree: {branch}"
        )
    if _branch_is_published(repo_root, branch, state.head):
        raise PromotionError(f"Automatic rebase refuses published branch: {branch}")
    merge_base = require_output(
        _git(repo_root, "merge-base", release_head, branch),
        cwd=repo_root,
    ).splitlines()[0]
    merges = run_command(
        _git(
            repo_root,
            "rev-list",
            "--merges",
            "--max-count=1",
            f"{merge_base}..{branch}",
        ),
        cwd=repo_root,
    )
    if merges.returncode:
        raise PromotionError(f"Could not inspect source history: {branch}")
    if merges.stdout.strip():
        raise PromotionError(
            f"Automatic rebase requires linear source history: {branch}"
        )
    return _automatic_rebase(
        repo_root,
        release_head,
        branch,
        merge_base,
        state,
    )


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


def _operation_ids(value: object, category: str) -> list[str]:
    """Require explicit complete YAML locations in the lifecycle-owned category."""

    selected = [] if value is None else value
    if not isinstance(selected, list):
        raise PromotionError("SDLC operations must be an ordered list.")
    for operation in selected:
        if operation_category(operation) != category:
            raise PromotionError(f"Expected {category} operation: {operation}")
    return list(selected)


def _validation_command(
    args: argparse.Namespace, repo_root: pathlib.Path, commit: str,
) -> list[str]:
    """Run repository-declared checks without inferring scripts or commands."""

    command = [
        sys.executable, str(OPERATION_RUNNER), "--repo-root", str(repo_root),
        "--sdlc-contract", str(args.sdlc_contract), "--validate", "--commit", commit,
    ]
    for operation in args.validation_operation or []:
        command.extend(("--validation-operation", operation))
    for operation in args.run_operation or []:
        command.extend(("--operation", operation))
    return command


def _ship_after_promotion(
    args: argparse.Namespace,
    repo_root: pathlib.Path,
    *,
    target_commit: str,
    pending_work_scope: object,
) -> dict[str, object]:
    """Delegate one exact promoted release to the terminal ship owner.

    ``ship-repository.py`` intentionally derives the canonical scope from the
    head branch. The recorded scope remains an explicit local handoff invariant
    while ``--commit`` binds that derived scope to the promoted head.
    """

    if not isinstance(pending_work_scope, str) or not pending_work_scope:
        raise PromotionError("Scope recording lacks its pending-work scope.")
    scope = pathlib.Path(pending_work_scope)
    if not scope.is_absolute() or not scope.resolve(strict=True).is_file():
        raise PromotionError("Recorded pending-work scope is unavailable for shipping.")
    command = [
        sys.executable,
        str(SHIP_REPOSITORY),
        "--repo-root",
        str(repo_root),
        "--head-branch",
        args.release_branch,
        "--base-branch",
        args.main_branch,
        "--remote-name",
        args.remote_name,
        "--commit",
        target_commit,
        "--reusable-head",
        "--sdlc-contract",
        str(args.sdlc_contract),
    ]
    for field in ("title", "body"):
        value = getattr(args, field, None)
        if value is not None:
            command.extend((f"--{field}", value))
    for flag, operations in (
        ("--validation-operation", args.validation_operation or []),
        ("--publish-operation", _operation_ids(args.publish_operation, "publish")),
        ("--deploy-operation", _operation_ids(args.deploy_operation, "deploy-local")),
    ):
        for operation in operations:
            command.extend((flag, operation))
    ship_code, shipped = _run_json(command, repo_root)
    status = shipped.get("status")
    if ship_code == 0:
        if (
            status not in {"shipped", "already_shipped"}
            or shipped.get("commit") != target_commit
            or not isinstance(shipped.get("synchronized_head"), str)
            or not isinstance(shipped.get("release_publication"), dict)
            or not isinstance(shipped.get("deployment"), dict)
            or "finalization" not in shipped
        ):
            raise PromotionError("Shipping returned an incomplete terminal result.")
        return shipped
    if ship_code == 2:
        if status != "pending_work" or not isinstance(shipped.get("findings"), list):
            raise PromotionError("Shipping returned an incomplete pending-work blocker.")
        return shipped
    if ship_code == 1:
        message = shipped.get("message")
        if status not in {"blocked", "error", "operation_failed", "validation_failed", "tests_failed", "handoff_required", "state_changed"} or not isinstance(message, str):
            raise PromotionError("Shipping returned an incomplete blocker.")
        raise PromotionError(message, shipped)
    raise PromotionError(f"Shipping returned unsupported exit code: {ship_code}")


def promote(args: argparse.Namespace) -> dict[str, object]:
    """Prepare a release branch, record selected work, and optionally deploy."""

    if args.release_branch != RELEASE_BRANCH:
        raise PromotionError(f"release_branch must be {RELEASE_BRANCH}.")
    repo_root = args.repo_root.expanduser().resolve(strict=True)
    if not repo_root.is_dir():
        raise PromotionError("Repository root is not a directory.")
    branches = list(dict.fromkeys(args.source_branch or []))
    ship_after_promotion = bool(getattr(args, "ship_after_promotion", False))
    if not ship_after_promotion and any(
        getattr(args, field, None) is not None for field in ("title", "body")
    ):
        raise PromotionError("PR metadata requires --ship-after-promotion.")
    shipping_operations_selected = any(
        value is not None
        for value in (
            args.publish_operation,
            args.deploy_operation,
        )
    )
    if len(branches) != len(args.source_branch or []):
        raise PromotionError("Source branches must be unique.")
    if args.prepare_release_only:
        if (
            branches
            or args.run_operation is not None
            or args.no_run_operation
            or ship_after_promotion
            or shipping_operations_selected
        ):
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
        if (
            ship_after_promotion
            and (args.run_operation is not None or args.no_run_operation)
        ):
            raise PromotionError(
                "Ship-after-promotion is mutually exclusive with operation flags."
            )
        if shipping_operations_selected and not ship_after_promotion:
            raise PromotionError(
                "Shipping operation selections require --ship-after-promotion."
            )
        if (
            args.run_operation is None
            and not args.no_run_operation
            and not ship_after_promotion
        ):
            raise PromotionError("Promotion requires an explicit deployment choice.")
        if args.release_branch in branches or args.main_branch in branches:
            raise PromotionError("Source branches cannot be release or main.")
    _operation_ids(args.run_operation, "deploy-local")
    _operation_ids(args.validation_operation, "validate")
    _operation_ids(args.publish_operation, "publish")
    _operation_ids(args.deploy_operation, "deploy-local")
    _clean(repo_root, "before promotion")
    source_states: dict[str, SourceState] = {}
    if not args.prepare_release_only:
        source_states = _preflight_sources(repo_root, branches)
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
    rebased: list[dict[str, str]] = []
    for branch in branches:
        release_head = _branch_head(repo_root, args.release_branch)
        rebase_result = _prepare_source_for_fast_forward(
            repo_root,
            release_head,
            branch,
            source_states[branch],
        )
        if rebase_result is not None:
            rebased.append(rebase_result)
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

    validation_code, validation = _run_json(
        _validation_command(args, repo_root, target_commit), repo_root,
    )
    if validation_code:
        raise PromotionError(
            str(validation.get("message", "Repository validation failed.")),
            {
                **validation, "phase": "promotion_validation",
                "remote_mutation": False, "pending_work_scope": record["pending_work_scope"],
                "release_branch": args.release_branch, "head": target_commit,
            },
        )
    operations: dict[str, Any] | None = None
    handoffs: list[dict[str, str]] = []
    if args.run_operation is not None:
        operation_command = [
            sys.executable, str(OPERATION_RUNNER), "--repo-root", str(repo_root),
            "--sdlc-contract", str(args.sdlc_contract), "--commit", target_commit,
        ]
        for operation_id in args.run_operation:
            operation_command.extend(("--operation", operation_id))
        for operation_id in args.validation_operation or []:
            operation_command.extend(("--validation-operation", operation_id))
        operation_code, operations = _run_json(operation_command, repo_root)
        if operation_code:
            raise PromotionError(
                str(operations.get("message", "Deployment failed.")),
                {**operations, "phase": "deployment", "remote_mutation": False,
                 "pending_work_scope": record["pending_work_scope"]},
            )
        for operation_result in operations.get("results", []):
            if operation_result.get("handoff") and not operation_result.get("handoff_completed"):
                handoffs.append({
                    "operation": operation_result["operation"],
                    "handoff": operation_result["handoff"],
                })

    _clean(repo_root, "before reporting ready state")
    pending_work_scope = record["pending_work_scope"]
    if ship_after_promotion:
        return _ship_after_promotion(
            args,
            repo_root,
            target_commit=target_commit,
            pending_work_scope=pending_work_scope,
        )
    result: dict[str, object] = {
        "status": "ready",
        "release_branch": args.release_branch,
        "head": target_commit,
        "release_start": release_start,
        "merged_branches": merged,
        "rebased_branches": rebased,
        "pending_work_scope": pending_work_scope,
        "operations": operations,
    }
    if record.get("preserved_sources"):
        result["preserved_sources"] = record["preserved_sources"]
    if handoffs:
        result["handoffs"] = handoffs
    validation_handoffs = [item for item in validation["results"] if item.get("handoff") and not item.get("handoff_completed")]
    if validation_handoffs:
        result["validation_handoffs"] = validation_handoffs
    return result


def build_parser() -> argparse.ArgumentParser:
    """Create the promotion parser."""

    parser = argparse.ArgumentParser(
        description="Promote selected branches into a local release branch."
    )
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--source-branch", action="append")
    parser.add_argument("--main-branch", default="main")
    parser.add_argument(
        "--release-branch",
        default=RELEASE_BRANCH,
        help="must be release/local",
    )
    parser.add_argument("--remote-name", default="origin")
    parser.add_argument("--title", help="PR title override for composed shipping.")
    parser.add_argument("--body", help="PR body override for composed shipping.")
    parser.add_argument(
        "--prepare-release-only",
        action="store_true",
        help="Prepare the release branch from a clean main checkout and stop.",
    )
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument(
        "--run-operation",
        action="append",
        help="Complete deploy-local YAML location; repeat in order.",
    )
    operation.add_argument(
        "--no-run-operation",
        action="store_true",
        help="Promote without running a deployment operation.",
    )
    operation.add_argument(
        "--ship-after-promotion",
        action="store_true",
        help=(
            "Promote, then invoke terminal shipping with release publication "
            "and local deployment only after merge."
        ),
    )
    parser.add_argument(
        "--sdlc-contract",
        type=pathlib.Path,
        default=DEFAULT_SDLC_CONTRACT,
    )
    parser.add_argument(
        "--validation-operation",
        action="append",
        help="Validate YAML location; repeats replace repository check discovery.",
    )
    parser.add_argument(
        "--publish-operation",
        action="append",
        help="Publish YAML location for composed shipping; repeat in order.",
    )
    parser.add_argument(
        "--deploy-operation",
        action="append",
        help="Deploy-local YAML location for composed shipping; repeat in order.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run promotion and emit one compact result."""

    args = build_parser().parse_args(argv)
    try:
        result = promote(args)
    except (
        CommandError,
        OperationError,
        PromotionError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        payload = (
            exc.payload
            if isinstance(exc, PromotionError) and exc.payload is not None
            else {"status": "error", "message": str(exc)}
        )
        print(json.dumps(payload, separators=(",", ":")), file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 2 if result.get("status") == "pending_work" else 0


if __name__ == "__main__":
    raise SystemExit(main())
