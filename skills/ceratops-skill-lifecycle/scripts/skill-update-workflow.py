#!/usr/bin/env python3
"""Prepare, verify, and finalize one declared skill update workflow.

The helper records the caller's pre-existing Git baseline before source edits,
then verifies that only declared paths changed and that undeclared dirty state
was preserved. One changed in-scope snapshot may start a correction generation
after success; it invalidates the earlier success before checks and cannot be
reopened after passing. Prepare collects declared pytest nodes without running
tests. Checks use closed structured forms and run without a shell.
Source files are never patched, staged, committed, installed, promoted, or
rolled back. Prepare records exact cleanup ownership and an active-update
retention marker beneath the verified task temp root, verify retains detailed
evidence, and finalize is the caller's explicit signal that successful
verification and requested deployment/use are complete. Finalize removes only
recorded workflow-owned request, state, evidence, and retention-marker files,
then removes the verified task-temp root only when empty.
Stdout is only ``OK`` and failures are one compact stderr line.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence

REQUEST_SCHEMA = "ceratops-skill-update-request.v2"
STATE_SCHEMA = "ceratops-skill-update-state.v2"
EVIDENCE_SCHEMA = "ceratops-skill-update-evidence.v2"
CLEANUP_SCHEMA = "ceratops-skill-update-cleanup.v1"
RETENTION_SCHEMA = "ceratops-skill-update-retention.v1"
RETENTION_MARKER = ".ceratops-skill-update-active.json"
REQUEST_FIELDS = {
    "schema",
    "repo_root",
    "task_temp_root",
    "evidence_output",
    "disposable_artifacts",
    "selected_skills",
    "allowed_paths",
    "change_groups",
    "checks",
}
GROUP_FIELDS = {"name", "paths"}
CHECK_FIELDS = {
    "pytest": {"kind", "nodes"},
    "command": {"kind", "argv"},
    "search": {"kind", "pattern", "paths", "expected_matches"},
}
STATE_FIELDS = {
    "schema",
    "repo_root",
    "branch",
    "head",
    "selected_skills",
    "allowed_paths",
    "change_groups",
    "checks",
    "baseline_dirty",
    "baseline_targets",
    "cleanup",
    "verification",
}
CLEANUP_FIELDS = {
    "schema",
    "task_temp_root",
    "owned_artifacts",
    "protected_artifacts",
}
OWNED_ARTIFACT_FIELDS = {"role", "path", "sha256"}
VERIFICATION_FIELDS = {"status", "evidence_sha256", "input_sha256", "generation"}
DISPOSABLE_ROLES = {"request", "state", "evidence"}
OWNED_ROLES = DISPOSABLE_ROLES | {"retention"}
SKILL_NAME_RE = re.compile(
    r"^(?![a-z0-9-]*--)[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$"
)
PYTEST_NODE_RE = re.compile(r"^tests/[A-Za-z0-9_./-]+\.py::\S+$")
MAX_CAPTURE = 32_000
MAX_COMPACT_DETAIL = 1_000


class UpdateExecutionError(RuntimeError):
    """One compact request, baseline, check, or evidence failure."""


def _run(
    arguments: Sequence[str],
    *,
    cwd: pathlib.Path,
) -> subprocess.CompletedProcess[str]:
    """Run one declared process without shell interpretation."""

    try:
        return subprocess.run(
            list(arguments),
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise UpdateExecutionError(
            f"could not start {arguments[0]}: {exc}"
        ) from exc


def _git(repo_root: pathlib.Path, *arguments: str) -> str:
    result = _run(["git", "-C", str(repo_root), *arguments], cwd=repo_root)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        message = f"git {' '.join(arguments)} failed"
        raise UpdateExecutionError(f"{message}: {detail}" if detail else message)
    return result.stdout


def _read_json(path: pathlib.Path, label: str) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateExecutionError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(value, Mapping):
        raise UpdateExecutionError(f"{label} must be a JSON object")
    return value


def _closed_fields(
    value: Mapping[str, object],
    fields: set[str],
    label: str,
) -> None:
    actual = set(value)
    if actual == fields:
        return
    missing = sorted(fields - actual)
    extra = sorted(actual - fields)
    details: list[str] = []
    if missing:
        details.append("missing " + ", ".join(missing))
    if extra:
        details.append("unknown " + ", ".join(extra))
    raise UpdateExecutionError(f"{label} fields are invalid: {'; '.join(details)}")


def _string_list(value: object, label: str) -> list[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise UpdateExecutionError(f"{label} must be a nonempty string list")
    result = list(value)
    if len(result) != len(set(result)):
        raise UpdateExecutionError(f"{label} values must be unique")
    return result


def _safe_relative(value: str, label: str) -> pathlib.PurePosixPath:
    pure = pathlib.PurePosixPath(value)
    windows = pathlib.PureWindowsPath(value)
    if (
        not value
        or "\\" in value
        or pure.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ".." in pure.parts
        or str(pure) != value
    ):
        raise UpdateExecutionError(f"{label} is not a safe repo-relative path: {value}")
    return pure


def _target(repo_root: pathlib.Path, value: str) -> pathlib.Path:
    pure = _safe_relative(value, "path")
    target = repo_root.joinpath(*pure.parts)
    try:
        target.resolve(strict=False).relative_to(repo_root)
    except ValueError as exc:
        raise UpdateExecutionError(f"path escapes the repository: {value}") from exc
    return target


def _outside_repo(path: pathlib.Path, repo_root: pathlib.Path, label: str) -> None:
    try:
        path.relative_to(repo_root)
    except ValueError:
        return
    raise UpdateExecutionError(f"{label} must be outside the repository")


def _absolute(path: pathlib.Path) -> pathlib.Path:
    """Return a lexical absolute path without resolving links."""

    return pathlib.Path(os.path.abspath(path.expanduser()))


def _is_link(path: pathlib.Path) -> bool:
    """Treat symbolic links and Windows junctions as cleanup escapes."""

    junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(junction and junction())


def _reject_link_chain(path: pathlib.Path, label: str) -> None:
    """Reject any existing link component from a path through its anchor."""

    for candidate in (path, *path.parents):
        if _is_link(candidate):
            raise UpdateExecutionError(f"{label} uses a symlink or junction: {candidate}")


def _task_artifact(
    path: pathlib.Path,
    task_temp_root: pathlib.Path,
    label: str,
    *,
    must_exist: bool,
) -> pathlib.Path:
    """Validate one exact file path inside the declared task temp root."""

    lexical = _absolute(path)
    try:
        relative = lexical.relative_to(task_temp_root)
    except ValueError as exc:
        raise UpdateExecutionError(f"{label} escapes task_temp_root") from exc
    if not relative.parts:
        raise UpdateExecutionError(f"{label} must be a file beneath task_temp_root")
    current = task_temp_root
    for part in relative.parts:
        current = current / part
        if _is_link(current):
            raise UpdateExecutionError(f"{label} uses a symlink or junction: {current}")
    if not lexical.parent.is_dir():
        raise UpdateExecutionError(f"{label} directory does not exist: {lexical.parent}")
    repository_probe = _run(
        ["git", "-C", str(lexical.parent), "rev-parse", "--show-toplevel"],
        cwd=lexical.parent,
    )
    if repository_probe.returncode == 0:
        raise UpdateExecutionError(f"{label} must not be a repository file")
    if must_exist:
        if not lexical.is_file():
            raise UpdateExecutionError(f"{label} must be a regular file: {lexical}")
    elif lexical.exists() and not lexical.is_file():
        raise UpdateExecutionError(f"{label} must be a regular file target: {lexical}")
    resolved = lexical.resolve(strict=must_exist)
    try:
        resolved.relative_to(task_temp_root)
    except ValueError as exc:
        raise UpdateExecutionError(f"{label} resolves outside task_temp_root") from exc
    return lexical


def _file_sha256(path: pathlib.Path) -> str:
    """Hash one recorded cleanup artifact without loading it all at once."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(
    path: pathlib.Path,
    value: Mapping[str, object],
    label: str,
) -> None:
    """Atomically write workflow state or evidence and clean its staging file."""

    if not path.parent.is_dir():
        raise UpdateExecutionError(f"{label} directory does not exist: {path.parent}")
    if _is_link(path) or (path.exists() and not path.is_file()):
        raise UpdateExecutionError(f"{label} must be a regular file target: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.skill-update.",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except OSError as exc:
        raise UpdateExecutionError(f"could not write {label}: {exc}") from exc
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _git_path(repo_root: pathlib.Path, value: str) -> pathlib.Path:
    path = pathlib.Path(value.strip())
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _verified_task_temp_root(
    value: object,
    repo_root: pathlib.Path,
) -> pathlib.Path:
    """Verify the repository-declared task-temp location and its boundaries."""

    if not isinstance(value, str) or not value:
        raise UpdateExecutionError("task_temp_root must be nonempty text")
    raw = pathlib.Path(value).expanduser()
    if not raw.is_absolute():
        raise UpdateExecutionError("task_temp_root must be absolute")
    lexical = _absolute(raw)
    _reject_link_chain(lexical, "task_temp_root")
    if not lexical.is_dir():
        raise UpdateExecutionError("task_temp_root must be an existing directory")
    resolved = lexical.resolve(strict=True)
    _outside_repo(resolved, repo_root, "task_temp_root")
    inside_git = _run(
        ["git", "-C", str(resolved), "rev-parse", "--show-toplevel"],
        cwd=resolved,
    )
    if inside_git.returncode == 0:
        raise UpdateExecutionError("task_temp_root must not be inside a Git worktree")
    common_dir = _git_path(
        repo_root,
        _git(repo_root, "rev-parse", "--git-common-dir"),
    )
    primary_root = common_dir.parent
    expected_parent = primary_root.parent / "tmp" / primary_root.name
    if resolved.parent != expected_parent.resolve(strict=True):
        raise UpdateExecutionError(
            f"task_temp_root must be one task directory under {expected_parent}"
        )
    return resolved


def _finalize_primary_root(cleanup: object) -> pathlib.Path:
    """Recover the live primary checkout after a task worktree was removed.

    Finalization uses this checkout only to revalidate the recorded task-temp
    boundary. The path is derived from the required sibling ``tmp/<repo>``
    layout and must resolve to the primary checkout of that Git repository.
    """

    if not isinstance(cleanup, Mapping):
        raise UpdateExecutionError("state cleanup must be an object")
    value = cleanup.get("task_temp_root")
    if not isinstance(value, str) or not value:
        raise UpdateExecutionError("state task_temp_root is invalid")
    raw = pathlib.Path(value).expanduser()
    if not raw.is_absolute():
        raise UpdateExecutionError("state task_temp_root must be absolute")
    task_temp_root = _absolute(raw)
    _reject_link_chain(task_temp_root, "task_temp_root")
    repository_temp_root = task_temp_root.parent
    temp_root = repository_temp_root.parent
    if temp_root.name != "tmp":
        raise UpdateExecutionError("state task_temp_root lacks the required tmp layout")
    primary_candidate = temp_root.parent / repository_temp_root.name
    _reject_link_chain(primary_candidate, "derived primary checkout")
    if not primary_candidate.is_dir():
        raise UpdateExecutionError("derived primary checkout is unavailable")
    primary_root = primary_candidate.resolve(strict=True)
    if _git(primary_root, "rev-parse", "--is-inside-work-tree").strip() != "true":
        raise UpdateExecutionError("derived primary checkout is not a Git worktree")
    top = pathlib.Path(
        _git(primary_root, "rev-parse", "--show-toplevel").strip()
    ).resolve(strict=True)
    git_dir = _git_path(primary_root, _git(primary_root, "rev-parse", "--git-dir"))
    common_dir = _git_path(
        primary_root,
        _git(primary_root, "rev-parse", "--git-common-dir"),
    )
    if top != primary_root or git_dir != common_dir or common_dir.parent != primary_root:
        raise UpdateExecutionError("derived checkout is not the repository primary")
    return primary_root


def _verify_task_worktree(repo_root: pathlib.Path) -> tuple[str, str]:
    if _git(repo_root, "rev-parse", "--is-inside-work-tree").strip() != "true":
        raise UpdateExecutionError("repo_root is not a Git worktree")
    top = pathlib.Path(_git(repo_root, "rev-parse", "--show-toplevel").strip()).resolve()
    if top != repo_root:
        raise UpdateExecutionError("repo_root must be the Git worktree root")
    git_dir = _git_path(repo_root, _git(repo_root, "rev-parse", "--git-dir"))
    common_dir = _git_path(
        repo_root,
        _git(repo_root, "rev-parse", "--git-common-dir"),
    )
    if git_dir == common_dir:
        raise UpdateExecutionError("repo_root must be a linked task worktree")
    branch = _git(repo_root, "branch", "--show-current").strip()
    if not branch:
        raise UpdateExecutionError("task worktree must not use detached HEAD")
    if branch in {"main", "release/local"}:
        raise UpdateExecutionError(f"protected branch is not a task branch: {branch}")
    return branch, _git(repo_root, "rev-parse", "HEAD").strip()


def _dirty_paths(repo_root: pathlib.Path) -> set[str]:
    commands = (
        ("diff", "--name-only", "--no-renames", "-z"),
        ("diff", "--cached", "--name-only", "--no-renames", "-z"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    )
    paths: set[str] = set()
    for command in commands:
        output = _git(repo_root, *command)
        paths.update(path.replace("\\", "/") for path in output.split("\0") if path)
    return paths


def _is_tracked(repo_root: pathlib.Path, path: str) -> bool:
    """Allow existing ancillary files without permitting undeclared new surfaces."""

    result = _run(
        ["git", "-C", str(repo_root), "ls-files", "--error-unmatch", "--", path],
        cwd=repo_root,
    )
    return result.returncode == 0


def _content_snapshot(target: pathlib.Path) -> dict[str, object]:
    if target.is_symlink():
        return {
            "kind": "symlink",
            "sha256": hashlib.sha256(os.readlink(target).encode()).hexdigest(),
        }
    if not target.exists():
        return {"kind": "missing"}
    if not target.is_file():
        return {"kind": "other"}
    try:
        content = target.read_bytes()
    except OSError as exc:
        raise UpdateExecutionError(f"could not read baseline path {target.name}: {exc}") from exc
    return {
        "kind": "file",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _snapshot(repo_root: pathlib.Path, path: str) -> dict[str, object]:
    target = repo_root.joinpath(*pathlib.PurePosixPath(path).parts)
    return {
        "content": _content_snapshot(target),
        "index": _git(repo_root, "ls-files", "--stage", "-z", "--", path),
        "status": _git(
            repo_root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            path,
        ),
    }


def _validate_checks(
    raw_checks: object,
    repo_root: pathlib.Path,
    allowed_paths: set[str],
) -> list[dict[str, object]]:
    if (
        not isinstance(raw_checks, Sequence)
        or isinstance(raw_checks, (str, bytes))
        or not raw_checks
    ):
        raise UpdateExecutionError("checks must be a nonempty list")
    checks: list[dict[str, object]] = []
    for index, raw in enumerate(raw_checks, start=1):
        if not isinstance(raw, Mapping):
            raise UpdateExecutionError(f"check {index} must be an object")
        kind = raw.get("kind")
        if not isinstance(kind, str) or kind not in CHECK_FIELDS:
            raise UpdateExecutionError(f"check {index} kind is invalid")
        _closed_fields(raw, CHECK_FIELDS[kind], f"check {index}")
        check = dict(raw)
        if kind == "pytest":
            nodes = _string_list(raw["nodes"], f"check {index} nodes")
            for node in nodes:
                if PYTEST_NODE_RE.fullmatch(node) is None:
                    raise UpdateExecutionError(f"pytest node is invalid: {node}")
                test_path = node.split("::", 1)[0]
                target = _target(repo_root, test_path)
                if target.is_symlink() or not target.is_file():
                    raise UpdateExecutionError(f"pytest node file does not exist: {node}")
            check["nodes"] = nodes
        elif kind == "command":
            argv = _string_list(raw["argv"], f"check {index} argv")
            if any("\0" in value for value in argv):
                raise UpdateExecutionError(f"check {index} argv contains NUL")
            check["argv"] = argv
        else:
            pattern = raw["pattern"]
            expected = raw["expected_matches"]
            if not isinstance(pattern, str) or not pattern:
                raise UpdateExecutionError(f"check {index} pattern must be text")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise UpdateExecutionError(f"check {index} pattern is invalid: {exc}") from exc
            paths = _string_list(raw["paths"], f"check {index} paths")
            if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
                raise UpdateExecutionError(
                    f"check {index} expected_matches must be a nonnegative integer"
                )
            for path in paths:
                target = _target(repo_root, path)
                if path not in allowed_paths and (target.is_symlink() or not target.is_file()):
                    raise UpdateExecutionError(f"search path does not exist: {path}")
            check["paths"] = paths
        checks.append(check)
    return checks


def _collect_declared_pytest_nodes(
    repo_root: pathlib.Path,
    checks: Sequence[Mapping[str, object]],
) -> None:
    """Reject uncollectable declared pytest nodes before source edits begin."""

    nodes: list[str] = []
    for check in checks:
        if check.get("kind") != "pytest":
            continue
        raw_nodes = check.get("nodes")
        if not isinstance(raw_nodes, list) or not all(
            isinstance(node, str) for node in raw_nodes
        ):
            raise UpdateExecutionError("validated pytest check is invalid")
        nodes.extend(raw_nodes)
    unique_nodes = list(dict.fromkeys(nodes))
    if not unique_nodes:
        return
    result = _run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *unique_nodes],
        cwd=repo_root,
    )
    if result.returncode:
        detail = " ".join((result.stderr or result.stdout).split())
        if len(detail) > MAX_COMPACT_DETAIL:
            detail = detail[:MAX_COMPACT_DETAIL] + " [truncated]"
        message = "pytest node collection failed"
        raise UpdateExecutionError(f"{message}: {detail}" if detail else message)


def _validated_request(
    path: pathlib.Path,
) -> tuple[
    dict[str, object],
    pathlib.Path,
    pathlib.Path,
    pathlib.Path,
    set[str],
]:
    request_path = _absolute(path)
    _reject_link_chain(request_path, "request")
    if not request_path.is_file():
        raise UpdateExecutionError(f"request must be a regular file: {request_path}")
    request = _read_json(request_path, "request")
    _closed_fields(request, REQUEST_FIELDS, "request")
    if request.get("schema") != REQUEST_SCHEMA:
        raise UpdateExecutionError(f"request schema must be {REQUEST_SCHEMA}")
    repo_value = request["repo_root"]
    if not isinstance(repo_value, str) or not repo_value:
        raise UpdateExecutionError("repo_root must be nonempty text")
    repo_root = pathlib.Path(repo_value).expanduser().resolve(strict=True)
    if not repo_root.is_dir():
        raise UpdateExecutionError("repo_root must be a directory")
    branch, head = _verify_task_worktree(repo_root)
    task_temp_root = _verified_task_temp_root(request["task_temp_root"], repo_root)
    evidence_value = request["evidence_output"]
    if not isinstance(evidence_value, str) or not evidence_value:
        raise UpdateExecutionError("evidence_output must be nonempty text")
    evidence_path = _task_artifact(
        pathlib.Path(evidence_value),
        task_temp_root,
        "evidence output",
        must_exist=False,
    )
    disposable = set(
        _string_list(request["disposable_artifacts"], "disposable_artifacts")
    )
    unknown_disposable = sorted(disposable - DISPOSABLE_ROLES)
    if unknown_disposable:
        raise UpdateExecutionError(
            f"unknown disposable artifact role: {unknown_disposable[0]}"
        )
    missing_outputs = sorted({"state", "evidence"} - disposable)
    if missing_outputs:
        raise UpdateExecutionError(
            f"workflow output is not declared disposable: {missing_outputs[0]}"
        )
    if "request" in disposable:
        _task_artifact(
            request_path,
            task_temp_root,
            "request",
            must_exist=True,
        )

    selected = _string_list(request["selected_skills"], "selected_skills")
    for skill in selected:
        if SKILL_NAME_RE.fullmatch(skill) is None:
            raise UpdateExecutionError(f"selected skill name is unsafe: {skill}")
        root = repo_root / "skills" / skill
        if root.is_symlink() or not (root / "SKILL.md").is_file():
            raise UpdateExecutionError(f"selected skill is not an existing source: {skill}")

    allowed = _string_list(request["allowed_paths"], "allowed_paths")
    allowed_set = set(allowed)
    owners: set[str] = set()
    for value in allowed:
        pure = _safe_relative(value, "allowed path")
        target = _target(repo_root, value)
        matches = [
            skill
            for skill in selected
            if pure.is_relative_to(pathlib.PurePosixPath("skills") / skill)
        ]
        if matches:
            owners.update(matches)
        existing_ancillary = target.is_file() and _is_tracked(repo_root, value)
        shared_source = pure.is_relative_to(
            pathlib.PurePosixPath("skills/sections")
        )
        new_shared_source = (
            shared_source and not target.exists() and target.parent.is_dir()
        )
        if not matches and not existing_ancillary and not new_shared_source:
            raise UpdateExecutionError(
                "allowed path must be selected-skill source, an existing "
                "tracked ancillary file, or a new shared-section source: "
                + value
            )
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise UpdateExecutionError(f"allowed path must be a regular file target: {value}")
        if not target.exists() and not target.parent.is_dir():
            raise UpdateExecutionError(f"allowed path parent does not exist: {value}")
    missing_owners = sorted(set(selected) - owners)
    if missing_owners:
        raise UpdateExecutionError(
            f"selected skill has no allowed source path: {missing_owners[0]}"
        )

    raw_groups = request["change_groups"]
    if (
        not isinstance(raw_groups, Sequence)
        or isinstance(raw_groups, (str, bytes))
        or not raw_groups
    ):
        raise UpdateExecutionError("change_groups must be a nonempty list")
    groups: list[dict[str, object]] = []
    covered: list[str] = []
    names: set[str] = set()
    for index, raw in enumerate(raw_groups, start=1):
        if not isinstance(raw, Mapping):
            raise UpdateExecutionError(f"change group {index} must be an object")
        _closed_fields(raw, GROUP_FIELDS, f"change group {index}")
        name = raw["name"]
        if not isinstance(name, str) or not name.strip() or name in names:
            raise UpdateExecutionError(f"change group {index} name is invalid")
        paths = _string_list(raw["paths"], f"change group {index} paths")
        unknown = sorted(set(paths) - allowed_set)
        if unknown:
            raise UpdateExecutionError(f"change group path is not allowed: {unknown[0]}")
        names.add(name)
        covered.extend(paths)
        groups.append({"name": name, "paths": paths})
    if len(covered) != len(set(covered)) or set(covered) != allowed_set:
        raise UpdateExecutionError(
            "change groups must cover every allowed path exactly once"
        )

    checks = _validate_checks(request["checks"], repo_root, allowed_set)
    _collect_declared_pytest_nodes(repo_root, checks)
    dirty = sorted(_dirty_paths(repo_root))
    baseline_dirty = {path: _snapshot(repo_root, path) for path in dirty}
    baseline_targets = {path: _snapshot(repo_root, path) for path in allowed}
    state: dict[str, object] = {
        "schema": STATE_SCHEMA,
        "repo_root": str(repo_root),
        "branch": branch,
        "head": head,
        "selected_skills": selected,
        "allowed_paths": allowed,
        "change_groups": groups,
        "checks": checks,
        "baseline_dirty": baseline_dirty,
        "baseline_targets": baseline_targets,
    }
    return state, repo_root, task_temp_root, evidence_path, disposable


def command_prepare(request_path: pathlib.Path, state_path: pathlib.Path) -> None:
    state, repo_root, task_temp_root, evidence_path, disposable = _validated_request(
        request_path
    )
    resolved_request = _absolute(request_path)
    resolved_state = _task_artifact(
        state_path,
        task_temp_root,
        "state output",
        must_exist=False,
    )
    retention_path = _task_artifact(
        task_temp_root / RETENTION_MARKER,
        task_temp_root,
        "retention marker",
        must_exist=False,
    )
    if len({resolved_request, resolved_state, evidence_path, retention_path}) != 4:
        raise UpdateExecutionError(
            "request, state, evidence, and retention paths must differ"
        )
    if resolved_state.exists():
        raise UpdateExecutionError(f"refusing to overwrite state output: {resolved_state}")
    if evidence_path.exists():
        raise UpdateExecutionError(
            f"refusing to overwrite evidence output: {evidence_path}"
        )
    if retention_path.exists():
        raise UpdateExecutionError(
            f"refusing to overwrite retention marker: {retention_path}"
        )
    try:
        _write_json_atomic(
            retention_path,
            {"schema": RETENTION_SCHEMA, "state": str(resolved_state)},
            "retention marker",
        )
        owned_artifacts: list[dict[str, object]] = [
            {
                "role": "retention",
                "path": str(retention_path),
                "sha256": _file_sha256(retention_path),
            },
            {"role": "state", "path": str(resolved_state), "sha256": None},
            {"role": "evidence", "path": str(evidence_path), "sha256": None},
        ]
        protected_artifacts: list[str] = []
        if "request" in disposable:
            owned_artifacts.insert(
                0,
                {
                    "role": "request",
                    "path": str(resolved_request),
                    "sha256": _file_sha256(resolved_request),
                },
            )
        else:
            protected_artifacts.append(str(resolved_request))
        state["cleanup"] = {
            "schema": CLEANUP_SCHEMA,
            "task_temp_root": str(task_temp_root),
            "owned_artifacts": owned_artifacts,
            "protected_artifacts": protected_artifacts,
        }
        state["verification"] = None
        _write_json_atomic(resolved_state, state, "state output")
    except (OSError, UpdateExecutionError):
        retention_path.unlink(missing_ok=True)
        raise


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validated_cleanup(
    raw: object,
    *,
    state_path: pathlib.Path,
    repo_root: pathlib.Path,
) -> dict[str, object]:
    """Validate the exact cleanup ownership recorded during prepare."""

    if not isinstance(raw, Mapping):
        raise UpdateExecutionError("state cleanup must be an object")
    _closed_fields(raw, CLEANUP_FIELDS, "state cleanup")
    if raw.get("schema") != CLEANUP_SCHEMA:
        raise UpdateExecutionError(f"state cleanup schema must be {CLEANUP_SCHEMA}")
    task_temp_root = _verified_task_temp_root(raw["task_temp_root"], repo_root)
    artifacts = raw["owned_artifacts"]
    if (
        not isinstance(artifacts, Sequence)
        or isinstance(artifacts, (str, bytes))
        or not artifacts
    ):
        raise UpdateExecutionError("state owned_artifacts must be a nonempty list")
    owned: list[dict[str, object]] = []
    roles: set[str] = set()
    paths: set[pathlib.Path] = set()
    for index, artifact in enumerate(artifacts, start=1):
        if not isinstance(artifact, Mapping):
            raise UpdateExecutionError(f"owned artifact {index} must be an object")
        _closed_fields(artifact, OWNED_ARTIFACT_FIELDS, f"owned artifact {index}")
        role = artifact["role"]
        if not isinstance(role, str) or role not in OWNED_ROLES:
            raise UpdateExecutionError(f"owned artifact {index} role is invalid")
        if role in roles:
            raise UpdateExecutionError(f"duplicate owned artifact role: {role}")
        raw_path = artifact["path"]
        if not isinstance(raw_path, str) or not raw_path:
            raise UpdateExecutionError(f"owned artifact {index} path is invalid")
        path = _task_artifact(
            pathlib.Path(raw_path),
            task_temp_root,
            f"owned {role}",
            must_exist=role == "state",
        )
        if path in paths:
            raise UpdateExecutionError("owned artifact paths must be unique")
        expected_hash = artifact["sha256"]
        if role in {"request", "retention"}:
            if not _valid_sha256(expected_hash):
                raise UpdateExecutionError(f"owned {role} hash is invalid")
        elif expected_hash is not None:
            raise UpdateExecutionError(f"owned {role} hash must be null")
        roles.add(role)
        paths.add(path)
        owned.append({"role": role, "path": path, "sha256": expected_hash})
    if not {"state", "evidence"}.issubset(roles):
        raise UpdateExecutionError("state cleanup lacks owned workflow outputs")
    state_record = next(item for item in owned if item["role"] == "state")
    if state_record["path"] != state_path:
        raise UpdateExecutionError("state cleanup path does not match loaded state")
    protected = raw["protected_artifacts"]
    if (
        not isinstance(protected, Sequence)
        or isinstance(protected, (str, bytes))
        or not all(isinstance(item, str) and item for item in protected)
    ):
        raise UpdateExecutionError("state protected_artifacts must be a string list")
    protected_paths = [_absolute(pathlib.Path(item)) for item in protected]
    if len(protected_paths) != len(set(protected_paths)):
        raise UpdateExecutionError("state protected_artifacts must be unique")
    overlap = paths.intersection(protected_paths)
    if overlap:
        raise UpdateExecutionError("owned and protected artifact paths overlap")
    return {
        "schema": CLEANUP_SCHEMA,
        "task_temp_root": task_temp_root,
        "owned_artifacts": owned,
        "protected_artifacts": protected_paths,
    }


def _validated_verification(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise UpdateExecutionError("state verification must be null or an object")
    _closed_fields(value, VERIFICATION_FIELDS, "state verification")
    status = value.get("status")
    if status not in {"passed", "pending", "invalidated"}:
        raise UpdateExecutionError("state verification status is invalid")
    evidence_sha256 = value.get("evidence_sha256")
    if status == "passed":
        if not _valid_sha256(evidence_sha256):
            raise UpdateExecutionError("state verification evidence hash is invalid")
    elif evidence_sha256 is not None:
        raise UpdateExecutionError("non-passed verification has an evidence hash")
    if not _valid_sha256(value.get("input_sha256")):
        raise UpdateExecutionError("state verification input hash is invalid")
    generation = value.get("generation")
    if (
        not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation not in {0, 1}
        or (status != "passed" and generation != 1)
    ):
        raise UpdateExecutionError("state verification generation is invalid")
    return dict(value)


def _cleanup_payload(cleanup: Mapping[str, object]) -> dict[str, object]:
    """Convert validated cleanup paths back to the closed JSON contract."""

    owned = cleanup["owned_artifacts"]
    protected = cleanup["protected_artifacts"]
    assert isinstance(owned, list)
    assert isinstance(protected, list)
    return {
        "schema": CLEANUP_SCHEMA,
        "task_temp_root": str(cleanup["task_temp_root"]),
        "owned_artifacts": [
            {
                "role": artifact["role"],
                "path": str(artifact["path"]),
                "sha256": artifact["sha256"],
            }
            for artifact in owned
        ],
        "protected_artifacts": [str(path) for path in protected],
    }


def _validated_state(path: pathlib.Path) -> dict[str, object]:
    state_path = _absolute(path)
    _reject_link_chain(state_path, "state")
    if not state_path.is_file():
        raise UpdateExecutionError(f"state must be a regular file: {state_path}")
    raw = _read_json(state_path, "state")
    _closed_fields(raw, STATE_FIELDS, "state")
    if raw.get("schema") != STATE_SCHEMA:
        raise UpdateExecutionError(f"state schema must be {STATE_SCHEMA}")
    repo_value = raw["repo_root"]
    if not isinstance(repo_value, str) or not repo_value:
        raise UpdateExecutionError("state repo_root is invalid")
    repo_root = pathlib.Path(repo_value).resolve(strict=True)
    branch, head = _verify_task_worktree(repo_root)
    if raw["branch"] != branch:
        raise UpdateExecutionError("task branch changed after prepare")
    if raw["head"] != head and raw["verification"] is None:
        raise UpdateExecutionError("task HEAD changed before successful verification")
    allowed = _string_list(raw["allowed_paths"], "state allowed_paths")
    selected = _string_list(raw["selected_skills"], "state selected_skills")
    for skill in selected:
        if SKILL_NAME_RE.fullmatch(skill) is None:
            raise UpdateExecutionError(f"state selected skill is unsafe: {skill}")
        root = repo_root / "skills" / skill
        if root.is_symlink() or not (root / "SKILL.md").is_file():
            raise UpdateExecutionError(f"selected skill source changed after prepare: {skill}")
    baseline_targets_value = raw["baseline_targets"]
    if not isinstance(baseline_targets_value, Mapping):
        raise UpdateExecutionError("state target baseline is invalid")
    owners: set[str] = set()
    for value in allowed:
        pure = _safe_relative(value, "state allowed path")
        _target(repo_root, value)
        matches = [
            skill
            for skill in selected
            if pure.is_relative_to(pathlib.PurePosixPath("skills") / skill)
        ]
        owners.update(matches)
        snapshot = baseline_targets_value.get(value)
        content = snapshot.get("content") if isinstance(snapshot, Mapping) else None
        new_shared_source = (
            pure.is_relative_to(pathlib.PurePosixPath("skills/sections"))
            and isinstance(content, Mapping)
            and content.get("kind") == "missing"
        )
        if not matches and not _is_tracked(repo_root, value) and not new_shared_source:
            raise UpdateExecutionError(
                f"state ancillary path is not tracked: {value}"
            )
    if owners != set(selected):
        raise UpdateExecutionError("state selected skills lack allowed source paths")
    cleanup = _validated_cleanup(
        raw["cleanup"],
        state_path=state_path,
        repo_root=repo_root,
    )
    verification = _validated_verification(raw["verification"])
    owned_cleanup = cleanup["owned_artifacts"]
    assert isinstance(owned_cleanup, list)
    for artifact in owned_cleanup:
        role = artifact["role"]
        if role not in {"request", "retention"}:
            continue
        owned_path = artifact["path"]
        expected_hash = artifact["sha256"]
        assert isinstance(role, str)
        assert isinstance(owned_path, pathlib.Path)
        if not owned_path.is_file() or _file_sha256(owned_path) != expected_hash:
            raise UpdateExecutionError(f"owned {role} changed after prepare")
    baseline_dirty = raw["baseline_dirty"]
    baseline_targets = raw["baseline_targets"]
    if not isinstance(baseline_dirty, Mapping) or not isinstance(baseline_targets, Mapping):
        raise UpdateExecutionError("state baselines must be objects")
    if not all(
        isinstance(path, str) and isinstance(snapshot, Mapping)
        for path, snapshot in baseline_dirty.items()
    ):
        raise UpdateExecutionError("state dirty baseline is invalid")
    for raw_path in baseline_dirty:
        assert isinstance(raw_path, str)
        _target(repo_root, raw_path)
    if not all(
        isinstance(path, str) and isinstance(snapshot, Mapping)
        for path, snapshot in baseline_targets.items()
    ):
        raise UpdateExecutionError("state target baseline is invalid")
    if set(baseline_targets) != set(allowed):
        raise UpdateExecutionError("state target baseline does not match allowed_paths")
    raw_groups = raw["change_groups"]
    if not isinstance(raw_groups, list) or not raw_groups:
        raise UpdateExecutionError("state change_groups must be a nonempty list")
    groups: list[dict[str, object]] = []
    covered: list[str] = []
    names: set[str] = set()
    for index, group in enumerate(raw_groups, start=1):
        if not isinstance(group, Mapping):
            raise UpdateExecutionError(f"state change group {index} is invalid")
        _closed_fields(group, GROUP_FIELDS, f"state change group {index}")
        name = group["name"]
        paths = _string_list(group["paths"], f"state change group {index} paths")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise UpdateExecutionError(f"state change group {index} name is invalid")
        if not set(paths).issubset(allowed):
            raise UpdateExecutionError(f"state change group {index} path is not allowed")
        names.add(name)
        covered.extend(paths)
        groups.append({"name": name, "paths": paths})
    if len(covered) != len(set(covered)) or set(covered) != set(allowed):
        raise UpdateExecutionError(
            "state change groups must cover every allowed path exactly once"
        )
    checks = _validate_checks(raw["checks"], repo_root, set(allowed))
    return {
        **raw,
        "repo_root": str(repo_root),
        "selected_skills": selected,
        "allowed_paths": allowed,
        "baseline_dirty": dict(baseline_dirty),
        "baseline_targets": dict(baseline_targets),
        "change_groups": groups,
        "checks": checks,
        "cleanup": cleanup,
        "verification": verification,
    }


def _baseline_changes(state: Mapping[str, object]) -> tuple[list[str], list[dict[str, object]]]:
    repo_root = pathlib.Path(str(state["repo_root"]))
    allowed_paths = state["allowed_paths"]
    assert isinstance(allowed_paths, list)
    allowed = {str(path) for path in allowed_paths}
    baseline_dirty = state["baseline_dirty"]
    baseline_targets = state["baseline_targets"]
    assert isinstance(baseline_dirty, Mapping)
    assert isinstance(baseline_targets, Mapping)
    current_dirty = _dirty_paths(repo_root)
    undeclared_new = sorted(current_dirty - set(baseline_dirty) - allowed)
    if undeclared_new:
        raise UpdateExecutionError(f"undeclared working-tree change: {undeclared_new[0]}")
    for path, snapshot in baseline_dirty.items():
        if path in allowed:
            continue
        if _snapshot(repo_root, path) != snapshot:
            raise UpdateExecutionError(f"pre-existing dirty path changed: {path}")
    changed = sorted(
        path
        for path, snapshot in baseline_targets.items()
        if _snapshot(repo_root, path) != snapshot
    )
    if not changed:
        raise UpdateExecutionError("no declared path changed after prepare")
    group_results: list[dict[str, object]] = []
    change_groups = state["change_groups"]
    assert isinstance(change_groups, list)
    for raw_group in change_groups:
        if not isinstance(raw_group, Mapping):
            raise UpdateExecutionError("state change group is invalid")
        paths = raw_group.get("paths")
        name = raw_group.get("name")
        if not isinstance(name, str) or not isinstance(paths, list):
            raise UpdateExecutionError("state change group is invalid")
        group_changed = [path for path in paths if path in changed]
        if not group_changed:
            raise UpdateExecutionError(f"change group has no changed path: {name}")
        group_results.append({"name": name, "changed_paths": group_changed})
    return changed, group_results


def _verification_surface_sha256(state: Mapping[str, object]) -> str:
    """Hash HEAD plus every prepared or currently dirty path without judging scope."""

    repo_root = pathlib.Path(str(state["repo_root"]))
    allowed_paths = state["allowed_paths"]
    assert isinstance(allowed_paths, list)
    observed = sorted(set(allowed_paths) | _dirty_paths(repo_root))
    payload = {
        "head": _git(repo_root, "rev-parse", "HEAD").strip(),
        "paths": {path: _snapshot(repo_root, path) for path in observed},
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verification_input(
    state: Mapping[str, object],
) -> tuple[str, list[str], list[dict[str, object]]]:
    """Validate and hash one complete prepared verification surface."""

    changed, groups = _baseline_changes(state)
    repo_root = pathlib.Path(str(state["repo_root"]))
    head = _git(repo_root, "rev-parse", "HEAD").strip()
    if head != state["head"]:
        ancestor = _run(
            [
                "git",
                "-C",
                str(repo_root),
                "merge-base",
                "--is-ancestor",
                str(state["head"]),
                head,
            ],
            cwd=repo_root,
        )
        if ancestor.returncode:
            raise UpdateExecutionError("task HEAD is not a descendant of prepared HEAD")
        committed = {
            path
            for path in _git(
                repo_root,
                "diff",
                "--name-only",
                "--no-renames",
                f"{state['head']}..{head}",
            ).splitlines()
            if path
        }
        allowed_paths = state["allowed_paths"]
        assert isinstance(allowed_paths, list)
        allowed = set(allowed_paths)
        broadened = sorted(committed - allowed)
        if broadened:
            raise UpdateExecutionError(
                f"committed path is outside prepared scope: {broadened[0]}"
            )
    return _verification_surface_sha256(state), changed, groups


def _bounded(value: str) -> str:
    return value if len(value) <= MAX_CAPTURE else value[:MAX_CAPTURE] + "\n[truncated]"


def _run_check(
    repo_root: pathlib.Path,
    check: Mapping[str, object],
) -> dict[str, object]:
    kind = check.get("kind")
    if kind == "pytest":
        nodes = check.get("nodes")
        if not isinstance(nodes, list) or not all(isinstance(node, str) for node in nodes):
            raise UpdateExecutionError("state pytest check is invalid")
        argv = [sys.executable, "-m", "pytest", "-q", *nodes]
        result = _run(argv, cwd=repo_root)
        evidence = {
            "kind": kind,
            "nodes": nodes,
            "returncode": result.returncode,
            "stdout": _bounded(result.stdout),
            "stderr": _bounded(result.stderr),
        }
        if result.returncode:
            raise CheckFailure("pytest check failed", evidence)
        return evidence
    if kind == "command":
        raw_argv = check.get("argv")
        if not isinstance(raw_argv, list) or not all(
            isinstance(item, str) for item in raw_argv
        ):
            raise UpdateExecutionError("state command check is invalid")
        command_argv = [str(item) for item in raw_argv]
        result = _run(command_argv, cwd=repo_root)
        evidence = {
            "kind": kind,
            "argv": command_argv,
            "returncode": result.returncode,
            "stdout": _bounded(result.stdout),
            "stderr": _bounded(result.stderr),
        }
        if result.returncode:
            raise CheckFailure(f"command check failed with {result.returncode}", evidence)
        return evidence
    if kind != "search":
        raise UpdateExecutionError("state check kind is invalid")
    pattern = check.get("pattern")
    paths = check.get("paths")
    expected = check.get("expected_matches")
    if (
        not isinstance(pattern, str)
        or not isinstance(paths, list)
        or not all(isinstance(path, str) for path in paths)
        or not isinstance(expected, int)
        or isinstance(expected, bool)
    ):
        raise UpdateExecutionError("state search check is invalid")
    regex = re.compile(pattern)
    matches = 0
    for path in paths:
        target = _target(repo_root, path)
        if target.is_symlink() or not target.is_file():
            raise UpdateExecutionError(f"search path does not exist: {path}")
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise UpdateExecutionError(f"search path is unreadable: {path}: {exc}") from exc
        matches += sum(1 for _ in regex.finditer(text))
    evidence = {
        "kind": kind,
        "pattern": pattern,
        "paths": paths,
        "expected_matches": expected,
        "actual_matches": matches,
        "returncode": 0 if matches == expected else 1,
    }
    if matches != expected:
        raise CheckFailure(
            f"search expected {expected} matches, found {matches}", evidence
        )
    return evidence


class CheckFailure(UpdateExecutionError):
    """A check failure that carries its detailed evidence record."""

    def __init__(self, message: str, evidence: dict[str, object]) -> None:
        super().__init__(message)
        self.evidence = evidence


def command_verify(state_path: pathlib.Path, evidence_path: pathlib.Path) -> None:
    state = _validated_state(state_path)
    repo_root = pathlib.Path(str(state["repo_root"]))
    cleanup = state["cleanup"]
    assert isinstance(cleanup, Mapping)
    owned_artifacts = cleanup["owned_artifacts"]
    assert isinstance(owned_artifacts, list)
    evidence_record = next(
        artifact for artifact in owned_artifacts if artifact["role"] == "evidence"
    )
    resolved_evidence = _absolute(evidence_path)
    if resolved_evidence != evidence_record["path"]:
        raise UpdateExecutionError("evidence output differs from prepared ownership")
    input_sha256 = _verification_surface_sha256(state)
    verification = state["verification"]
    generation = 0
    terminal_error: str | None = None
    if verification is not None:
        assert isinstance(verification, Mapping)
        status = verification["status"]
        generation = int(verification["generation"])
        if status == "invalidated":
            raise UpdateExecutionError("state is permanently invalidated")
        if status == "passed":
            if input_sha256 == verification["input_sha256"]:
                raise UpdateExecutionError(
                    "prepared scope has not changed since successful verification"
                )
            if generation == 1:
                status = "invalidated"
                terminal_error = "prepared scope changed after the correction generation"
            else:
                status = "pending"
                generation = 1
            state["verification"] = {
                "status": status,
                "evidence_sha256": None,
                "input_sha256": input_sha256,
                "generation": 1,
            }
            state["cleanup"] = _cleanup_payload(cleanup)
            _write_json_atomic(_absolute(state_path), state, "state output")
        elif status == "pending" and input_sha256 != verification["input_sha256"]:
            state["verification"] = {
                "status": "pending",
                "evidence_sha256": None,
                "input_sha256": input_sha256,
                "generation": 1,
            }
            state["cleanup"] = _cleanup_payload(cleanup)
            _write_json_atomic(_absolute(state_path), state, "state output")
    changed: list[str] = []
    groups: list[dict[str, object]] = []
    results: list[dict[str, object]] = []
    failures: list[str] = [terminal_error] if terminal_error else []
    if not failures:
        try:
            validated_input, changed, groups = _verification_input(state)
            if validated_input != input_sha256:
                failures.append("prepared scope changed before checks started")
        except UpdateExecutionError as exc:
            failures.append(str(exc))
    checks = state["checks"]
    assert isinstance(checks, list)
    for raw_check in (checks if not failures else []):
        if not isinstance(raw_check, Mapping):
            failures.append("state check is invalid")
            break
        try:
            results.append(_run_check(repo_root, raw_check))
        except CheckFailure as exc:
            results.append(exc.evidence)
            failures.append(str(exc))
            break
        except UpdateExecutionError as exc:
            results.append(
                {
                    "kind": raw_check.get("kind", "unknown"),
                    "error": str(exc),
                }
            )
            failures.append(str(exc))
            break
    if not failures or results:
        try:
            final_input_sha256, final_changed, final_groups = _verification_input(state)
            if (
                final_input_sha256 != input_sha256
                or final_changed != changed
                or final_groups != groups
            ):
                failures.append("prepared scope changed while checks were running")
        except UpdateExecutionError as exc:
            failures.append(str(exc))
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "status": "failed" if failures else "passed",
        "branch": state["branch"],
        "head": _git(repo_root, "rev-parse", "HEAD").strip(),
        "generation": generation,
        "input_sha256": input_sha256,
        "selected_skills": state["selected_skills"],
        "changed_paths": changed,
        "change_groups": groups,
        "checks": results,
        "failures": failures,
    }
    _write_json_atomic(resolved_evidence, evidence, "evidence output")
    if failures:
        raise UpdateExecutionError(failures[0])
    state["verification"] = {
        "status": "passed",
        "evidence_sha256": _file_sha256(resolved_evidence),
        "input_sha256": input_sha256,
        "generation": generation,
    }
    state["cleanup"] = _cleanup_payload(cleanup)
    _write_json_atomic(_absolute(state_path), state, "state output")


def command_finalize(state_path: pathlib.Path) -> None:
    """Remove exact owned artifacts after the caller signals completed use."""

    resolved_state = _absolute(state_path)
    _reject_link_chain(resolved_state, "state")
    if not resolved_state.is_file():
        raise UpdateExecutionError(f"state must be a regular file: {resolved_state}")
    raw = _read_json(resolved_state, "state")
    _closed_fields(raw, STATE_FIELDS, "state")
    if raw.get("schema") != STATE_SCHEMA:
        raise UpdateExecutionError(f"state schema must be {STATE_SCHEMA}")
    repo_value = raw["repo_root"]
    if not isinstance(repo_value, str) or not repo_value:
        raise UpdateExecutionError("state repo_root is invalid")
    repo_path = pathlib.Path(repo_value).expanduser()
    if not repo_path.is_absolute():
        raise UpdateExecutionError("state repo_root must be absolute")
    lexical_repo = _absolute(repo_path)
    _reject_link_chain(lexical_repo, "state repo_root")
    if lexical_repo.exists() and not lexical_repo.is_dir():
        raise UpdateExecutionError("state repo_root must be a directory")
    if lexical_repo.is_dir() and any(lexical_repo.iterdir()):
        repo_root = lexical_repo.resolve(strict=True)
    else:
        # Git may unregister a worktree while Windows retains its empty directory.
        repo_root = _finalize_primary_root(raw["cleanup"])
    cleanup = _validated_cleanup(
        raw["cleanup"],
        state_path=resolved_state,
        repo_root=repo_root,
    )
    verification = _validated_verification(raw["verification"])
    if verification is None or verification["status"] != "passed":
        raise UpdateExecutionError("refusing to finalize before successful verification")
    artifacts = cleanup["owned_artifacts"]
    assert isinstance(artifacts, list)
    for artifact in artifacts:
        role = artifact["role"]
        path = artifact["path"]
        assert isinstance(role, str)
        assert isinstance(path, pathlib.Path)
        if not path.exists():
            continue
        if _is_link(path) or not path.is_file():
            raise UpdateExecutionError(f"owned {role} is not a regular file: {path}")
        expected_hash = artifact["sha256"]
        if role == "evidence":
            expected_hash = verification["evidence_sha256"]
        if expected_hash is not None and _file_sha256(path) != expected_hash:
            raise UpdateExecutionError(f"owned {role} changed after recording")
    for artifact in artifacts:
        if artifact["role"] == "state":
            continue
        path = artifact["path"]
        assert isinstance(path, pathlib.Path)
        path.unlink(missing_ok=True)
    task_temp_root = cleanup["task_temp_root"]
    assert isinstance(task_temp_root, pathlib.Path)
    remove_task_temp_root = set(task_temp_root.iterdir()) == {resolved_state}
    resolved_state.unlink()
    if remove_task_temp_root:
        try:
            task_temp_root.rmdir()
        except OSError:
            # Preserve retryable verified state if an empty-root removal fails
            # after its preflight, such as when a concurrent file appears.
            _write_json_atomic(resolved_state, raw, "state output")
            raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--request", required=True, type=pathlib.Path)
    prepare.add_argument("--state", required=True, type=pathlib.Path)
    verify = commands.add_parser("verify")
    verify.add_argument("--state", required=True, type=pathlib.Path)
    verify.add_argument("--evidence-output", required=True, type=pathlib.Path)
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--state", required=True, type=pathlib.Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            command_prepare(args.request, args.state)
        elif args.command == "verify":
            command_verify(args.state, args.evidence_output)
        else:
            command_finalize(args.state)
    except (UpdateExecutionError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
