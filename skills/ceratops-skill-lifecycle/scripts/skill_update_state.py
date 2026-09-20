"""State, filesystem boundaries and cleanup records for skill updates.

All file ownership is confined to the verified task temp directory. This module
does not decide update scope or execute checks; the workflow owns those steps.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence

from skill_update_checks import UpdateExecutionError, _run

REQUEST_SCHEMA = "ceratops-skill-update-request.v2"
STATE_SCHEMA = "ceratops-skill-update-state.v2"
EVIDENCE_SCHEMA = "ceratops-skill-update-evidence.v3"
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
STATE_OPTIONAL_FIELDS = {"failure_evidence_sha256", "superseded_artifacts"}
CLEANUP_FIELDS = {
    "schema",
    "task_temp_root",
    "owned_artifacts",
    "protected_artifacts",
}
OWNED_ARTIFACT_FIELDS = {"role", "path", "sha256"}
VERIFICATION_FIELDS = {"status", "evidence_sha256", "input_sha256", "generation"}
EVIDENCE_FIELDS = {
    "schema",
    "status",
    "branch",
    "head",
    "generation",
    "input_sha256",
    "selected_skills",
    "changed_paths",
    "change_groups",
    "checks",
    "failures",
}
DISPOSABLE_ROLES = {"request", "state", "evidence"}
OWNED_ROLES = DISPOSABLE_ROLES | {"retention"}
SKILL_NAME_RE = re.compile(
    r"^(?![a-z0-9-]*--)[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$"
)
def _run_bytes(
    arguments: Sequence[str],
    *,
    cwd: pathlib.Path,
) -> subprocess.CompletedProcess[bytes]:
    """Run one Git object query without decoding repository bytes."""

    try:
        return subprocess.run(
            list(arguments),
            cwd=cwd,
            capture_output=True,
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


def _validate_state_fields(raw: Mapping[str, object]) -> None:
    """Optional provenance is absent until an attempt records it."""
    _closed_fields(raw, STATE_FIELDS | (STATE_OPTIONAL_FIELDS & set(raw)), "state")
    failure_hash = raw.get("failure_evidence_sha256")
    if failure_hash is not None and not _valid_sha256(failure_hash):
        raise UpdateExecutionError("failed evidence hash is invalid")


def _string_list(value: object, label: str, *, unique: bool = True) -> list[str]:
    """Preserve ordered strings; identity lists also require unique entries."""

    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise UpdateExecutionError(f"{label} must be a nonempty string list")
    result = list(value)
    if unique and len(result) != len(set(result)):
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
    elif status == "pending":
        if evidence_sha256 is not None and not _valid_sha256(evidence_sha256):
            raise UpdateExecutionError("pending verification evidence hash is invalid")
    elif evidence_sha256 is not None:
        raise UpdateExecutionError("invalidated verification has an evidence hash")
    if not _valid_sha256(value.get("input_sha256")):
        raise UpdateExecutionError("state verification input hash is invalid")
    generation = value.get("generation")
    if (
        not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation not in {0, 1}
        or (status == "invalidated" and generation != 1)
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


def _inherited_artifacts(
    state: Mapping[str, object], cleanup: Mapping[str, object], *, required: bool = False,
) -> list[dict[str, object]]:
    """Preflight all superseded records before transfer or any deletion.

    Missing files are accepted only for resumable finalization, after a previous
    attempt may have removed some records. Transfer requires every record intact.
    """
    raw = state.get("superseded_artifacts", [])
    if not isinstance(raw, list):
        raise UpdateExecutionError("superseded_artifacts must be a list")
    owned = cleanup["owned_artifacts"]
    protected = cleanup["protected_artifacts"]
    assert isinstance(owned, list) and isinstance(protected, list)
    paths = {item["path"] for item in owned} | set(protected)
    root = pathlib.Path(str(cleanup["task_temp_root"]))
    records = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise UpdateExecutionError("superseded artifact must be an object")
        _closed_fields(item, {"path", "sha256"}, "superseded artifact")
        if not isinstance(item["path"], str) or not _valid_sha256(item["sha256"]):
            raise UpdateExecutionError("superseded artifact identity is invalid")
        path = _task_artifact(pathlib.Path(item["path"]), root, "superseded artifact", must_exist=required)
        if path in paths:
            raise UpdateExecutionError("superseded artifact paths overlap")
        paths.add(path)
        if path.exists() and _file_sha256(path) != item["sha256"]:
            raise UpdateExecutionError(f"superseded artifact changed: {path}")
        records.append({"role": "superseded", "path": path, "sha256": item["sha256"]})
    return records

def _prepared_request_path(cleanup: Mapping[str, object]) -> pathlib.Path:
    """Return the one prepared request path without changing its ownership."""

    owned = cleanup["owned_artifacts"]
    protected = cleanup["protected_artifacts"]
    assert isinstance(owned, list)
    assert isinstance(protected, list)
    owned_request = [item["path"] for item in owned if item["role"] == "request"]
    if owned_request:
        assert len(owned_request) == 1
        path = owned_request[0]
        assert isinstance(path, pathlib.Path)
        return path
    if len(protected) != 1 or not isinstance(protected[0], pathlib.Path):
        raise UpdateExecutionError("state does not identify one protected request")
    return protected[0]



def _validated_evidence(
    path: pathlib.Path,
    expected_sha256: str,
) -> dict[str, object]:
    """Validate one exact helper-written evidence record before reuse."""

    if not path.is_file() or _file_sha256(path) != expected_sha256:
        raise UpdateExecutionError("recorded verification evidence changed")
    raw = _read_json(path, "verification evidence")
    _closed_fields(raw, EVIDENCE_FIELDS, "verification evidence")
    if raw.get("schema") != EVIDENCE_SCHEMA:
        raise UpdateExecutionError(
            f"verification evidence schema must be {EVIDENCE_SCHEMA}"
        )
    if raw.get("status") not in {"failed", "passed"}:
        raise UpdateExecutionError("verification evidence status is invalid")
    if not _valid_sha256(raw.get("input_sha256")):
        raise UpdateExecutionError("verification evidence input hash is invalid")
    if not isinstance(raw.get("checks"), list) or not isinstance(
        raw.get("failures"), list
    ):
        raise UpdateExecutionError("verification evidence results are invalid")
    return dict(raw)
