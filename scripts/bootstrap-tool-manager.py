#!/usr/bin/env python3
"""Install the manager into its own directory using existing global Python and uv.

Prerequisite probes happen before filesystem changes. Packaging owns build
scratch and the shared deployment engine owns failed candidates. This command
never installs global prerequisites, edits Codex settings, or restarts apps.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib

from tool_manager_support import SOURCE  # isort: skip
from ceratops_tool_manager.contracts import DeploymentError
from ceratops_tool_manager.engine import Engine, global_runtime
from ceratops_tool_manager.storage import Layout


def ensure_launchers(layout: Layout) -> None:
    """Provision the stable launcher after validating global prerequisites."""
    global_runtime()
    layout.directory("bin")
    launcher = layout.path("bin", "ceratops-tool-manager.py")
    if not launcher.exists():
        shutil.copyfile(SOURCE / "launcher.py", launcher)
    command = layout.path("bin", "ceratops-tool-manager.cmd")
    if not command.exists():
        command.write_text('@echo off\r\npython -I -B "%~dp0ceratops-tool-manager.py" %*\r\n', encoding="utf-8", newline="")


def main() -> int:
    try:
        global_runtime()
        engine = Engine()
        if engine.selected("ceratops-tool-manager") is not None:
            raise DeploymentError("manager is already installed; use its install or update command")
        from pathlib import Path

        result = subprocess.run([sys.executable, str(Path(__file__).with_name("package-tool-release.py")), "--source", str(SOURCE)], check=False)
        if result.returncode:
            return result.returncode
        version = tomllib.loads((SOURCE / "pyproject.toml").read_text())["project"]["version"]
        ensure_launchers(engine.layout)
        outcome = engine.install("ceratops-tool-manager", version)
        print(json.dumps(outcome, sort_keys=True))
        return 0
    except (DeploymentError, OSError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
