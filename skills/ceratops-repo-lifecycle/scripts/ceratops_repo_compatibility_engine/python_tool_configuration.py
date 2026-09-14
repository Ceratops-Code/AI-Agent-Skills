"""Plan Python validation defaults without overwriting repository configuration.

The owned project template supplies complete Ruff and mypy tables. We append
only wholly absent tool tables when the repository has no root configuration,
so existing TOML comments, dependencies and settings remain untouched. Parsing
the result rejects ambiguous inline-table extensions before the compatibility
transaction writes anything. This limited
append operation needs no third-party TOML editor in the bootstrap environment.
"""

from __future__ import annotations

import json
import pathlib
import re
import tomllib
from collections.abc import Iterable


def project_text(root: pathlib.Path, template: pathlib.Path, dependencies: Iterable[str] = ()) -> str:
    """Render a new tooling project or append missing default tool tables."""
    defaults = template.read_text(encoding="utf-8").replace(
        "__DEPENDENCIES__", json.dumps(sorted(dependencies)),
    )
    tomllib.loads(defaults)
    groups = re.split(r"(?m)(?=^\[tool\.(?:ruff|mypy)\]$)", defaults)
    path = root / "scripts/pyproject.toml"
    if path.is_symlink():
        raise RuntimeError(f"tooling project must be a regular file: {path}")
    existing = path.read_text(encoding="utf-8") if path.is_file() else groups[0]
    tools = tomllib.loads(existing).get("tool", {})
    if not isinstance(tools, dict):
        raise RuntimeError("tooling project tool configuration must be a table")
    # These two complete table groups are owned template data, not arbitrary
    # repository TOML to rewrite. Validate the merged result before returning it.
    for group in groups[1:]:
        tool = next(iter(tomllib.loads(group)["tool"]))
        if tool not in tools and not repository_configured(root, tool):
            existing = existing.rstrip("\n") + "\n\n" + group
    tomllib.loads(existing)
    return existing


def repository_configured(root: pathlib.Path, tool: str) -> bool:
    """Respect the ordinary root configuration precedence of each tool."""
    names = {"ruff": ("ruff.toml", ".ruff.toml"), "mypy": ("mypy.ini", ".mypy.ini")}
    if any((root / name).is_file() for name in names[tool]):
        return True
    project = root / "pyproject.toml"
    if project.is_file() and tool in tomllib.loads(project.read_text(encoding="utf-8")).get("tool", {}):
        return True
    setup = root / "setup.cfg"
    return tool == "mypy" and setup.is_file() and bool(
        re.search(r"(?m)^\s*\[mypy\]\s*$", setup.read_text(encoding="utf-8"))
    )
