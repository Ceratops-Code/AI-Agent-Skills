#!/usr/bin/env python3
"""Preserve pre-edit line endings around Codex ``apply_patch`` calls.

Input contract: Codex invokes this command as ``pre`` for ``PreToolUse`` and
``post`` for ``PostToolUse``, passing one hook JSON object on stdin. The object
must identify ``apply_patch`` and include ``session_id``, ``tool_use_id``,
``cwd``, and ``tool_input.command``.

Safety boundaries: only paths named by Update/Add/Delete patch headers are
parsed, and only existing regular, non-symlink text files named by Update
headers are recorded. Binary, undecodable, no-EOL, and mixed-EOL inputs are
ignored. Post mode changes only logical newline sequences, while restoring the
recorded encoding and BOM and preserving the edited text and terminal-newline
presence.

Temporary-state ownership: manifests contain metadata but never file contents.
They live in an owned system-temporary subdirectory, are isolated by a hash of
``session_id`` and ``tool_use_id``, are removed by matching post execution, and
are garbage-collected by pre execution after 24 hours.
"""

from __future__ import annotations

import codecs
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "codex-apply-patch-eol.v1"
MANIFEST_DIRECTORY = "codex-preserve-eol-apply-patch"
MANIFEST_PREFIX = "manifest-"
STALE_AFTER_SECONDS = 24 * 60 * 60
PATCH_HEADER = re.compile(r"^\*\*\* (Update|Add|Delete) File:(.*)$")
EOL_BYTES = {"crlf": "\r\n", "lf": "\n", "cr": "\r"}
BOM_ENCODINGS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)
VALID_ENCODING_BOMS = {
    "utf-8": {b"", codecs.BOM_UTF8},
    "utf-16-le": {codecs.BOM_UTF16_LE},
    "utf-16-be": {codecs.BOM_UTF16_BE},
    "utf-32-le": {codecs.BOM_UTF32_LE},
    "utf-32-be": {codecs.BOM_UTF32_BE},
}


class HookError(RuntimeError):
    """One concise, actionable hook-contract or filesystem failure."""


def _required_text(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise HookError(f"hook input needs nonempty {key}")
    return result


def _load_hook_input(mode: str) -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HookError(f"hook stdin is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise HookError("hook stdin must be a JSON object")

    expected_event = "PreToolUse" if mode == "pre" else "PostToolUse"
    if value.get("hook_event_name") != expected_event:
        raise HookError(f"{mode} mode requires {expected_event} input")
    if value.get("tool_name") != "apply_patch":
        raise HookError(f"{mode} mode accepts only apply_patch input")

    _required_text(value, "session_id")
    _required_text(value, "tool_use_id")
    _required_text(value, "cwd")
    tool_input = value.get("tool_input")
    if not isinstance(tool_input, dict):
        raise HookError("hook input needs a tool_input object")
    if not isinstance(tool_input.get("command"), str):
        raise HookError("apply_patch tool_input.command must be a string")
    return value


def _manifest_root() -> Path:
    root = Path(tempfile.gettempdir()) / MANIFEST_DIRECTORY
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise HookError(f"cannot create manifest directory: {exc}") from exc
    if root.is_symlink() or not root.is_dir():
        raise HookError(f"manifest directory is unsafe: {root}")
    return root


def _manifest_path(root: Path, session_id: str, tool_use_id: str) -> Path:
    digest = hashlib.sha256()
    for value in (session_id, tool_use_id):
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return root / f"{MANIFEST_PREFIX}{digest.hexdigest()}.json"


def _clean_stale_manifests(root: Path) -> None:
    cutoff = time.time() - STALE_AFTER_SECONDS
    try:
        candidates = list(root.glob(f"{MANIFEST_PREFIX}*.json"))
    except OSError as exc:
        raise HookError(f"cannot enumerate stale manifests: {exc}") from exc
    for candidate in candidates:
        try:
            if candidate.stat(follow_symlinks=False).st_mtime < cutoff:
                candidate.unlink(missing_ok=True)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise HookError(f"cannot remove stale manifest {candidate.name}: {exc}") from exc


def _looks_binary(text: str) -> bool:
    if "\x00" in text:
        return True
    controls = sum(
        1 for character in text
        if ord(character) < 32 and character not in "\t\n\r\f\b"
    )
    return controls > max(1, len(text) // 100)


def _decode_text(data: bytes) -> tuple[str, str, bytes] | None:
    for bom, encoding in BOM_ENCODINGS:
        if data.startswith(bom):
            try:
                text = data[len(bom):].decode(encoding, errors="strict")
            except UnicodeDecodeError:
                return None
            return None if _looks_binary(text) else (text, encoding, bom)
    if b"\x00" in data:
        return None
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    return None if _looks_binary(text) else (text, "utf-8", b"")


def _uniform_eol(text: str) -> str:
    crlf_count = text.count("\r\n")
    without_crlf = text.replace("\r\n", "")
    lf_count = without_crlf.count("\n")
    cr_count = without_crlf.count("\r")
    styles = [
        name for name, count in (
            ("crlf", crlf_count),
            ("lf", lf_count),
            ("cr", cr_count),
        )
        if count
    ]
    if not styles:
        return "none"
    if len(styles) > 1:
        return "mixed"
    return styles[0]


def _absolute_patch_path(cwd: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = cwd / candidate
    return Path(os.path.abspath(os.path.normpath(str(candidate))))


def _updated_paths(command: str, cwd: Path) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for line in command.splitlines():
        match = PATCH_HEADER.fullmatch(line)
        if match is None:
            continue
        action, raw_path = match.groups()
        raw_path = raw_path.strip()
        if not raw_path:
            raise HookError(f"{action} File header has an empty path")
        if action != "Update":
            continue
        path = _absolute_patch_path(cwd, raw_path)
        identity = os.path.normcase(str(path))
        if identity not in seen:
            seen.add(identity)
            result.append(path)
    return result


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    encoded = (json.dumps(manifest, separators=(",", ":")) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise HookError(f"manifest collision for tool call: {path.name}") from exc
    except OSError as exc:
        raise HookError(f"cannot create manifest: {exc}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise HookError(f"cannot write manifest: {exc}") from exc


def _run_pre(value: dict[str, Any]) -> None:
    root = _manifest_root()
    _clean_stale_manifests(root)
    cwd = Path(os.path.abspath(_required_text(value, "cwd")))
    if not cwd.is_dir():
        raise HookError(f"hook cwd does not exist: {cwd}")

    tool_input = value["tool_input"]
    assert isinstance(tool_input, dict)
    command = tool_input["command"]
    assert isinstance(command, str)
    files: list[dict[str, str]] = []
    for path in _updated_paths(command, cwd):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            decoded = _decode_text(path.read_bytes())
        except OSError as exc:
            raise HookError(f"cannot inspect updated file {path}: {exc}") from exc
        if decoded is None:
            continue
        text, encoding, bom = decoded
        eol = _uniform_eol(text)
        if eol not in EOL_BYTES:
            continue
        files.append(
            {
                "path": str(path),
                "eol": eol,
                "encoding": encoding,
                "bom": bom.hex(),
            }
        )

    session_id = _required_text(value, "session_id")
    tool_use_id = _required_text(value, "tool_use_id")
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "session_id": session_id,
        "tool_use_id": tool_use_id,
        "cwd": str(cwd),
        "files": files,
    }
    _write_manifest(_manifest_path(root, session_id, tool_use_id), manifest)


def _load_manifest(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HookError(f"matching pre-hook manifest is missing: {path.name}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HookError(f"matching manifest is unreadable: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise HookError("matching manifest has an invalid schema")
    for key in ("session_id", "tool_use_id"):
        if manifest.get(key) != _required_text(value, key):
            raise HookError(f"matching manifest has the wrong {key}")
    manifest_cwd = manifest.get("cwd")
    input_cwd = os.path.abspath(_required_text(value, "cwd"))
    if (
        not isinstance(manifest_cwd, str)
        or os.path.normcase(os.path.abspath(manifest_cwd))
        != os.path.normcase(input_cwd)
    ):
        raise HookError("matching manifest has the wrong cwd")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise HookError("matching manifest has an invalid files list")
    return manifest


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _restore_eol(text: str, eol: str) -> str:
    normalized = _normalize_newlines(text)
    restored = normalized.replace("\n", EOL_BYTES[eol])
    if _normalize_newlines(restored) != normalized:
        raise HookError("newline restoration changed logical text")
    if text.endswith(("\r\n", "\r", "\n")) != restored.endswith(
        ("\r\n", "\r", "\n")
    ):
        raise HookError("newline restoration changed final-newline presence")
    return restored


def _safe_replace(path: Path, content: bytes) -> None:
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.eol-",
            dir=path.parent,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        shutil.copystat(path, temporary_path, follow_symlinks=False)
        os.replace(temporary_path, path)
        temporary_path = None
    except OSError as exc:
        raise HookError(f"cannot safely restore {path}: {exc}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _restore_file(record: Any) -> None:
    if not isinstance(record, dict):
        raise HookError("matching manifest contains an invalid file record")
    expected_keys = {"path", "eol", "encoding", "bom"}
    if set(record) != expected_keys:
        raise HookError("matching manifest file record has invalid fields")
    path_value = record.get("path")
    eol = record.get("eol")
    encoding = record.get("encoding")
    bom_hex = record.get("bom")
    if not isinstance(path_value, str) or not Path(path_value).is_absolute():
        raise HookError("matching manifest contains an invalid file path")
    if eol not in EOL_BYTES or not isinstance(encoding, str) or not isinstance(bom_hex, str):
        raise HookError(f"matching manifest metadata is invalid for {path_value}")
    try:
        bom = bytes.fromhex(bom_hex)
    except ValueError as exc:
        raise HookError(f"matching manifest BOM is invalid for {path_value}") from exc
    if encoding not in VALID_ENCODING_BOMS or bom not in VALID_ENCODING_BOMS[encoding]:
        raise HookError(f"matching manifest encoding or BOM is invalid for {path_value}")

    path = Path(path_value)
    if path.is_symlink() or not path.is_file():
        return
    try:
        current_bytes = path.read_bytes()
    except OSError as exc:
        raise HookError(f"cannot read updated file {path}: {exc}") from exc
    decoded = _decode_text(current_bytes)
    if decoded is None:
        return
    current_text, _, _ = decoded
    restored_text = _restore_eol(current_text, eol)
    try:
        restored_bytes = bom + restored_text.encode(encoding, errors="strict")
    except (LookupError, UnicodeEncodeError) as exc:
        raise HookError(f"cannot restore recorded encoding for {path}: {exc}") from exc
    if restored_bytes != current_bytes:
        _safe_replace(path, restored_bytes)


def _run_post(value: dict[str, Any]) -> None:
    root = _manifest_root()
    session_id = _required_text(value, "session_id")
    tool_use_id = _required_text(value, "tool_use_id")
    path = _manifest_path(root, session_id, tool_use_id)
    try:
        manifest = _load_manifest(path, value)
        for record in manifest["files"]:
            _restore_file(record)
    finally:
        path.unlink(missing_ok=True)


def _parse_mode() -> str:
    if len(sys.argv) != 2 or sys.argv[1] not in {"pre", "post"}:
        raise HookError("usage: preserve-eol-for-apply-patch-tool.py pre|post")
    return sys.argv[1]


def main() -> int:
    try:
        mode = _parse_mode()
        value = _load_hook_input(mode)
        if mode == "pre":
            _run_pre(value)
        else:
            _run_post(value)
    except (HookError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
