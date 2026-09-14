"""Public CLI: repository installation, packaging, and registered releases.

Repository installation packages reviewed source then invokes the shared engine.
MCP accepts only registered releases; build inputs stay in this development CLI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import TOOL_NAME
from .contracts import DeploymentError
from .engine import Engine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=TOOL_NAME)
    commands = parser.add_subparsers(dest="operation", required=True)
    packaging = commands.add_parser("package", help="prepare an exact local tool package without installing it")
    packaging.add_argument("--source", type=Path, required=True, help="reviewed tool source directory")
    packaging.add_argument("--lock", action="store_true", help="refresh pylock.toml instead of building a package")
    install = commands.add_parser("install", help="build and install the version declared by the selected source")
    install.add_argument("--source", type=Path, default=Path.cwd(), help="repository or tool directory; defaults to the current directory")
    install.add_argument("--tool-name", help="project.name; required when the repository declares multiple tools")
    update = commands.add_parser("update")
    update.add_argument("tool_name")
    update.add_argument("version")
    versions = commands.add_parser("versions")
    versions.add_argument("tool_name", nargs="?", default=TOOL_NAME)
    args = parser.parse_args(argv)
    try:
        if args.operation == "package":
            from .packaging import package

            result = package(args.source, lock_only=args.lock)
        elif args.operation == "install":
            from .packaging import install_from_source

            result = install_from_source(args.source, args.tool_name)
        else:
            engine = Engine()
            result = engine.update(args.tool_name, args.version) if args.operation == "update" else engine.versions(args.tool_name)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (DeploymentError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"error": str(exc)[-1800:]}), file=sys.stderr)
        return 2
