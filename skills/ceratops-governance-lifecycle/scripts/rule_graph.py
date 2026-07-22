#!/usr/bin/env python3
"""Parse and validate the canonical structured AGENTS rule graph.

This module is the deterministic syntax owner shared by governance inventory
and history lookup helpers. It never changes rule or history sources. Semantic
decisions such as missing relations and relation compatibility remain with the
calling governance action.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


RULE_ID_PATTERN = r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+"
RULE_START = re.compile(
    rf"^- \[(?P<id>{RULE_ID_PATTERN})\] (?P<body>\S.*)$"
)
BRACKET_RULE_START = re.compile(r"^- \[(?P<id>[^]]+)\](?:\s|$)")
METADATA = re.compile(
    r"^  - (?P<key>[a-z][a-z-]*): (?P<value>\S.*)$"
)
RELATION_VALUE = re.compile(
    rf"{RULE_ID_PATTERN}(?:, {RULE_ID_PATTERN})*"
)
LEGACY_RELATION = re.compile(
    rf"`(?:requires|limits|overrides|overlaps|conflicts) "
    rf"{RULE_ID_PATTERN}(?:, {RULE_ID_PATTERN})*`"
)

RELATION_KEYS = ("requires", "limits", "overrides", "overlaps", "conflicts")
DIRECTIONAL_KEYS = ("requires", "limits", "overrides")
SYMMETRIC_KEYS = ("overlaps", "conflicts")
SELF_KEY = "self"
SELF_STATUSES = ("exceeds-limit", "list-heavy")
METADATA_KEYS = (*RELATION_KEYS, SELF_KEY)
METADATA_ORDER = {key: index for index, key in enumerate(METADATA_KEYS)}
HISTORY_VERSION = 2
HISTORY_ENTRY_KEYS = ("rules", "decision", "reason", "regression")
HISTORY_MAX_BYTES = 8 * 1024
HISTORY_MAX_ENTRIES = 20


@dataclass
class RuleRecord:
    """One parsed rule and the metadata needed by graph consumers."""

    rule_id: str
    source: str
    line: int
    body_lines: list[str]
    relations: dict[str, list[str]] = field(default_factory=dict)
    self_statuses: list[str] = field(default_factory=list)


@dataclass
class ParsedRuleSource:
    """Parsed rules plus deterministic findings for one AGENTS source."""

    source: str
    records: list[RuleRecord]
    findings: list[dict[str, object]]
    debts: list[dict[str, object]]
    semantic_reviews: list[dict[str, object]]


def _finding(
    code: str,
    source: str,
    line: int,
    *,
    rule_id: str | None = None,
    detail: str | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {"code": code, "source": source, "line": line}
    if rule_id:
        item["rule_id"] = rule_id
    if detail:
        item["detail"] = detail
    return item


def parse_rule_text(text: str, source: str) -> ParsedRuleSource:
    """Parse canonical rule and metadata lines without accepting legacy syntax."""
    records: list[RuleRecord] = []
    findings: list[dict[str, object]] = []
    debts: list[dict[str, object]] = []
    semantic_reviews: list[dict[str, object]] = []
    current: RuleRecord | None = None
    metadata_started = False
    last_metadata_order = -1
    seen_metadata: set[str] = set()

    for line_number, line in enumerate(text.splitlines(), start=1):
        rule_match = RULE_START.match(line)
        if rule_match:
            current = RuleRecord(
                rule_id=rule_match.group("id"),
                source=source,
                line=line_number,
                body_lines=[line],
            )
            records.append(current)
            metadata_started = False
            last_metadata_order = -1
            seen_metadata = set()
            continue

        if line.startswith("- "):
            bracket_match = BRACKET_RULE_START.match(line)
            code = "malformed_rule_id" if bracket_match else "missing_rule_id"
            detail = bracket_match.group("id") if bracket_match else line[:160]
            findings.append(_finding(code, source, line_number, detail=detail))
            current = None
            continue

        indented_bullet = line[:1].isspace() and line.lstrip().startswith("- ")
        if current is None:
            if indented_bullet:
                findings.append(
                    _finding(
                        "orphan_metadata",
                        source,
                        line_number,
                        detail=line.strip(),
                    )
                )
            continue

        if indented_bullet and not line.startswith("  - "):
            findings.append(
                _finding(
                    "malformed_metadata",
                    source,
                    line_number,
                    rule_id=current.rule_id,
                    detail=line.strip(),
                )
            )
            continue

        if line.startswith("  - "):
            metadata_started = True
            metadata_match = METADATA.fullmatch(line)
            if not metadata_match:
                findings.append(
                    _finding(
                        "malformed_metadata",
                        source,
                        line_number,
                        rule_id=current.rule_id,
                        detail=line.strip(),
                    )
                )
                continue
            key = metadata_match.group("key")
            value = metadata_match.group("value")
            if key not in METADATA_ORDER:
                findings.append(
                    _finding(
                        "unknown_metadata_key",
                        source,
                        line_number,
                        rule_id=current.rule_id,
                        detail=key,
                    )
                )
                continue
            if key in seen_metadata:
                findings.append(
                    _finding(
                        "duplicate_metadata_key",
                        source,
                        line_number,
                        rule_id=current.rule_id,
                        detail=key,
                    )
                )
            seen_metadata.add(key)
            key_order = METADATA_ORDER[key]
            if key_order < last_metadata_order:
                findings.append(
                    _finding(
                        "metadata_order",
                        source,
                        line_number,
                        rule_id=current.rule_id,
                        detail=key,
                    )
                )
            last_metadata_order = max(last_metadata_order, key_order)

            if key in RELATION_KEYS:
                if not RELATION_VALUE.fullmatch(value):
                    findings.append(
                        _finding(
                            "invalid_relation_targets",
                            source,
                            line_number,
                            rule_id=current.rule_id,
                            detail=value,
                        )
                    )
                    continue
                targets = value.split(", ")
                if len(targets) != len(set(targets)):
                    findings.append(
                        _finding(
                            "duplicate_relation_target",
                            source,
                            line_number,
                            rule_id=current.rule_id,
                            detail=value,
                        )
                    )
                current.relations[key] = targets
            else:
                statuses = value.split(", ")
                if len(statuses) != len(set(statuses)):
                    findings.append(
                        _finding(
                            "duplicate_self_status",
                            source,
                            line_number,
                            rule_id=current.rule_id,
                            detail=value,
                        )
                    )
                unknown = sorted(set(statuses) - set(SELF_STATUSES))
                if unknown:
                    findings.append(
                        _finding(
                            "unknown_self_status",
                            source,
                            line_number,
                            rule_id=current.rule_id,
                            detail=", ".join(unknown),
                        )
                    )
                current.self_statuses = statuses
            continue

        if line.startswith("  ") and line.strip():
            if metadata_started:
                findings.append(
                    _finding(
                        "body_after_metadata",
                        source,
                        line_number,
                        rule_id=current.rule_id,
                        detail=line.strip(),
                    )
                )
            else:
                current.body_lines.append(line)
            continue

        current = None

    seen_ids: dict[str, int] = {}
    for record in records:
        prior_line = seen_ids.get(record.rule_id)
        if prior_line is not None:
            findings.append(
                _finding(
                    "duplicate_rule_id",
                    source,
                    record.line,
                    rule_id=record.rule_id,
                    detail=f"first declared at line {prior_line}",
                )
            )
        else:
            seen_ids[record.rule_id] = record.line

        legacy_match = LEGACY_RELATION.search(" ".join(record.body_lines))
        if legacy_match:
            findings.append(
                _finding(
                    "legacy_relation_syntax",
                    source,
                    record.line,
                    rule_id=record.rule_id,
                    detail=legacy_match.group(0),
                )
            )

        exceeds = len(record.body_lines) > 6 or any(
            len(body_line) > 80 for body_line in record.body_lines
        )
        has_exceeds_status = "exceeds-limit" in record.self_statuses
        if exceeds and not has_exceeds_status:
            findings.append(
                _finding(
                    "missing_exceeds_limit_status",
                    source,
                    record.line,
                    rule_id=record.rule_id,
                )
            )
        elif has_exceeds_status and not exceeds:
            findings.append(
                _finding(
                    "unnecessary_exceeds_limit_status",
                    source,
                    record.line,
                    rule_id=record.rule_id,
                )
            )
        elif has_exceeds_status:
            debts.append(
                _finding(
                    "exceeds-limit",
                    source,
                    record.line,
                    rule_id=record.rule_id,
                )
            )

        if "list-heavy" in record.self_statuses:
            debt = _finding(
                "list-heavy",
                source,
                record.line,
                rule_id=record.rule_id,
            )
            debts.append(debt)
            semantic_reviews.append(debt)

    return ParsedRuleSource(source, records, findings, debts, semantic_reviews)


def parse_rule_source(path: Path) -> ParsedRuleSource:
    """Read and parse one required UTF-8 AGENTS source."""
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"rules does not exist: {resolved}")
    text = resolved.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"rules is empty: {resolved}")
    return parse_rule_text(text, str(resolved))


def _strong_components(
    nodes: Iterable[str], edges: dict[str, set[str]]
) -> list[list[str]]:
    """Return strongly connected components that contain a directed cycle."""
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in edges.get(node, set()):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] != indices[node]:
            return
        component: list[str] = []
        while stack:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node:
                break
        if len(component) > 1 or node in edges.get(node, set()):
            components.append(sorted(component))

    for node in sorted(set(nodes)):
        if node not in indices:
            visit(node)
    return sorted(components)


def validate_rule_stack(
    sources: list[ParsedRuleSource], *, global_source: str
) -> dict[str, object]:
    """Validate IDs, targets, relation cycles, and cross-scope legality."""
    findings: list[dict[str, object]] = []
    semantic_reviews: list[dict[str, object]] = []
    records_by_id: dict[str, RuleRecord] = {}
    all_records = [record for source in sources for record in source.records]
    for record in all_records:
        prior = records_by_id.get(record.rule_id)
        if prior is not None:
            findings.append(
                {
                    "code": "duplicate_stack_rule_id",
                    "rule_id": record.rule_id,
                    "sources": [prior.source, record.source],
                }
            )
        else:
            records_by_id[record.rule_id] = record

    edges: list[dict[str, object]] = []
    symmetric_seen: set[tuple[str, str, str]] = set()
    directional_graphs = {
        key: {rule_id: set() for rule_id in records_by_id}
        for key in DIRECTIONAL_KEYS
    }
    combined_graph = {rule_id: set() for rule_id in records_by_id}
    for record in all_records:
        for relation, targets in record.relations.items():
            for target in targets:
                target_record = records_by_id.get(target)
                edge = {
                    "source": record.rule_id,
                    "relation": relation,
                    "target": target,
                    "source_file": record.source,
                }
                if target_record is not None:
                    edge["target_file"] = target_record.source
                edges.append(edge)
                if target == record.rule_id:
                    findings.append(
                        {
                            "code": "self_relation",
                            "rule_id": record.rule_id,
                            "relation": relation,
                        }
                    )
                if target_record is None:
                    findings.append(
                        {
                            "code": "unknown_relation_target",
                            "rule_id": record.rule_id,
                            "relation": relation,
                            "target": target,
                        }
                    )
                    continue
                if record.source == global_source and target_record.source != global_source:
                    findings.append(
                        {
                            "code": "global_relation_targets_local",
                            "rule_id": record.rule_id,
                            "relation": relation,
                            "target": target,
                        }
                    )
                if (
                    record.source != global_source
                    and target_record.source == global_source
                    and relation == "overrides"
                ):
                    semantic_reviews.append(
                        {
                            "code": "local_override_delegation",
                            "rule_id": record.rule_id,
                            "target": target,
                        }
                    )
                if relation in DIRECTIONAL_KEYS:
                    directional_graphs[relation][record.rule_id].add(target)
                    combined_graph[record.rule_id].add(target)
                else:
                    pair = tuple(sorted((record.rule_id, target)))
                    marker = (relation, *pair)
                    review = {
                        "code": relation,
                        "rules": list(pair),
                    }
                    if marker in symmetric_seen:
                        findings.append(
                            {
                                "code": "duplicate_symmetric_edge",
                                "relation": relation,
                                "rules": list(pair),
                            }
                        )
                    else:
                        symmetric_seen.add(marker)
                        semantic_reviews.append(review)

    cycles: list[dict[str, object]] = []
    for relation, graph in directional_graphs.items():
        for members in _strong_components(records_by_id, graph):
            cycle = {"relation": relation, "rules": members}
            cycles.append(cycle)
            target = findings if relation == "overrides" else semantic_reviews
            target.append({"code": f"{relation}_cycle", "rules": members})
    for members in _strong_components(records_by_id, combined_graph):
        relation_types = sorted(
            {
                str(edge["relation"])
                for edge in edges
                if edge["relation"] in DIRECTIONAL_KEYS
                and edge["source"] in members
                and edge["target"] in members
            }
        )
        if len(relation_types) > 1:
            cycle = {"relation": "mixed", "types": relation_types, "rules": members}
            cycles.append(cycle)
            semantic_reviews.append({"code": "mixed_cycle", **cycle})

    return {
        "rule_count": len(all_records),
        "relation_counts": dict(
            sorted(Counter(str(edge["relation"]) for edge in edges).items())
        ),
        "edges": edges,
        "cycles": cycles,
        "findings": findings,
        "semantic_reviews": semantic_reviews,
    }


def rule_source_summary(source: ParsedRuleSource) -> dict[str, object]:
    """Return compact per-source facts for inventory output."""
    def compact(items: list[dict[str, object]]) -> dict[str, object]:
        grouped: dict[str, list[dict[str, object]]] = {}
        for item in items:
            grouped.setdefault(str(item["code"]), []).append(item)
        summaries = []
        for code, matches in sorted(grouped.items()):
            summary: dict[str, object] = {"code": code, "count": len(matches)}
            rule_ids = sorted(
                {str(item["rule_id"]) for item in matches if "rule_id" in item}
            )
            lines = sorted(
                {int(item["line"]) for item in matches if "line" in item}
            )
            details = sorted(
                {str(item["detail"]) for item in matches if "detail" in item}
            )
            if rule_ids:
                summary["rule_ids"] = rule_ids
            if lines:
                summary["lines"] = lines
            if details:
                summary["details"] = details[:3]
                if len(details) > 3:
                    summary["details_truncated"] = len(details) - 3
            summaries.append(summary)
        return {"count": len(items), "items": summaries}

    relation_counts = Counter(
        relation
        for record in source.records
        for relation, targets in record.relations.items()
        for _ in targets
    )
    return {
        "path": source.source,
        "rule_count": len(source.records),
        "relation_counts": dict(sorted(relation_counts.items())),
        "findings": compact(source.findings),
        "approved_debt": compact(source.debts),
        "semantic_reviews": compact(source.semantic_reviews),
    }


def load_history_references(
    entries: list[dict[str, object]], current_rule_ids: set[str]
) -> list[dict[str, object]]:
    """Report history references that cannot constrain any current rule."""
    findings: list[dict[str, object]] = []
    for index, entry in enumerate(entries):
        values = entry["rules"]
        obsolete = sorted(
            str(value)
            for value in values
            if value != "*" and value not in current_rule_ids
        )
        if obsolete:
            findings.append(
                {
                    "code": "obsolete_history_reference",
                    "entry": index,
                    "references": obsolete,
                }
            )
    return findings


def load_history_source(path: Path) -> list[dict[str, object]]:
    """Load the canonical non-empty regression-memory history object."""
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"history does not exist: {resolved}")
    text = resolved.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"history is empty: {resolved}")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("history root must be an object")
    if set(data) != {"version", "entries"}:
        raise ValueError("history root fields must be ('version', 'entries')")
    if data.get("version") != HISTORY_VERSION:
        raise ValueError(f"history version must be {HISTORY_VERSION}")
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("history entries must be a non-empty list")
    if not all(isinstance(entry, dict) for entry in entries):
        raise ValueError("each history entry must be an object")
    expected_keys = set(HISTORY_ENTRY_KEYS)
    for index, entry in enumerate(entries):
        actual_keys = set(entry)
        if actual_keys != expected_keys:
            raise ValueError(
                f"history entry {index} fields must be {HISTORY_ENTRY_KEYS}; "
                f"found {tuple(sorted(actual_keys))}"
            )
        rules = entry["rules"]
        if (
            not isinstance(rules, list)
            or not rules
            or not all(isinstance(value, str) and value for value in rules)
        ):
            raise ValueError(f"history entry {index} rules must be non-empty strings")
        if len(rules) != len(set(rules)):
            raise ValueError(f"history entry {index} rules must be unique")
        if "*" in rules and rules != ["*"]:
            raise ValueError(f"history entry {index} wildcard must be the only rule")
        invalid_rules = [
            value
            for value in rules
            if value != "*" and not re.fullmatch(RULE_ID_PATTERN, value)
        ]
        if invalid_rules:
            raise ValueError(
                f"history entry {index} has invalid rule IDs: {invalid_rules}"
            )
        for field_name in HISTORY_ENTRY_KEYS[1:]:
            value = entry[field_name]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"history entry {index} {field_name} must be non-empty text"
                )
    return entries


def history_limit_findings(
    path: Path, entries: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Report deterministic triggers that require semantic history compaction."""
    findings: list[dict[str, object]] = []
    byte_count = path.resolve().stat().st_size
    if byte_count > HISTORY_MAX_BYTES:
        findings.append(
            {
                "code": "history_size_limit",
                "bytes": byte_count,
                "limit": HISTORY_MAX_BYTES,
            }
        )
    if len(entries) > HISTORY_MAX_ENTRIES:
        findings.append(
            {
                "code": "history_entry_limit",
                "entries": len(entries),
                "limit": HISTORY_MAX_ENTRIES,
            }
        )
    return findings


def load_graph(paths: list[Path]) -> tuple[dict[str, set[str]], set[str]]:
    """Load a structurally valid stack and return undirected adjacency."""
    parsed = [parse_rule_source(path) for path in paths]
    source_findings = [finding for source in parsed for finding in source.findings]
    if source_findings:
        first = source_findings[0]
        raise ValueError(f"invalid rule source: {first}")
    global_source = parsed[0].source if parsed else ""
    validation = validate_rule_stack(parsed, global_source=global_source)
    if validation["findings"]:
        raise ValueError(f"invalid rule graph: {validation['findings'][0]}")
    graph: dict[str, set[str]] = {
        record.rule_id: set()
        for source in parsed
        for record in source.records
    }
    for edge in validation["edges"]:
        source_id = str(edge["source"])
        target_id = str(edge["target"])
        graph[source_id].add(target_id)
        graph[target_id].add(source_id)
    return graph, set(graph)
