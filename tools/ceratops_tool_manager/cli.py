"""Public CLI: explicit source packaging and the shared deployment operations.

Only deployment operations mirror MCP. Packaging accepts reviewed source and
can build/download code, but never activates the resulting tool version.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import TOOL_ID
from .contracts import DeploymentError
from .engine import Engine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=TOOL_ID)
    commands = parser.add_subparsers(dest="operation", required=True)
    packaging = commands.add_parser("package", help="prepare an exact local tool package without installing it")
    packaging.add_argument("--source", type=Path, required=True, help="reviewed tool source directory")
    packaging.add_argument("--lock", action="store_true", help="refresh pylock.toml instead of building a package")
    for operation in ("install", "update"):
        command = commands.add_parser(operation)
        command.add_argument("tool_id")
        command.add_argument("version")
    versions = commands.add_parser("versions")
    versions.add_argument("tool_id", nargs="?", default=TOOL_ID)
    args = parser.parse_args(argv)
    try:
        if args.operation == "package":
            from .packaging import package

            result = package(args.source, lock_only=args.lock)
        else:
            engine = Engine()
            result = getattr(engine, args.operation)(args.tool_id, args.version) if args.operation != "versions" else engine.versions(args.tool_id)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (DeploymentError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"error": str(exc)[-1800:]}), file=sys.stderr)
        return 2
