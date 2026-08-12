#!/usr/bin/env python3
"""Record, prepare, recheck, and finalize one selected repository work scope.

Scope files live under the repository's common Git directory and persist the
exact source tips approved for one integration target plus helper-owned cleanup
state. Unrelated branches and worktrees are never enumerated. Finalization
removes only clean selected worktrees under the repository's expected worktree
root and merged branches.
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


RESIDUAL_CLEANUP_RECORD_VERSION = 1
RESIDUAL_CLEANUP_RECORD_FIELDS = {
    "version",
    "scope",
    "branch",
    "worktree_path",
    "expected_root",
}
ADMINISTRATORS_SID = "*S-1-5-32-544"


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


def _residual_cleanup_record_path(scope: pathlib.Path, branch: str) -> pathlib.Path:
    """Return the exact record for one automatic residual cleanup."""

    digest = hashlib.sha256(branch.encode("utf-8")).hexdigest()
    return scope.with_name(f"{scope.stem}.cleanup-sha256-{digest}.json")


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


def _lstat(path: pathlib.Path) -> os.stat_result | None:
    """Distinguish an absent path from an inaccessible cleanup target."""

    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


def _is_reparse(path: pathlib.Path, attributes: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(
        getattr(attributes, "st_file_attributes", 0) & reparse_flag
    )


def _validate_worktree_path(
    path: pathlib.Path,
    expected_root: pathlib.Path,
    *,
    allow_inaccessible: bool,
) -> None:
    """Confine cleanup to one non-reparse child of the canonical root."""

    if not path.is_absolute() or not _inside(path, expected_root) or path == expected_root:
        raise PendingWorkError("Recorded worktree is outside the expected root.")
    root_attributes = _lstat(expected_root)
    if root_attributes is None:
        raise PendingWorkError("Expected worktree root does not exist.")
    if _is_reparse(expected_root, root_attributes):
        raise PendingWorkError("Expected worktree root is a reparse point.")
    try:
        attributes = _lstat(path)
    except PermissionError:
        if allow_inaccessible:
            return
        raise
    if attributes is not None and _is_reparse(path, attributes):
        raise PendingWorkError("Recorded worktree is a reparse point.")


def _registered_worktree_paths(repo_root: pathlib.Path) -> set[pathlib.Path]:
    """Return every Git-registered worktree path for residual-path checks."""

    raw = require_output(
        _git(repo_root, "worktree", "list", "--porcelain"), cwd=repo_root
    )
    return {
        pathlib.Path(line.removeprefix("worktree ")).resolve()
        for line in raw.splitlines()
        if line.startswith("worktree ")
    }


def _read_residual_cleanup_record(
    repo_root: pathlib.Path,
    record_path: pathlib.Path,
) -> tuple[pathlib.Path, str, pathlib.Path, pathlib.Path]:
    """Validate one residual-cleanup record against repository topology."""

    if record_path.is_symlink() or not record_path.is_file():
        raise PendingWorkError("Residual-cleanup record is not a regular file.")
    try:
        value = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PendingWorkError(
            f"Could not read residual-cleanup record {record_path}: {exc}"
        ) from exc
    if (
        not isinstance(value, dict)
        or set(value) != RESIDUAL_CLEANUP_RECORD_FIELDS
        or value.get("version") != RESIDUAL_CLEANUP_RECORD_VERSION
        or any(
            not isinstance(value.get(field), str) or not value[field]
            for field in ("scope", "branch", "worktree_path", "expected_root")
        )
    ):
        raise PendingWorkError("Residual-cleanup record has invalid structure.")
    branch = value["branch"]
    _validate_branch(repo_root, branch)
    scope = pathlib.Path(value["scope"])
    worktree = pathlib.Path(value["worktree_path"])
    expected_root = pathlib.Path(value["expected_root"])
    canonical_root = (repo_root.parent / "worktrees" / repo_root.name).resolve()
    if expected_root != canonical_root:
        raise PendingWorkError("Residual-cleanup record has an unexpected root.")
    expected_record = _residual_cleanup_record_path(scope, branch).resolve()
    if record_path.resolve() != expected_record:
        raise PendingWorkError("Residual-cleanup record has an unexpected path.")
    promotions = (
        _common_git_dir(repo_root)
        / "codex"
        / "repository-lifecycle"
        / "promotions"
    ).resolve()
    if scope.parent.resolve() != promotions:
        raise PendingWorkError("Residual-cleanup record has an unexpected scope.")
    _validate_worktree_path(worktree, expected_root, allow_inaccessible=True)
    return scope, branch, worktree, expected_root


def _write_residual_cleanup_record(
    repo_root: pathlib.Path,
    scope: pathlib.Path,
    branch: str,
    worktree: pathlib.Path,
    expected_root: pathlib.Path,
) -> pathlib.Path:
    """Persist exact identity before automatic residual cleanup can be needed."""

    record_path = _residual_cleanup_record_path(scope, branch)
    record = {
        "version": RESIDUAL_CLEANUP_RECORD_VERSION,
        "scope": str(scope.resolve()),
        "branch": branch,
        "worktree_path": str(worktree),
        "expected_root": str(expected_root),
    }
    if record_path.exists():
        _, existing_branch, existing_worktree, existing_root = (
            _read_residual_cleanup_record(repo_root, record_path)
        )
        if (
            existing_branch != branch
            or existing_worktree != worktree
            or existing_root != expected_root
        ):
            raise PendingWorkError("Residual-cleanup record has conflicting identity.")
        return record_path
    _write_scope(record_path, record)
    return record_path


def _take_ownership_and_remove(
    repo_root: pathlib.Path,
    path: pathlib.Path,
    expected_root: pathlib.Path,
) -> None:
    """Repair Windows ACL ownership for one already validated residual path."""

    _validate_worktree_path(path, expected_root, allow_inaccessible=False)
    if path in _registered_worktree_paths(repo_root):
        raise PendingWorkError("Refusing to take ownership of a registered worktree.")
    require_success(
        ["takeown.exe", "/F", str(path), "/A", "/R", "/D", "Y", "/SKIPSL"],
        cwd=path.parent,
    )
    _validate_worktree_path(path, expected_root, allow_inaccessible=False)
    require_success(
        [
            "icacls.exe",
            str(path),
            "/grant",
            f"{ADMINISTRATORS_SID}:(OI)(CI)F",
            "/T",
            "/C",
            "/L",
            "/Q",
        ],
        cwd=path.parent,
    )
    _validate_worktree_path(path, expected_root, allow_inaccessible=False)
    if path in _registered_worktree_paths(repo_root):
        raise PendingWorkError("Refusing to remove a registered worktree path.")
    shutil.rmtree(path)


def _run_recorded_residual_cleanup(
    repo_root: pathlib.Path,
    record_path: pathlib.Path,
) -> None:
    """Revalidate and remove one unregistered residual worktree directory."""

    _, branch, worktree, expected_root = _read_residual_cleanup_record(
        repo_root, record_path
    )
    _validate_worktree_path(worktree, expected_root, allow_inaccessible=False)
    registered = _selected_worktree(repo_root, branch)
    if registered is not None or worktree in _registered_worktree_paths(repo_root):
        raise PendingWorkError("Refusing to remove a registered worktree path.")
    if _lstat(worktree) is None:
        return
    if os.name == "nt":
        _take_ownership_and_remove(repo_root, worktree, expected_root)
    else:
        shutil.rmtree(worktree)


def _finish_recorded_residual_cleanup(
    repo_root: pathlib.Path,
    record_path: pathlib.Path,
) -> None:
    """Run automatic residual cleanup and retire its record after absence."""

    _, branch, worktree, _ = _read_residual_cleanup_record(repo_root, record_path)
    registered = _selected_worktree(repo_root, branch)
    if registered is not None or worktree in _registered_worktree_paths(repo_root):
        raise PendingWorkError("Refusing to clean up a registered worktree path.")
    try:
        if _lstat(worktree) is not None:
            shutil.rmtree(worktree)
    except PermissionError:
        _run_recorded_residual_cleanup(repo_root, record_path)
    if _lstat(worktree) is not None:
        raise PendingWorkError("Residual worktree directory still exists after cleanup.")
    record_path.unlink()


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
    if _read_scope(path) != scope:
        _write_scope(path, scope)
    return scope


def _ready_without_scope() -> dict[str, object]:
    """Return the compact no-op result used when no selected work remains."""

    return {
        "status": "ready",
        "source_branches": [],
        "pending_work_scope": "",
    }


def _branch_exists(repo_root: pathlib.Path, branch: str) -> bool:
    """Return exact local-branch existence without treating Git errors as absence."""

    result = run_command(
        _git(repo_root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"),
        cwd=repo_root,
    )
    if result.returncode not in {0, 1}:
        raise PendingWorkError(f"Could not verify pending-work branch {branch!r}.")
    return result.returncode == 0


def _commit_exists(repo_root: pathlib.Path, commit: str) -> bool:
    """Return whether one recorded full SHA still resolves to a commit object."""

    result = run_command(
        _git(repo_root, "cat-file", "-e", f"{commit}^{{commit}}"),
        cwd=repo_root,
    )
    return result.returncode == 0


def _is_ancestor(repo_root: pathlib.Path, ancestor: str, descendant: str) -> bool:
    """Compare two recorded commits while preserving Git comparison errors."""

    result = run_command(
        _git(repo_root, "merge-base", "--is-ancestor", ancestor, descendant),
        cwd=repo_root,
    )
    if result.returncode not in {0, 1}:
        raise PendingWorkError(
            f"Could not compare recorded commits {ancestor} and {descendant}."
        )
    return result.returncode == 0


def _source_record(repo_root: pathlib.Path, branch: str) -> dict[str, str]:
    """Capture one selected branch's exact current tip before scope recording."""

    commit = require_output(
        _git(repo_root, "rev-parse", f"refs/heads/{branch}"), cwd=repo_root
    ).splitlines()[0]
    if ship.FULL_SHA_RE.fullmatch(commit) is None:
        raise PendingWorkError(f"Source branch has an invalid commit: {branch!r}")
    return {"branch": branch, "commit": commit, "state": "retained"}


def _source_branches(scope: dict[str, Any]) -> list[str]:
    """Return the compact branch-only result retained by the public CLI."""

    return [str(source["branch"]) for source in scope["sources"]]


def _scope_with_sources(
    scope: dict[str, Any], sources: list[dict[str, str]]
) -> dict[str, Any]:
    """Build the canonical v2 record ordering used by every atomic write."""

    return {
        **scope,
        "sources": sorted(sources, key=lambda source: source["branch"]),
    }


def _recover_completed_deletions(
    repo_root: pathlib.Path,
    path: pathlib.Path,
    scope: dict[str, Any],
) -> dict[str, Any] | None:
    """Retire only evidence-proven interruptions after helper-owned deletion.

    ``deleting`` is written before cleanup begins. A missing branch alone is
    never sufficient: its recorded source commit must still exist and be
    contained in this scope's recorded target. Any residual-worktree record is
    completed before the source identity is discarded.
    """

    retained: list[dict[str, str]] = []
    changed = False
    target_commit = str(scope["target_commit"])
    for source in scope["sources"]:
        normalized = {
            "branch": str(source["branch"]),
            "commit": str(source["commit"]),
            "state": str(source["state"]),
        }
        branch = normalized["branch"]
        if (
            normalized["state"] != "deleting"
            or _branch_exists(repo_root, branch)
            or not _commit_exists(repo_root, normalized["commit"])
            or not _is_ancestor(repo_root, normalized["commit"], target_commit)
        ):
            retained.append(normalized)
            continue
        residual_record = _residual_cleanup_record_path(path, branch)
        if residual_record.exists():
            _finish_recorded_residual_cleanup(repo_root, residual_record)
        changed = True
    if not changed:
        return scope
    if retained:
        recovered = _scope_with_sources(scope, retained)
        _write_scope(path, recovered)
        return recovered
    path.unlink()
    return None


def _set_source_state(
    path: pathlib.Path,
    scope: dict[str, Any],
    branch: str,
    state: str,
) -> dict[str, Any]:
    """Atomically persist one helper-owned cleanup transition."""

    updated: list[dict[str, str]] = []
    found = False
    for source in scope["sources"]:
        normalized = {
            "branch": str(source["branch"]),
            "commit": str(source["commit"]),
            "state": str(source["state"]),
        }
        if normalized["branch"] == branch:
            normalized["state"] = state
            found = True
        updated.append(normalized)
    if not found:
        raise PendingWorkError(f"Pending-work source is missing: {branch!r}")
    transitioned = _scope_with_sources(scope, updated)
    _write_scope(path, transitioned)
    return transitioned


def _remove_source_record(
    path: pathlib.Path,
    scope: dict[str, Any],
    branch: str,
) -> dict[str, Any] | None:
    """Atomically retire one source only after its branch deletion succeeded."""

    remaining = [
        {
            "branch": str(source["branch"]),
            "commit": str(source["commit"]),
            "state": str(source["state"]),
        }
        for source in scope["sources"]
        if source["branch"] != branch
    ]
    if len(remaining) == len(scope["sources"]):
        raise PendingWorkError(f"Pending-work source is missing: {branch!r}")
    if remaining:
        updated = _scope_with_sources(scope, remaining)
        _write_scope(path, updated)
        return updated
    path.unlink()
    return None


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

    requested_sources = sorted(
        (_source_record(repo_root, branch) for branch in source_branches),
        key=lambda source: source["branch"],
    )
    requested_scope = {
        "version": ship.PENDING_WORK_SCOPE_VERSION,
        "target_branch": target_branch,
        "target_commit": target_commit,
        "sources": requested_sources,
    }
    findings = ship._pending_work_findings(repo_root, requested_scope)
    if findings:
        return {
            "status": "pending_work",
            "remote_mutation": False,
            "findings": findings,
        }

    path = _scope_path(repo_root, target_branch)
    retained: list[dict[str, str]] = []
    if path.is_file():
        raw_existing = _read_scope(path)
        recorded_target = raw_existing.get("target_commit")
        if (
            not isinstance(recorded_target, str)
            or ship.FULL_SHA_RE.fullmatch(recorded_target.lower()) is None
        ):
            raise PendingWorkError("Pending-work scope has an invalid target commit.")
        existing = _validated_scope(
            repo_root,
            path,
            target_branch=target_branch,
            target_commit=recorded_target.lower(),
        )
        old_target = str(existing["target_commit"])
        if old_target != target_commit:
            if not _commit_exists(repo_root, old_target):
                return {
                    "status": "pending_work",
                    "remote_mutation": False,
                    "findings": [
                        {
                            "kind": "missing_target_commit",
                            "subject": target_branch,
                            "detail": "recorded target commit is unavailable",
                        }
                    ],
                }
            if not _is_ancestor(repo_root, old_target, target_commit):
                return {
                    "status": "pending_work",
                    "remote_mutation": False,
                    "findings": [
                        {
                            "kind": "target_history_diverged",
                            "subject": target_branch,
                            "detail": "recorded target is not an ancestor of new target",
                        }
                    ],
                }
        existing = _recover_completed_deletions(repo_root, path, existing)
        if existing is not None:
            candidate_existing = {**existing, "target_commit": target_commit}
            existing_findings = ship._pending_work_findings(
                repo_root, candidate_existing
            )
            existing_findings.extend(
                {
                    "kind": "incomplete_cleanup",
                    "subject": str(source["branch"]),
                    "detail": "complete prior helper cleanup before recording",
                }
                for source in existing["sources"]
                if source["state"] == "deleting"
                and _branch_exists(repo_root, str(source["branch"]))
            )
            if existing_findings:
                return {
                    "status": "pending_work",
                    "remote_mutation": False,
                    "findings": existing_findings,
                }
            retained = [
                {
                    "branch": str(source["branch"]),
                    "commit": str(source["commit"]),
                    "state": str(source["state"]),
                }
                for source in existing["sources"]
            ]
    merged_by_branch = {source["branch"]: source for source in retained}
    merged_by_branch.update(
        {source["branch"]: source for source in requested_sources}
    )
    merged = sorted(merged_by_branch.values(), key=lambda source: source["branch"])
    scope = {
        "version": ship.PENDING_WORK_SCOPE_VERSION,
        "target_branch": target_branch,
        "target_commit": target_commit,
        "sources": merged,
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
        "source_branches": _source_branches(scope),
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

    expected_path = _scope_path(repo_root, target_branch)
    if path.resolve() != expected_path:
        raise PendingWorkError(
            "Pending-work manager accepts only its generated scope path."
        )
    if not path.exists():
        return _ready_without_scope()
    scope = _validated_scope(
        repo_root,
        path,
        target_branch=target_branch,
        target_commit=target_commit,
    )
    scope = _recover_completed_deletions(repo_root, path, scope)
    if scope is None:
        return _ready_without_scope()
    findings = ship._pending_work_findings(repo_root, scope)
    if findings:
        return {
            "status": "pending_work",
            "remote_mutation": False,
            "findings": findings,
            "target_commit": scope["target_commit"],
            "pending_work_scope": str(path.resolve()),
        }
    return {
        "status": "ready",
        "target_commit": scope["target_commit"],
        "source_branches": _source_branches(scope),
        "pending_work_scope": str(path.resolve()),
    }


def prepare_scope(
    repo_root: pathlib.Path,
    *,
    target_branch: str,
    target_commit: str | None = None,
) -> dict[str, object]:
    """Resume the recorded target identity and recheck its selected scope."""

    _validate_branch(repo_root, target_branch)
    path = _scope_path(repo_root, target_branch)
    if not path.exists():
        return _ready_without_scope()
    recorded_scope = _read_scope(path)
    recorded_commit = recorded_scope.get("target_commit")
    if (
        not isinstance(recorded_commit, str)
        or ship.FULL_SHA_RE.fullmatch(recorded_commit) is None
    ):
        raise PendingWorkError("Pending-work scope has an invalid target commit.")
    if target_commit is not None:
        target_commit = target_commit.lower()
        if ship.FULL_SHA_RE.fullmatch(target_commit) is None:
            raise PendingWorkError("Target commit must be a full Git SHA.")
        if target_commit != recorded_commit:
            raise PendingWorkError(
                "Explicit target commit does not match the retained pending-work scope."
            )
    require_success(
        _git(repo_root, "cat-file", "-e", f"{recorded_commit}^{{commit}}"),
        cwd=repo_root,
    )
    return check_scope(
        repo_root,
        path,
        target_branch=target_branch,
        target_commit=recorded_commit,
    )


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
    scope: pathlib.Path,
    branch: str,
    path: pathlib.Path,
    expected_root: pathlib.Path,
) -> None:
    """Remove a worktree with an exact automatic residual-cleanup record."""

    _validate_worktree_path(path, expected_root, allow_inaccessible=False)
    record_path = _write_residual_cleanup_record(
        repo_root,
        scope,
        branch,
        path,
        expected_root,
    )
    result = run_command(
        _git(repo_root, "worktree", "remove", str(path)),
        cwd=repo_root,
    )
    registered = _selected_worktree(repo_root, branch)
    if registered is not None:
        if registered != path:
            raise PendingWorkError(
                f"Selected branch moved to another worktree during cleanup: {branch}"
            )
        detail = "\n".join(
            line
            for stream in (result.stdout, result.stderr)
            for line in stream.splitlines()[-8:]
            if line.strip()
        )
        suffix = f"\n{detail}" if detail else ""
        raise CommandError(f"Git did not unregister selected worktree {branch!r}.{suffix}")
    _finish_recorded_residual_cleanup(repo_root, record_path)


def finalize_scope(
    repo_root: pathlib.Path,
    path: pathlib.Path,
    *,
    target_branch: str,
    target_commit: str,
    current_branch: str,
    current_commit: str,
) -> dict[str, object]:
    """Late-recheck selected source work and prune its empty project root."""

    checked = check_scope(
        repo_root,
        path,
        target_branch=target_branch,
        target_commit=target_commit,
    )
    if checked["status"] != "ready":
        return checked
    if not checked["pending_work_scope"]:
        return {
            "status": "finalized",
            "removed": [],
            "pending_work_scope": "",
        }
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

    scope = _validated_scope(
        repo_root,
        path,
        target_branch=target_branch,
        target_commit=target_commit,
    )
    expected_root = (repo_root.parent / "worktrees" / repo_root.name).resolve()
    removed: list[str] = []
    sources = list(scope["sources"])
    for source in sources:
        branch = str(source["branch"])
        if branch in {current_branch, target_branch}:
            raise PendingWorkError("Pending-work scope contains a protected branch.")
        if source["state"] == "retained":
            scope = _set_source_state(path, scope, branch, "deleting")
        worktree = _selected_worktree(repo_root, branch)
        if worktree is not None:
            _remove_selected_worktree(
                repo_root,
                path,
                branch,
                worktree,
                expected_root,
            )
        else:
            record_path = _residual_cleanup_record_path(path, branch)
            if record_path.exists():
                _finish_recorded_residual_cleanup(repo_root, record_path)
        require_success(
            _git(repo_root, "branch", "-d", branch),
            cwd=repo_root,
        )
        removed.append(branch)
        scope = _remove_source_record(path, scope, branch)
    if expected_root.is_dir() and not any(expected_root.iterdir()):
        expected_root.rmdir()
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

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--target-branch", required=True)
    prepare.add_argument("--target-commit")

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
        if args.command == "prepare":
            result = prepare_scope(
                repo_root,
                target_branch=args.target_branch,
                target_commit=(
                    args.target_commit.lower() if args.target_commit else None
                ),
            )
        elif args.command == "record":
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
