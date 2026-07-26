#!/usr/bin/env python3
"""Apply one approved, mechanically validated rules/history transaction.

The UTF-8 JSON request has the closed top-level fields ``version``,
``rule_stack``, ``rule_replacements``, and ``history_operations``. Paths are
resolved from the caller's working directory. Each replacement names its rules
source, companion history source, exact expected-old text, and exact replacement
text. History operations support only an approved ``append`` entry.

This helper owns stale-text detection, structural validation, change coverage,
and rollback-protected writes. It does not establish semantic equivalence; the
calling governance workflow must account for every operative old-text clause.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Never, cast

from rule_graph import (
    HISTORY_ENTRY_KEYS,
    HISTORY_VERSION,
    ParsedRuleSource,
    RuleRecord,
    load_history_source,
    parse_history_text,
    parse_rule_text,
    validate_rule_stack,
)


REQUEST_VERSION = 1
UTF8_BOM = b"\xef\xbb\xbf"
ROOT_FIELDS = {
    "version",
    "rule_stack",
    "rule_replacements",
    "history_operations",
}
REPLACEMENT_FIELDS = {
    "rules",
    "history",
    "expected_old",
    "replacement",
}
HISTORY_OPERATION_FIELDS = {"history", "operation", "entry"}


class ApplicationError(ValueError):
    """One compact, actionable request or transaction failure."""


class CompactParser(argparse.ArgumentParser):
    """Avoid argparse's multi-line usage output for invalid invocations."""

    def error(self, message: str) -> Never:
        raise ApplicationError(message)


@dataclass(frozen=True)
class TextSource:
    """Original bytes plus the encoding and newline state that must survive."""

    path: Path
    raw: bytes
    text: str
    has_bom: bool
    newline: str
    trailing_newline: bool

    def encode(self, text: str) -> bytes:
        encoded = text.encode("utf-8")
        return UTF8_BOM + encoded if self.has_bom else encoded


@dataclass
class PreparedUpdate:
    """Fully validated candidates and evidence needed for commit/reopen checks."""

    stack_paths: list[Path]
    originals: dict[Path, TextSource]
    candidates: dict[Path, bytes]
    baseline_reviews: set[str]
    expected_history_entries: dict[Path, list[dict[str, object]]]


def require_fields(value: object, fields: set[str], label: str) -> dict[str, Any]:
    """Return a closed-schema object or reject it with its exact field delta."""
    if not isinstance(value, dict):
        raise ApplicationError(f"{label} must be an object")
    missing = sorted(fields - set(value))
    extra = sorted(set(value) - fields)
    if missing or extra:
        raise ApplicationError(
            f"{label} fields invalid; missing={missing} extra={extra}"
        )
    return cast(dict[str, Any], value)


def require_path(value: object, label: str) -> Path:
    """Resolve one required path from the caller's working directory."""
    if not isinstance(value, str) or not value:
        raise ApplicationError(f"{label} must be a non-empty path")
    path = Path(value)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def newline_styles(text: str) -> set[str]:
    """Return every concrete line-ending form present in text."""
    without_crlf = text.replace("\r\n", "")
    styles: set[str] = set()
    if "\r\n" in text:
        styles.add("\r\n")
    if "\n" in without_crlf:
        styles.add("\n")
    if "\r" in without_crlf:
        styles.add("\r")
    return styles


def read_source(path: Path, label: str) -> TextSource:
    """Read one UTF-8 source without normalizing bytes or line endings."""
    if not path.is_file():
        raise ApplicationError(f"{label} does not exist: {path}")
    raw = path.read_bytes()
    has_bom = raw.startswith(UTF8_BOM)
    payload = raw[len(UTF8_BOM) :] if has_bom else raw
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ApplicationError(f"{label} is not UTF-8: {path}") from error
    if not text.strip():
        raise ApplicationError(f"{label} is empty: {path}")
    styles = newline_styles(text)
    if len(styles) > 1:
        raise ApplicationError(f"{label} has mixed line endings: {path}")
    newline = next(iter(styles), "\n")
    return TextSource(
        path=path,
        raw=raw,
        text=text,
        has_bom=has_bom,
        newline=newline,
        trailing_newline=text.endswith(newline),
    )


def finding_text(prefix: str, finding: dict[str, object]) -> str:
    """Compress one validator finding without dumping the full graph."""
    code = finding.get("code", "unknown")
    rule = f" rule={finding['rule_id']}" if "rule_id" in finding else ""
    target = f" target={finding['target']}" if "target" in finding else ""
    source = finding.get("source")
    line = finding.get("line")
    location = f" {source}:{line}" if source and line else ""
    return f"{prefix}: {code}{rule}{target}{location}"


def review_key(review: dict[str, object]) -> str:
    """Ignore line drift while retaining semantic-review identity."""
    stable = {key: value for key, value in review.items() if key != "line"}
    return json.dumps(stable, separators=(",", ":"), sort_keys=True)


def validate_stack_texts(
    stack_paths: list[Path],
    texts: dict[Path, str],
    *,
    label: str,
) -> tuple[list[ParsedRuleSource], dict[str, Any], set[str]]:
    """Run the shared source and graph validators over one effective stack."""
    parsed = [
        parse_rule_text(texts[path], str(path))
        for path in stack_paths
    ]
    for source in parsed:
        if source.findings:
            raise ApplicationError(finding_text(label, source.findings[0]))
    validation = validate_rule_stack(parsed, global_source=str(stack_paths[0]))
    findings = cast(list[dict[str, object]], validation["findings"])
    if findings:
        raise ApplicationError(finding_text(label, findings[0]))
    reviews = [
        *(
            review
            for source in parsed
            for review in source.semantic_reviews
        ),
        *cast(list[dict[str, object]], validation["semantic_reviews"]),
    ]
    review_keys = {review_key(review) for review in reviews}
    return parsed, validation, review_keys


def record_signature(record: RuleRecord) -> tuple[object, ...]:
    """Return the validator-owned rule content used for change accounting."""
    return (
        tuple(record.body_lines),
        tuple(
            (key, tuple(values))
            for key, values in sorted(record.relations.items())
        ),
        tuple(record.self_statuses),
    )


def changed_rule_ids(
    before: ParsedRuleSource, after: ParsedRuleSource
) -> set[str]:
    """Derive changed, added, and removed IDs from parsed rule records."""
    old = {record.rule_id: record_signature(record) for record in before.records}
    new = {record.rule_id: record_signature(record) for record in after.records}
    return {
        rule_id
        for rule_id in old.keys() | new.keys()
        if old.get(rule_id) != new.get(rule_id)
    }


def exact_occurrences(text: str, needle: str) -> list[int]:
    """Return overlapping exact-match starts so ambiguity cannot hide."""
    return [
        match.start()
        for match in re.finditer(f"(?={re.escape(needle)})", text)
    ]


def apply_replacements(
    source: TextSource, replacements: list[dict[str, Any]]
) -> str:
    """Construct one non-overlapping exact replacement candidate in memory."""
    spans: list[tuple[int, int, str]] = []
    for index, replacement in enumerate(replacements):
        expected = replacement["expected_old"]
        new_text = replacement["replacement"]
        if not isinstance(expected, str) or not expected:
            raise ApplicationError(
                f"rule_replacements[{index}].expected_old must be non-empty text"
            )
        if not isinstance(new_text, str):
            raise ApplicationError(
                f"rule_replacements[{index}].replacement must be text"
            )
        matches = exact_occurrences(source.text, expected)
        if len(matches) != 1:
            raise ApplicationError(
                f"expected_old occurrence count is {len(matches)} in {source.path}"
            )
        start = matches[0]
        spans.append((start, start + len(expected), new_text))
    spans.sort(key=lambda item: item[0])
    for previous, current in zip(spans, spans[1:]):
        if current[0] < previous[1]:
            raise ApplicationError(
                f"rule replacements overlap in {source.path}"
            )
    parts: list[str] = []
    cursor = 0
    for start, end, new_value in spans:
        parts.extend((source.text[cursor:start], new_value))
        cursor = end
    parts.append(source.text[cursor:])
    candidate = "".join(parts)
    styles = newline_styles(candidate)
    if styles and styles != {source.newline}:
        raise ApplicationError(
            f"replacement changes line-ending convention in {source.path}"
        )
    if candidate.endswith(source.newline) != source.trailing_newline:
        raise ApplicationError(
            f"replacement changes trailing newline state in {source.path}"
        )
    return candidate


def render_history(
    source: TextSource, entries: list[dict[str, object]]
) -> str:
    """Render canonical JSON with the source's existing encoding/newline form."""
    text = json.dumps(
        {"version": HISTORY_VERSION, "entries": entries},
        ensure_ascii=False,
        indent=2,
    )
    if source.trailing_newline:
        text += "\n"
    if source.newline != "\n":
        text = text.replace("\n", source.newline)
    return text


def load_request(path: Path) -> dict[str, Any]:
    """Load the closed request without accepting a non-UTF-8 plan."""
    if not path.is_file():
        raise ApplicationError(f"request does not exist: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError as error:
        raise ApplicationError(f"request is not UTF-8: {path}") from error
    return require_fields(data, ROOT_FIELDS, "request")


def prepare(request: dict[str, Any]) -> PreparedUpdate:
    """Build and validate every candidate before any durable target write."""
    if request["version"] != REQUEST_VERSION:
        raise ApplicationError(f"request version must be {REQUEST_VERSION}")
    stack_values = request["rule_stack"]
    if not isinstance(stack_values, list) or not stack_values:
        raise ApplicationError("rule_stack must be a non-empty list")
    stack_paths = [
        require_path(value, f"rule_stack[{index}]")
        for index, value in enumerate(stack_values)
    ]
    if len(stack_paths) != len(set(stack_paths)):
        raise ApplicationError("rule_stack paths must be unique")

    rule_sources = {
        path: read_source(path, "rules source") for path in stack_paths
    }
    baseline_parsed, _, baseline_reviews = validate_stack_texts(
        stack_paths,
        {path: source.text for path, source in rule_sources.items()},
        label="invalid current rule stack",
    )

    replacement_values = request["rule_replacements"]
    if not isinstance(replacement_values, list) or not replacement_values:
        raise ApplicationError("rule_replacements must be a non-empty list")
    replacements_by_rules: dict[Path, list[dict[str, Any]]] = {}
    history_by_rules: dict[Path, Path] = {}
    for index, value in enumerate(replacement_values):
        replacement = require_fields(
            value, REPLACEMENT_FIELDS, f"rule_replacements[{index}]"
        )
        rules = require_path(
            replacement["rules"], f"rule_replacements[{index}].rules"
        )
        history = require_path(
            replacement["history"], f"rule_replacements[{index}].history"
        )
        if rules not in rule_sources:
            raise ApplicationError(
                f"rules target is not in rule_stack: {rules}"
            )
        companion = rules.with_name("AGENTS.history.json").resolve()
        if history != companion:
            raise ApplicationError(
                f"history is not the companion source for {rules}"
            )
        prior_history = history_by_rules.setdefault(rules, history)
        if prior_history != history:
            raise ApplicationError(f"rules target has multiple histories: {rules}")
        replacements_by_rules.setdefault(rules, []).append(replacement)

    candidate_rule_texts = {
        path: source.text for path, source in rule_sources.items()
    }
    for rules, replacements in replacements_by_rules.items():
        candidate_rule_texts[rules] = apply_replacements(
            rule_sources[rules], replacements
        )
    candidate_parsed, _, candidate_reviews = validate_stack_texts(
        stack_paths,
        candidate_rule_texts,
        label="invalid candidate rule stack",
    )
    new_reviews = candidate_reviews - baseline_reviews
    if new_reviews:
        review = json.loads(sorted(new_reviews)[0])
        raise ApplicationError(finding_text("new semantic review", review))

    baseline_by_path = {
        Path(source.source): source for source in baseline_parsed
    }
    candidate_by_path = {
        Path(source.source): source for source in candidate_parsed
    }
    changed_by_history: dict[Path, set[str]] = {}
    for rules, history in history_by_rules.items():
        changed = changed_rule_ids(
            baseline_by_path[rules], candidate_by_path[rules]
        )
        if not changed:
            raise ApplicationError(f"replacement changes no rules in {rules}")
        changed_by_history.setdefault(history, set()).update(changed)

    operation_values = request["history_operations"]
    if not isinstance(operation_values, list) or not operation_values:
        raise ApplicationError("history_operations must be a non-empty list")
    operations_by_history: dict[Path, list[dict[str, object]]] = {}
    for index, value in enumerate(operation_values):
        operation = require_fields(
            value,
            HISTORY_OPERATION_FIELDS,
            f"history_operations[{index}]",
        )
        history = require_path(
            operation["history"], f"history_operations[{index}].history"
        )
        if history not in changed_by_history:
            raise ApplicationError(
                f"history operation has no changed rules source: {history}"
            )
        if operation["operation"] != "append":
            raise ApplicationError(
                f"history_operations[{index}].operation must be append"
            )
        entry = require_fields(
            operation["entry"],
            set(HISTORY_ENTRY_KEYS),
            f"history_operations[{index}].entry",
        )
        operations_by_history.setdefault(history, []).append(
            cast(dict[str, object], entry)
        )

    originals: dict[Path, TextSource] = {
        rules: rule_sources[rules] for rules in replacements_by_rules
    }
    candidates = {
        rules: rule_sources[rules].encode(candidate_rule_texts[rules])
        for rules in replacements_by_rules
    }
    expected_history_entries: dict[Path, list[dict[str, object]]] = {}
    for history, changed in changed_by_history.items():
        appends = operations_by_history.get(history)
        if not appends:
            raise ApplicationError(
                f"changed rules lack approved history append: {history}"
            )
        source = read_source(history, "history source")
        originals[history] = source
        existing = load_history_source(history)
        candidate_entries = [*existing, *appends]
        candidate_text = render_history(source, candidate_entries)
        validated_entries = parse_history_text(candidate_text)
        if validated_entries[: len(existing)] != existing:
            raise ApplicationError(f"history prefix changed: {history}")
        covered: set[str] = set()
        wildcard = False
        for entry in appends:
            recorded_rules = cast(list[str], entry["rules"])
            wildcard = wildcard or recorded_rules == ["*"]
            covered.update(recorded_rules)
        missing = sorted(changed - covered) if not wildcard else []
        if missing:
            raise ApplicationError(
                f"history does not cover changed rule IDs {missing}: {history}"
            )
        candidates[history] = source.encode(candidate_text)
        expected_history_entries[history] = validated_entries

    return PreparedUpdate(
        stack_paths=stack_paths,
        originals=originals,
        candidates=candidates,
        baseline_reviews=baseline_reviews,
        expected_history_entries=expected_history_entries,
    )


def staged_copy(path: Path, payload: bytes, suffix: str) -> Path:
    """Create a same-directory durable temp that retains source metadata."""
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.rules-update.", suffix=suffix, dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    shutil.copy2(path, temporary)
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return temporary


def rollback(
    applied: list[Path],
    backups: dict[Path, Path],
    originals: dict[Path, TextSource],
) -> list[str]:
    """Restore every replaced target and verify its exact original bytes."""
    failures: list[str] = []
    for path in reversed(applied):
        try:
            os.replace(backups[path], path)
        except OSError:
            failures.append(str(path))
    for path, source in originals.items():
        try:
            if path.read_bytes() != source.raw and str(path) not in failures:
                failures.append(str(path))
        except OSError:
            if str(path) not in failures:
                failures.append(str(path))
    return failures


def revalidate(update: PreparedUpdate) -> None:
    """Reopen committed targets and repeat shared validation and byte checks."""
    for path, expected in update.candidates.items():
        if path.read_bytes() != expected:
            raise ApplicationError(f"post-write bytes differ: {path}")
    reopened_rules = {
        path: read_source(path, "rules source").text
        for path in update.stack_paths
    }
    _, _, reviews = validate_stack_texts(
        update.stack_paths,
        reopened_rules,
        label="invalid reopened rule stack",
    )
    if reviews - update.baseline_reviews:
        raise ApplicationError("reopened rule stack adds a semantic review")
    for history, expected_entries in update.expected_history_entries.items():
        if load_history_source(history) != expected_entries:
            raise ApplicationError(f"reopened history differs: {history}")


def commit(update: PreparedUpdate) -> None:
    """Replace every target with rollback on write or post-write failure."""
    targets = sorted(update.candidates, key=lambda path: str(path).lower())
    backups: dict[Path, Path] = {}
    staged: dict[Path, Path] = {}
    applied: list[Path] = []
    try:
        for path in targets:
            backups[path] = staged_copy(path, update.originals[path].raw, ".bak")
            staged[path] = staged_copy(path, update.candidates[path], ".new")
        for path in targets:
            if path.read_bytes() != update.originals[path].raw:
                raise ApplicationError(f"source changed before commit: {path}")
        for path in targets:
            if path.read_bytes() != update.originals[path].raw:
                raise ApplicationError(f"source changed during commit: {path}")
            applied.append(path)
            os.replace(staged[path], path)
        revalidate(update)
    except (Exception, KeyboardInterrupt) as error:
        failures = rollback(applied, backups, update.originals)
        if failures:
            raise ApplicationError(
                f"rollback incomplete for {failures[0]}"
            ) from error
        raise ApplicationError(f"update rolled back: {error}") from error
    finally:
        for temporary in [*staged.values(), *backups.values()]:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def build_parser() -> argparse.ArgumentParser:
    """Build the single application command."""
    parser = CompactParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    return parser


def main() -> int:
    """Apply one request with decision-sized output."""
    try:
        args = build_parser().parse_args()
        request_path = args.request
        if not request_path.is_absolute():
            request_path = Path.cwd() / request_path
        update = prepare(load_request(request_path.resolve()))
        commit(update)
        print("OK")
        return 0
    except (
        ApplicationError,
        OSError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
