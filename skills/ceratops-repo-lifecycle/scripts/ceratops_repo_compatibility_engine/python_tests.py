"""Discover conventional Python test candidates without importing repository code.

Detection is deliberately bounded to configured files and conventional names.
Unconventional suite ownership remains repository review; finding candidates
does not establish coverage or require a particular application environment.
"""

from __future__ import annotations

import fnmatch
import os
import pathlib
from collections.abc import Mapping
from typing import Any

import tomllib


def discover_python_tests(root: pathlib.Path, rules: Mapping[str, Any]) -> list[str]:
    """Return stable repository-relative candidates, skipping linked directories."""

    found: list[str] = []
    excluded = set(rules["excluded_directories"])
    for directory, names, files in os.walk(root, followlinks=False):
        base = pathlib.Path(directory)
        names[:] = sorted(name for name in names if name not in excluded and not (base / name).is_symlink())
        for name in sorted(files):
            path = base / name
            if path.is_symlink():
                continue
            if any(fnmatch.fnmatchcase(name, pattern) for pattern in rules["patterns"]):
                found.append(path.relative_to(root).as_posix())
    if found:
        return found
    if any((root / name).is_file() for name in rules["configuration_files"]):
        return ["."]
    project = root / "pyproject.toml"
    if project.is_file():
        value = tomllib.loads(project.read_text(encoding="utf-8"))
        if "pytest" in value.get("tool", {}):
            return ["."]
    for name, section in (("tox.ini", "[pytest]"), ("setup.cfg", "[tool:pytest]")):
        path = root / name
        if path.is_file() and section in path.read_text(encoding="utf-8"):
            return ["."]
    return []


def test_operation(root: pathlib.Path, runner: str) -> dict[str, Any]:
    """Use the scripts project for generated tests; preserve explicit SDLC operations."""
    return {
        "requires": {"capabilities": ["uv"]},
        "steps": [{"run": ["uv", "run", "--locked", runner]}],
    }
