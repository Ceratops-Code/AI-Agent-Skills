#!/usr/bin/env python3
"""Own v2 and pending versioned artifact-store transactions.

The repository operation runner owns build and test selection. This module owns
the shared Git store and the byte-level storage transaction it calls: staging,
measurement, receipt persistence, atomic directory publication, locking,
retention, diagnostics, and interrupted-write cleanup. The supported v2
transaction intentionally keeps one store lock for its complete build/test
lifetime. The internal versioned route instead records durable ownership under
short lock sections and preserves unresolved state for explicit recovery.
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
VERSIONED_ARTIFACT_RETENTION = 3
BUILD_KEY_RE = re.compile(r"^[a-f0-9]{64}$")
RELEASE_UNIT_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
LOGICAL_ID_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$"
)
REPOSITORY_ID_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._/-]*[A-Za-z0-9])?$"
)
FULL_VERSION_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:(?P<class>a|b)(?:0|[1-9][0-9]*))?"
    r"(?:\+[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*)?$"
)
ARTIFACT_RESERVATION_SCHEMA = "ceratops-artifact-reservation.v1"
ARTIFACT_JOURNAL_SCHEMA = "ceratops-artifact-transaction.v1"


class OperationError(RuntimeError):
    """A malformed selection or unsafe repository boundary."""


class RecoveryRequired(OperationError):
    """An unresolved versioned-store owner requires explicit recovery."""

    status = "recovery_required"


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


@dataclass(frozen=True)
class PendingArtifactTransaction:
    """Durable ownership and paths for one internal unit/version attempt.

    The transaction owns all required targets until 1d.3 finalization removes
    its journal and reservation. No method here publishes final bytes or tags.
    """

    repo_root: pathlib.Path
    repository: str
    release_unit: str
    version: str
    version_class: str
    attempt_id: str
    pre_test_commit: str
    required_targets: tuple[str, ...]
    store: pathlib.Path
    reservation_path: pathlib.Path
    pending_root: pathlib.Path
    journal_path: pathlib.Path
    staging_root: pathlib.Path
    diagnostic_root: pathlib.Path
    lock_path: pathlib.Path

    def target_output(self, target: str) -> pathlib.Path:
        _require_transaction_target(self, target)
        return self.staging_root / target / "output"

    def target_work(self, target: str) -> pathlib.Path:
        _require_transaction_target(self, target)
        return self.staging_root / target / "work"

    def pending_receipt(self, target: str) -> pathlib.Path:
        _require_transaction_target(self, target)
        return self.pending_root / "receipts" / f"{target}.json"

    def pending_git_root(self, target: str) -> pathlib.Path:
        _require_transaction_target(self, target)
        return self.pending_root / "git" / target


@dataclass(frozen=True)
class PreparedBuildReceipt:
    """Exact receipt bytes and pending identities handed to the finalizer."""

    target: str
    receipt_path: str
    pending_receipt_path: pathlib.Path
    raw: bytes
    sha256: str
    store_files: tuple[Mapping[str, Any], ...]
    git_files: tuple[Mapping[str, Any], ...]


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


def _git_common_path(repo_root: pathlib.Path) -> pathlib.Path:
    """Resolve one worktree's shared Git directory without creating state."""

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
    return common


def _build_store_path(repo_root: pathlib.Path) -> pathlib.Path:
    """Resolve the v2 shared store without creating reader-visible state."""

    return _git_common_path(repo_root) / "ceratops" / "builds"


def _artifact_store_path(repo_root: pathlib.Path) -> pathlib.Path:
    """Resolve the versioned artifact store without creating it."""

    return _git_common_path(repo_root) / "ceratops" / "artifacts"


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


# The versioned route below is intentionally additive. Existing live callers
# continue to use the v2 transaction above until worktree admission arrives in
# 2A. Its journal is local recovery state, not an acceptance record.


@dataclass(frozen=True)
class _CompletedArtifactOutput:
    repository: str
    release_unit: str
    version: str
    target: str
    version_class: str
    root: pathlib.Path
    version_root: pathlib.Path
    mtime_ns: int


def _require_identifier(
    value: object,
    *,
    label: str,
    pattern: re.Pattern[str],
    maximum: int = 128,
) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or pattern.fullmatch(value) is None
    ):
        raise OperationError(f"Invalid {label}.")
    return value


def _validated_repository(value: object) -> str:
    repository = _require_identifier(
        value,
        label="repository identity",
        pattern=REPOSITORY_ID_RE,
        maximum=256,
    )
    if "//" in repository or any(
        part in {".", ".."} for part in repository.split("/")
    ):
        raise OperationError("Invalid repository identity.")
    return repository


def _version_classification(version: object) -> tuple[str, str]:
    value = _require_identifier(
        version,
        label="full version",
        pattern=FULL_VERSION_RE,
    )
    match = FULL_VERSION_RE.fullmatch(value)
    assert match is not None
    return value, {"a": "alpha", "b": "beta"}.get(
        match.group("class"), "stable"
    )


def _validated_targets(required_targets: object) -> tuple[str, ...]:
    if isinstance(required_targets, (str, bytes)) or not isinstance(
        required_targets, Sequence
    ):
        raise OperationError("Required targets must be a nonempty sequence.")
    targets = tuple(
        _require_identifier(item, label="target", pattern=LOGICAL_ID_RE)
        for item in required_targets
    )
    if not targets or len(set(targets)) != len(targets):
        raise OperationError("Required targets must be nonempty and unique.")
    return tuple(sorted(targets))


def _require_transaction_target(
    transaction: PendingArtifactTransaction, target: str
) -> None:
    if target not in transaction.required_targets:
        raise OperationError("Target is not owned by this artifact transaction.")


def _git_text(
    repo_root: pathlib.Path, arguments: Sequence[str], *, label: str
) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise OperationError(f"Git could not resolve {label}{suffix}"[:1024])
    value = completed.stdout.strip()
    if not value or "\n" in value or "\r" in value:
        raise OperationError(f"Git returned an invalid {label}.")
    return value


def _validated_worktree(repo_root: pathlib.Path) -> pathlib.Path:
    root = sdlc_results._plain_path(
        pathlib.Path(repo_root), directory=True, label="Repository"
    )[0]
    top = pathlib.Path(
        _git_text(root, ["rev-parse", "--show-toplevel"], label="worktree root")
    )
    top = sdlc_results._plain_path(top, directory=True, label="Worktree")[0]
    if os.path.normcase(str(top)) != os.path.normcase(str(root)):
        raise OperationError("Versioned storage requires the worktree root.")
    return root


def _validated_commit(repo_root: pathlib.Path, commit: object) -> str:
    if not isinstance(commit, str) or re.fullmatch(r"[a-f0-9]{40}", commit) is None:
        raise OperationError("Pre-test commit must be a lowercase SHA-1 commit.")
    resolved = _git_text(
        repo_root,
        ["rev-parse", "--verify", "--end-of-options", f"{commit}^{{commit}}"],
        label="pre-test commit",
    )
    if resolved != commit:
        raise OperationError("Pre-test commit does not resolve exactly.")
    return commit


def _artifact_infrastructure(
    repo_root: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path]:
    store = _build_directory(_artifact_store_path(repo_root))
    for name in (".locks", ".reservations", ".pending", ".staging", ".diagnostics"):
        _build_directory(store / name)
    lock_path = store / ".locks" / "store.lock"
    if lock_path.exists() or lock_path.is_symlink():
        sdlc_results._plain_path(lock_path, label="Artifact store lock")
    return store, lock_path


@contextmanager
def _locked_artifact_store(lock_path: pathlib.Path) -> Iterator[None]:
    """Serialize only short versioned-store metadata mutations."""

    from filelock import FileLock

    with FileLock(
        lock_path,
        timeout=30,
        fallback_to_soft=False,
        preserve_lock_file=True,
    ):
        yield


def _store_relative(store: pathlib.Path, path: pathlib.Path) -> str:
    return path.relative_to(store).as_posix()


def _read_transaction_record(path: pathlib.Path, label: str) -> dict[str, Any]:
    try:
        checked, info = sdlc_results._plain_path(path, label=label)
        if info.st_size > sdlc_results.NEW_RECEIPT_BYTES:
            raise RecoveryRequired(f"{label} is oversized.")
        raw = checked.read_bytes()
        value = json.loads(
            raw,
            object_pairs_hook=sdlc_results._unique_result_object,
        )
        if not isinstance(value, dict) or raw != canonical_json(value):
            raise RecoveryRequired(f"{label} is not canonical JSON.")
        return value
    except RecoveryRequired:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError, StepResultError) as exc:
        raise RecoveryRequired(f"{label} is unreadable.") from exc


def _write_transaction_record(
    path: pathlib.Path,
    value: Mapping[str, Any],
    *,
    replace: bool,
    label: str,
) -> None:
    """Durably replace one bounded record; a leftover temp requires recovery."""

    _build_directory(path.parent)
    temporary = path.with_name(f"{path.name}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise RecoveryRequired(f"Interrupted {label} write requires recovery.")
    if not replace and (path.exists() or path.is_symlink()):
        raise RecoveryRequired(f"{label.capitalize()} already exists.")
    if replace and (path.exists() or path.is_symlink()):
        sdlc_results._plain_path(path, label=label)
    raw = canonical_json(value)
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except BaseException:
        # The temp is intentionally retained: its presence makes an interrupted
        # ownership mutation explicit on the next call.
        raise


def _expected_staging_paths(
    store: pathlib.Path,
    attempt_id: str,
    targets: Sequence[str],
) -> dict[str, dict[str, str]]:
    staging = store / ".staging" / attempt_id
    return {
        target: {
            "output": _store_relative(store, staging / target / "output"),
            "work": _store_relative(store, staging / target / "work"),
        }
        for target in targets
    }


def _new_transaction_records(
    transaction: PendingArtifactTransaction,
) -> tuple[dict[str, Any], dict[str, Any]]:
    common = {
        "repository": transaction.repository,
        "worktree": str(transaction.repo_root),
        "releaseUnit": transaction.release_unit,
        "version": transaction.version,
        "attemptId": transaction.attempt_id,
        "preTestCommit": transaction.pre_test_commit,
        "requiredTargets": list(transaction.required_targets),
    }
    reservation = {
        "schema": ARTIFACT_RESERVATION_SCHEMA,
        **common,
        "journalPath": _store_relative(
            transaction.store, transaction.journal_path
        ),
    }
    journal = {
        "schema": ARTIFACT_JOURNAL_SCHEMA,
        **common,
        "reservationPath": _store_relative(
            transaction.store, transaction.reservation_path
        ),
        "stagingPaths": _expected_staging_paths(
            transaction.store,
            transaction.attempt_id,
            transaction.required_targets,
        ),
        "phase": "reserved",
        "preparedReceipts": {},
    }
    return reservation, journal


def _validate_transaction_pair(
    transaction: PendingArtifactTransaction,
    reservation: Mapping[str, Any],
    journal: Mapping[str, Any],
) -> None:
    expected_reservation, expected_journal = _new_transaction_records(transaction)
    if dict(reservation) != expected_reservation:
        raise RecoveryRequired("Artifact reservation identity is inconsistent.")
    base_journal = dict(journal)
    prepared = base_journal.pop("preparedReceipts", None)
    phase = base_journal.pop("phase", None)
    expected_base = dict(expected_journal)
    expected_base.pop("preparedReceipts")
    expected_base.pop("phase")
    if base_journal != expected_base:
        raise RecoveryRequired("Artifact transaction journal is inconsistent.")
    if phase not in {"reserved", "receipt_prepared", "receipts_prepared"}:
        raise RecoveryRequired("Artifact transaction journal has an invalid phase.")
    if not isinstance(prepared, dict) or any(
        target not in transaction.required_targets
        or not isinstance(record, dict)
        for target, record in prepared.items()
    ):
        raise RecoveryRequired("Prepared receipt journal data is inconsistent.")
    complete = len(prepared) == len(transaction.required_targets)
    expected_phase = (
        "receipts_prepared"
        if complete
        else "receipt_prepared"
        if prepared
        else "reserved"
    )
    if phase != expected_phase:
        raise RecoveryRequired("Artifact transaction phase is inconsistent.")


def _validate_record_identity(
    record: Mapping[str, Any], *, journal: bool
) -> tuple[str, str, str, str, str, tuple[str, ...]]:
    expected = {
        "schema",
        "repository",
        "worktree",
        "releaseUnit",
        "version",
        "attemptId",
        "preTestCommit",
        "requiredTargets",
    }
    expected.update(
        ("reservationPath", "stagingPaths", "phase", "preparedReceipts")
        if journal
        else ("journalPath",)
    )
    schema = ARTIFACT_JOURNAL_SCHEMA if journal else ARTIFACT_RESERVATION_SCHEMA
    if set(record) != expected or record.get("schema") != schema:
        raise RecoveryRequired("Artifact transaction record has an invalid shape.")
    try:
        repository = _validated_repository(record["repository"])
        worktree = str(
            sdlc_results._plain_path(
                pathlib.Path(record["worktree"]),
                directory=True,
                label="Recorded worktree",
            )[0]
        )
        unit = _require_identifier(
            record["releaseUnit"],
            label="release unit",
            pattern=RELEASE_UNIT_RE,
        )
        version, _classification = _version_classification(record["version"])
        attempt = _require_identifier(
            record["attemptId"], label="attempt ID", pattern=LOGICAL_ID_RE
        )
        commit = record["preTestCommit"]
        if not isinstance(commit, str) or re.fullmatch(r"[a-f0-9]{40}", commit) is None:
            raise OperationError("Invalid pre-test commit.")
        targets = _validated_targets(record["requiredTargets"])
    except (OSError, OperationError, StepResultError) as exc:
        raise RecoveryRequired("Artifact transaction identity is invalid.") from exc
    if journal:
        expected_reservation = f".reservations/{unit}/{version}.json"
        expected_staging = {
            target: {
                "output": f".staging/{attempt}/{target}/output",
                "work": f".staging/{attempt}/{target}/work",
            }
            for target in targets
        }
        prepared = record["preparedReceipts"]
        if (
            record["reservationPath"] != expected_reservation
            or record["stagingPaths"] != expected_staging
            or record["phase"]
            not in {"reserved", "receipt_prepared", "receipts_prepared"}
            or not isinstance(prepared, dict)
        ):
            raise RecoveryRequired("Artifact transaction journal is inconsistent.")
        for target, saved in prepared.items():
            expected_receipt = (
                f".build/{unit}/{version}/receipt.json"
                if len(targets) == 1
                else f".build/{unit}/{version}/{target}/receipt.json"
            )
            if (
                target not in targets
                or not isinstance(saved, dict)
                or set(saved)
                != {
                    "receiptPath",
                    "pendingReceiptPath",
                    "size",
                    "sha256",
                    "outputPath",
                    "storeFiles",
                    "gitFiles",
                }
                or saved["receiptPath"] != expected_receipt
                or saved["pendingReceiptPath"]
                != f".pending/{attempt}/receipts/{target}.json"
                or saved["outputPath"] != f".staging/{attempt}/{target}/output"
                or not isinstance(saved["size"], int)
                or saved["size"] < 1
                or not isinstance(saved["sha256"], str)
                or re.fullmatch(r"[a-f0-9]{64}", saved["sha256"]) is None
                or not isinstance(saved["storeFiles"], list)
                or not isinstance(saved["gitFiles"], list)
            ):
                raise RecoveryRequired("Prepared receipt journal data is inconsistent.")
        expected_phase = (
            "receipts_prepared"
            if len(prepared) == len(targets)
            else "receipt_prepared"
            if prepared
            else "reserved"
        )
        if record["phase"] != expected_phase:
            raise RecoveryRequired("Artifact transaction phase is inconsistent.")
    return repository, worktree, unit, version, attempt, targets


def _scan_transaction_records_unchecked(
    store: pathlib.Path,
) -> tuple[
    dict[tuple[str, str], dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    """Read all ownership state and reject partial or ambiguous transactions."""

    reservations: dict[tuple[str, str], dict[str, Any]] = {}
    reservation_root = store / ".reservations"
    for unit_path in reservation_root.iterdir():
        if not unit_path.is_dir() or unit_path.is_symlink():
            raise RecoveryRequired("Artifact reservation storage is ambiguous.")
        unit = _require_identifier(
            unit_path.name, label="reservation unit", pattern=RELEASE_UNIT_RE
        )
        for path in unit_path.iterdir():
            if not path.is_file() or path.is_symlink() or path.suffix != ".json":
                raise RecoveryRequired("Artifact reservation storage is ambiguous.")
            record = _read_transaction_record(path, "Artifact reservation")
            identity = _validate_record_identity(record, journal=False)
            key = (identity[2], identity[3])
            if unit != identity[2] or path.stem != identity[3] or key in reservations:
                raise RecoveryRequired("Artifact reservation location is inconsistent.")
            reservations[key] = record

    journals: dict[str, dict[str, Any]] = {}
    pending_root = store / ".pending"
    for attempt_path in pending_root.iterdir():
        if not attempt_path.is_dir() or attempt_path.is_symlink():
            raise RecoveryRequired("Pending artifact storage is ambiguous.")
        attempt = _require_identifier(
            attempt_path.name, label="pending attempt", pattern=LOGICAL_ID_RE
        )
        journal_path = attempt_path / "journal.json"
        journal_temp = attempt_path / "journal.json.tmp"
        if journal_temp.exists() or journal_temp.is_symlink():
            raise RecoveryRequired("Interrupted journal write requires recovery.")
        if not journal_path.is_file() or journal_path.is_symlink():
            raise RecoveryRequired("Pending artifact journal is missing.")
        record = _read_transaction_record(journal_path, "Artifact transaction journal")
        identity = _validate_record_identity(record, journal=True)
        if attempt != identity[4] or attempt in journals:
            raise RecoveryRequired("Pending artifact journal location is inconsistent.")
        journals[attempt] = record

    for key, reservation in reservations.items():
        attempt = str(reservation["attemptId"])
        journal = journals.get(attempt)
        if journal is None:
            raise RecoveryRequired("Artifact reservation has no transaction journal.")
        if any(
            reservation[field] != journal[field]
            for field in (
                "repository",
                "worktree",
                "releaseUnit",
                "version",
                "attemptId",
                "preTestCommit",
                "requiredTargets",
            )
        ):
            raise RecoveryRequired("Reservation and journal ownership disagree.")
        expected_journal = f".pending/{attempt}/journal.json"
        expected_reservation = f".reservations/{key[0]}/{key[1]}.json"
        if (
            reservation["journalPath"] != expected_journal
            or journal["reservationPath"] != expected_reservation
        ):
            raise RecoveryRequired("Reservation and journal paths disagree.")
    if len(reservations) != len(journals):
        raise RecoveryRequired("Pending artifact journal has no reservation.")

    staging_root = store / ".staging"
    for attempt_path in staging_root.iterdir():
        if (
            not attempt_path.is_dir()
            or attempt_path.is_symlink()
            or attempt_path.name not in journals
        ):
            raise RecoveryRequired("Unowned artifact staging requires recovery.")
    return reservations, journals


def _scan_transaction_records(
    store: pathlib.Path,
) -> tuple[
    dict[tuple[str, str], dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    try:
        return _scan_transaction_records_unchecked(store)
    except RecoveryRequired:
        raise
    except (OSError, OperationError, StepResultError) as exc:
        raise RecoveryRequired("Artifact transaction storage requires recovery.") from exc


def _artifact_tag_exists(
    repo_root: pathlib.Path, release_unit: str, version: str
) -> bool:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/tags/{release_unit}/{version}",
        ],
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise OperationError("Git could not inspect the immutable version tag.")
    return result.returncode == 0


def _completed_artifact_record(
    receipt_path: pathlib.Path,
    *,
    unit: str,
    version: str,
    target: str | None,
    root: pathlib.Path,
    version_root: pathlib.Path,
) -> _CompletedArtifactOutput:
    try:
        receipt = sdlc_results.read_artifact_receipt(receipt_path).value
    except (OSError, StepResultError) as exc:
        raise OperationError("Completed artifact receipt is invalid.") from exc
    identity = receipt["identity"]
    if (
        identity["releaseUnit"] != unit
        or identity["version"] != version
        or (target is not None and identity["target"] != target)
    ):
        raise OperationError("Completed artifact location does not match its identity.")
    _version, version_class = _version_classification(version)
    return _CompletedArtifactOutput(
        repository=_validated_repository(identity["repository"]),
        release_unit=unit,
        version=version,
        target=identity["target"],
        version_class=version_class,
        root=root,
        version_root=version_root,
        mtime_ns=sdlc_results._plain_path(
            root, directory=True, label="Completed artifact output"
        )[1].st_mtime_ns,
    )


def _completed_artifact_outputs(
    store: pathlib.Path,
) -> list[_CompletedArtifactOutput]:
    outputs: list[_CompletedArtifactOutput] = []
    for unit_path in store.iterdir():
        if unit_path.name.startswith("."):
            continue
        if not unit_path.is_dir() or unit_path.is_symlink():
            raise OperationError("Artifact store contains an invalid release unit.")
        unit = _require_identifier(
            unit_path.name, label="stored release unit", pattern=RELEASE_UNIT_RE
        )
        for version_path in unit_path.iterdir():
            if not version_path.is_dir() or version_path.is_symlink():
                raise OperationError("Artifact store contains an invalid version.")
            version, _version_class = _version_classification(version_path.name)
            direct_receipt = version_path / "artifact-receipt.json"
            if direct_receipt.exists() or direct_receipt.is_symlink():
                if any(
                    child.is_dir()
                    and not child.is_symlink()
                    and (child / "artifact-receipt.json").exists()
                    for child in version_path.iterdir()
                ):
                    raise OperationError("Completed artifact layout is ambiguous.")
                outputs.append(
                    _completed_artifact_record(
                        direct_receipt,
                        unit=unit,
                        version=version,
                        target=None,
                        root=version_path,
                        version_root=version_path,
                    )
                )
                continue
            target_paths = list(version_path.iterdir())
            if not target_paths:
                raise OperationError("Completed artifact version has no receipt.")
            for target_path in target_paths:
                if not target_path.is_dir() or target_path.is_symlink():
                    raise OperationError("Targeted artifact layout is invalid.")
                target = _require_identifier(
                    target_path.name, label="stored target", pattern=LOGICAL_ID_RE
                )
                receipt_path = target_path / "artifact-receipt.json"
                if not receipt_path.exists() or receipt_path.is_symlink():
                    raise OperationError("Targeted artifact output has no receipt.")
                outputs.append(
                    _completed_artifact_record(
                        receipt_path,
                        unit=unit,
                        version=version,
                        target=target,
                        root=target_path,
                        version_root=version_path,
                    )
                )
    return outputs


def _remove_versioned_tree(
    path: pathlib.Path, parent: pathlib.Path, *, label: str
) -> None:
    if path.parent != parent:
        raise OperationError(f"Unsafe {label} cleanup target.")
    sdlc_results._plain_path(path, directory=True, label=label)

    def remove_readonly(
        function: Callable[..., Any], name: str, error: BaseException
    ) -> None:
        target = pathlib.Path(name).absolute()
        if not isinstance(error, PermissionError) or not target.is_relative_to(path):
            raise error
        _resolved, info = sdlc_results._plain_path(
            target, directory=target.is_dir(), label=label
        )
        if info.st_mode & stat.S_IWRITE:
            raise error
        target.chmod(info.st_mode | stat.S_IWRITE)
        function(name)

    shutil.rmtree(path, onexc=remove_readonly)
    if path.exists() or path.is_symlink():
        raise OperationError(f"{label.capitalize()} cleanup did not complete.")


def _prune_completed_artifacts(
    store: pathlib.Path,
    reservations: Mapping[tuple[str, str], Mapping[str, Any]],
) -> None:
    groups: dict[
        tuple[str, str, str, str], list[_CompletedArtifactOutput]
    ] = {}
    protected = set(reservations)
    for output in _completed_artifact_outputs(store):
        group = (
            output.repository,
            output.release_unit,
            output.target,
            output.version_class,
        )
        groups.setdefault(group, []).append(output)
    for entries in groups.values():
        entries.sort(
            key=lambda item: (item.mtime_ns, item.version), reverse=True
        )
        retained = 0
        for output in entries:
            if (output.release_unit, output.version) in protected:
                continue
            retained += 1
            if retained <= VERSIONED_ARTIFACT_RETENTION:
                continue
            if output.root == output.version_root:
                _remove_versioned_tree(
                    output.root, output.version_root.parent, label="artifact output"
                )
            else:
                _remove_versioned_tree(
                    output.root, output.version_root, label="artifact target"
                )
                if not any(output.version_root.iterdir()):
                    output.version_root.rmdir()


def reserve_versioned_artifacts(
    repo_root: pathlib.Path,
    *,
    repository: str,
    release_unit: str,
    version: str,
    required_targets: Sequence[str],
    attempt_id: str,
    pre_test_commit: str,
    recovery_confirmed: bool = False,
) -> PendingArtifactTransaction:
    """Reserve one internal full-version transaction under a short store lock.

    ``pre_test_commit`` is checkpoint B and must already exist. New production
    starts only after the caller has created B and completed build-independent
    checks. Passing ``recovery_confirmed`` can resume only the exact recorded
    attempt; it never adopts, expires, or deletes another owner.
    """

    root = _validated_worktree(pathlib.Path(repo_root))
    repository = _validated_repository(repository)
    release_unit = _require_identifier(
        release_unit, label="release unit", pattern=RELEASE_UNIT_RE
    )
    version, version_class = _version_classification(version)
    targets = _validated_targets(required_targets)
    attempt_id = _require_identifier(
        attempt_id, label="attempt ID", pattern=LOGICAL_ID_RE
    )
    pre_test_commit = _validated_commit(root, pre_test_commit)
    store, lock_path = _artifact_infrastructure(root)
    transaction = PendingArtifactTransaction(
        repo_root=root,
        repository=repository,
        release_unit=release_unit,
        version=version,
        version_class=version_class,
        attempt_id=attempt_id,
        pre_test_commit=pre_test_commit,
        required_targets=targets,
        store=store,
        reservation_path=store / ".reservations" / release_unit / f"{version}.json",
        pending_root=store / ".pending" / attempt_id,
        journal_path=store / ".pending" / attempt_id / "journal.json",
        staging_root=store / ".staging" / attempt_id,
        diagnostic_root=store / ".diagnostics" / release_unit,
        lock_path=lock_path,
    )
    resumed = False
    with _locked_artifact_store(lock_path):
        reservations, journals = _scan_transaction_records(store)
        key = (release_unit, version)
        existing = reservations.get(key)
        final_root = store / release_unit / version
        if final_root.exists() or final_root.is_symlink():
            raise OperationError("Completed artifact version already exists.")
        if _artifact_tag_exists(root, release_unit, version):
            raise OperationError("Immutable artifact version tag already exists.")
        if existing is not None:
            if existing["attemptId"] != attempt_id:
                raise OperationError("Artifact version is reserved by another attempt.")
            if not recovery_confirmed:
                raise RecoveryRequired(
                    "Existing artifact reservation requires explicit recovery."
                )
            journal = journals[attempt_id]
            _validate_transaction_pair(transaction, existing, journal)
            resumed = True
        else:
            if attempt_id in journals:
                raise RecoveryRequired("Attempt ID already owns another reservation.")
            for journal in journals.values():
                if (
                    os.path.normcase(str(journal["worktree"]))
                    == os.path.normcase(str(root))
                    and journal["releaseUnit"] == release_unit
                ):
                    raise RecoveryRequired(
                        "Worktree already has an unfinished attempt for this unit."
                    )
            _prune_completed_artifacts(store, reservations)
            reservation, journal = _new_transaction_records(transaction)
            # Journal first ensures a crash cannot leave an ownerless reservation.
            _write_transaction_record(
                transaction.journal_path,
                journal,
                replace=False,
                label="artifact transaction journal",
            )
            _write_transaction_record(
                transaction.reservation_path,
                reservation,
                replace=False,
                label="artifact reservation",
            )
    for target in targets:
        _build_directory(transaction.target_output(target))
        _build_directory(transaction.target_work(target))
        _build_directory(transaction.pending_git_root(target))
    _build_directory(transaction.pending_root / "receipts")
    if resumed:
        # Re-open after path creation so malformed replacement state cannot be
        # mistaken for a successfully resumed owner.
        with _locked_artifact_store(lock_path):
            reservations, journals = _scan_transaction_records(store)
            _validate_transaction_pair(
                transaction, reservations[(release_unit, version)], journals[attempt_id]
            )
    return transaction


def measure_versioned_artifact(
    transaction: PendingArtifactTransaction,
    target: str,
    descriptor: Mapping[str, Any],
) -> dict[str, Any]:
    """Measure one owned artifact before tests consume its exact bytes."""

    _require_transaction_target(transaction, target)
    measured = measure_build_file(transaction.target_output(target), descriptor)
    if transaction.version not in pathlib.PurePosixPath(measured["path"]).name:
        raise OperationError("Artifact filename must contain the full version.")
    measured["root"] = "store"
    return measured


def _receipt_store_records(receipt: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = [
        *receipt["artifactInputs"],
        *receipt["checkInputs"],
        *(artifact for item in receipt["dependencies"] for artifact in item["artifacts"]),
        *receipt["artifacts"],
        *receipt["supportingFiles"],
    ]
    return [dict(item) for item in records if item["root"] == "store"]


def _receipt_git_inputs(receipt: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in [*receipt["artifactInputs"], *receipt["checkInputs"]]
        if item["root"] == "git"
    ]


def _receipt_git_results(receipt: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in receipt["supportingFiles"]
        if item["root"] == "git"
    ]


def _verify_output_inventory(
    root: pathlib.Path, records: Sequence[Mapping[str, Any]]
) -> None:
    expected = {str(item["path"]) for item in records}
    actual: set[str] = set()
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in directories:
            sdlc_results._plain_path(
                pathlib.Path(parent) / name,
                directory=True,
                label="Pending artifact directory",
            )
        for name in files:
            path = pathlib.Path(parent) / name
            sdlc_results._plain_path(path, label="Pending artifact file")
            actual.add(path.relative_to(root).as_posix())
    if actual != expected:
        raise OperationError("Pending output contains missing or unlisted files.")
    for record in records:
        sdlc_results._verify_bundle_file(root, record)


def _copy_recorded_file(
    source_root: pathlib.Path,
    destination_root: pathlib.Path,
    record: Mapping[str, Any],
) -> pathlib.Path:
    relative = sdlc_results._bundle_relative_path(
        str(record["path"]), label="Pending Git result"
    )
    source, before = sdlc_results._plain_path(
        source_root.joinpath(*relative.parts), label="Pending Git result"
    )
    if not source.is_relative_to(source_root):
        raise OperationError("Pending Git result escapes its worktree.")
    destination = destination_root.joinpath(*relative.parts)
    _build_directory(destination.parent)
    if destination.exists() or destination.is_symlink():
        try:
            sdlc_results._verify_bundle_file(destination_root, record)
        except StepResultError as exc:
            raise RecoveryRequired("Pending Git result conflicts with saved bytes.") from exc
        return destination
    temporary = destination.with_name(f"{destination.name}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise RecoveryRequired("Interrupted Git-result copy requires recovery.")
    digest = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as input_stream, temporary.open("xb") as output_stream:
            if sdlc_results._file_state(os.fstat(input_stream.fileno())) != sdlc_results._file_state(before):
                raise OperationError("Git result changed before retention.")
            while chunk := input_stream.read(
                min(1024 * 1024, int(record["size"]) + 1 - size)
            ):
                digest.update(chunk)
                size += len(chunk)
                output_stream.write(chunk)
            after = os.fstat(input_stream.fileno())
            output_stream.flush()
            os.fsync(output_stream.fileno())
        if (
            sdlc_results._file_state(after) != sdlc_results._file_state(before)
            or sdlc_results._file_state(
                sdlc_results._plain_path(source, label="Pending Git result")[1]
            )
            != sdlc_results._file_state(before)
            or size != record["size"]
            or digest.hexdigest() != record["sha256"]
        ):
            raise OperationError("Git result changed or mismatched during retention.")
        temporary.replace(destination)
    except BaseException:
        # An interrupted copy remains visible and blocks implicit adoption.
        raise
    sdlc_results._verify_bundle_file(destination_root, record)
    return destination


def _persist_exact_bytes(path: pathlib.Path, raw: bytes, *, label: str) -> None:
    _build_directory(path.parent)
    if path.exists() or path.is_symlink():
        checked, _info = sdlc_results._plain_path(path, label=label)
        if checked.read_bytes() != raw:
            raise RecoveryRequired(f"Saved {label} conflicts with prepared bytes.")
        return
    temporary = path.with_name(f"{path.name}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise RecoveryRequired(f"Interrupted {label} write requires recovery.")
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _prepared_result(
    transaction: PendingArtifactTransaction,
    target: str,
    record: Mapping[str, Any],
) -> PreparedBuildReceipt:
    path = transaction.pending_receipt(target)
    raw = sdlc_results._plain_path(path, label="Prepared build receipt")[0].read_bytes()
    if len(raw) != record["size"] or hashlib.sha256(raw).hexdigest() != record["sha256"]:
        raise RecoveryRequired("Prepared receipt bytes do not match the journal.")
    return PreparedBuildReceipt(
        target=target,
        receipt_path=str(record["receiptPath"]),
        pending_receipt_path=path,
        raw=raw,
        sha256=str(record["sha256"]),
        store_files=tuple(deepcopy(record["storeFiles"])),
        git_files=tuple(deepcopy(record["gitFiles"])),
    )


def prepare_versioned_build_receipt(
    transaction: PendingArtifactTransaction,
    target: str,
    receipt: Mapping[str, Any],
) -> PreparedBuildReceipt:
    """Verify qualified bytes and persist one target's exact v3 receipt once.

    Artifact tests must already have consumed the measured output identities.
    This boundary rechecks those retained bytes, preserves Git result evidence,
    and journals the canonical receipt bytes/hash. It creates no commit, artifact
    receipt, final version directory, or tag; those effects belong to 1d.3.
    """

    _require_transaction_target(transaction, target)
    try:
        raw = sdlc_results.encode_new_receipt(receipt)
    except StepResultError as exc:
        raise OperationError(str(exc)) from exc
    identity = receipt["identity"]
    expected_identity = {
        "repository": transaction.repository,
        "releaseUnit": transaction.release_unit,
        "version": transaction.version,
        "target": target,
        "attemptId": transaction.attempt_id,
    }
    if identity != expected_identity:
        raise OperationError("Prepared receipt identity does not match its reservation.")
    if tuple(sorted(receipt["requiredTargets"])) != transaction.required_targets:
        raise OperationError("Prepared receipt required targets do not match its reservation.")
    if receipt["preTestCommit"] != transaction.pre_test_commit:
        raise OperationError("Prepared receipt does not identify checkpoint B.")
    base = f".build/{transaction.release_unit}/{transaction.version}"
    expected_receipt_path = (
        f"{base}/receipt.json"
        if len(transaction.required_targets) == 1
        else f"{base}/{target}/receipt.json"
    )
    if receipt["receiptPath"] != expected_receipt_path:
        raise OperationError("Prepared receipt uses the wrong target layout.")
    if _git_text(
        transaction.repo_root, ["rev-parse", "HEAD"], label="worktree HEAD"
    ) != transaction.pre_test_commit:
        raise OperationError("Worktree HEAD moved after checkpoint B.")
    for artifact in receipt["artifacts"]:
        if transaction.version not in pathlib.PurePosixPath(artifact["path"]).name:
            raise OperationError("Artifact filename must contain the full version.")

    with _locked_artifact_store(transaction.lock_path):
        reservations, journals = _scan_transaction_records(transaction.store)
        reservation = reservations.get(
            (transaction.release_unit, transaction.version)
        )
        journal = journals.get(transaction.attempt_id)
        if reservation is None or journal is None:
            raise RecoveryRequired("Artifact transaction ownership disappeared.")
        _validate_transaction_pair(transaction, reservation, journal)
        prepared = journal["preparedReceipts"].get(target)
        if prepared is not None:
            if prepared["sha256"] != hashlib.sha256(raw).hexdigest():
                raise RecoveryRequired("Prepared receipt conflicts with saved receipt.")
            return _prepared_result(transaction, target, prepared)

    git_inputs = _receipt_git_inputs(receipt)
    for record in git_inputs:
        sdlc_results._read_git_record(
            transaction.repo_root, transaction.pre_test_commit, record
        )
        sdlc_results._verify_bundle_file(transaction.repo_root, record)

    store_records = _receipt_store_records(receipt)
    output_root = transaction.target_output(target)
    _verify_output_inventory(output_root, store_records)
    git_records = _receipt_git_results(receipt)
    pending_git_root = transaction.pending_git_root(target)
    for record in git_records:
        _copy_recorded_file(transaction.repo_root, pending_git_root, record)

    digest = hashlib.sha256(raw).hexdigest()
    stored_identities = [
        {
            "root": "store",
            "path": item["path"],
            "size": item["size"],
            "sha256": item["sha256"],
        }
        for item in sorted(store_records, key=lambda value: value["path"])
    ]
    git_identities = [
        {
            "root": "git",
            "path": item["path"],
            "size": item["size"],
            "sha256": item["sha256"],
            "pendingPath": _store_relative(
                transaction.store,
                pending_git_root.joinpath(
                    *sdlc_results._bundle_relative_path(item["path"]).parts
                ),
            ),
        }
        for item in sorted(git_records, key=lambda value: value["path"])
    ]
    prepared_record = {
        "receiptPath": receipt["receiptPath"],
        "pendingReceiptPath": _store_relative(
            transaction.store, transaction.pending_receipt(target)
        ),
        "size": len(raw),
        "sha256": digest,
        "outputPath": _store_relative(transaction.store, output_root),
        "storeFiles": stored_identities,
        "gitFiles": git_identities,
    }
    with _locked_artifact_store(transaction.lock_path):
        reservations, journals = _scan_transaction_records(transaction.store)
        reservation = reservations.get(
            (transaction.release_unit, transaction.version)
        )
        journal = journals.get(transaction.attempt_id)
        if reservation is None or journal is None:
            raise RecoveryRequired("Artifact transaction ownership disappeared.")
        _validate_transaction_pair(transaction, reservation, journal)
        existing = journal["preparedReceipts"].get(target)
        if existing is not None:
            if existing != prepared_record:
                raise RecoveryRequired("Prepared receipt journal entry conflicts.")
            return _prepared_result(transaction, target, existing)
        _persist_exact_bytes(
            transaction.pending_receipt(target), raw, label="prepared build receipt"
        )
        updated = deepcopy(journal)
        updated["preparedReceipts"][target] = prepared_record
        updated["phase"] = (
            "receipts_prepared"
            if len(updated["preparedReceipts"])
            == len(transaction.required_targets)
            else "receipt_prepared"
        )
        _write_transaction_record(
            transaction.journal_path,
            updated,
            replace=True,
            label="artifact transaction journal",
        )
    return PreparedBuildReceipt(
        target=target,
        receipt_path=receipt["receiptPath"],
        pending_receipt_path=transaction.pending_receipt(target),
        raw=raw,
        sha256=digest,
        store_files=tuple(deepcopy(stored_identities)),
        git_files=tuple(deepcopy(git_identities)),
    )


def write_versioned_failure_diagnostic(
    transaction: PendingArtifactTransaction,
    target: str,
    error: str,
) -> pathlib.Path:
    """Atomically replace the one bounded failure report for a storage group."""

    _require_transaction_target(transaction, target)
    destination = (
        transaction.diagnostic_root
        / target
        / f"{transaction.version_class}.json"
    )
    value = {
        "schema": "ceratops-artifact-failure.v1",
        "repository": transaction.repository,
        "releaseUnit": transaction.release_unit,
        "version": transaction.version,
        "versionClass": transaction.version_class,
        "target": target,
        "attemptId": transaction.attempt_id,
        "error": str(error)[:4096],
    }
    with _locked_artifact_store(transaction.lock_path):
        _build_directory(destination.parent)
        temporary = destination.with_name(f"{destination.name}.tmp")
        if temporary.exists() or temporary.is_symlink():
            sdlc_results._plain_path(temporary, label="Artifact diagnostic temp")
            temporary.unlink()
        _write_transaction_record(
            destination,
            value,
            replace=destination.exists() or destination.is_symlink(),
            label="artifact failure diagnostic",
        )
    return destination
