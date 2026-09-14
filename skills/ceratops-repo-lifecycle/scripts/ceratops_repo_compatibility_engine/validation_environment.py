"""Plan and initialize the repository-owned uv validator runtime.

The compatibility transaction owns generated files. uv owns its environment and
cache. Failed initial setup removes only the newly created environment inside
the verified target; an existing environment is never recursively discarded.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import tomllib
from collections.abc import Mapping
from typing import Any

import yaml


def runtime_files(root: pathlib.Path, bundle: pathlib.Path, contract: Mapping[str, Any], checks: list[dict[str, Any]]) -> dict[pathlib.Path, str]:
    """Render declarations and copy one engine implementation into the target."""

    runtime = contract["runtime"]
    files: dict[pathlib.Path, str] = {}
    dependencies = {"jsonschema", "PyYAML"}
    for check in checks:
        command = check["command"]
        if len(command) >= 3 and command[:2] == ["{python}", "-m"]:
            module = command[2]
            if module in {"ruff", "mypy", "yamllint"}:
                dependencies.add(module)
    project = root / contract["surfaces"]["validation_project"]["path"]
    template = bundle / "references/templates" / contract["surfaces"]["validation_project"]["template"]
    if project.is_file():
        document = tomllib.loads(project.read_text(encoding="utf-8"))
        declared = document.get("project", {}).get("dependencies", [])
        names = {re.split(r"[<>=!~;\[ ]", value, maxsplit=1)[0].lower().replace("_", "-") for value in declared}
        missing = {name for name in dependencies if name.lower().replace("_", "-") not in names}
        if missing:
            raise RuntimeError("existing validator project must declare: " + ", ".join(sorted(missing)))
    else:
        files[project] = template.read_text(encoding="utf-8").replace("__DEPENDENCIES__", json.dumps(sorted(dependencies)))
    for relative in runtime["payloads"]:
        source = bundle / relative
        if source.is_symlink() or not source.is_file():
            raise RuntimeError(f"missing regular SDLC runtime payload: {relative}")
        files[root / runtime["payload_root"] / relative] = source.read_text(encoding="utf-8")
    files[root / runtime["project"] / ".gitignore"] = "\n".join(runtime["ignored_paths"]) + "\n"
    for key in ("sdlc_runner",):
        surface = contract["surfaces"][key]
        destination = root / surface["path"]
        source = bundle / "references/templates" / surface["template"]
        files[destination] = source.read_text(encoding="utf-8")
    dependabot = root / ".github/dependabot.yml"
    data = yaml.safe_load(dependabot.read_text(encoding="utf-8")) if dependabot.is_file() else {"version": 2, "updates": []}
    if not isinstance(data, dict) or data.get("version") != 2 or not isinstance(data.get("updates"), list):
        raise RuntimeError("Dependabot configuration must have version 2 and an updates list")
    registration = contract["dependency_updates"]
    if not all(isinstance(item, dict) for item in data["updates"]):
        raise RuntimeError("Dependabot updates must be objects")
    if not any(item.get("package-ecosystem") == registration["package-ecosystem"] and (
        item.get("directory") == registration["directory"] or registration["directory"] in item.get("directories", [])
    ) for item in data["updates"]):
        data["updates"].append(dict(registration))
        files[dependabot] = yaml.safe_dump(data, sort_keys=False)
    return files


def setup_runtime(root: pathlib.Path, runtime: Mapping[str, Any]) -> None:
    """Resolve only on initial setup, then sync the declared locked environment."""

    executable = shutil.which("uv")
    if executable is None:
        raise RuntimeError("uv is required before compatibility setup; install uv and retry")
    project = root / runtime["project"]
    lock = root / runtime["lockfile"]
    environment = os.environ.copy()
    environment["UV_PROJECT_ENVIRONMENT"] = str(root / runtime["environment"])
    commands = [] if lock.is_file() else [[executable, "lock", "--project", str(project)]]
    commands.append([executable, "sync", "--project", str(project), "--locked"])
    for command in commands:
        result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        if result.returncode:
            raise RuntimeError("validator environment setup failed: " + (result.stderr or result.stdout)[-4096:])


def remove_created_environment(root: pathlib.Path, relative: str) -> None:
    """Delete only the failed transaction's newly created target environment."""

    target = root / relative
    resolved = target.resolve()
    if target.is_symlink() or not resolved.is_relative_to(root.resolve()) or resolved == root.resolve():
        raise RuntimeError("refusing unsafe validator environment cleanup")
    if target.exists():
        shutil.rmtree(target)
