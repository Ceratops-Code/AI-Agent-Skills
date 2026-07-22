#!/usr/bin/env python3
"""Return history relevant to named rules and their direct graph neighbors.

Usage:
    python scripts/rule_history.py lookup \
        --history HISTORY --rules RULES [--history ... --rules ...] ID...

The helper is read-only. It gives the proposal workflow a targeted history view
without loading unrelated entries or inferring graph neighbors manually.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


VERSION = 2
RULE_START = re.compile(r"^- \[(?P<id>[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\] ")
RELATION = re.compile(
    r"`(?:requires|limits|overrides) "
    r"(?P<targets>[A-Z][A-Z0-9-]*(?:, [A-Z][A-Z0-9-]*)*)`"
)
METADATA_RELATION = re.compile(
    r"^- (?:requires|limits|overrides): "
    r"(?P<targets>[A-Z][A-Z0-9-]*(?:, [A-Z][A-Z0-9-]*)*)$"
)


def read_text(path: Path, label: str) -> str:
    """Read a required non-empty UTF-8 file."""
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    value = path.read_text(encoding="utf-8")
    if not value.strip():
        raise ValueError(f"{label} is empty: {path}")
    return value


def file_hash(path: Path) -> str:
    """Return the SHA-256 hash identifying the consulted history state."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_relations(text: str) -> dict[str, set[str]]:
    """Parse rule IDs and outgoing relationships from one rule source."""
    records: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = RULE_START.match(line)
        if match:
            current = match.group("id")
            records[current] = [line]
        elif current and line.startswith("  ") and line.strip():
            records[current].append(line.strip())
        elif not line.strip() or line.startswith("## "):
            current = None

    relations: dict[str, set[str]] = {rule_id: set() for rule_id in records}
    for rule_id, parts in records.items():
        record = " ".join(parts)
        for match in RELATION.finditer(record):
            relations[rule_id].update(match.group("targets").split(", "))
        for part in parts:
            match = METADATA_RELATION.fullmatch(part)
            if match:
                relations[rule_id].update(match.group("targets").split(", "))
    return relations


def load_graph(paths: list[Path]) -> dict[str, set[str]]:
    """Merge rule sources and return undirected cross-source adjacency."""
    outgoing: dict[str, set[str]] = {}
    for path in paths:
        for rule_id, targets in parse_relations(
            read_text(path.resolve(), "rules")
        ).items():
            if rule_id in outgoing:
                raise ValueError(f"duplicate rule ID across sources: {rule_id}")
            outgoing[rule_id] = targets
    graph: dict[str, set[str]] = {rule_id: set() for rule_id in outgoing}
    for rule_id, targets in outgoing.items():
        for target in targets:
            if target not in graph:
                raise ValueError(f"{rule_id} relates to unknown rule {target}")
            graph[rule_id].add(target)
            graph[target].add(rule_id)
    return graph


def load_history(path: Path) -> list[dict[str, Any]]:
    """Load the supported history schema."""
    data = json.loads(read_text(path, "history"))
    if not isinstance(data, dict) or data.get("version") != VERSION:
        raise ValueError(f"history version must be {VERSION}")
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("history entries must be a non-empty list")
    if not all(isinstance(entry, dict) for entry in entries):
        raise ValueError("each history entry must be an object")
    return entries


def command_lookup(args: argparse.Namespace) -> None:
    """Print only baseline or directly relevant history entries."""
    history_paths = [path.resolve() for path in args.history]
    graph = load_graph(args.rules)
    requested = set(args.rule_ids)
    known = requested & set(graph)
    neighbors = (
        set().union(*(graph[rule_id] for rule_id in known)) if known else set()
    )
    consulted = requested | neighbors
    relevant = []
    for history_path in history_paths:
        for entry in load_history(history_path):
            affected = entry.get("rules")
            if not isinstance(affected, list):
                raise ValueError("history entry rules must be a list")
            if "*" in affected or consulted.intersection(affected):
                relevant.append(
                    {"history": str(history_path), "entry": entry}
                )
    result = {
        "requested": sorted(requested),
        "unknown": sorted(requested - set(graph)),
        "neighbors": sorted(neighbors),
        "consulted": sorted(consulted),
        "history_sha256": {
            str(path): file_hash(path) for path in history_paths
        },
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
