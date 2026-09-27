"""Stable bootstrap ABI: select a complete tool environment on each launch.

The same standalone file is installed below every tool's ``bin`` directory.
It derives that tool's identity from the parent directory, validates the
selected receipt, and holds an instance lease until the child exits so producer
retention never removes files used by a running process.
"""

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    identity = root.name
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*", identity):
        raise ValueError("invalid tool identity")

    def checked(path: Path) -> Path:
        if not path.is_relative_to(root):
            raise ValueError("launcher path escaped installation root")
        for item in (path, *path.parents):
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("launcher rejects links and reparse points")
        return path

    selected = json.loads(checked(root / "current.json").read_text())
    if set(selected) != {"schema", "tool_id", "version", "manifest_sha256", "instance", "module"} or selected["schema"] != 1 or selected["tool_id"] != identity:
        raise ValueError("invalid tool selection")
    if not isinstance(selected["instance"], str) or not re.fullmatch("[0-9a-f]{32}", selected["instance"]):
        raise ValueError("invalid installation identity")
    if not isinstance(selected["version"], str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", selected["version"]):
        raise ValueError("invalid selected version")
    directory = root / "versions" / selected["version"] / selected["instance"]
    locks = root / "locks"
    locks.mkdir(exist_ok=True)
    checked(locks)
    lease = locks / f"{selected['instance']}.lease.lock"
    with lease.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        try:
            if json.loads(checked(directory / "receipt.json").read_text()) != selected:
                raise ValueError("tool receipt mismatch")
            python = checked(directory / "environment" / "Scripts" / "python.exe")
            env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("PYTHON", "PIP_", "UV_"))}
            return subprocess.call([str(python), "-I", "-B", "-m", selected["module"], *sys.argv[1:]], env=env)
        finally:
            if sys.platform == "win32":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as exc:
        print(f"Tool manager launch failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
