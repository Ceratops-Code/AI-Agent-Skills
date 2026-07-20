"""Command-line routing for GitHub lifecycle contract operations."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from . import collect_non_deterministic_evidence
from . import organization_validator
from . import repository_validator
from . import source_documents


Command = Callable[[list[str] | None], int]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m github_contract_engine",
        description="Collect and validate Ceratops GitHub lifecycle contracts.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("collect", "check-source-docs", "validate"),
        help="operation to run",
    )
    return parser


def _validation_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m github_contract_engine validate",
        description="Run one deterministic GitHub lifecycle validator.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        choices=("org", "repo", "consistency"),
        help="validation target",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch to one functionally separate contract operation."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    if not arguments or arguments[0] in {"-h", "--help"}:
        parser.print_help()
        return 0
    command = arguments.pop(0)
    direct: dict[str, Command] = {
        "collect": collect_non_deterministic_evidence.main,
        "check-source-docs": source_documents.main,
    }
    if command in direct:
        return direct[command](arguments)
    if command != "validate":
        parser.error(f"unknown command: {command}")

    validation_parser = _validation_parser()
    if not arguments or arguments[0] in {"-h", "--help"}:
        validation_parser.print_help()
        return 0
    target = arguments.pop(0)
    if target == "consistency":
        # Keep schema tooling scoped to the consistency command; collection and
        # live validators do not need to import the optional validation library.
        from . import consistency

        return consistency.main(arguments)
    validators: dict[str, Command] = {
        "org": organization_validator.main,
        "repo": repository_validator.main,
    }
    if target not in validators:
        validation_parser.error(f"unknown validation target: {target}")
    return validators[target](arguments)
