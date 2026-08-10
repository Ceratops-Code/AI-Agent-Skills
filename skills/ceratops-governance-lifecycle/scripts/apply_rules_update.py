#!/usr/bin/env python3
"""Apply one approved, validated champion without reformatting its text.

The UTF-8 JSON request has the closed top-level fields ``version``,
``task_temp_root``, ownership flags, ``rule_stack``, the exact validated
candidate path and hash, caller-selected validation evidence, and
``history_operations``.
``rule_stack`` lists the global source first and every source in one complete
project scope after it. The candidate is the sole replacement-text owner and
names each target, companion history, source hash, declared Markdown policy,
and every exact replacement. History operations support only an approved
``append`` entry.

This helper owns stale-text detection, structural validation, change coverage,
rollback-protected writes, and successful-request cleanup. It deletes the exact
unchanged artifacts only when the request declares workflow ownership beneath a
verified task-temp root and the transaction, reopen, and validation all pass.
Every failure preserves them for diagnosis. It invokes the shared candidate
validator in check-only mode, applies the approved replacement text unchanged,
and never reformats it. Semantic equivalence remains the calling workflow's
responsibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
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
)
from validate_rule_candidate import (
    RuleCandidateValidationError,
    TextSource,
    read_source,
    validate_rule_candidate,
    validate_stack_texts,
)

REQUEST_VERSION = 3
ROOT_FIELDS = {
    "version",
    "task_temp_root",
    "request_disposable",
    "rule_stack",
    "validated_candidate",
    "validated_candidate_sha256",
    "candidate_disposable",
    "validation_evidence",
    "validation_evidence_disposable",
    "history_operations",
}
HISTORY_OPERATION_FIELDS = {"history", "operation", "entry"}


class ApplicationError(ValueError):
    """One compact, actionable request or transaction failure."""


class CompactParser(argparse.ArgumentParser):
    """Avoid argparse's multi-line usage output for invalid invocations."""

    def error(self, message: str) -> Never:
        raise ApplicationError(message)


@dataclass
class PreparedUpdate:
    """Fully validated candidates and evidence needed for commit/reopen checks."""

    stack_paths: list[Path]
    originals: dict[Path, TextSource]
    candidates: dict[Path, bytes]
    baseline_reviews: set[str]
    expected_history_entries: dict[Path, list[dict[str, object]]]
    task_temp_root: Path
    request_disposable: bool
    candidate_path: Path
    candidate_sha256: str
    candidate_disposable: bool
    validation_evidence: Path
    validation_evidence_sha256: str
    validation_evidence_disposable: bool
    policy_hashes: dict[Path, str]


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


def absolute_path(path: Path) -> Path:
    """Return a lexical absolute path without resolving links."""

    return Path(os.path.abspath(path.expanduser()))


def is_link(path: Path) -> bool:
    """Treat symbolic links and Windows junctions as cleanup escapes."""

    junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(junction and junction())


def reject_link_chain(path: Path, label: str) -> None:
    """Reject link-based escapes before reading or deleting a request."""

    for candidate in (path, *path.parents):
        if is_link(candidate):
            raise ApplicationError(
                f"{label} uses a symlink or junction: {candidate}"
            )


def inside_git_worktree(directory: Path, label: str) -> bool:
    """Return whether Git classifies a cleanup location as repository state."""

    try:
        result = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--show-toplevel"],
            cwd=directory,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise ApplicationError(f"could not verify {label}: {error}") from error
    return result.returncode == 0


def verified_task_temp_root(value: object) -> Path:
    """Validate the caller-declared non-repository cleanup boundary."""

    if not isinstance(value, str) or not value:
        raise ApplicationError("task_temp_root must be a non-empty path")
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raise ApplicationError("task_temp_root must be absolute")
    lexical = absolute_path(raw)
    reject_link_chain(lexical, "task_temp_root")
    if not lexical.is_dir():
        raise ApplicationError("task_temp_root must be an existing directory")
    resolved = lexical.resolve(strict=True)
    if inside_git_worktree(resolved, "task_temp_root"):
        raise ApplicationError("task_temp_root must not be inside a Git worktree")
    return resolved


def workflow_artifact(path: Path, task_temp_root: Path, label: str) -> Path:
    """Validate one exact disposable artifact without deriving its name."""

    lexical = absolute_path(path)
    try:
        relative = lexical.relative_to(task_temp_root)
    except ValueError as error:
        raise ApplicationError(f"disposable {label} escapes task_temp_root") from error
    if not relative.parts:
        raise ApplicationError(f"disposable {label} must be beneath task_temp_root")
    current = task_temp_root
    for part in relative.parts:
        current = current / part
        if is_link(current):
            raise ApplicationError(
                f"disposable {label} uses a symlink or junction: {current}"
            )
    if not lexical.is_file():
        raise ApplicationError(
            f"disposable {label} is not a regular file: {lexical}"
        )
    if inside_git_worktree(lexical.parent, f"disposable {label}"):
        raise ApplicationError(
            f"disposable {label} must not be a repository file"
        )
    if lexical.resolve(strict=True).parent != lexical.parent.resolve(strict=True):
        raise ApplicationError(
            f"disposable {label} resolves outside its directory"
        )
    return lexical


def file_hash(path: Path) -> str:
    """Hash the request so successful cleanup cannot delete changed content."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finding_text(prefix: str, finding: dict[str, object]) -> str:
    """Compress one validator finding without dumping the full graph."""
    code = finding.get("code", "unknown")
    rule = f" rule={finding['rule_id']}" if "rule_id" in finding else ""
    target = f" target={finding['target']}" if "target" in finding else ""
    source = finding.get("source")
    line = finding.get("line")
    location = f" {source}:{line}" if source and line else ""
    return f"{prefix}: {code}{rule}{target}{location}"


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
    task_temp_root = verified_task_temp_root(request["task_temp_root"])
    request_disposable = request["request_disposable"]
    if not isinstance(request_disposable, bool):
        raise ApplicationError("request_disposable must be boolean")
    stack_values = request["rule_stack"]
    if not isinstance(stack_values, list) or not stack_values:
        raise ApplicationError("rule_stack must be a non-empty list")
    stack_paths = [
        require_path(value, f"rule_stack[{index}]")
        for index, value in enumerate(stack_values)
    ]
    if len(stack_paths) != len(set(stack_paths)):
        raise ApplicationError("rule_stack paths must be unique")

    candidate_path = require_path(
        request["validated_candidate"],
        "validated_candidate",
    )
    expected_candidate_hash = request["validated_candidate_sha256"]
    if (
        not isinstance(expected_candidate_hash, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_candidate_hash)
    ):
        raise ApplicationError("validated_candidate_sha256 is invalid")
    if not candidate_path.is_file():
        raise ApplicationError(f"validated_candidate does not exist: {candidate_path}")
    if file_hash(candidate_path) != expected_candidate_hash:
        raise ApplicationError("validated_candidate_sha256 is stale")
    validation_evidence = require_path(
        request["validation_evidence"],
        "validation_evidence",
    )
    if not validation_evidence.parent.is_dir():
        raise ApplicationError("validation_evidence directory does not exist")
    if validation_evidence == candidate_path:
        raise ApplicationError("validation_evidence must differ from candidate")
    candidate_disposable = request["candidate_disposable"]
    evidence_disposable = request["validation_evidence_disposable"]
    if not isinstance(candidate_disposable, bool):
        raise ApplicationError("candidate_disposable must be boolean")
    if not isinstance(evidence_disposable, bool):
        raise ApplicationError("validation_evidence_disposable must be boolean")
    if candidate_disposable:
        workflow_artifact(candidate_path, task_temp_root, "candidate")

    try:
        validation = validate_rule_candidate(
            candidate_path,
            validation_evidence,
            fix=False,
        )
    except RuleCandidateValidationError as error:
        raise ApplicationError(str(error)) from error
    if validation.candidate_sha256 != expected_candidate_hash:
        raise ApplicationError("validated candidate changed during check-only validation")
    if evidence_disposable:
        workflow_artifact(validation_evidence, task_temp_root, "validation evidence")
    validation_evidence_sha256 = file_hash(validation_evidence)

    candidate_stack = validation.candidate["rule_stack"]
    if [require_path(value, "candidate rule_stack") for value in candidate_stack] != stack_paths:
        raise ApplicationError("candidate rule_stack differs from request rule_stack")
    rule_sources = {
        path: read_source(path, "rules source") for path in stack_paths
    }
    baseline_parsed, _, baseline_reviews = validate_stack_texts(
        stack_paths,
        {path: source.text for path, source in rule_sources.items()},
        label="invalid current rule stack",
        # Candidate validation remains strict, so a transaction can proceed
        # from an invalid baseline only when it resolves every finding.
        allow_findings=True,
    )

    history_by_rules: dict[Path, Path] = {}
    policy_hashes: dict[Path, str] = {}
    targets = validation.candidate["targets"]
    if not isinstance(targets, list) or not targets:
        raise ApplicationError("validated candidate has no targets")
    for index, target in enumerate(targets):
        if not isinstance(target, dict):
            raise ApplicationError(f"candidate target {index} must be an object")
        rules = require_path(target["rules"], f"candidate target {index}.rules")
        if target["history"] is None:
            raise ApplicationError(
                f"candidate target lacks companion history: {rules}"
            )
        history = require_path(
            target["history"], f"candidate target {index}.history"
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
        policy = target["markdown_policy"]
        if not isinstance(policy, dict):
            raise ApplicationError(f"candidate target {index} policy is invalid")
        configuration = require_path(
            policy["configuration"],
            f"candidate target {index}.markdown_policy.configuration",
        )
        configuration_hash = policy["configuration_sha256"]
        if not isinstance(configuration_hash, str):
            raise ApplicationError(
                f"candidate target {index} policy hash is invalid"
            )
        prior_policy = policy_hashes.setdefault(configuration, configuration_hash)
        if prior_policy != configuration_hash:
            raise ApplicationError(
                f"candidate has conflicting policy hashes: {configuration}"
            )

    candidate_rule_texts = {
        path: source.text for path, source in rule_sources.items()
    }
    candidate_rule_texts.update(validation.prospective_texts)
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
        rules: rule_sources[rules] for rules in history_by_rules
    }
    candidates = {
        rules: rule_sources[rules].encode(candidate_rule_texts[rules])
        for rules in history_by_rules
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

    for governed_path in {*stack_paths, *originals}:
        try:
            governed_path.relative_to(task_temp_root)
        except ValueError:
            continue
        raise ApplicationError("task_temp_root must not contain a governed target")

    return PreparedUpdate(
        stack_paths=stack_paths,
        originals=originals,
        candidates=candidates,
        baseline_reviews=baseline_reviews,
        expected_history_entries=expected_history_entries,
        task_temp_root=task_temp_root,
        request_disposable=request_disposable,
        candidate_path=candidate_path,
        candidate_sha256=expected_candidate_hash,
        candidate_disposable=candidate_disposable,
        validation_evidence=validation_evidence,
        validation_evidence_sha256=validation_evidence_sha256,
        validation_evidence_disposable=evidence_disposable,
        policy_hashes=policy_hashes,
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


def verify_application_inputs(update: PreparedUpdate) -> None:
    """Recheck the exact approved artifact and declared Markdown policies."""

    if file_hash(update.candidate_path) != update.candidate_sha256:
        raise ApplicationError("validated candidate changed before application")
    for configuration, expected_hash in update.policy_hashes.items():
        if file_hash(configuration) != expected_hash:
            raise ApplicationError(
                f"Markdown policy changed before application: {configuration}"
            )


def revalidate(update: PreparedUpdate) -> None:
    """Reopen committed targets and repeat shared validation and byte checks."""
    for path, expected in update.candidates.items():
        if path.read_bytes() != expected:
            raise ApplicationError(f"post-write bytes differ: {path}")
    verify_application_inputs(update)
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
        verify_application_inputs(update)
        for path in targets:
            backups[path] = staged_copy(path, update.originals[path].raw, ".bak")
            staged[path] = staged_copy(path, update.candidates[path], ".new")
        for path in targets:
            verify_application_inputs(update)
            if path.read_bytes() != update.originals[path].raw:
                raise ApplicationError(f"source changed before commit: {path}")
        for path in targets:
            verify_application_inputs(update)
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
        request_path = absolute_path(args.request)
        reject_link_chain(request_path, "request")
        if not request_path.is_file():
            raise ApplicationError(f"request does not exist: {request_path}")
        request_sha256 = file_hash(request_path)
        update = prepare(load_request(request_path))
        if update.request_disposable:
            request_path = workflow_artifact(
                request_path,
                update.task_temp_root,
                "request",
            )
        if request_path in {update.candidate_path, update.validation_evidence}:
            raise ApplicationError("request, candidate, and evidence paths must differ")
        commit(update)
        cleanup: list[tuple[Path, str, str]] = []
        if update.candidate_disposable:
            candidate = workflow_artifact(
                update.candidate_path,
                update.task_temp_root,
                "candidate",
            )
            cleanup.append((candidate, update.candidate_sha256, "candidate"))
        if update.validation_evidence_disposable:
            evidence = workflow_artifact(
                update.validation_evidence,
                update.task_temp_root,
                "validation evidence",
            )
            cleanup.append(
                (
                    evidence,
                    update.validation_evidence_sha256,
                    "validation evidence",
                )
            )
        if update.request_disposable:
            request_path = workflow_artifact(
                request_path,
                update.task_temp_root,
                "request",
            )
            cleanup.append((request_path, request_sha256, "request"))
        for path, expected_hash, label in cleanup:
            if file_hash(path) != expected_hash:
                raise ApplicationError(
                    f"disposable {label} changed during transaction"
                )
        for path, _, _ in cleanup:
            path.unlink()
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
