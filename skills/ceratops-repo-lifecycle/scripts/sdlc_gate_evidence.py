"""Retain latest SDLC stage outcomes and verify them without running checks.

Records belong to one checkout, clean commit, expanded operation and execution
environment. They bind command completion, not arbitrary claims about product
behavior. Domain receipts remain authoritative for artifact qualification.
The latest attempt replaces earlier success before a command starts, so failure
or interruption cannot expose an older pass. Test reuse requires the same key;
standalone non-Git capability calls are never cached. The owning runner writes
records under .build/sdlc; temporary write files are removed on every exit.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Mapping
from typing import Any

from sdlc_results import _unique_result_object

SCHEMA = "ceratops-sdlc-stage-result.v1"
PASSED = {"completed", "no_op"}
ENVIRONMENT_KEYS = ("PATH", "PYTHONPATH", "PSModulePath", "PSMODULEPATH",
                    "VIRTUAL_ENV", "NODE_OPTIONS", "PYTHONHOME", "PLAYWRIGHT_BROWSERS_PATH")


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def source_is_clean(root: pathlib.Path, commit: str | None) -> bool:
    """Owned untracked result files are output; tracked changes remain blockers."""
    if not commit:
        return False
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=False)
    status = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
                            capture_output=True, text=True, check=False)
    dirty = [line for line in status.stdout.splitlines() if not re.fullmatch(
        r"\?\? \.build/sdlc/(?:[0-9a-f]{64}\.(?:json|lock)|\.stage-[^/]+\.tmp)", line)]
    return head.returncode == status.returncode == 0 and head.stdout.strip() == commit and not dirty


def _directory(root: pathlib.Path, *, create: bool = False) -> pathlib.Path:
    directory = root / ".build" / "sdlc"
    for path in (root / ".build", directory):
        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root):
            raise ValueError("SDLC result directory must not be redirected.")
        if path.exists() and not path.is_dir():
            raise ValueError("SDLC result directory is not a directory.")
    if create:
        directory.mkdir(parents=True, exist_ok=True)
        # Existing repositories may predate the template's .build exclusion.
        # Keep generated records out of later `git add .` and clean-tree gates
        # without editing the repository's tracked ignore rules.
        ignore = directory / ".gitignore"
        if ignore.is_symlink() or ignore.is_junction():
            raise ValueError("SDLC result ignore file must not be redirected.")
        try:
            with ignore.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write("*\n")
        except FileExistsError:
            pass
    return directory


def _path(prepared: Any) -> pathlib.Path:
    return _directory(prepared.repo_root) / (_digest(prepared.operation) + ".json")


def identity(prepared: Any) -> dict[str, Any]:
    """Bind commands and tools without launching version probes or test processes."""
    tools = []
    # Nested repository scripts commonly dispatch these interpreters. Reading
    # their file metadata also binds those tools without executing probes.
    commands = [(step.argv[0], step.cwd) for step in prepared.steps]
    commands.extend((name, prepared.repo_root) for name in ("python", "pwsh", "node", "git", "uv"))
    for name, cwd in commands:
        executable = shutil.which(name) if not any(c in name for c in ("/", "\\")) else str(cwd / name)
        path = pathlib.Path(executable).resolve() if executable else None
        stat = path.stat() if path and path.is_file() else None
        tools.append({"path": str(path) if path else name,
                      "size": stat.st_size if stat else None,
                      "modified_ns": stat.st_mtime_ns if stat else None})
    contract = prepared.repo_root / (prepared.contract_path or "sdlc/sdlc.yml")
    return {
        "repository": str(prepared.repo_root), "commit": prepared.commit,
        "operation": prepared.operation, "category": prepared.category,
        "contractSha256": hashlib.sha256(contract.read_bytes()).hexdigest() if contract.is_file() else None,
        "steps": [{"position": step.position, "argv": list(step.argv), "cwd": str(step.cwd)} for step in prepared.steps],
        "handoff": prepared.handoff, "context": prepared.handoff_mode,
        "noOpReason": prepared.no_op_reason, "tools": tools,
        "python": {"executable": sys.executable, "version": list(sys.version_info[:3])},
        "platform": platform.platform(),
        "environment": {key: os.environ.get(key) for key in ENVIRONMENT_KEYS},
    }


def _read(prepared: Any) -> dict[str, Any] | None:
    path = _path(prepared)
    if path.is_symlink() or path.is_junction():
        raise ValueError("SDLC result file must not be redirected.")
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return None
        record = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_result_object)
        if not isinstance(record, dict):
            return None
        digest = record.pop("sha256", None)
        return record if digest == _digest(record) and record.get("schema") == SCHEMA else None
    except (OSError, ValueError, TypeError):
        return None


def _write(prepared: Any, record: Mapping[str, Any]) -> None:
    directory = _directory(prepared.repo_root, create=True)
    path = _path(prepared)
    if path.is_symlink() or path.is_junction():
        raise ValueError("SDLC result file must not be redirected.")
    payload = {**record, "sha256": _digest(record)}
    descriptor, name = tempfile.mkstemp(prefix=".stage-", suffix=".tmp", dir=directory)
    temporary = pathlib.Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def lock(prepared: Any) -> Iterator[None]:
    """An OS lock survives a crashed attempt without leaving a stale lock owner."""
    directory = _directory(prepared.repo_root, create=True)
    path = directory / (_digest(prepared.operation) + ".lock")
    if path.is_symlink() or path.is_junction():
        raise ValueError("SDLC result lock must not be redirected.")
    with path.open("a+b") as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"\0")
            stream.flush()
        if os.name == "nt":
            import msvcrt

            def acquire() -> None:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)

            def release() -> None:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def acquire() -> None:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            def release() -> None:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        deadline = time.monotonic() + 10
        while True:
            try:
                acquire()
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ValueError("Another SDLC stage or delivery owns the result record.") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            release()


def require_pass(prepared: Any) -> dict[str, Any]:
    """Inspect the latest outcome only; absence and mismatch never trigger checks."""
    record = _read(prepared)
    reason = None
    if not source_is_clean(prepared.repo_root, prepared.commit):
        reason = "source is not the recorded clean commit"
    elif not record:
        reason = "saved result is missing or corrupt"
    elif record.get("status") not in PASSED or not record.get("reusable"):
        reason = "latest attempt is not a reusable success"
    elif record.get("identity") != identity(prepared):
        reason = "saved source, command or environment does not match"
    elif not isinstance(record.get("result"), dict) or any(
        record["result"].get(key) != value for key, value in {
            "status": record["status"], "operation": prepared.operation,
            "commit": prepared.commit,
            "steps": [step.position for step in prepared.steps],
        }.items()
    ):
        reason = "saved command completion is incomplete"
    if reason:
        raise ValueError(f"{prepared.operation}: {reason}; run its {prepared.category} stage before deployment.")
    assert record is not None
    return record


def run_stage(prepared: Any, execute: Any, *, fresh: bool = False) -> dict[str, Any]:
    """Run validation or reuse/run tests, atomically retaining every attempt."""
    with lock(prepared):
        if prepared.category == "tests" and not fresh:
            try:
                prior = require_pass(prepared)
                return {**prior["result"], "reused": True, "evidence_file": str(_path(prepared))}
            except ValueError:
                pass
        bound = identity(prepared)
        clean_before = source_is_clean(prepared.repo_root, prepared.commit)
        record = {"schema": SCHEMA, "identity": bound, "status": "running",
                  "reusable": False, "startedAt": time.time()}
        _write(prepared, record)
        result = execute()
        unchanged = identity(prepared) == bound and source_is_clean(prepared.repo_root, prepared.commit)
        if clean_before and not unchanged:
            result = {**result, "status": "state_changed", "message": "Stage inputs changed while checking."}
        record.update(status=result["status"], reusable=clean_before and unchanged and result["status"] in PASSED,
                      finishedAt=time.time(), result=result)
        _write(prepared, record)
        return {**result, "evidence_file": str(_path(prepared))}
