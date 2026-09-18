"""Bound selected-work directory cleanup and preserve active update state.

Callers validate a recorded worktree or task-temp identity before requesting
deletion. This module checks real directory boundaries and never follows links
while preparing a tree for removal.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat


class PendingWorkError(RuntimeError):
    """Raised when selected-scope persistence or cleanup is unsafe."""


SKILL_UPDATE_RETENTION_MARKER = ".ceratops-skill-update-active.json"
SKILL_UPDATE_RETENTION_SCHEMA = "ceratops-skill-update-retention.v1"


def _inside(path: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


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


def _cleanup_boundary(
    path: pathlib.Path,
    boundary_names: set[str],
) -> pathlib.Path:
    """Resolve the nearest named ancestor that empty cleanup must preserve."""

    if not path.is_absolute():
        raise PendingWorkError(f"Cleanup path must be absolute: {path}")
    boundary = next(
        (
            candidate
            for candidate in (path, *path.parents)
            if candidate.name.casefold() in boundary_names
        ),
        None,
    )
    if boundary is None:
        names = ", ".join(sorted(boundary_names))
        raise PendingWorkError(f"Cleanup path has no {names} directory boundary: {path}")
    attributes = _lstat(boundary)
    if attributes is None or not stat.S_ISDIR(attributes.st_mode):
        raise PendingWorkError(f"Cleanup boundary is not a directory: {boundary}")
    if _is_reparse(boundary, attributes):
        raise PendingWorkError(f"Cleanup boundary is a reparse point: {boundary}")
    return boundary


def _remove_empty_parents(
    path: pathlib.Path,
    *,
    boundary_names: set[str],
) -> None:
    """Remove empty real directories below, but never including, a named boundary."""

    boundary = _cleanup_boundary(path, boundary_names)
    current = path
    while current != boundary:
        attributes = _lstat(current)
        if attributes is None:
            current = current.parent
            continue
        if not stat.S_ISDIR(attributes.st_mode) or _is_reparse(current, attributes):
            raise PendingWorkError(f"Empty-folder cleanup target is unsafe: {current}")
        try:
            if any(current.iterdir()):
                return
            current.rmdir()
        except OSError as exc:
            raise PendingWorkError(
                f"Could not remove empty cleanup directory {current}: {exc}"
            ) from exc
        current = current.parent


def _remove_tree(root: pathlib.Path) -> None:
    """Remove one caller-validated tree, clearing Windows read-only Git objects.

    The scoped finalizer owns this cleanup. Links inside the tree are left for
    ``shutil.rmtree`` to unlink; their targets are never traversed or changed.
    """

    attributes = _lstat(root)
    if (
        attributes is None
        or not root.is_absolute()
        or not stat.S_ISDIR(attributes.st_mode)
        or _is_reparse(root, attributes)
    ):
        raise PendingWorkError(f"Tree cleanup target is not a real directory: {root}")
    if os.name == "nt":
        canonical_root = root.resolve(strict=True)
        readonly_flag = stat.FILE_ATTRIBUTE_READONLY
        for current, directory_names, file_names in os.walk(root, followlinks=False):
            directory = pathlib.Path(current)
            current_attributes = _lstat(directory)
            if (
                current_attributes is None
                or not stat.S_ISDIR(current_attributes.st_mode)
                or _is_reparse(directory, current_attributes)
                or not _inside(directory.resolve(strict=True), canonical_root)
            ):
                raise PendingWorkError(f"Tree cleanup crossed its boundary: {directory}")
            for name in directory_names[:]:
                child = directory / name
                child_attributes = _lstat(child)
                if child_attributes is None:
                    raise PendingWorkError(f"Tree cleanup path disappeared: {child}")
                if _is_reparse(child, child_attributes):
                    directory_names.remove(name)
                    continue
                if not stat.S_ISDIR(child_attributes.st_mode):
                    raise PendingWorkError(f"Tree cleanup path is not a directory: {child}")
            for name in file_names:
                child = directory / name
                child_attributes = _lstat(child)
                if child_attributes is None:
                    raise PendingWorkError(f"Tree cleanup path disappeared: {child}")
                if _is_reparse(child, child_attributes):
                    continue
                if not stat.S_ISREG(child_attributes.st_mode):
                    raise PendingWorkError(f"Tree cleanup path is not a regular file: {child}")
                if getattr(child_attributes, "st_file_attributes", 0) & readonly_flag:
                    os.chmod(child, child_attributes.st_mode | stat.S_IWRITE)
            if getattr(current_attributes, "st_file_attributes", 0) & readonly_flag:
                os.chmod(directory, current_attributes.st_mode | stat.S_IWRITE)
    shutil.rmtree(root)


def _active_skill_update_state(candidate: pathlib.Path) -> pathlib.Path | None:
    """Return the state protected by a valid active-update retention marker.

    The marker is a non-executable handoff owned by the skill-update helper.
    Invalid marker or state paths block destructive cleanup instead of turning
    missing verification evidence into successful finalization.
    """

    marker = candidate / SKILL_UPDATE_RETENTION_MARKER
    attributes = _lstat(marker)
    if attributes is None:
        return None
    if not stat.S_ISREG(attributes.st_mode) or _is_reparse(marker, attributes):
        raise PendingWorkError(
            f"Skill-update retention marker is not a regular file: {marker}"
        )
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PendingWorkError(
            f"Could not read skill-update retention marker {marker}: {exc}"
        ) from exc
    if not isinstance(value, dict) or set(value) != {"schema", "state"}:
        raise PendingWorkError(f"Skill-update retention marker is invalid: {marker}")
    if value.get("schema") != SKILL_UPDATE_RETENTION_SCHEMA:
        raise PendingWorkError(
            f"Skill-update retention marker has an unsupported schema: {marker}"
        )
    raw_state = value.get("state")
    if not isinstance(raw_state, str) or not raw_state:
        raise PendingWorkError(f"Skill-update retention marker has no state: {marker}")
    state_path = pathlib.Path(raw_state)
    if not state_path.is_absolute():
        raise PendingWorkError(
            f"Skill-update retention state escapes its task-temp directory: {state_path}"
        )
    try:
        resolved_state = state_path.resolve(strict=True)
    except OSError as exc:
        raise PendingWorkError(
            f"Could not resolve skill-update retention state {state_path}: {exc}"
        ) from exc
    if resolved_state != state_path or not _inside(resolved_state, candidate):
        raise PendingWorkError(
            f"Skill-update retention state escapes its task-temp directory: {state_path}"
        )
    state_attributes = _lstat(state_path)
    if (
        state_attributes is None
        or not stat.S_ISREG(state_attributes.st_mode)
        or _is_reparse(state_path, state_attributes)
    ):
        raise PendingWorkError(
            f"Skill-update retention state is not a regular file: {state_path}"
        )
    return state_path


def _remove_matching_task_temp_directories(
    repo_root: pathlib.Path,
    task_temp_root: pathlib.Path,
    *,
    worktree_name: str,
    thread_id: str | None,
) -> None:
    """Remove unambiguous task directories without consuming active updates.

    A worktree name owns only an exact directory name. A canonical thread UUID
    may own its exact name or a ``UUID-`` suffix because the full UUID plus the
    delimiter cannot collide with another worktree-name prefix. A valid
    helper-owned retention marker preserves its matching directory for the
    required post-deployment skill-update finalizer.
    """

    canonical_root = (repo_root.parent / "tmp" / repo_root.name).resolve()
    if task_temp_root != canonical_root:
        raise PendingWorkError("Residual-cleanup record has an unexpected task-temp root.")
    attributes = _lstat(task_temp_root)
    if attributes is None:
        return
    _cleanup_boundary(task_temp_root, {"tmp", "temp"})
    if not stat.S_ISDIR(attributes.st_mode) or _is_reparse(task_temp_root, attributes):
        raise PendingWorkError(f"Task-temp root is not a real directory: {task_temp_root}")
    exact_names = {worktree_name.casefold()}
    thread_prefix = None
    if isinstance(thread_id, str) and thread_id:
        folded_thread = thread_id.casefold()
        exact_names.add(folded_thread)
        thread_prefix = f"{folded_thread}-"

    def matches_recorded_identity(candidate: pathlib.Path) -> bool:
        folded_name = candidate.name.casefold()
        return folded_name in exact_names or (
            thread_prefix is not None and folded_name.startswith(thread_prefix)
        )

    retained: set[pathlib.Path] = set()
    for candidate in sorted(task_temp_root.iterdir(), key=lambda item: item.name.casefold()):
        if not matches_recorded_identity(candidate):
            continue
        candidate_attributes = _lstat(candidate)
        if candidate_attributes is None:
            continue
        if _is_reparse(candidate, candidate_attributes):
            raise PendingWorkError(f"Matching task-temp directory is a reparse point: {candidate}")
        if not stat.S_ISDIR(candidate_attributes.st_mode):
            continue
        if _active_skill_update_state(candidate) is not None:
            retained.add(candidate)
            continue
        _remove_tree(candidate)
        if _lstat(candidate) is not None:
            raise PendingWorkError(f"Task-temp directory still exists after cleanup: {candidate}")
    for candidate in task_temp_root.iterdir():
        if not matches_recorded_identity(candidate):
            continue
        if candidate in retained:
            continue
        candidate_attributes = _lstat(candidate)
        if candidate_attributes is not None and (
            stat.S_ISDIR(candidate_attributes.st_mode)
            or _is_reparse(candidate, candidate_attributes)
        ):
            raise PendingWorkError(
                f"Matching task-temp directory still exists after cleanup: {candidate}"
            )
    _remove_empty_parents(task_temp_root, boundary_names={"tmp", "temp"})
