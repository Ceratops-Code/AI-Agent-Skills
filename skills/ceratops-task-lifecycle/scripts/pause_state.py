#!/usr/bin/env python3
"""Capture or verify a compact checkpoint for local Git worktrees.

The token covers HEAD, index entries, tracked worktree diffs, Git-visible
status, and untracked file contents. Ignored files, external services, and
non-Git state are intentionally outside the contract. Submodules are rejected
because a compact parent-worktree fingerprint cannot prove their dirty content
is unchanged.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import pathlib
import stat
import subprocess
import sys
from typing import Iterable


SCHEMA_VERSION = 1


class SnapshotError(RuntimeError):
    """Report a state that cannot be represented by this checkpoint contract."""


def _git(root: pathlib.Path, *args: str, allow_failure: bool = False) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode and not allow_failure:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise SnapshotError(message or f"git {' '.join(args)} failed")
    return result.stdout


def _repo_root(candidate: str) -> pathlib.Path:
    result = subprocess.run(
        ["git", "-C", candidate, "rev-parse", "--show-toplevel"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise SnapshotError(f"not a Git worktree: {candidate}")
    return pathlib.Path(result.stdout.decode("utf-8", "replace").strip()).resolve()


def _update(hasher: hashlib._Hash, label: bytes, payload: bytes) -> None:
    hasher.update(label)
    hasher.update(b"\0")
    hasher.update(len(payload).to_bytes(8, "big"))
    hasher.update(payload)


def _hash_untracked(
    hasher: hashlib._Hash, root: pathlib.Path, relative_paths: Iterable[bytes]
) -> None:
    for raw_path in sorted(relative_paths):
        if not raw_path:
            continue
        relative = pathlib.PurePosixPath(os.fsdecode(raw_path))
        path = root.joinpath(*relative.parts)
        _update(hasher, b"untracked-path", raw_path)
        try:
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                _update(hasher, b"untracked-link", os.fsencode(os.readlink(path)))
            elif stat.S_ISREG(mode):
                file_hash = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        file_hash.update(chunk)
                _update(hasher, b"untracked-file", file_hash.digest())
            else:
                _update(hasher, b"untracked-other", str(mode).encode("ascii"))
        except OSError as exc:
            raise SnapshotError(f"untracked path changed during capture: {relative}") from exc


def _fingerprint(root: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    head = _git(root, "rev-parse", "--verify", "HEAD", allow_failure=True)
    index = _git(root, "ls-files", "--stage", "-z")
    if any(entry.startswith(b"160000 ") for entry in index.split(b"\0") if entry):
        raise SnapshotError(f"submodules are unsupported: {root}")
    status_bytes = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    worktree_diff = _git(root, "diff", "--no-ext-diff", "--binary", "--")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")

    _update(hasher, b"root", os.fsencode(str(root)))
    _update(hasher, b"head", head or b"UNBORN")
    _update(hasher, b"index", index)
    _update(hasher, b"status", status_bytes)
    _update(hasher, b"worktree-diff", worktree_diff)
    _hash_untracked(hasher, root, untracked.split(b"\0"))
    return hasher.hexdigest()


def _encode(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(token: str) -> dict[str, object]:
    padding = "=" * (-len(token) % 4)
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(token + padding).decode("utf-8")
        )
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError("invalid state token") from exc
    if payload.get("schema") != SCHEMA_VERSION:
        raise SnapshotError("unsupported state-token schema")
    return payload


def capture(repo_args: list[str]) -> str:
    roots = sorted({_repo_root(value) for value in repo_args or [os.getcwd()]})
    snapshots = [
        {"root": str(root), "fingerprint": _fingerprint(root)} for root in roots
    ]
    return "TOKEN " + _encode({"schema": SCHEMA_VERSION, "snapshots": snapshots})


def verify(token: str) -> str:
    payload = _decode(token)
    snapshots = payload.get("snapshots")
    if not isinstance(snapshots, list) or not snapshots:
        raise SnapshotError("state token has no snapshots")
    changed: list[str] = []
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            raise SnapshotError("invalid snapshot entry")
        root_value = snapshot.get("root")
        expected = snapshot.get("fingerprint")
        if not isinstance(root_value, str) or not isinstance(expected, str):
            raise SnapshotError("invalid snapshot fields")
        root = _repo_root(root_value)
        if _fingerprint(root) != expected:
            changed.append(str(root))
    return "UNCHANGED" if not changed else "CHANGED " + " | ".join(changed)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture or verify a compact local Git-worktree state token."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--repo", action="append", default=[])
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("token")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output = capture(args.repo) if args.action == "capture" else verify(args.token)
    except SnapshotError as exc:
        print(f"UNAVAILABLE {exc}")
        return 0
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
