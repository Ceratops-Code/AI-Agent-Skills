"""Command-line routing for the functionally separate PR workflow operations."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from . import codex_review, ensure_pr, merge, readiness, sync


Command = Callable[[list[str] | None], int]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m github_pr_workflow",
        description="Ensure, validate, review, merge, and synchronize GitHub PR workflows.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("ensure-pr", "validate", "wait", "resolve", "merge", "sync"),
        help="workflow operation",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch one PR workflow responsibility to its owning module."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    if not arguments or arguments[0] in {"-h", "--help"}:
        parser.print_help()
        return 0
    command = arguments.pop(0)
    commands: dict[str, Command] = {
        "ensure-pr": ensure_pr.main,
        "validate": readiness.main,
        "wait": lambda values: codex_review.main(["wait", *(values or [])]),
        "resolve": lambda values: codex_review.main(["resolve", *(values or [])]),
        "merge": merge.main,
        "sync": sync.main,
    }
    if command not in commands:
        parser.error(f"unknown command: {command}")
    return commands[command](arguments)
