#!/usr/bin/env python3
"""Own v2 artifact-store paths, persistence, publication, and cleanup.

The repository operation runner owns build and test selection. This module owns
the shared Git store and the byte-level storage transaction it calls: staging,
measurement, receipt persistence, atomic directory publication, locking,
retention, diagnostics, and interrupted-write cleanup. The current transaction
intentionally keeps one store lock for its complete build/test lifetime.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import sdlc_results
from sdlc_results import StepResultError

BUILD_BUNDLE_RETENTION = 3
BUILD_KEY_RE = re.compile(r"^[a-f0-9]{64}$")


class OperationError(RuntimeError):
    """A malformed selection or unsafe repository boundary."""


@dataclass(frozen=True)
class BuildProduct:
    """Adapter outputs relative to the supplied bundle directory.

    File descriptors contain type/path and, for artifacts, deliverable. The
    transaction measures size/hash itself before handing those bytes to tests.
    Dependencies pair an exact receipt identity with their copied artifacts.
    Scratch source trees and test environments belong in the separate work dir.
    """

    artifacts: Sequence[Mapping[str, Any]]
    dependencies: Sequence[Mapping[str, Any]] = ()
    supporting_files: Sequence[Mapping[str, Any]] = ()


@dataclass(frozen=True)
class CompletedDependency:
    """One recorded dependency identity and its exact stored artifact paths."""

    identity: Mapping[str, str]
    artifacts: tuple[pathlib.Path, ...]


@dataclass(frozen=True)
class CompletedBuild:
    """A verified completed v2 build selected for downstream consumption."""

    receipt_path: pathlib.Path
    receipt: Mapping[str, Any]
    artifacts: tuple[pathlib.Path, ...]
    dependencies: tuple[CompletedDependency, ...]
    supporting_files: tuple[pathlib.Path, ...]


@dataclass(frozen=True)
class BuildStorage:
    """Resolved paths for one v2 store transaction.

    The build key is derived from the validated identity. Every mutable path is
    helper-owned and remains below the resolved shared Git store.
    """

    identity: Mapping[str, str]
    key: str
    store: pathlib.Path
    staging_root: pathlib.Path
    diagnostics: pathlib.Path
    completed: pathlib.Path
    staging: pathlib.Path
    diagnostic_path: pathlib.Path
    lock_path: pathlib.Path

    @property
    def bundle(self) -> pathlib.Path:
        return self.staging / "bundle"

    @property
    def work(self) -> pathlib.Path:
        return self.staging / "work"


def canonical_json(value: object) -> bytes:
    """Serialize one store record with stable UTF-8/LF bytes."""

    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _build_directory(path: pathlib.Path) -> pathlib.Path:
    """Create only real directories, never following a pre-existing junction."""

    if not path.exists() and not path.is_symlink():
        _build_directory(path.parent)
        path.mkdir(exist_ok=True)
    return sdlc_results._plain_path(path, directory=True)[0]


def _build_store_path(repo_root: pathlib.Path) -> pathlib.Path:
    """Resolve the shared store location without creating reader-visible state."""

    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise OperationError("Build storage requires a Git repository.")
    common = sdlc_results._plain_path(
        pathlib.Path(result.stdout.strip()), directory=True
    )[0]
    return common / "ceratops" / "builds"


def _build_store(repo_root: pathlib.Path) -> pathlib.Path:
    return _build_directory(_build_store_path(repo_root))


def validated_build_selection(selection: Mapping[str, str]) -> dict[str, str]:
    """Return one canonical v2 build identity after schema validation."""

    result_validator = sdlc_results._operation_result_validator()
    validator = result_validator.evolve(
        schema={
            "$ref": "#/$defs/buildSelection",
            "$defs": result_validator.schema["$defs"],
        }
    )
    errors = list(validator.iter_errors(dict(selection)))
    if errors:
        raise OperationError(f"Invalid build selection: {errors[0].message}")
    identity = json.loads(canonical_json(dict(selection)))
    return {field: identity[field] for field in sdlc_results.BUILD_SELECTION_FIELDS}


def measure_build_file(
    root: pathlib.Path, descriptor: Mapping[str, Any]
) -> dict[str, Any]:
    """Measure one adapter-owned file and reject links or escaping paths."""

    record = dict(descriptor)
    if set(record) not in ({"type", "path"}, {"type", "path", "deliverable"}):
        raise OperationError(
            "Build adapters return file descriptors, not supplied hashes."
        )
    path = root.joinpath(*sdlc_results._bundle_relative_path(record["path"]).parts)
    path, before = sdlc_results._plain_path(path)
    if not path.is_relative_to(root):
        raise OperationError("Build output escapes its private bundle.")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        remaining = before.st_size + 1
        while remaining and (chunk := stream.read(min(1024 * 1024, remaining))):
            digest.update(chunk)
            remaining -= len(chunk)
    record.update(size=before.st_size, sha256=digest.hexdigest())
    sdlc_results._verify_bundle_file(root, record)
    return record


def require_recorded_acceptance(receipt: Mapping[str, Any]) -> None:
    """Require passed tests with evidence covering every primary artifact."""

    tests = receipt["tests"]
    if (
        receipt["status"] != "passed"
        or not tests
        or any(
            test["status"] != "passed" or not test["evidence"] for test in tests
        )
    ):
        raise OperationError(
            "Every required artifact test must pass with recorded evidence."
        )
    tested = {item["path"] for test in tests for item in test["artifacts"]}
    if not {item["path"] for item in receipt["artifacts"]}.issubset(tested):
        raise OperationError(
            "Required tests do not cover every built artifact."
        )


def _completed_build_gate(receipt: Mapping[str, Any]) -> None:
    """Require recorded successful acceptance without consulting today's tests."""

    require_recorded_acceptance(receipt)
    if not any(
        item["type"] == "build-inputs"
        and item["path"] == "supporting-files/build-inputs.json"
        for item in receipt["supportingFiles"]
    ):
        raise OperationError("Completed build lacks its recorded build inputs.")


def _build_inventory(root: pathlib.Path, receipt: Mapping[str, Any]) -> None:
    """Do not publish unlisted scratch, environments, or linked payloads."""

    expected = {
        "receipt.json",
        *(item["path"] for item in sdlc_results._build_files(receipt)),
    }
    actual: set[str] = set()
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in directories:
            sdlc_results._plain_path(pathlib.Path(parent) / name, directory=True)
        for name in files:
            path = pathlib.Path(parent) / name
            sdlc_results._plain_path(path)
            actual.add(path.relative_to(root).as_posix())
    if actual != expected:
        raise OperationError("Build bundle contains missing or unlisted files.")


def _recorded_build_path(
    root: pathlib.Path, record: Mapping[str, Any]
) -> pathlib.Path:
    """Resolve a previously verified record without repeating its byte checks."""

    path = root.joinpath(*sdlc_results._bundle_relative_path(record["path"]).parts)
    path, _info = sdlc_results._plain_path(path)
    if not path.is_relative_to(root):
        raise OperationError("Build receipt path escapes its completed bundle.")
    return path


def read_completed_build(
    repo_root: pathlib.Path,
    *,
    selection: Mapping[str, str] | None = None,
    receipt_path: pathlib.Path | None = None,
) -> CompletedBuild:
    """Read one explicitly selected completed v2 build without building or testing.

    Callers select either the six-field build identity or an absolute saved
    ``receipt.json`` path in this repository's shared store. The v2 reader checks
    identity plus every recorded file once here. Returned paths come only from
    that verified record, so nested consumers need not reopen or reinterpret it.
    """

    if (selection is None) == (receipt_path is None):
        raise OperationError(
            "Select a completed build by identity or receipt path, not both."
        )
    try:
        store = sdlc_results._plain_path(
            _build_store_path(repo_root), directory=True
        )[0]
        if receipt_path is None:
            assert selection is not None
            identity = validated_build_selection(selection)
            key = hashlib.sha256(canonical_json(identity)).hexdigest()
            bundle = store / key
            selected_receipt = bundle / "receipt.json"
        else:
            selected_receipt = pathlib.Path(receipt_path)
            if not selected_receipt.is_absolute():
                raise OperationError(
                    "An explicit completed-build receipt path must be absolute."
                )
            selected_receipt, _info = sdlc_results._plain_path(selected_receipt)
            bundle = sdlc_results._plain_path(
                selected_receipt.parent, directory=True
            )[0]
            if selected_receipt.name != "receipt.json" or bundle.parent != store:
                raise OperationError(
                    "Completed-build receipt is outside the shared build store."
                )
            identity = validated_build_selection(
                sdlc_results._read_build_receipt(selected_receipt)["identity"]
            )
            key = hashlib.sha256(canonical_json(identity)).hexdigest()
        if bundle.parent != store or bundle.name != key:
            raise OperationError(
                "Completed build directory does not match its identity."
            )
        receipt = sdlc_results.verify_release_unit_build(
            selected_receipt, bundle, expected=identity
        )
        _completed_build_gate(receipt)
        _build_inventory(bundle, receipt)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, (OperationError, StepResultError)):
            raise
        raise OperationError(f"Cannot read completed build: {exc}"[:1024]) from exc

    return CompletedBuild(
        receipt_path=selected_receipt,
        receipt=receipt,
        artifacts=tuple(
            _recorded_build_path(bundle, item) for item in receipt["artifacts"]
        ),
        dependencies=tuple(
            CompletedDependency(
                identity=deepcopy(item["identity"]),
                artifacts=tuple(
                    _recorded_build_path(bundle, artifact)
                    for artifact in item["artifacts"]
                ),
            )
            for item in receipt["dependencies"]
        ),
        supporting_files=tuple(
            _recorded_build_path(bundle, item)
            for item in receipt["supportingFiles"]
        ),
    )


def _remove_build_tree(
    path: pathlib.Path, parent: pathlib.Path, label: str
) -> None:
    """Remove one helper-owned hash directory without following links."""

    if path.parent != parent or BUILD_KEY_RE.fullmatch(path.name) is None:
        raise OperationError(f"Unsafe {label} cleanup target.")
    if path.exists() or path.is_symlink():
        sdlc_results._plain_path(path, directory=True)

        def remove_readonly(
            function: Callable[..., Any], name: str, error: BaseException
        ) -> None:
            target = pathlib.Path(name).absolute()
            if not isinstance(error, PermissionError) or not target.is_relative_to(path):
                raise error
            # Git copies and test environments can contain read-only files on
            # Windows. Never chmod a link/hardlink or an unrelated target.
            _resolved, info = sdlc_results._plain_path(
                target, directory=target.is_dir()
            )
            if info.st_mode & stat.S_IWRITE:
                raise error
            target.chmod(info.st_mode | stat.S_IWRITE)
            function(name)

        # Python rmtree does not traverse directory junctions or symlink entries.
        shutil.rmtree(path, onexc=remove_readonly)
    if path.exists() or path.is_symlink():
        raise OperationError(f"{label.capitalize()} cleanup did not complete.")


def _discard_build_work(staging: pathlib.Path, staging_root: pathlib.Path) -> None:
    _remove_build_tree(staging, staging_root, "build staging")


def _cleanup_build_staging(staging_root: pathlib.Path) -> None:
    """Remove every recognizable orphan after the repository lock is held."""

    for path in staging_root.iterdir():
        if BUILD_KEY_RE.fullmatch(path.name):
            _discard_build_work(path, staging_root)


def _build_group(identity: Mapping[str, str]) -> dict[str, str]:
    """Group successive local builds that serve the same release purpose."""

    return {
        name: identity[name]
        for name in ("repository", "releaseUnit", "channel", "target")
    }


def _build_group_key(identity: Mapping[str, str]) -> str:
    return hashlib.sha256(canonical_json(_build_group(identity))).hexdigest()


def _build_diagnostic_path(
    diagnostics: pathlib.Path, identity: Mapping[str, str]
) -> pathlib.Path:
    return diagnostics / f"{_build_group_key(identity)}.json"


def _clear_build_diagnostic(path: pathlib.Path) -> None:
    if path.exists() or path.is_symlink():
        sdlc_results._plain_path(path)
        path.unlink()


def _cleanup_build_diagnostic_temps(diagnostics: pathlib.Path) -> None:
    """Discard interrupted writes; stable reports are overwritten by group."""

    for path in diagnostics.iterdir():
        if re.fullmatch(r"[a-f0-9]{64}\.tmp", path.name):
            sdlc_results._plain_path(path)
            path.unlink()


def _completed_build_groups(
    store: pathlib.Path, validator: Any
) -> dict[str, list[tuple[int, str, pathlib.Path]]]:
    """Classify well-formed completed bundles without reading artifact bytes."""

    groups: dict[str, list[tuple[int, str, pathlib.Path]]] = {}
    for path in store.iterdir():
        if BUILD_KEY_RE.fullmatch(path.name) is None:
            continue
        _resolved, info = sdlc_results._plain_path(path, directory=True)
        receipt_path, receipt_info = sdlc_results._plain_path(path / "receipt.json")
        if receipt_info.st_size > sdlc_results.STEP_RESULT_BYTES:
            raise OperationError(
                "Completed build receipt is too large for retention."
            )
        try:
            receipt = json.loads(
                receipt_path.read_bytes(),
                object_pairs_hook=sdlc_results._unique_result_object,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OperationError(
                f"Completed build receipt is unreadable: {path.name}"
            ) from exc
        errors = list(validator.iter_errors(receipt))
        if errors or receipt.get("schema") != sdlc_results.BUILD_RECEIPT_SCHEMA:
            detail = errors[0].message if errors else "unexpected schema"
            raise OperationError(f"Completed build receipt is invalid: {detail}")
        identity = receipt["identity"]
        if path.name != hashlib.sha256(canonical_json(identity)).hexdigest():
            raise OperationError(
                "Completed build directory does not match its identity."
            )
        group = _build_group_key(identity)
        groups.setdefault(group, []).append((info.st_mtime_ns, path.name, path))
    return groups


def _prune_completed_builds(
    store: pathlib.Path, validator: Any, *, current_key: str | None = None
) -> None:
    """Keep the current bundle and two predecessors for every release group."""

    for entries in _completed_build_groups(store, validator).values():
        entries.sort(
            key=lambda item: (item[1] == current_key, item[0], item[1]),
            reverse=True,
        )
        for _mtime, _key, path in entries[BUILD_BUNDLE_RETENTION:]:
            _remove_build_tree(path, store, "completed build")


def _build_diagnostic(
    destination: pathlib.Path,
    identity: Mapping[str, str],
    error: str,
    required_tests: Sequence[str],
    tests: Sequence[Mapping[str, Any]],
    bundle: pathlib.Path,
) -> None:
    """Preserve bounded failure evidence before private test files are removed.

    Diagnostic excerpts are not verification evidence. Unsafe/missing evidence
    remains an error description, never a reason to read outside the bundle.
    """

    excerpts = []
    for result in tests[:20]:
        if not isinstance(result, Mapping):
            continue
        entry: dict[str, Any] = {
            "id": str(result.get("id", ""))[:256],
            "status": str(result.get("status", ""))[:32],
        }
        evidence = result.get("evidence")
        if isinstance(evidence, Mapping) and isinstance(evidence.get("path"), str):
            try:
                path = bundle.joinpath(
                    *sdlc_results._bundle_relative_path(evidence["path"]).parts
                )
                path, _info = sdlc_results._plain_path(path)
                if not path.is_relative_to(bundle):
                    raise OperationError(
                        "Diagnostic evidence escapes the bundle."
                    )
                with path.open("rb") as stream:
                    raw = stream.read(16385)
                entry["evidence"] = raw[:16384].decode("utf-8", errors="replace")
                entry["truncated"] = len(raw) > 16384
            except (OSError, StepResultError, OperationError) as exc:
                entry["evidence_error"] = str(exc)[:1024]
        excerpts.append(entry)
    temporary = destination.with_suffix(".tmp")
    if temporary.exists() or temporary.is_symlink():
        sdlc_results._plain_path(temporary)
        temporary.unlink()
    with temporary.open("xb") as stream:
        stream.write(
            canonical_json(
                {
                    "identity": identity,
                    "error": error[:4096],
                    "requiredTests": list(required_tests),
                    "tests": excerpts,
                    "omittedTests": max(0, len(tests) - 20),
                }
            )
        )
        stream.flush()
        os.fsync(stream.fileno())
    if destination.exists() or destination.is_symlink():
        sdlc_results._plain_path(destination)
    temporary.replace(destination)


def prepare_build_storage(
    repo_root: pathlib.Path, identity: Mapping[str, str]
) -> BuildStorage:
    """Resolve and create the unchanged v2 store infrastructure."""

    key = hashlib.sha256(canonical_json(identity)).hexdigest()
    store = _build_store(repo_root)
    staging_root = _build_directory(store / ".staging")
    locks = _build_directory(store / ".locks")
    diagnostics = _build_directory(store / ".diagnostics")
    lock_path = locks / "store.lock"
    if lock_path.exists() or lock_path.is_symlink():
        sdlc_results._plain_path(lock_path)
    return BuildStorage(
        identity=deepcopy(identity),
        key=key,
        store=store,
        staging_root=staging_root,
        diagnostics=diagnostics,
        completed=store / key,
        staging=staging_root / key,
        diagnostic_path=_build_diagnostic_path(diagnostics, identity),
        lock_path=lock_path,
    )


@contextmanager
def locked_build_storage(storage: BuildStorage) -> Iterator[None]:
    """Hold the persistent store lock for the caller's full transaction."""

    from filelock import FileLock

    # One persistent lock avoids unlink/recreate races and makes cleanup of
    # earlier transactions safe. OS ownership ends when a process dies.
    with FileLock(
        storage.lock_path,
        timeout=30,
        fallback_to_soft=False,
        preserve_lock_file=True,
    ):
        yield


def start_build_storage(
    storage: BuildStorage, validator: Any
) -> tuple[pathlib.Path, pathlib.Path]:
    """Clean prior owned state and create this identity's private directories.

    The caller must hold ``locked_build_storage``. Cleanup deliberately retains
    the v2 rule of removing every recognizable staging directory on entry.
    """

    _cleanup_build_staging(storage.staging_root)
    _cleanup_build_diagnostic_temps(storage.diagnostics)
    _prune_completed_builds(storage.store, validator)
    if storage.completed.exists() or storage.completed.is_symlink():
        raise OperationError(
            "Completed build identity already exists; read it explicitly or use a new identity."
        )
    work = _build_directory(storage.work)
    bundle = _build_directory(storage.bundle)
    return bundle, work


def write_build_inputs(storage: BuildStorage, locked_inputs: bytes) -> dict[str, Any]:
    """Persist and measure the canonical build-input record in private staging."""

    inputs_path = storage.bundle / "supporting-files" / "build-inputs.json"
    _build_directory(inputs_path.parent)
    with inputs_path.open("xb") as stream:
        stream.write(locked_inputs)
    return measure_build_file(
        storage.bundle,
        {"type": "build-inputs", "path": "supporting-files/build-inputs.json"},
    )


def publish_completed_build(
    storage: BuildStorage, receipt: Mapping[str, Any], validator: Any
) -> pathlib.Path:
    """Write one verified receipt and atomically publish its complete directory."""

    receipt_path = storage.bundle / "receipt.json"
    with receipt_path.open("xb") as stream:
        stream.write(canonical_json(receipt))
        stream.flush()
        os.fsync(stream.fileno())
    sdlc_results.verify_release_unit_build(
        receipt_path, storage.bundle, expected=storage.identity
    )
    _build_inventory(storage.bundle, receipt)
    if storage.completed.exists() or storage.completed.is_symlink():
        raise OperationError(
            "Completed build appeared during the reserved transaction."
        )
    storage.bundle.rename(storage.completed)
    os.utime(storage.completed, None)
    _prune_completed_builds(
        storage.store, validator, current_key=storage.key
    )
    _clear_build_diagnostic(storage.diagnostic_path)
    return storage.completed / "receipt.json"


def write_failure_diagnostic(
    storage: BuildStorage,
    error: str,
    required_tests: Sequence[str],
    tests: Sequence[Mapping[str, Any]],
) -> None:
    """Atomically replace this release group's bounded latest-failure report."""

    _build_diagnostic(
        storage.diagnostic_path,
        storage.identity,
        error,
        required_tests,
        tests,
        storage.bundle,
    )


def discard_build_storage(storage: BuildStorage) -> None:
    """Remove only this transaction's recognizable private staging tree."""

    _discard_build_work(storage.staging, storage.staging_root)
