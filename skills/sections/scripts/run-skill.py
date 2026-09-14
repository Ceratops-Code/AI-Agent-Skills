#!/usr/bin/env python3
"""Run a bundled Python helper in its shared, locked uv environment.

Usage: uv run --no-project --python 3.14 python scripts/run-skill.py HELPER ...
HELPER is relative to the installed skill, or ``-m MODULE``. The caller's cwd,
arguments, output streams, and exit status are preserved. uv creates the Python
environment at its final location; virtual environments are never copied.

The installed pyproject/lock pair is authoritative. Its content identity selects
one persistent cache project under CODEX_HOME/runtimes/ceratops. Identical pairs
share an environment; different locks cannot mutate each other's environments.
Only unpublished staging directories are temporary and owned by this launcher.
Published cache projects remain reusable after success or failure; uv owns
environment synchronization and locking, including recovery on the next launch.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Sequence

DECLARATIONS = ("pyproject.toml", "uv.lock")


def checked_path(path: pathlib.Path) -> pathlib.Path:
    """Reject redirected cache and bundle paths before resolving them."""
    absolute = pathlib.Path(os.path.abspath(path.expanduser()))
    for item in (absolute, *absolute.parents):
        if item.is_symlink() or item.is_junction():
            raise ValueError(f"Python runtime paths must not be links: {item}")
    return absolute


def shared_project(skill_root: pathlib.Path, codex_home: pathlib.Path) -> pathlib.Path:
    """Publish immutable declarations atomically; uv manages the final .venv."""
    source = checked_path(skill_root / "scripts/python-runtime")
    contents: dict[str, bytes] = {}
    identity = hashlib.sha256()
    for name in DECLARATIONS:
        path = checked_path(source / name)
        if not path.is_file():
            raise ValueError(f"Missing bundled Python runtime declaration: {path}")
        data = path.read_bytes().replace(b"\r\n", b"\n")
        document = tomllib.loads(data.decode("utf-8"))
        if name == "pyproject.toml" and not document.get("project", {}).get("requires-python"):
            raise ValueError("Bundled Python runtime must declare project.requires-python")
        contents[name] = data
        identity.update(name.encode() + b"\0" + len(data).to_bytes(8, "big") + data)
    parent = checked_path(codex_home / "runtimes/ceratops")
    parent.mkdir(parents=True, exist_ok=True)
    target = checked_path(parent / identity.hexdigest())
    if not target.exists():
        staging = pathlib.Path(tempfile.mkdtemp(prefix=".prepare-", dir=parent))
        try:
            for name, data in contents.items():
                (staging / name).write_bytes(data)
            try:
                staging.rename(target)
            except OSError:
                # Concurrent first callers publish the same complete bytes.
                # Never replace a previously published project or environment.
                if not target.is_dir():
                    raise
        finally:
            if staging.exists():
                if checked_path(staging).parent != parent:
                    raise ValueError("Unsafe Python runtime staging cleanup")
                shutil.rmtree(staging)
    for name, data in contents.items():
        path = checked_path(target / name)
        if not path.is_file() or path.read_bytes() != data:
            raise ValueError(f"Shared Python runtime declaration changed: {path}")
    checked_path(target / ".venv")
    return target


def helper_arguments(skill_root: pathlib.Path, arguments: Sequence[str]) -> list[str]:
    """Bind script paths to the bundle without changing the helper's cwd."""
    args = list(arguments)
    if args and args[0] == "--":
        args.pop(0)
    if not args:
        raise ValueError("Specify a bundled helper path or -m MODULE")
    if args[0] == "-m":
        if len(args) < 2 or not args[1] or args[1].startswith("-"):
            raise ValueError("-m requires a module name")
        return args
    path = pathlib.Path(args[0])
    path = checked_path(path if path.is_absolute() else skill_root / path)
    if not path.is_relative_to(skill_root) or not path.is_file() or path.suffix != ".py":
        raise ValueError(f"Helper must be a Python file inside the installed skill: {path}")
    if path == skill_root / "scripts/run-skill.py":
        raise ValueError("The Python launcher cannot invoke itself")
    args[0] = str(path)
    return args


def run_helper(skill_root: pathlib.Path, arguments: Sequence[str]) -> int:
    """Prepare dependencies before Python starts and return the helper's status."""
    root = checked_path(skill_root)
    args = helper_arguments(root, arguments)
    uv = shutil.which("uv")
    if uv is None:
        raise ValueError("uv is required to run this skill's Python helpers")
    codex_home = pathlib.Path(os.environ.get("CODEX_HOME", str(pathlib.Path.home() / ".codex")))
    project = shared_project(root, codex_home)
    environment = os.environ.copy()
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT", "UV_WORKING_DIRECTORY",
                "UV_NO_SYNC", "UV_FROZEN", "UV_PYTHON", "UV_PYTHON_DOWNLOADS"):
        environment.pop(key, None)
    environment["UV_PROJECT_ENVIRONMENT"] = str(project / ".venv")
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(root / "scripts")
    command = [uv, "run", "--quiet", "--project", str(project), "--locked", "--exact",
               "--no-active", "python", *args]
    return subprocess.run(command, env=environment, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments == ["--help"]:
        print(__doc__)
        return 0
    try:
        return run_helper(pathlib.Path(__file__).resolve().parents[1], arguments)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
