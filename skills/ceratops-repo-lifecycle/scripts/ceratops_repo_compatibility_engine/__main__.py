"""Dispatch the compatibility engine's declared command-line operations."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate or materialize Ceratops repository compatibility."
    )
    parser.add_argument(
        "command",
        choices=("materialize", "synchronize-bootstrap"),
        help="Compatibility operation to run.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch one active package command without loading unrelated helpers."""

    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "materialize":
        from .repository_materialization import main as materialize

        return materialize(args[1:])
    if args and args[0] == "synchronize-bootstrap":
        from .bootstrap_installer_synchronization import main as synchronize

        return synchronize(args[1:])
    _parser().parse_args(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
