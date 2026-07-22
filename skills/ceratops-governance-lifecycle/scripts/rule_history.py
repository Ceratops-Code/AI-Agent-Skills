#!/usr/bin/env python3
"""Return history relevant to named rules and their direct graph neighbors.

Usage:
    python scripts/rule_history.py lookup \
        --history HISTORY --rules RULES [--history ... --rules ...] \
        [--full] ID...

The helper is read-only. It gives the proposal workflow a targeted history view
without loading unrelated entries or inferring graph neighbors manually. Lookup
output is compact unless the caller explicitly requests full entry evidence.
Pass rule sources in effective global-to-local order.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rule_graph import (
    history_limit_findings,
    load_graph,
    load_history_references,
    load_history_source,
)


COMPACT_ENTRY_FIELDS = (
    "decision",
)


def entry_view(entry: dict[str, Any], *, full: bool, consulted: set[str]) -> dict[str, Any]:
    """Return full evidence only when the caller explicitly requests it."""
    if full:
        return entry
    view = {key: entry[key] for key in COMPACT_ENTRY_FIELDS if key in entry}
    affected = set(entry["rules"])
    view["matched_rules"] = sorted(
        consulted if "*" in affected else consulted.intersection(affected)
    )
    if "*" in affected:
        view["wildcard"] = True
    return view


def command_lookup(args: argparse.Namespace) -> None:
    """Print only baseline or directly relevant history entries."""
    history_paths = [path.resolve() for path in args.history]
    graph, current_rule_ids = load_graph(args.rules)
    requested = set(args.rule_ids)
    known = requested & set(graph)
    neighbors = (
        set().union(*(graph[rule_id] for rule_id in known)) if known else set()
    )
    consulted = requested | neighbors
    relevant = []
    for history_path in history_paths:
        entries = load_history_source(history_path)
        maintenance_findings = [
            *load_history_references(entries, current_rule_ids),
            *history_limit_findings(history_path, entries),
        ]
        if maintenance_findings:
            raise ValueError(
                "history cleanup required before lookup: "
                + json.dumps(maintenance_findings, separators=(",", ":"))
            )
        for entry in entries:
            affected = entry.get("rules")
            if not isinstance(affected, list):
                raise ValueError("history entry rules must be a list")
            if "*" in affected or consulted.intersection(affected):
                relevant.append(
                    {
                        "history": str(history_path),
                        "entry": entry_view(entry, full=args.full, consulted=consulted),
                    }
                )
    result = {
        "detail": "full" if args.full else "compact",
        "requested": sorted(requested),
        "unknown": sorted(requested - set(graph)),
        "neighbors": sorted(neighbors),
        "consulted": sorted(consulted),
        "entries": relevant,
    }
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    """Build the single read-only command consumed by the skill."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    lookup = commands.add_parser("lookup", help="query targeted rule history")
    lookup.add_argument("--history", type=Path, action="append", required=True)
    lookup.add_argument("--rules", type=Path, action="append", required=True)
    lookup.add_argument(
        "--full",
        action="store_true",
        help="include complete causal and regression evidence",
    )
    lookup.add_argument("rule_ids", nargs="+")
    lookup.set_defaults(handler=command_lookup)
    return parser


def main() -> int:
    """Run a command with compact errors for agent consumption."""
    try:
        args = build_parser().parse_args()
        args.handler(args)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
