#!/usr/bin/env python3
"""Install the first tool manager using existing global Python and uv.

Prerequisite probes happen before filesystem changes. Locked Python libraries
are provisioned only in owned temporary storage, then the manager's packaging
and deployment implementations perform the first installation. This command
never installs global prerequisites, edits Codex settings, or restarts apps.
"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE = importlib.import_module("tool-manager-support").SOURCE
from ceratops_tool_manager.contracts import DeploymentError  # noqa: E402
from ceratops_tool_manager.engine import (  # noqa: E402
    Engine,
    Runtime,
    child_environment,
    global_runtime,
    run,
)
from ceratops_tool_manager.storage import Layout  # noqa: E402


def ensure_launchers(layout: Layout) -> None:
    """Provision the stable launcher after validating global prerequisites."""
    global_runtime()
    layout.directory("bin")
    launcher = layout.path("bin", "ceratops_tool_manager.py")
    if not launcher.exists():
        shutil.copyfile(SOURCE / "launcher.py", launcher)
    command = layout.path("bin", "ceratops_tool_manager.cmd")
    if not command.exists():
        command.write_text('@echo off\r\npython -I -B "%~dp0ceratops_tool_manager.py" %*\r\n', encoding="utf-8", newline="")


def package_manager(engine: Engine, runtime: Runtime) -> dict:
    """Use the manager's source implementation without preinstalled libraries.

    uv installs only hash-locked wheels into disposable bootstrap storage.
    The first-install script owns its cleanup on every return path; the manager
    owns the resulting immutable package and its ordinary build scratch.
    """
    with tempfile.TemporaryDirectory(prefix="bootstrap_", dir=engine.layout.directory("staging")) as work:
        temporary = Path(work)
        libraries = temporary / "libraries"
        run([str(runtime.uv), "pip", "sync", str(SOURCE / "pylock.toml"), "--python", str(runtime.python),
             "--target", str(libraries), "--require-hashes", "--only-binary", ":all:", "--no-config"],
            cwd=SOURCE, env=child_environment(engine.layout, temporary))
        sys.path.insert(0, str(libraries))
        try:
            from ceratops_tool_manager.packaging import package

            return package(SOURCE)
        finally:
            sys.path.remove(str(libraries))


def main() -> int:
    try:
        runtime = global_runtime()
        engine = Engine()
        if engine.selected("ceratops_tool_manager") is not None:
            raise DeploymentError("manager is already installed; use its install or update command")
        result = package_manager(engine, runtime)
        ensure_launchers(engine.layout)
        outcome = engine.install("ceratops_tool_manager", result["version"])
        print(json.dumps(outcome, sort_keys=True))
        return 0
    except (DeploymentError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(str(exc)[-1800:], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
