"""Fixed installation layout, atomic selection, and kernel-released locks.

Inactive successful installations remain immutable for processes still using
them. Failed candidates are removed by their creating transaction. No active
directory is renamed, overwritten, or deleted during an installation.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import stat
import sys
import uuid
from pathlib import Path
from typing import Any

from . import TOOL_ID
from .contracts import DeploymentError, token

INSTALL_ROOT = Path("C:/AI-Agents-Tools")


class Layout:
    """The internal root seam exists for isolated tests, never public inputs."""

    def __init__(self, tool_id: str = TOOL_ID) -> None:
        self.root = INSTALL_ROOT / token(tool_id)

    def path(self, *parts: str) -> Path:
        target = self.root.joinpath(*parts)
        if not target.is_relative_to(self.root) or any(
            p in (".", "..") or ":" in p or "\\" in p or "/" in p
            for p in parts
        ):
            raise DeploymentError("path escapes installation root")
        # Resolve no links, including Windows junctions and ancestor reparse points.
        for parent in (target, *target.parents):
            if parent.exists() or parent.is_symlink():
                info = parent.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise DeploymentError("links and reparse points are not allowed")
        if target.resolve() != target.absolute():
            raise DeploymentError("path resolution escaped installation root")
        return target

    def directory(self, *parts: str) -> Path:
        target = self.path(*parts)
        target.mkdir(parents=True, exist_ok=True)
        return self.path(*parts)

    def atomic_json(self, target: Path, value: Any) -> None:
        relative = target.relative_to(self.root)
        self.path(*relative.parts)
        temporary = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(value, stream, sort_keys=True, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            self.path(*relative.parts)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def _remove_tree(self, path: Path) -> None:
        self.path(*path.relative_to(self.root).parts)
        # Refuse linked descendants before deleting transaction-owned files.
        for current, directories, files in os.walk(path, followlinks=False):
            for name in directories + files:
                self.path(*(Path(current) / name).relative_to(self.root).parts)
        shutil.rmtree(path)

    def remove_candidate(self, path: Path) -> None:
        parts = path.relative_to(self.root).parts
        if len(parts) != 3 or parts[0] != "versions":
            raise DeploymentError("invalid candidate cleanup target")
        self._remove_tree(path)
        if not any(path.parent.iterdir()):
            path.parent.rmdir()

    def remove_scratch(self, path: Path) -> None:
        """Remove this transaction's scratch before selecting its installation."""
        parts = path.relative_to(self.root).parts
        if len(parts) != 4 or parts[0] != "versions" or parts[-1] != "tmp":
            raise DeploymentError("invalid scratch cleanup target")
        self._remove_tree(path)

    @contextlib.contextmanager
    def lock(self, name: str):
        self.directory("locks")
        path = self.path("locks", name + ".lock")
        with path.open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            try:
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise DeploymentError("another deployment owns this lock; retry after it finishes") from exc
            try:
                yield
            finally:
                stream.seek(0)
                if sys.platform == "win32":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
