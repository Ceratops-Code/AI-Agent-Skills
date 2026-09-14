#!/usr/bin/env python3
"""Run a bundled Python helper in its shared, locked uv environment.

Usage: uv run --no-project --python 3.14 python scripts/run-skill.py HELPER ...
HELPER is relative to the installed skill, or ``-m MODULE``. The caller's cwd,
arguments, output streams, and exit status are preserved. uv creates the Python
environment at its final location; virtual environments are never copied.

The installed pyproject/lock pair is authoritative. uv synchronizes one fixed
environment at CODEX_HOME/runtimes/ceratops/.venv for every managed skill.
All skills share its active dependency set; launching a different locked bundle
can update that set. The launcher serializes environment preparation across
bundles; uv owns dependency synchronization. No
environment or declaration copy is deployed, and this launcher owns no temporary
staging directory. Existing environments remain reusable after helper failure.
"""

from __future__ import annotations

import contextlib
import errno
import os
import pathlib
import shutil
import subprocess
import sys
import time
import tomllib
from collections.abc import Iterator, Sequence

DECLARATIONS = ("pyproject.toml", "uv.lock")


@contextlib.contextmanager
def preparation_lock(runtime: pathlib.Path) -> Iterator[None]:
    """Serialize setup before uv's environment-internal lock can exist.

    Bundles have different project directories, so their uv project locks do
    not protect shared environment creation. Use an OS lock, released even if
    this process dies. Its fixed file remains as reusable coordination state.
    The bootstrap cannot depend on a package inside the unprepared environment.
    """
    lock_path = checked_path(runtime / "runtime.lock")
    with lock_path.open("a+b") as handle:
        if sys.platform == "win32":
            import msvcrt

            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                handle.flush()

            def acquire() -> None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

            def release() -> None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def acquire() -> None:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

            def release() -> None:
                fcntl.flock(handle, fcntl.LOCK_UN)

        deadline = time.monotonic() + 300
        while True:
            try:
                acquire()
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError("Shared skills environment preparation is busy") from exc
                time.sleep(0.1)
        try:
            yield
        finally:
            release()


def checked_path(path: pathlib.Path) -> pathlib.Path:
    """Reject redirected cache and bundle paths before resolving them."""
    absolute = pathlib.Path(os.path.abspath(path.expanduser()))
    for item in (absolute, *absolute.parents):
        if item.is_symlink() or item.is_junction():
            raise ValueError(f"Python runtime paths must not be links: {item}")
    return absolute


def runtime_project(skill_root: pathlib.Path) -> pathlib.Path:
    """Validate the installed declarations without copying or renaming them."""
    source = checked_path(skill_root / "scripts/python-runtime")
    for name in DECLARATIONS:
        path = checked_path(source / name)
        if not path.is_file():
            raise ValueError(f"Missing bundled Python runtime declaration: {path}")
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        if name == "pyproject.toml" and not document.get("project", {}).get("requires-python"):
            raise ValueError("Bundled Python runtime must declare project.requires-python")
    return source


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
    project = runtime_project(root)
    runtime = checked_path(codex_home / "runtimes/ceratops")
    runtime.mkdir(parents=True, exist_ok=True)
    checked_path(runtime / ".venv")
    environment = os.environ.copy()
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT", "UV_WORKING_DIRECTORY",
                "UV_NO_SYNC", "UV_FROZEN", "UV_PYTHON", "UV_PYTHON_DOWNLOADS"):
        environment.pop(key, None)
    environment["UV_PROJECT_ENVIRONMENT"] = str(runtime / ".venv")
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(root / "scripts")
    with preparation_lock(runtime):
        checked_path(runtime / ".venv")
        prepared = subprocess.run(
            [uv, "sync", "--quiet", "--project", str(project), "--locked", "--no-active"],
            env=environment, check=False,
        )
        if prepared.returncode:
            return prepared.returncode
    # Sync is exact by default. Launch directly so a second uv operation cannot
    # recreate the shared environment outside the preparation lock. Helpers can
    # invoke other skills without holding this lock for their entire lifetime.
    scripts = runtime / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    # The override belongs only to skill preparation. Forwarding it would make
    # repository uv commands synchronize the shared skill environment instead
    # of the repository's declared project environment.
    environment.pop("UV_PROJECT_ENVIRONMENT")
    environment["VIRTUAL_ENV"] = str(runtime / ".venv")
    environment["PATH"] = str(scripts) + os.pathsep + environment.get("PATH", "")
    return subprocess.run([str(python), *args], env=environment, check=False).returncode


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
