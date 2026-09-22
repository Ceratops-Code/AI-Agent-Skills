"""Capture SDLC results and explicitly verify saved release-unit build receipts.

The read-only CLI checks a receipt against an independently supplied release
selection and the files under its bundle root. It does not build, run tests,
install, establish provenance, or freeze files against later changes. Ordinary
command-output capture remains independent of artifact filesystem access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import ntpath
import os
import pathlib
import stat
import sys
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any

import jsonschema

STEP_RESULT_BYTES = 65536
STEP_RESULT_DEPTH = 64
BUILD_RECEIPT_SCHEMA = "ceratops-build-result.v2"
BUILD_SELECTION_FIELDS = (
    "repository", "sourceCommit", "releaseUnit", "channel", "version", "target",
)
OPERATION_RESULT_SCHEMA = (
    pathlib.Path(__file__).resolve().parents[1]
    / "references"
    / "schemas"
    / "operation-result.v1.schema.json"
)


class StepResultError(ValueError):
    """A declared operation result is missing or violates its contract."""


def _unique_result_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous JSON members rather than silently replace receipt values."""

    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate result member.")
        value[key] = item
    return value


@lru_cache(maxsize=1)
def _operation_result_validator() -> jsonschema.Draft202012Validator:
    """Load the installed canonical operation-result schema once per process."""

    try:
        schema = json.loads(OPERATION_RESULT_SCHEMA.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        jsonschema.SchemaError,
    ) as exc:
        raise StepResultError(f"Operation-result schema is invalid: {exc}") from exc
    return jsonschema.Draft202012Validator(schema)


def _raise_required(message: str, expected_schema: str | None) -> None:
    if expected_schema is not None:
        raise StepResultError(message)


def capture_step_result(
    stdout: str,
    *,
    require_identity: bool = True,
    expected_schema: str | None = None,
    expected_stage: str | None = None,
) -> dict[str, Any]:
    """Retain a whole JSON receipt without forwarding logs or interpreting success.

    Successful output requires nonempty schema/status strings; a failed command
    may preserve any complete JSON object from either stream. Parsing never
    scans log fragments. Oversized output gets a
    content-free omission marker; malformed and ordinary output stay suppressed.
    Container depth is bounded so downstream checkpoint readers can decode it.
    When an SDLC action declares ``result-schema``, malformed or absent output
    raises ``StepResultError``. The caller must retain command completion and
    must not replay a side effect merely to recover its result.
    """

    if len(stdout.encode("utf-8")) > STEP_RESULT_BYTES:
        _raise_required("Required operation result exceeds the stdout limit.", expected_schema)
        return {"result_omitted": "stdout_limit"}
    try:
        value = json.loads(stdout, object_pairs_hook=_unique_result_object)
        if not isinstance(value, dict) or (require_identity and not all(
            isinstance(value.get(key), str) and value[key].strip()
            for key in ("schema", "status")
        )):
            _raise_required("Required operation result is not one complete JSON object.", expected_schema)
            return {}
        pending: list[tuple[dict[str, Any] | list[Any], int]] = [(value, 1)]
        while pending:
            container, depth = pending.pop()
            if depth > STEP_RESULT_DEPTH:
                _raise_required("Required operation result exceeds the nesting limit.", expected_schema)
                return {}
            children = container.values() if isinstance(container, dict) else container
            pending.extend(
                (child, depth + 1)
                for child in children
                if isinstance(child, (dict, list))
            )
        # Reject non-finite numbers, including exponent overflow, at every depth.
        json.dumps(value, allow_nan=False)
    except StepResultError:
        raise
    except (ValueError, RecursionError) as exc:
        _raise_required(f"Required operation result is invalid JSON: {exc}", expected_schema)
        return {}
    if expected_schema is not None:
        errors = list(_operation_result_validator().iter_errors(value))
        if errors:
            error = jsonschema.exceptions.best_match(errors) or errors[0]
            location = ".".join(str(part) for part in error.absolute_path)
            suffix = f" at {location}" if location else ""
            raise StepResultError(
                f"Required operation result violates the canonical schema{suffix}: "
                f"{error.message}"[:1024]
            )
        if value.get("schema") != expected_schema:
            raise StepResultError(
                "Required operation result schema differs from the SDLC declaration."
            )
        if expected_stage is not None and value.get("stage") != expected_stage:
            raise StepResultError(
                "Required repository-stage result differs from the selected SDLC stage."
            )
        if value.get("status") != "passed":
            raise StepResultError(
                "A successful SDLC command must emit a passed terminal result."
            )
    return {"result": value}


def _plain_path(path: pathlib.Path, *, directory: bool = False) -> tuple[pathlib.Path, os.stat_result]:
    """Reject link/reparse traversal and non-regular payloads before opening them.

    Check ancestors too: checking just the final filename would allow a directory
    junction or symlink to redirect a relative bundle path outside the bundle.
    Hard-linked payloads are rejected so separate paths cannot alias one file.
    """

    path = path.absolute()
    for current in (*reversed(path.parents), path):
        info = current.lstat()
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise StepResultError(f"Build receipt path traverses a link: {current}")
        if current != path or directory:
            if not stat.S_ISDIR(info.st_mode):
                raise StepResultError(f"Build receipt directory is not a directory: {current}")
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise StepResultError(f"Build receipt file must be regular and unlinked: {current}")
    return path.resolve(strict=True), info


def _file_state(info: os.stat_result) -> tuple[int, ...]:
    """Bind a descriptor to file identity, byte count and content modification time.

    Windows can change ctime when resolving/opening an unchanged file, so it is
    not content-change evidence. Payload bytes are also checked by size and hash.
    """

    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _read_build_receipt(path: pathlib.Path) -> dict[str, Any]:
    """Read one bounded, unambiguous JSON object without interpreting its status."""

    path, before = _plain_path(path)
    if before.st_size > STEP_RESULT_BYTES:
        raise StepResultError("Build receipt exceeds the JSON size limit.")
    with path.open("rb") as stream:
        if _file_state(os.fstat(stream.fileno())) != _file_state(before):
            raise StepResultError("Build receipt changed before reading.")
        raw = stream.read(STEP_RESULT_BYTES + 1)
        after = os.fstat(stream.fileno())
    if (_file_state(after) != _file_state(before)
            or _file_state(_plain_path(path)[1]) != _file_state(before)):
        raise StepResultError("Build receipt changed while reading.")
    captured = capture_step_result(raw.decode("utf-8"))
    value = captured.get("result")
    if not isinstance(value, dict):
        raise StepResultError("Build receipt must be one bounded JSON result object.")
    if value.get("schema") != BUILD_RECEIPT_SCHEMA:
        raise StepResultError(f"Build receipt schema must be {BUILD_RECEIPT_SCHEMA}.")
    errors = list(_operation_result_validator().iter_errors(value))
    if errors:
        error = jsonschema.exceptions.best_match(errors) or errors[0]
        location = ".".join(str(part) for part in error.absolute_path)
        raise StepResultError(
            f"Build receipt violates its schema at {location or '<root>'}: "
            f"{error.message}"[:1024]
        )
    return value


def _bundle_relative_path(value: str) -> pathlib.PurePosixPath:
    """Require one portable spelling; reject Windows aliases even on POSIX."""

    parts = value.split("/")
    if (not value or any(part in {"", ".", ".."} for part in parts)
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or "\\" in value or ":" in value or ntpath.isreserved(value)
            or any(part.endswith((" ", ".")) for part in parts)):
        raise StepResultError(f"Unsafe build receipt path: {value!r}")
    return pathlib.PurePosixPath(value)


def _build_files(receipt: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate the entire inventory and evidence references before payload reads."""

    files: dict[str, dict[str, Any]] = {}
    spellings: set[str] = set()
    artifacts: dict[str, dict[str, Any]] = {}
    supporting: dict[str, dict[str, Any]] = {}

    def add(record: dict[str, Any], destination: dict[str, dict[str, Any]]) -> None:
        path = record["path"]
        _bundle_relative_path(path)
        if path.casefold() in spellings:
            raise StepResultError(f"Duplicate build receipt path: {path}")
        spellings.add(path.casefold())
        files[path] = destination[path] = record

    for artifact in receipt["artifacts"]:
        add(artifact, artifacts)
    owner = receipt["identity"]
    dependencies: set[tuple[str, str, str]] = set()
    for dependency in receipt["dependencies"]:
        identity = dependency["identity"]
        key = (identity["repository"], identity["releaseUnit"], identity["target"])
        if key in dependencies:
            raise StepResultError("Duplicate or competing build dependency selection.")
        if key[:2] == (owner["repository"], owner["releaseUnit"]):
            raise StepResultError("A build receipt cannot depend on its own release unit.")
        dependencies.add(key)
        for artifact in dependency["artifacts"]:
            add(artifact, artifacts)
    for support in receipt["supportingFiles"]:
        add(support, supporting)

    test_ids: set[str] = set()
    for test in receipt["tests"]:
        if test["id"] in test_ids:
            raise StepResultError(f"Duplicate build test ID: {test['id']}")
        test_ids.add(test["id"])
        tested: set[str] = set()
        for reference in test["artifacts"]:
            path = reference["path"]
            artifact = artifacts.get(path)
            if path in tested or artifact is None or reference["sha256"] != artifact["sha256"]:
                raise StepResultError(f"Build test does not identify one exact artifact: {path}")
            tested.add(path)
        evidence = test["evidence"]
        if evidence is not None:
            file = supporting.get(evidence["path"])
            if (file is None or file["type"] != "test-evidence"
                    or file["sha256"] != evidence["sha256"]):
                raise StepResultError("Build test evidence must identify a declared test-evidence file.")
    return list(files.values())


def _verify_bundle_file(root: pathlib.Path, record: Mapping[str, Any]) -> None:
    """Hash a bounded regular file, detecting replacement or modification on read."""

    path, before = _plain_path(root.joinpath(*_bundle_relative_path(record["path"]).parts))
    if not path.is_relative_to(root):
        raise StepResultError(f"Build receipt path escapes the bundle: {record['path']}")
    if before.st_size != record["size"]:
        raise StepResultError(f"Build receipt size mismatch: {record['path']}")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        if _file_state(os.fstat(stream.fileno())) != _file_state(before):
            raise StepResultError(f"Build artifact changed before reading: {record['path']}")
        # At most the declared bytes plus one are read, even if another process
        # grows the file continuously. A directory/FIFO/device never reaches here.
        while chunk := stream.read(min(1024 * 1024, record["size"] + 1 - size)):
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(stream.fileno())
    if (_file_state(after) != _file_state(before)
            or _file_state(_plain_path(path)[1]) != _file_state(before)):
        raise StepResultError(f"Build artifact changed while reading: {record['path']}")
    if size != record["size"]:
        raise StepResultError(f"Build receipt size mismatch: {record['path']}")
    if digest.hexdigest() != record["sha256"]:
        raise StepResultError(f"Build receipt SHA-256 mismatch: {record['path']}")


def verify_release_unit_build(
    receipt_path: pathlib.Path,
    bundle_root: pathlib.Path,
    *,
    expected: Mapping[str, str],
) -> dict[str, Any]:
    """Verify a saved v2 build receipt and return its unchanged recorded statuses.

    The expected selection must independently supply repository, sourceCommit,
    releaseUnit, channel, version and target. Every artifact, dependency artifact
    and supporting file is checked under bundle_root; test references must match
    that checked inventory. A valid inventory can have absent, skipped, blocked
    or failed tests. This does not decide test sufficiency or deployment eligibility.

    No command is executed and no file is written. Verification describes the
    bytes observed during this call, not their provenance or future immutability.
    The caller must reverify before later consumption or use an immutable store.
    """

    if (not isinstance(expected, Mapping)
            or set(expected) != set(BUILD_SELECTION_FIELDS)
            or not all(isinstance(value, str) and value.strip() for value in expected.values())):
        raise StepResultError("Expected build selection must supply all six identity fields.")
    try:
        receipt = _read_build_receipt(pathlib.Path(receipt_path))
        for field in BUILD_SELECTION_FIELDS:
            if receipt["identity"][field] != expected[field]:
                raise StepResultError(f"Build receipt identity mismatch: {field}")
        files = _build_files(receipt)
        root, _ = _plain_path(pathlib.Path(bundle_root), directory=True)
        for record in files:
            _verify_bundle_file(root, record)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, StepResultError):
            raise
        raise StepResultError(f"Cannot verify build receipt: {exc}"[:1024]) from exc
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    """Expose only explicit read-only receipt verification; success prints OK."""

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser(
        "verify-release-unit-build",
        help="Check identity and bytes, not test success or deployment permission.",
    )
    verify.add_argument("--receipt", type=pathlib.Path, required=True)
    verify.add_argument("--bundle-root", type=pathlib.Path, required=True)
    for field, option in (
        ("repository", "--repository"), ("sourceCommit", "--source-commit"),
        ("releaseUnit", "--release-unit"), ("channel", "--channel"),
        ("version", "--version"), ("target", "--target"),
    ):
        verify.add_argument(option, dest=field, required=True)
    args = parser.parse_args(argv)
    try:
        verify_release_unit_build(
            args.receipt, args.bundle_root,
            expected={field: getattr(args, field) for field in BUILD_SELECTION_FIELDS},
        )
    except StepResultError as exc:
        print(" ".join(str(exc).split())[:1024], file=sys.stderr)
        return 2
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
