#!/usr/bin/env python3
"""Render and transactionally install managed runtime skill batches.

The builder stages every selected present skill before touching canonical
runtime folders. It then retires every selected canonical target, activates the
complete staged batch, and deletes retired folders only after all activations
complete. Pre-commit-point failures are compensated from in-memory state.

No transaction journal or recovery database is written. Interrupted
``deployed`` and ``retired`` folders are resolved only when their names,
ownership, and batch state prove one safe outcome. The same affected set, or an
all-managed install, is therefore the convergence boundary after a hard crash.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import errno
import hashlib
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast


ROOT = pathlib.Path(__file__).resolve().parents[4]
SECTION_MANIFEST = ROOT / "skills" / "skill-sections.json"
SKILLS = ROOT / "skills"
START = "<!-- CERATOPS_SHARED_SECTIONS_START -->"
END = "<!-- CERATOPS_SHARED_SECTIONS_END -->"
SOURCE_PREFIX = "<!-- SECTION SOURCE: "
SOURCE_SUFFIX = " -->"
MANIFEST_NAME = ".runtime-manifest.json"
RUNTIME_MANIFEST_SCHEMA = "ceratops-runtime-skill.v3"
VALIDATION_PROFILES = {"ceratops", "ceratops-compatible"}
IGNORE_NAMES = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
}
SKILL_NAME_RE = re.compile(
    r"^(?![a-z0-9-]*--)[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$"
)
REMNANT_RE = re.compile(
    r"^\.(?P<skill>(?![a-z0-9-]*--)[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?)"
    r"-(?P<kind>deployed|retired)-(?P<transaction>[0-9a-f]{32})$"
)
TRANSIENT_WINDOWS_ERRORS = {32, 33}
RENAME_ATTEMPTS = 4


class TransactionError(RuntimeError):
    """One compact transactional failure with rollback evidence."""

    def __init__(
        self,
        reason: str,
        *,
        phase: str,
        skill: str = "",
        rollback_state: str = "not_started",
    ) -> None:
        super().__init__(reason)
        self.phase = phase
        self.skill = skill
        self.rollback_state = rollback_state

    def result(self) -> dict[str, object]:
        return {
            "status": "error",
            "phase": self.phase,
            "skill": self.skill,
            "rollback": self.rollback_state,
            "reason": str(self),
        }


class InstallBusy(TransactionError):
    """Raised when another process holds the runtime-root writer lock."""

    def __init__(self) -> None:
        super().__init__("runtime installation is already active", phase="install_busy")


@dataclass(frozen=True)
class TransactionResult:
    """Compact successful or post-commit-cleanup-blocked transaction result."""

    status: str
    deployed: tuple[str, ...]
    removed: tuple[str, ...]
    transaction_id: str
    retained_retired: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "deployed": list(self.deployed),
            "removed": list(self.removed),
            "transaction_id": self.transaction_id,
            "retained_retired": list(self.retained_retired),
        }


def configure_repo(repo_root: pathlib.Path) -> None:
    """Select the source repository used by subsequent build operations."""

    global ROOT, SECTION_MANIFEST, SKILLS
    ROOT = repo_root.resolve()
    SECTION_MANIFEST = ROOT / "skills" / "skill-sections.json"
    SKILLS = ROOT / "skills"


def load_manifest() -> dict[str, object]:
    """Load the shared-section and payload manifest."""

    value = json.loads(SECTION_MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("section manifest must be a JSON object")
    return value


def source_skill_names() -> list[str]:
    """Return source skill folder names containing ``SKILL.md``."""

    return sorted(path.parent.name for path in SKILLS.glob("*/SKILL.md"))


def valid_skill_name(value: str) -> bool:
    """Return whether a skill name is safe as one direct child directory."""

    return SKILL_NAME_RE.fullmatch(value) is not None


def _safe_repo_pattern(pattern: str) -> bool:
    normalized = pattern.replace("\\", "/")
    pure = pathlib.PurePosixPath(normalized)
    windows = pathlib.PureWindowsPath(pattern)
    return bool(
        normalized
        and not pure.is_absolute()
        and not windows.is_absolute()
        and not windows.drive
        and ".." not in pure.parts
    )


def validate_manifest(
    manifest: Mapping[str, object],
    source_names: set[str],
    selected: set[str],
    *,
    all_managed: bool,
) -> list[str]:
    """Validate global identity plus only the selected rendering inputs."""

    errors: list[str] = []
    source_id = manifest.get("runtime_source_id")
    profile = manifest.get("validation_profile")
    sections = manifest.get("sections")
    assignments = manifest.get("skills")
    payloads = manifest.get("runtime_payloads", {})
    if not isinstance(source_id, str) or not source_id.strip():
        errors.append("section manifest runtime_source_id must be a nonempty string")
    if profile not in VALIDATION_PROFILES:
        errors.append(
            "section manifest validation_profile must be ceratops or "
            "ceratops-compatible"
        )
    if not isinstance(sections, Mapping):
        errors.append("section manifest is missing a valid sections object")
    if not isinstance(assignments, Mapping):
        errors.append("section manifest is missing a valid skills object")
    if not isinstance(payloads, Mapping):
        errors.append("section manifest runtime_payloads must be an object")
    if errors or not isinstance(sections, Mapping) or not isinstance(assignments, Mapping):
        return errors

    checked_skills = source_names if all_managed else selected
    for skill_name in sorted(checked_skills):
        section_names = assignments.get(skill_name)
        if not isinstance(section_names, Sequence) or isinstance(section_names, str):
            errors.append(f"{skill_name}: section assignment must be a list")
            continue
        if "core" not in section_names:
            errors.append(f"{skill_name}: section assignment must include core")
        for section_name in section_names:
            rel_path = sections.get(section_name)
            if not isinstance(rel_path, str):
                errors.append(f"{skill_name}: unknown section assignment {section_name}")
                continue
            section_path = ROOT / rel_path
            try:
                _assert_inside(section_path, ROOT)
            except ValueError:
                errors.append(f"{skill_name}: invalid section path {rel_path}")
                continue
            if (
                not _safe_repo_pattern(rel_path)
                or _unsafe_link(section_path)
                or not section_path.is_file()
            ):
                errors.append(f"{skill_name}: invalid section path {rel_path}")

    if all_managed:
        for assigned in assignments:
            if assigned not in source_names:
                errors.append(f"unknown skill section assignment: {assigned}")

    if isinstance(payloads, Mapping):
        payload_keys = {"*", *checked_skills}
        for key in sorted(payload_keys):
            values = payloads.get(key, [])
            if not isinstance(values, Sequence) or isinstance(values, str):
                errors.append(f"runtime_payloads.{key} must be a list")
                continue
            for value in values:
                if not isinstance(value, str) or not _safe_repo_pattern(value):
                    errors.append(f"runtime_payloads.{key} has unsafe path {value!r}")
    return errors


def section_text(rel_path: str) -> str:
    """Read one shared section and strip internal-only comments."""

    lines = (ROOT / rel_path).read_text(encoding="utf-8").splitlines()
    visible = [
        line for line in lines if not line.strip().startswith("<!-- INTERNAL:")
    ]
    return "\n".join(visible).strip("\n")


def rendered_sections_block(
    skill_name: str, manifest: Mapping[str, object]
) -> str:
    """Render the generated shared-section block for one runtime skill."""

    sections = cast(Mapping[str, str], manifest["sections"])
    assignments = cast(Mapping[str, Sequence[str]], manifest["skills"])
    rendered: list[str] = []
    for name in assignments[skill_name]:
        rel_path = sections[name]
        rendered.append(f"{SOURCE_PREFIX}{rel_path}{SOURCE_SUFFIX}")
        rendered.append(section_text(rel_path))
    body = "\n\n".join(rendered)
    return f"{START}\n{body}\n{END}"


def compose_runtime_skill(
    source_text: str, shared_block: str, skill_name: str
) -> str:
    """Insert generated shared sections after frontmatter and the H1 title."""

    if START in source_text or END in source_text:
        raise ValueError(
            f"{skill_name}: source SKILL.md must be delta-only"
        )
    lines = source_text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0] != "---":
        raise ValueError(f"{skill_name}: missing frontmatter")
    try:
        frontmatter_end = lines[1:].index("---") + 1
    except ValueError as exc:
        raise ValueError(
            f"{skill_name}: missing closing frontmatter marker"
        ) from exc
    insert_after = frontmatter_end
    for index in range(frontmatter_end + 1, len(lines)):
        if not lines[index].strip():
            continue
        if lines[index].startswith("# "):
            insert_after = index
        break
    before = "\n".join(lines[: insert_after + 1]).rstrip()
    after = "\n".join(lines[insert_after + 1 :]).strip("\n")
    return (
        f"{before}\n\n{shared_block}\n\n{after}\n"
        if after
        else f"{before}\n\n{shared_block}\n"
    )


def ignore_source_dir(_directory: str, names: list[str]) -> set[str]:
    """Filter cache and VCS folders out of copied source skill trees."""

    return {name for name in names if name in IGNORE_NAMES}


def _assert_inside(path: pathlib.Path, parent: pathlib.Path) -> None:
    try:
        path.resolve(strict=False).relative_to(parent.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes its declared root: {path}") from exc


def _unsafe_link(path: pathlib.Path) -> bool:
    if path.is_symlink():
        return True
    if os.name != "nt":
        return False
    try:
        attributes = getattr(
            path.stat(follow_symlinks=False), "st_file_attributes", 0
        )
    except (AttributeError, FileNotFoundError, OSError):
        return False
    return bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def validate_tree_links(root: pathlib.Path) -> None:
    """Reject links or reparse points anywhere in one generated tree."""

    if _unsafe_link(root):
        raise ValueError(f"unsafe runtime tree root: {root}")
    for path in root.rglob("*"):
        if _unsafe_link(path):
            raise ValueError(f"unsafe runtime tree entry: {path}")


def copy_path(source: pathlib.Path, target: pathlib.Path) -> None:
    """Copy one manifest-declared payload under its repository-relative path."""

    _assert_inside(source, ROOT)
    if _unsafe_link(source):
        raise ValueError(f"runtime payload cannot be a link: {source}")
    if source.is_dir():
        for child in source.rglob("*"):
            if any(part in IGNORE_NAMES for part in child.parts):
                continue
            if _unsafe_link(child):
                raise ValueError(f"runtime payload cannot contain links: {child}")
            rel = child.relative_to(source)
            destination = target / rel
            if child.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(child, destination)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def expand_payload_patterns(patterns: Sequence[str]) -> list[pathlib.Path]:
    """Expand validated runtime payload globs relative to the source root."""

    paths: list[pathlib.Path] = []
    for pattern in patterns:
        if not _safe_repo_pattern(pattern):
            raise ValueError(f"unsafe runtime payload pattern: {pattern}")
        matches = sorted(ROOT.glob(pattern))
        if not matches:
            if any(token in pattern for token in "*?["):
                continue
            raise FileNotFoundError(
                f"runtime payload path does not exist: {pattern}"
            )
        paths.extend(path for path in matches if ".git" not in path.parts)
    unique: dict[str, pathlib.Path] = {}
    for path in paths:
        _assert_inside(path, ROOT)
        if path.resolve() == ROOT.resolve():
            raise ValueError("runtime payload cannot select the repository root")
        unique[path.relative_to(ROOT).as_posix()] = path
    return list(unique.values())


def payload_patterns_for(
    skill_name: str, manifest: Mapping[str, object]
) -> list[str]:
    """Return global and skill-specific runtime payload patterns."""

    payloads = manifest.get("runtime_payloads", {})
    if not isinstance(payloads, Mapping):
        return []
    patterns: list[str] = []
    for key in ("*", skill_name):
        values = payloads.get(key, [])
        if isinstance(values, Sequence) and not isinstance(values, str):
            patterns.extend(str(value) for value in values)
    return patterns


def read_runtime_manifest(path: pathlib.Path) -> dict[str, object]:
    """Read one runtime manifest used for ownership decisions."""

    value = json.loads((path / MANIFEST_NAME).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("runtime manifest must be a JSON object")
    return value


def install_target_error(
    path: pathlib.Path, source_id: str, *, expected_skill: str | None = None
) -> str | None:
    """Return why an existing target cannot be changed by this source."""

    if not path.exists() and not path.is_symlink():
        return None
    if _unsafe_link(path):
        return f"refusing to replace unmanaged runtime skill link: {path}"
    if not path.is_dir() or not (path / MANIFEST_NAME).is_file():
        return f"refusing to replace unmanaged runtime skill folder: {path}"
    try:
        manifest = read_runtime_manifest(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return f"invalid ownership manifest: {path}: {exc}"
    skill = expected_skill or path.name
    if manifest.get("schema") != RUNTIME_MANIFEST_SCHEMA:
        return f"unsupported ownership manifest: {path}"
    if manifest.get("skill") != skill:
        return f"mismatched ownership manifest: {path}"
    if manifest.get("runtime_source_id") != source_id:
        return (
            "runtime skill is owned by "
            f"{manifest.get('runtime_source_id')!r}: {path}"
        )
    return None


def enable_windows_acl_inheritance(path: pathlib.Path) -> None:
    """Enable inherited ACLs before a staged folder becomes canonical."""

    if os.name != "nt":
        return
    result = subprocess.run(
        ["icacls", str(path), "/inheritance:e", "/T", "/C"],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(
            f"could not enable ACL inheritance on staged runtime skill{suffix}"
        )


def write_expected_skill(
    skill_name: str,
    target_skill: pathlib.Path,
    manifest: Mapping[str, object],
    *,
    source_repository_root: pathlib.Path | None = None,
) -> None:
    """Write one canonical managed runtime tree into an empty target."""

    source_dir = SKILLS / skill_name
    source_skill = source_dir / "SKILL.md"
    source_id = cast(str, manifest["runtime_source_id"])
    validation_profile = cast(str, manifest["validation_profile"])
    if not source_skill.is_file():
        raise FileNotFoundError(f"missing source skill: {source_skill}")
    if target_skill.exists() or target_skill.is_symlink():
        raise FileExistsError(f"staging target already exists: {target_skill}")

    validate_tree_links(source_dir)
    shutil.copytree(source_dir, target_skill, ignore=ignore_source_dir)
    shared_block = rendered_sections_block(skill_name, manifest)
    runtime_skill_text = compose_runtime_skill(
        source_skill.read_text(encoding="utf-8"), shared_block, skill_name
    )
    (target_skill / "SKILL.md").write_text(
        runtime_skill_text, encoding="utf-8", newline="\n"
    )
    for payload in expand_payload_patterns(
        payload_patterns_for(skill_name, manifest)
    ):
        relative = payload.relative_to(ROOT)
        copy_path(payload, target_skill / relative)

    runtime_manifest = {
        "schema": RUNTIME_MANIFEST_SCHEMA,
        "skill": skill_name,
        "runtime_source_id": source_id,
        "validation_profile": validation_profile,
        "source_path": source_dir.relative_to(ROOT).as_posix(),
        "source_repository_root": str(source_repository_root or ROOT),
        "generated_from": SECTION_MANIFEST.relative_to(ROOT).as_posix(),
        "payload_patterns": payload_patterns_for(skill_name, manifest),
    }
    (target_skill / MANIFEST_NAME).write_text(
        json.dumps(runtime_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    validate_tree_links(target_skill)


def _runtime_identity(path: pathlib.Path) -> str:
    normalized = os.path.normcase(str(path.resolve()))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@contextlib.contextmanager
def runtime_lock(install_root: pathlib.Path) -> Iterator[None]:
    """Hold one nonblocking writer lock derived from runtime-root identity."""

    install_root.mkdir(parents=True, exist_ok=True)
    identity = _runtime_identity(install_root)
    if os.name == "nt":
        windows_ctypes = cast(Any, ctypes)
        kernel32 = windows_ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel32.CreateMutexW
        create.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
        create.restype = ctypes.c_void_p
        wait = kernel32.WaitForSingleObject
        wait.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        wait.restype = ctypes.c_uint32
        release = kernel32.ReleaseMutex
        release.argtypes = (ctypes.c_void_p,)
        close = kernel32.CloseHandle
        close.argtypes = (ctypes.c_void_p,)
        handle = create(None, False, f"Local\\CeratopsSkillInstall-{identity}")
        if not handle:
            raise OSError(windows_ctypes.get_last_error(), "CreateMutexW failed")
        acquired = False
        try:
            result = wait(handle, 0)
            if result == 0x00000102:
                raise InstallBusy()
            if result == 0xFFFFFFFF:
                raise OSError(
                    windows_ctypes.get_last_error(), "WaitForSingleObject failed"
                )
            if result not in {0x00000000, 0x00000080}:
                raise OSError(f"unexpected mutex wait result: {result}")
            acquired = True
            yield
        finally:
            if acquired:
                release(handle)
            close(handle)
        return

    posix_lock = cast(Any, __import__("fcntl"))

    lock_path = install_root / f".ceratops-install-{identity}.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            posix_lock.flock(
                descriptor, posix_lock.LOCK_EX | posix_lock.LOCK_NB
            )
        except BlockingIOError as exc:
            raise InstallBusy() from exc
        yield
    finally:
        try:
            posix_lock.flock(descriptor, posix_lock.LOCK_UN)
        finally:
            os.close(descriptor)


def _transient_rename_error(exc: OSError) -> bool:
    if os.name != "nt":
        return exc.errno in {errno.EINTR, errno.EBUSY}
    return getattr(exc, "winerror", None) in TRANSIENT_WINDOWS_ERRORS


def rename_with_retry(source: pathlib.Path, target: pathlib.Path) -> None:
    """Rename once, retrying only recognized transient sharing failures."""

    for attempt in range(RENAME_ATTEMPTS):
        try:
            source.replace(target)
            return
        except OSError as exc:
            if not _transient_rename_error(exc) or attempt + 1 == RENAME_ATTEMPTS:
                raise
            time.sleep(0.05 * (2**attempt))


def _remove_tree(path: pathlib.Path, install_root: pathlib.Path) -> None:
    _assert_inside(path, install_root)
    if path.exists() or path.is_symlink():
        if _unsafe_link(path):
            raise RuntimeError(f"refusing to remove unsafe runtime path: {path}")
        shutil.rmtree(path)


def _remnants(
    install_root: pathlib.Path,
) -> dict[str, dict[str, dict[str, pathlib.Path]]]:
    groups: dict[str, dict[str, dict[str, pathlib.Path]]] = {}
    if not install_root.is_dir():
        return groups
    seen_skill_transactions: dict[str, set[str]] = {}
    for path in install_root.iterdir():
        if not path.name.startswith("."):
            continue
        match = REMNANT_RE.fullmatch(path.name)
        if match is None:
            if "-deployed-" in path.name or "-retired-" in path.name:
                raise TransactionError(
                    f"malformed transaction remnant: {path.name}",
                    phase="recovery",
                )
            continue
        if _unsafe_link(path) or not path.is_dir():
            raise TransactionError(
                f"unsafe transaction remnant: {path.name}",
                phase="recovery",
                skill=match.group("skill"),
            )
        skill = match.group("skill")
        transaction = match.group("transaction")
        kind = match.group("kind")
        seen_skill_transactions.setdefault(skill, set()).add(transaction)
        if len(seen_skill_transactions[skill]) > 1:
            raise TransactionError(
                f"conflicting transaction IDs for {skill}",
                phase="recovery",
                skill=skill,
            )
        by_skill = groups.setdefault(transaction, {}).setdefault(skill, {})
        if kind in by_skill:
            raise TransactionError(
                f"duplicate {kind} remnant for {skill}",
                phase="recovery",
                skill=skill,
            )
        by_skill[kind] = path
    return groups


def recover_interrupted(
    install_root: pathlib.Path,
    source_id: str,
    *,
    remove_names: set[str],
    all_managed: bool,
    source_names: set[str],
) -> None:
    """Resolve ownership-proven remnants within the current convergence scope."""

    for transaction, skills in _remnants(install_root).items():
        del transaction
        has_deployed = any("deployed" in paths for paths in skills.values())
        for skill, paths in skills.items():
            canonical = install_root / skill
            for path in paths.values():
                error = install_target_error(
                    path, source_id, expected_skill=skill
                )
                if error is not None:
                    raise TransactionError(
                        error, phase="recovery", skill=skill
                    )
            if canonical.exists() or canonical.is_symlink():
                error = install_target_error(canonical, source_id)
                if error is not None:
                    raise TransactionError(
                        error, phase="recovery", skill=skill
                    )
        if has_deployed:
            for skill, paths in skills.items():
                canonical = install_root / skill
                retired = paths.get("retired")
                deployed = paths.get("deployed")
                if retired is not None:
                    if canonical.exists() or canonical.is_symlink():
                        _remove_tree(canonical, install_root)
                    rename_with_retry(retired, canonical)
                if deployed is not None:
                    _remove_tree(deployed, install_root)
            continue

        absent = {
            skill
            for skill in skills
            if not (install_root / skill).exists()
            and not (install_root / skill).is_symlink()
        }
        if not absent:
            for paths in skills.values():
                _remove_tree(paths["retired"], install_root)
            continue

        intended_removals = {
            skill
            for skill in absent
            if skill in remove_names
            or (all_managed and skill not in source_names)
        }
        if intended_removals != absent:
            unresolved = sorted(absent - intended_removals)[0]
            raise TransactionError(
                "retired remnant requires the same affected set or an "
                "all-managed installation",
                phase="recovery",
                skill=unresolved,
            )
        remaining_removals = {
            skill
            for skill in remove_names
            if (install_root / skill).exists()
            or (install_root / skill).is_symlink()
        }
        if remaining_removals:
            for skill, paths in skills.items():
                if skill in absent:
                    rename_with_retry(
                        paths["retired"], install_root / skill
                    )
                else:
                    _remove_tree(paths["retired"], install_root)
            continue
        for skill, paths in skills.items():
            _remove_tree(paths["retired"], install_root)


def same_source_stale(
    install_root: pathlib.Path, source_names: set[str], source_id: str
) -> list[str]:
    """Return stale same-source canonical skills for an all-managed install."""

    stale: list[str] = []
    if not install_root.is_dir():
        return stale
    for path in install_root.iterdir():
        if path.name.startswith(".") or _unsafe_link(path) or not path.is_dir():
            continue
        if not (path / MANIFEST_NAME).is_file() or path.name in source_names:
            continue
        try:
            manifest = read_runtime_manifest(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if (
            manifest.get("schema") == RUNTIME_MANIFEST_SCHEMA
            and manifest.get("skill") == path.name
            and manifest.get("runtime_source_id") == source_id
        ):
            stale.append(path.name)
    return sorted(stale)


def _rollback(
    install_root: pathlib.Path,
    deployed_paths: Mapping[str, pathlib.Path],
    retired_paths: Mapping[str, pathlib.Path],
    activated: Sequence[str],
) -> str:
    failures: list[str] = []
    for skill in reversed(activated):
        try:
            _remove_tree(install_root / skill, install_root)
        except (OSError, RuntimeError):
            failures.append(f"remove-active:{skill}")
    for skill, retired in reversed(list(retired_paths.items())):
        try:
            canonical = install_root / skill
            if canonical.exists() or canonical.is_symlink():
                _remove_tree(canonical, install_root)
            rename_with_retry(retired, canonical)
        except (OSError, RuntimeError):
            failures.append(f"restore-retired:{skill}")
    for skill, deployed in deployed_paths.items():
        try:
            _remove_tree(deployed, install_root)
        except (OSError, RuntimeError):
            failures.append(f"remove-deployed:{skill}")
    return "complete" if not failures else "incomplete:" + ",".join(failures)


def install_transaction(
    repo_root: pathlib.Path,
    install_root: pathlib.Path,
    *,
    selected: Sequence[str] = (),
    remove: Sequence[str] = (),
    all_managed: bool = False,
) -> TransactionResult:
    """Install one exact selected batch under a single writer transaction."""

    configure_repo(repo_root)
    manifest = load_manifest()
    source_names = set(source_skill_names())
    deploy_names = source_names if all_managed else set(selected)
    remove_names = set(remove)
    if all_managed and selected:
        raise TransactionError(
            "all-managed installation cannot include selected skills",
            phase="preflight",
        )
    if len(deploy_names) != len(tuple(selected)) and not all_managed:
        raise TransactionError(
            "selected skill names must be unique", phase="preflight"
        )
    if len(remove_names) != len(tuple(remove)):
        raise TransactionError(
            "removed skill names must be unique", phase="preflight"
        )
    if deploy_names & remove_names:
        raise TransactionError(
            "a skill cannot be both deployed and removed", phase="preflight"
        )
    for skill in sorted(deploy_names | remove_names):
        if not valid_skill_name(skill):
            raise TransactionError(
                f"unsafe skill name: {skill}",
                phase="preflight",
                skill=skill,
            )
    unknown = sorted(deploy_names - source_names)
    if unknown:
        raise TransactionError(
            f"unknown selected skill: {unknown[0]}",
            phase="preflight",
            skill=unknown[0],
        )
    still_present = sorted(remove_names & source_names)
    if still_present:
        raise TransactionError(
            "cannot remove a skill still present in the source snapshot",
            phase="preflight",
            skill=still_present[0],
        )
    errors = validate_manifest(
        manifest, source_names, deploy_names, all_managed=all_managed
    )
    if errors:
        raise TransactionError(errors[0], phase="preflight")
    source_id = cast(str, manifest["runtime_source_id"])
    install_root = install_root.resolve()

    with runtime_lock(install_root):
        if all_managed:
            remove_names.update(
                same_source_stale(install_root, source_names, source_id)
            )
        recover_interrupted(
            install_root,
            source_id,
            remove_names=remove_names,
            all_managed=all_managed,
            source_names=source_names,
        )
        if all_managed:
            remove_names.update(
                same_source_stale(install_root, source_names, source_id)
            )
        for skill in sorted(deploy_names | remove_names):
            error = install_target_error(install_root / skill, source_id)
            if error is not None:
                raise TransactionError(
                    error, phase="preflight", skill=skill
                )

        transaction_id = uuid.uuid4().hex
        deployed_paths: dict[str, pathlib.Path] = {}
        retired_paths: dict[str, pathlib.Path] = {}
        activated: list[str] = []
        phase = "staging"
        current_skill = ""
        commit_point = False
        try:
            for skill in sorted(deploy_names):
                current_skill = skill
                staged = install_root / f".{skill}-deployed-{transaction_id}"
                deployed_paths[skill] = staged
                write_expected_skill(skill, staged, manifest)
                enable_windows_acl_inheritance(staged)
                staged_manifest = read_runtime_manifest(staged)
                if (
                    staged_manifest.get("schema") != RUNTIME_MANIFEST_SCHEMA
                    or staged_manifest.get("skill") != skill
                    or staged_manifest.get("runtime_source_id") != source_id
                ):
                    raise ValueError("staged runtime manifest identity mismatch")

            phase = "retirement"
            for skill in sorted(deploy_names | remove_names):
                current_skill = skill
                canonical = install_root / skill
                if not canonical.exists() and not canonical.is_symlink():
                    continue
                retired = install_root / f".{skill}-retired-{transaction_id}"
                rename_with_retry(canonical, retired)
                retired_paths[skill] = retired

            phase = "activation"
            for skill in sorted(deploy_names):
                current_skill = skill
                rename_with_retry(deployed_paths[skill], install_root / skill)
                activated.append(skill)
            commit_point = True

            phase = "cleanup"
            retained: list[str] = []
            for skill, retired in retired_paths.items():
                current_skill = skill
                try:
                    _remove_tree(retired, install_root)
                except (OSError, RuntimeError):
                    retained.append(retired.name)
            status = "cleanup_blocked" if retained else "ok"
            return TransactionResult(
                status=status,
                deployed=tuple(sorted(deploy_names)),
                removed=tuple(sorted(remove_names)),
                transaction_id=transaction_id,
                retained_retired=tuple(sorted(retained)),
            )
        except (
            OSError,
            RuntimeError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
        ) as exc:
            if commit_point:
                raise TransactionError(
                    str(exc),
                    phase=phase,
                    skill=current_skill,
                    rollback_state="not_available_after_commit",
                ) from exc
            rollback = _rollback(
                install_root, deployed_paths, retired_paths, activated
            )
            raise TransactionError(
                str(exc),
                phase=phase,
                skill=current_skill,
                rollback_state=rollback,
            ) from exc


def build_parser() -> argparse.ArgumentParser:
    """Create the direct transaction CLI used by tests and runtime callers."""

    parser = argparse.ArgumentParser(
        description="Transactionally install managed runtime skill batches."
    )
    parser.add_argument("--repo-root", required=True, type=pathlib.Path)
    parser.add_argument("--install-root", required=True, type=pathlib.Path)
    parser.add_argument("--skill", action="append")
    parser.add_argument("--remove-skill", action="append")
    parser.add_argument("--all-managed", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute one transaction and emit a compact structured result."""

    args = build_parser().parse_args(argv)
    try:
        result = install_transaction(
            args.repo_root.resolve(),
            args.install_root.resolve(),
            selected=args.skill or (),
            remove=args.remove_skill or (),
            all_managed=args.all_managed,
        )
    except (
        InstallBusy,
        TransactionError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        payload = (
            exc.result()
            if isinstance(exc, TransactionError)
            else {
                "status": "error",
                "phase": "preflight",
                "skill": "",
                "rollback": "not_started",
                "reason": str(exc),
            }
        )
        print(json.dumps(payload, separators=(",", ":")), file=sys.stderr)
        return 1
    print(json.dumps(result.as_dict(), separators=(",", ":")))
    return 2 if result.status == "cleanup_blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
