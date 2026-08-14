#!/usr/bin/env python3
"""Select, explain, validate, and run repository tests from deterministic data.

The runner accepts only explicit full-suite, committed-revision, manifest, or
worktree modes. Worktree mode compares tracked and untracked paths with the
resolved HEAD commit; no mode is inferred from ambient state. The runner uses
Git, the checked-in impact manifest, and pytest through argv arrays; it never
invokes a shell, network client, model, prompt, agent, or semantic classifier.
A mapping gap deliberately runs every suite and returns exit code 3 when pytest
passes so CI cannot silently accept incomplete ownership data.
"""

from __future__ import annotations

import argparse
import fnmatch
import functools
import json
import pathlib
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

SCHEMA = "ai-agent-skills-test-impact-result.v1"
MANIFEST_VERSION = 1
MAPPING_GAP_EXIT_CODE = 3
CONFIGURATION_EXIT_CODE = 2
FULL_SHA = re.compile(r"[0-9a-fA-F]{40}")
STABLE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class ImpactError(RuntimeError):
    """Report invalid deterministic input without falling back heuristically."""


@dataclass(frozen=True)
class Suite:
    """One test owner and its declared dependency edges."""

    suite_id: str
    pytest: tuple[str, ...]
    depends_on: tuple[str, ...]


@dataclass(frozen=True)
class Rule:
    """Map repository path globs to an intentional suite fan-out."""

    rule_id: str
    paths: tuple[str, ...]
    suites: tuple[str, ...]


@dataclass(frozen=True)
class Ignore:
    """Exclude non-executable repository metadata with an auditable reason."""

    ignore_id: str
    paths: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class Manifest:
    """Validated in-memory representation of ``tests/test-impact.json``."""

    suites: dict[str, Suite]
    rules: tuple[Rule, ...]
    full_suite_paths: tuple[str, ...]
    ignored_paths: tuple[Ignore, ...]
    unmapped_production: str


@dataclass(frozen=True)
class ChangedFile:
    """One Git name-status record, retaining both copy or rename paths."""

    status: str
    paths: tuple[str, ...]

    def payload(self) -> dict[str, object]:
        return {"paths": list(self.paths), "status": self.status}


@dataclass(frozen=True, order=True)
class SelectionReason:
    """Tie every selected suite to one path and deterministic rule."""

    suite: str
    path: str | None
    rule: str

    def explanation(self) -> str:
        if self.rule == "--all":
            return f"{self.suite} selected because --all requested the full suite."
        if self.rule.startswith("dependency:"):
            parent = self.rule.split(":", 1)[1]
            return (
                f"{self.suite} selected because {self.path} selected dependency "
                f"{parent}."
            )
        if self.rule.startswith("test-owner:"):
            return f"{self.suite} selected because {self.path} is owned by {self.suite}."
        if self.rule.startswith("mapping-gap:"):
            return (
                f"{self.suite} selected because {self.path} triggered full-suite "
                "fallback for a mapping gap."
            )
        return f"{self.suite} selected because {self.path} matched {self.rule}."

    def payload(self) -> dict[str, object]:
        return {
            "explanation": self.explanation(),
            "path": self.path,
            "rule": self.rule,
            "suite": self.suite,
        }


@dataclass(frozen=True)
class Selection:
    """Complete deterministic selection result before collection and execution."""

    suites: tuple[str, ...]
    pytest_targets: tuple[str, ...]
    reasons: tuple[SelectionReason, ...]
    mapping_gaps: tuple[dict[str, str], ...]
    ignored: tuple[dict[str, str], ...]
    full_suite: bool
    full_suite_fallback: bool


TextRunner = Callable[
    [Sequence[str], pathlib.Path], subprocess.CompletedProcess[str]
]
BytesRunner = Callable[
    [Sequence[str], pathlib.Path], subprocess.CompletedProcess[bytes]
]


def run_text(
    command: Sequence[str], cwd: pathlib.Path
) -> subprocess.CompletedProcess[str]:
    """Run one local argv command and capture UTF-8 diagnostics without a shell."""

    return subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def run_bytes(
    command: Sequence[str], cwd: pathlib.Path
) -> subprocess.CompletedProcess[bytes]:
    """Run one Git command while preserving NUL-delimited path records."""

    return subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        check=False,
    )


def normalize_path(value: str) -> str:
    """Return one safe forward-slash repository-relative path."""

    normalized = value.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    path = pathlib.PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ImpactError(f"invalid repository-relative path: {value!r}")
    return path.as_posix()


def normalize_pattern(value: str) -> str:
    """Validate one manifest glob without interpreting platform separators."""

    if not isinstance(value, str) or not value or "\\" in value:
        raise ImpactError(f"invalid forward-slash manifest pattern: {value!r}")
    if value.startswith("/") or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ImpactError(f"invalid repository-relative manifest pattern: {value!r}")
    return value


def path_matches(pattern: str, path: str) -> bool:
    """Match ``*`` per path segment and ``**`` across zero or more segments."""

    pattern_parts = tuple(pattern.split("/"))
    path_parts = tuple(path.split("/"))

    @functools.cache
    def match(pattern_index: int, path_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        part = pattern_parts[pattern_index]
        if part == "**":
            return match(pattern_index + 1, path_index) or (
                path_index < len(path_parts) and match(pattern_index, path_index + 1)
            )
        return (
            path_index < len(path_parts)
            and fnmatch.fnmatchcase(path_parts[path_index], part)
            and match(pattern_index + 1, path_index + 1)
        )

    return match(0, 0)
def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ImpactError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ImpactError(f"{field} must be an array of strings")
    if len(value) != len(set(value)):
        raise ImpactError(f"{field} contains duplicate values")
    return tuple(value)


def load_manifest(path: pathlib.Path) -> Manifest:
    """Parse the versioned manifest while rejecting duplicate JSON keys."""

    try:
        data = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
        )
    except (OSError, json.JSONDecodeError, ImpactError) as exc:
        raise ImpactError(f"cannot load impact manifest: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != MANIFEST_VERSION:
        raise ImpactError(f"impact manifest version must be {MANIFEST_VERSION}")
    raw_suites = data.get("suites")
    if not isinstance(raw_suites, dict) or not raw_suites:
        raise ImpactError("impact manifest suites must be a non-empty object")
    suites: dict[str, Suite] = {}
    for suite_id, raw in raw_suites.items():
        if not isinstance(suite_id, str) or not STABLE_ID.fullmatch(suite_id):
            raise ImpactError(f"invalid suite ID: {suite_id!r}")
        if not isinstance(raw, dict):
            raise ImpactError(f"suite {suite_id} must be an object")
        targets = _string_tuple(raw.get("pytest"), f"suite {suite_id}.pytest")
        if not targets:
            raise ImpactError(f"suite {suite_id}.pytest must not be empty")
        dependencies = _string_tuple(
            raw.get("depends_on"), f"suite {suite_id}.depends_on"
        )
        suites[suite_id] = Suite(suite_id, targets, dependencies)
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list):
        raise ImpactError("impact manifest rules must be an array")
    rules: list[Rule] = []
    rule_ids: set[str] = set()
    for raw in raw_rules:
        if not isinstance(raw, dict):
            raise ImpactError("each impact rule must be an object")
        rule_id = raw.get("id")
        if not isinstance(rule_id, str) or not STABLE_ID.fullmatch(rule_id):
            raise ImpactError(f"invalid rule ID: {rule_id!r}")
        if rule_id in rule_ids:
            raise ImpactError(f"duplicate rule ID: {rule_id}")
        rule_ids.add(rule_id)
        paths = tuple(
            normalize_pattern(item)
            for item in _string_tuple(raw.get("paths"), f"rule {rule_id}.paths")
        )
        selected = _string_tuple(raw.get("suites"), f"rule {rule_id}.suites")
        if not paths or not selected:
            raise ImpactError(f"rule {rule_id} paths and suites must not be empty")
        rules.append(Rule(rule_id, paths, selected))
    full_suite_paths = tuple(
        normalize_pattern(item)
        for item in _string_tuple(data.get("full_suite_paths"), "full_suite_paths")
    )
    raw_ignored = data.get("ignored_paths", [])
    if not isinstance(raw_ignored, list):
        raise ImpactError("ignored_paths must be an array")
    ignored: list[Ignore] = []
    ignore_ids: set[str] = set()
    for raw in raw_ignored:
        if not isinstance(raw, dict):
            raise ImpactError("each ignored path group must be an object")
        ignore_id = raw.get("id")
        reason = raw.get("reason")
        if not isinstance(ignore_id, str) or not STABLE_ID.fullmatch(ignore_id):
            raise ImpactError(f"invalid ignored path ID: {ignore_id!r}")
        if ignore_id in ignore_ids:
            raise ImpactError(f"duplicate ignored path ID: {ignore_id}")
        if not isinstance(reason, str) or not reason.strip():
            raise ImpactError(f"ignored path {ignore_id} requires a reason")
        ignore_ids.add(ignore_id)
        paths = tuple(
            normalize_pattern(item)
            for item in _string_tuple(raw.get("paths"), f"ignore {ignore_id}.paths")
        )
        if not paths:
            raise ImpactError(f"ignore {ignore_id}.paths must not be empty")
        ignored.append(Ignore(ignore_id, paths, reason))
    unmapped = data.get("unmapped_production")
    if unmapped != "full-and-error":
        raise ImpactError("unmapped_production must be 'full-and-error'")
    return Manifest(
        suites=suites,
        rules=tuple(rules),
        full_suite_paths=full_suite_paths,
        ignored_paths=tuple(ignored),
        unmapped_production=unmapped,
    )


def parse_name_status_z(raw: bytes) -> tuple[ChangedFile, ...]:
    """Parse Git's NUL protocol for single-path and copy/rename records."""

    tokens = raw.split(b"\0")
    if tokens and tokens[-1] == b"":
        tokens.pop()
    records: list[ChangedFile] = []
    index = 0
    while index < len(tokens):
        header = tokens[index].decode("utf-8", "surrogateescape")
        index += 1
        inline_path: str | None = None
        if "\t" in header:
            header, inline_path = header.split("\t", 1)
        if not header or header[0] not in "ACDMRTUXB":
            raise ImpactError(f"unsupported Git name-status record: {header!r}")
        count = 2 if header[0] in "CR" else 1
        paths: list[str] = []
        if inline_path is not None:
            paths.append(normalize_path(inline_path))
        while len(paths) < count:
            if index >= len(tokens):
                raise ImpactError(f"truncated Git name-status record: {header}")
            paths.append(
                normalize_path(tokens[index].decode("utf-8", "surrogateescape"))
            )
            index += 1
        records.append(ChangedFile(header, tuple(paths)))
    return tuple(sorted(records, key=lambda item: (item.paths, item.status)))


def resolve_revision(
    repo_root: pathlib.Path, revision: str, *, runner: TextRunner = run_text
) -> str:
    """Require one exact commit SHA and prove that Git resolves it unchanged."""

    if not FULL_SHA.fullmatch(revision):
        raise ImpactError(f"revision must be a full 40-character SHA: {revision!r}")
    result = runner(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"], repo_root
    )
    resolved = result.stdout.strip().lower()
    if result.returncode != 0 or resolved != revision.lower():
        raise ImpactError(f"revision is not an exact local commit: {revision}")
    return resolved


def changed_files(
    repo_root: pathlib.Path,
    base: str,
    head: str,
    *,
    runner: BytesRunner = run_bytes,
) -> tuple[ChangedFile, ...]:
    """Read committed changes using the required merge-base Git diff protocol."""

    result = runner(
        [
            "git",
            "diff",
            "--name-status",
            "-z",
            "--find-renames",
            f"{base}...{head}",
        ],
        repo_root,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise ImpactError(f"Git diff failed: {detail or result.returncode}")
    return parse_name_status_z(result.stdout)


def resolve_worktree_base(
    repo_root: pathlib.Path, *, runner: TextRunner = run_text
) -> str:
    """Resolve the explicit worktree mode's immutable HEAD baseline."""

    result = runner(["git", "rev-parse", "--verify", "HEAD^{commit}"], repo_root)
    resolved = result.stdout.strip().lower()
    if result.returncode != 0 or not FULL_SHA.fullmatch(resolved):
        raise ImpactError("worktree mode requires a resolvable HEAD commit")
    return resolved


def worktree_changed_files(
    repo_root: pathlib.Path,
    base: str,
    *,
    runner: BytesRunner = run_bytes,
) -> tuple[ChangedFile, ...]:
    """Read tracked and untracked worktree changes relative to ``base``."""

    tracked = runner(
        [
            "git",
            "diff",
            "--name-status",
            "-z",
            "--find-renames",
            base,
            "--",
        ],
        repo_root,
    )
    if tracked.returncode != 0:
        detail = tracked.stderr.decode("utf-8", "replace").strip()
        raise ImpactError(f"worktree Git diff failed: {detail or tracked.returncode}")
    records = list(parse_name_status_z(tracked.stdout))
    records.extend(
        ChangedFile("A", (path,)) for path in untracked_paths(repo_root, runner=runner)
    )
    return tuple(sorted(records, key=lambda item: (item.paths, item.status)))


def tracked_paths(
    repo_root: pathlib.Path, *, runner: BytesRunner = run_bytes
) -> tuple[str, ...]:
    result = runner(["git", "ls-files", "-z"], repo_root)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise ImpactError(f"git ls-files failed: {detail or result.returncode}")
    return tuple(
        sorted(
            normalize_path(item.decode("utf-8", "surrogateescape"))
            for item in result.stdout.split(b"\0")
            if item
        )
    )


def untracked_paths(
    repo_root: pathlib.Path, *, runner: BytesRunner = run_bytes
) -> tuple[str, ...]:
    result = runner(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], repo_root
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise ImpactError(
            f"worktree untracked-file discovery failed: {detail or result.returncode}"
        )
    return tuple(
        sorted(
            normalize_path(item.decode("utf-8", "surrogateescape"))
            for item in result.stdout.split(b"\0")
            if item
        )
    )


def is_executable_production_path(path: str) -> bool:
    """Classify repository-controlled behavior without consulting the manifest."""

    if path == "AGENTS.md" or path.startswith("skills/"):
        return True
    if path.startswith(("deploy/", "release/", ".github/workflows/")):
        return True
    if path.startswith(("hooks/", "scripts/")) and pathlib.PurePosixPath(path).suffix in {
        ".py",
        ".ps1",
        ".sh",
        ".js",
        ".mjs",
        ".cjs",
    }:
        return True
    return path in {
        "package-lock.json",
        "package.json",
        "pyproject.toml",
        "requirements-dev.txt",
        "requirements-runtime.txt",
    }


def pattern_hits(pattern: str, paths: Iterable[str]) -> bool:
    return any(path_matches(pattern, path) for path in paths)


def owning_suites(manifest: Manifest, test_path: str) -> tuple[str, ...]:
    owners: list[str] = []
    for suite_id, suite in manifest.suites.items():
        for target in suite.pytest:
            target_path = normalize_path(target.split("::", 1)[0])
            if test_path == target_path or test_path.startswith(target_path.rstrip("/") + "/"):
                owners.append(suite_id)
                break
    return tuple(sorted(owners))


def dependency_errors(manifest: Manifest) -> list[str]:
    errors: list[str] = []
    for suite in manifest.suites.values():
        for dependency in suite.depends_on:
            if dependency not in manifest.suites:
                errors.append(
                    f"suite {suite.suite_id} references unknown dependency {dependency}"
                )
    state: dict[str, int] = {}

    def visit(suite_id: str, stack: tuple[str, ...]) -> None:
        marker = state.get(suite_id, 0)
        if marker == 2 or suite_id not in manifest.suites:
            return
        if marker == 1:
            errors.append("suite dependency cycle: " + " -> ".join((*stack, suite_id)))
            return
        state[suite_id] = 1
        for dependency in manifest.suites[suite_id].depends_on:
            visit(dependency, (*stack, suite_id))
        state[suite_id] = 2

    for suite_id in sorted(manifest.suites):
        visit(suite_id, ())
    return errors


def target_path(repo_root: pathlib.Path, target: str) -> pathlib.Path:
    relative = normalize_path(target.split("::", 1)[0])
    resolved_root = repo_root.resolve()
    resolved = (resolved_root / pathlib.PurePosixPath(relative)).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ImpactError(f"pytest target escapes repository: {target}") from exc
    return resolved


def collect_errors(
    repo_root: pathlib.Path,
    targets: Iterable[str],
    *,
    runner: TextRunner = run_text,
) -> list[str]:
    """Prove every target exists and independently collects at least one case."""

    errors: list[str] = []
    for target in sorted(set(targets)):
        try:
            path = target_path(repo_root, target)
        except ImpactError as exc:
            errors.append(str(exc))
            continue
        if not path.exists():
            errors.append(f"pytest target does not exist: {target}")
            continue
        result = runner(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", target],
            repo_root,
        )
        collected = any(
            line.startswith("tests/") and "::" in line
            for line in result.stdout.splitlines()
        )
        if result.returncode != 0 or not collected:
            detail = (result.stdout + result.stderr).strip().splitlines()
            tail = " | ".join(detail[-3:]) if detail else f"exit {result.returncode}"
            errors.append(f"pytest target does not collect: {target}: {tail}")
    return errors


def validate_manifest(
    repo_root: pathlib.Path,
    manifest: Manifest,
    *,
    collect: bool,
    include_untracked: bool = False,
    text_runner: TextRunner = run_text,
    bytes_runner: BytesRunner = run_bytes,
) -> tuple[str, ...]:
    """Validate ownership, coverage, stale globs, dependencies, and collection."""

    errors = dependency_errors(manifest)
    for rule in manifest.rules:
        for suite_id in rule.suites:
            if suite_id not in manifest.suites:
                errors.append(f"rule {rule.rule_id} references unknown suite {suite_id}")
    try:
        repository_paths = set(tracked_paths(repo_root, runner=bytes_runner))
        if include_untracked:
            repository_paths.update(untracked_paths(repo_root, runner=bytes_runner))
    except ImpactError as exc:
        return (str(exc),)
    tracked = tuple(sorted(repository_paths))
    for rule in manifest.rules:
        for pattern in rule.paths:
            if not pattern_hits(pattern, tracked):
                errors.append(f"stale rule glob {rule.rule_id}: {pattern}")
    for ignored_group in manifest.ignored_paths:
        for pattern in ignored_group.paths:
            matching = [path for path in tracked if path_matches(pattern, path)]
            if not matching:
                errors.append(
                    f"stale ignored glob {ignored_group.ignore_id}: {pattern}"
                )
            for path in matching:
                if is_executable_production_path(path):
                    errors.append(
                        "ignored executable production path "
                        f"{path}: {ignored_group.ignore_id}"
                    )
    for path in tracked:
        if not is_executable_production_path(path):
            continue
        matched_rules = [
            rule.rule_id
            for rule in manifest.rules
            if any(path_matches(pattern, path) for pattern in rule.paths)
        ]
        full = any(path_matches(pattern, path) for pattern in manifest.full_suite_paths)
        matched_ignores = [
            item.ignore_id
            for item in manifest.ignored_paths
            if any(path_matches(pattern, path) for pattern in item.paths)
        ]
        if matched_ignores and (matched_rules or full):
            errors.append(f"path is both ignored and selected: {path}")
        elif len(matched_rules) > 1:
            errors.append(
                f"ambiguous production mapping {path}: {', '.join(sorted(matched_rules))}"
            )
        elif not full and not matched_rules and not matched_ignores:
            errors.append(f"unmapped executable production path: {path}")
    test_files = sorted(
        path.relative_to(repo_root).as_posix()
        for path in (repo_root / "tests").rglob("test_*.py")
        if path.is_file()
    )
    for path in test_files:
        owners = owning_suites(manifest, path)
        if len(owners) != 1:
            errors.append(
                f"test file must have exactly one suite owner: {path}: {list(owners)}"
            )
    required_full = {
        ".github/workflows/validate.yml",
        "pyproject.toml",
        "scripts/run-tests.py",
        "scripts/validate-repository.py",
        "tests/__init__.py",
        "tests/support/example.py",
        "tests/test-impact.json",
    }
    if (repo_root / "tests" / "conftest.py").exists():
        required_full.add("tests/conftest.py")
    for path in sorted(required_full):
        if not any(path_matches(pattern, path) for pattern in manifest.full_suite_paths):
            errors.append(f"missing full-suite trigger coverage: {path}")
    if collect:
        errors.extend(
            collect_errors(
                repo_root,
                (
                    target
                    for suite in manifest.suites.values()
                    for target in suite.pytest
                ),
                runner=text_runner,
            )
        )
    return tuple(sorted(set(errors)))


def add_all_reasons(
    reasons: set[SelectionReason],
    manifest: Manifest,
    *,
    path: str | None,
    rule: str,
) -> None:
    for suite_id in manifest.suites:
        reasons.add(SelectionReason(suite_id, path, rule))


def expand_dependencies(
    manifest: Manifest, reasons: set[SelectionReason]
) -> set[SelectionReason]:
    expanded = set(reasons)
    pending = list(sorted(reasons))
    while pending:
        reason = pending.pop(0)
        for dependency in manifest.suites[reason.suite].depends_on:
            dependent = SelectionReason(
                dependency, reason.path, f"dependency:{reason.suite}"
            )
            if dependent not in expanded:
                expanded.add(dependent)
                pending.append(dependent)
                pending.sort()
    return expanded


def selection_from_changes(
    manifest: Manifest, changes: Iterable[ChangedFile]
) -> Selection:
    """Map every evaluated path, failing closed on overlap or missing ownership."""

    reasons: set[SelectionReason] = set()
    gaps: list[dict[str, str]] = []
    ignored_paths: list[dict[str, str]] = []
    full_suite = False
    fallback = False
    for changed in sorted(changes, key=lambda item: (item.paths, item.status)):
        for path in changed.paths:
            full_patterns = sorted(
                pattern
                for pattern in manifest.full_suite_paths
                if path_matches(pattern, path)
            )
            if full_patterns:
                full_suite = True
                for pattern in full_patterns:
                    add_all_reasons(
                        reasons,
                        manifest,
                        path=path,
                        rule=f"full-suite:{pattern}",
                    )
                continue
            if path.startswith("tests/"):
                owners = owning_suites(manifest, path)
                if len(owners) == 1:
                    reasons.add(
                        SelectionReason(owners[0], path, f"test-owner:{owners[0]}")
                    )
                    continue
                detail = (
                    "unmapped test path"
                    if not owners
                    else f"ambiguous test ownership: {', '.join(owners)}"
                )
                gaps.append({"path": path, "reason": detail})
                fallback = full_suite = True
                add_all_reasons(
                    reasons, manifest, path=path, rule=f"mapping-gap:{detail}"
                )
                continue
            matched_rules = sorted(
                (
                    rule
                    for rule in manifest.rules
                    if any(path_matches(pattern, path) for pattern in rule.paths)
                ),
                key=lambda item: item.rule_id,
            )
            matched_ignores = sorted(
                (
                    item
                    for item in manifest.ignored_paths
                    if any(path_matches(pattern, path) for pattern in item.paths)
                ),
                key=lambda item: item.ignore_id,
            )
            if len(matched_rules) == 1 and not matched_ignores:
                rule = matched_rules[0]
                for suite_id in rule.suites:
                    reasons.add(SelectionReason(suite_id, path, rule.rule_id))
                continue
            if not matched_rules and len(matched_ignores) == 1:
                item = matched_ignores[0]
                ignored_paths.append(
                    {"id": item.ignore_id, "path": path, "reason": item.reason}
                )
                continue
            if matched_rules and matched_ignores:
                detail = (
                    "path matches selection rules "
                    f"{', '.join(rule.rule_id for rule in matched_rules)} and ignore "
                    f"rules {', '.join(item.ignore_id for item in matched_ignores)}"
                )
            elif len(matched_rules) > 1:
                detail = "ambiguous production mapping: " + ", ".join(
                    rule.rule_id for rule in matched_rules
                )
            elif len(matched_ignores) > 1:
                detail = "ambiguous ignore mapping: " + ", ".join(
                    item.ignore_id for item in matched_ignores
                )
            else:
                detail = "unmapped repository path"
            gaps.append({"path": path, "reason": detail})
            fallback = full_suite = True
            add_all_reasons(
                reasons, manifest, path=path, rule=f"mapping-gap:{detail}"
            )
    reasons = expand_dependencies(manifest, reasons)
    suites = tuple(sorted({reason.suite for reason in reasons}))
    targets = tuple(
        sorted(
            {
                target
                for suite_id in suites
                for target in manifest.suites[suite_id].pytest
            }
        )
    )
    return Selection(
        suites=suites,
        pytest_targets=targets,
        reasons=tuple(sorted(reasons)),
        mapping_gaps=tuple(sorted(gaps, key=lambda item: (item["path"], item["reason"]))),
        ignored=tuple(
            sorted(ignored_paths, key=lambda item: (item["path"], item["id"]))
        ),
        full_suite=full_suite,
        full_suite_fallback=fallback,
    )


def all_selection(manifest: Manifest) -> Selection:
    reasons: set[SelectionReason] = set()
    add_all_reasons(reasons, manifest, path=None, rule="--all")
    reasons = expand_dependencies(manifest, reasons)
    suites = tuple(sorted(manifest.suites))
    targets = tuple(
        sorted(
            {
                target
                for suite in manifest.suites.values()
                for target in suite.pytest
            }
        )
    )
    return Selection(
        suites=suites,
        pytest_targets=targets,
        reasons=tuple(sorted(reasons)),
        mapping_gaps=(),
        ignored=(),
        full_suite=True,
        full_suite_fallback=False,
    )


def outcome_name(exit_code: int) -> str:
    if exit_code == 0:
        return "passed"
    if exit_code == 5:
        return "no-tests-collected"
    return "failed"


def base_payload(
    *,
    mode: str,
    base: str | None,
    head: str | None,
    changes: Iterable[ChangedFile] = (),
) -> dict[str, object]:
    return {
        "base": base,
        "changed": [item.payload() for item in changes],
        "full_suite": False,
        "full_suite_fallback": False,
        "head": head,
        "ignored_paths": [],
        "manifest_errors": [],
        "mapping_gaps": [],
        "mode": mode,
        "pytest": {"exit_code": None, "outcome": "not-run"},
        "pytest_targets": [],
        "schema": SCHEMA,
        "selected_suites": [],
        "selections": [],
        "status": "pending",
    }


def emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True))


def execute(
    argv: Sequence[str] | None = None,
    *,
    repo_root: pathlib.Path | None = None,
    text_runner: TextRunner = run_text,
    bytes_runner: BytesRunner = run_bytes,
) -> int:
    """Execute one explicit mode and emit exactly one stable JSON result."""

    root = (repo_root or pathlib.Path(__file__).resolve().parents[1]).resolve()
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--validate-manifest", action="store_true")
    parser.add_argument("--worktree", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    selected_modes = int(args.all) + int(args.validate_manifest) + int(args.worktree) + int(
        args.base is not None or args.head is not None
    )
    if selected_modes != 1 or ((args.base is None) != (args.head is None)):
        payload = base_payload(mode="configuration", base=args.base, head=args.head)
        payload["manifest_errors"] = [
            "choose exactly one of --all, --validate-manifest, --worktree, or "
            "--base with --head"
        ]
        payload["status"] = "configuration-error"
        emit(payload)
        return CONFIGURATION_EXIT_CODE
    mode = (
        "validate-manifest"
        if args.validate_manifest
        else "all"
        if args.all
        else "worktree"
        if args.worktree
        else "diff"
    )
    payload = base_payload(mode=mode, base=args.base, head=args.head)
    try:
        manifest = load_manifest(root / "tests" / "test-impact.json")
    except ImpactError as exc:
        payload["manifest_errors"] = [str(exc)]
        payload["status"] = "manifest-invalid"
        emit(payload)
        return CONFIGURATION_EXIT_CODE
    errors = validate_manifest(
        root,
        manifest,
        collect=args.validate_manifest,
        include_untracked=args.worktree,
        text_runner=text_runner,
        bytes_runner=bytes_runner,
    )
    if errors:
        payload["manifest_errors"] = list(errors)
        payload["status"] = "manifest-invalid"
        emit(payload)
        return CONFIGURATION_EXIT_CODE
    if args.validate_manifest:
        payload["status"] = "manifest-valid"
        emit(payload)
        return 0
    changes: tuple[ChangedFile, ...] = ()
    if args.all:
        selection = all_selection(manifest)
    elif args.worktree:
        try:
            base = resolve_worktree_base(root, runner=text_runner)
            changes = worktree_changed_files(root, base, runner=bytes_runner)
        except ImpactError as exc:
            payload["manifest_errors"] = [str(exc)]
            payload["status"] = "configuration-error"
            emit(payload)
            return CONFIGURATION_EXIT_CODE
        payload["base"] = base
        payload["head"] = "WORKTREE"
        payload["changed"] = [item.payload() for item in changes]
        selection = selection_from_changes(manifest, changes)
    else:
        try:
            base = resolve_revision(root, args.base, runner=text_runner)
            head = resolve_revision(root, args.head, runner=text_runner)
            changes = changed_files(root, base, head, runner=bytes_runner)
        except ImpactError as exc:
            payload["manifest_errors"] = [str(exc)]
            payload["status"] = "configuration-error"
            emit(payload)
            return CONFIGURATION_EXIT_CODE
        payload["base"] = base
        payload["head"] = head
        payload["changed"] = [item.payload() for item in changes]
        selection = selection_from_changes(manifest, changes)
    payload.update(
        {
            "full_suite": selection.full_suite,
            "full_suite_fallback": selection.full_suite_fallback,
            "ignored_paths": list(selection.ignored),
            "mapping_gaps": list(selection.mapping_gaps),
            "pytest_targets": list(selection.pytest_targets),
            "selected_suites": list(selection.suites),
            "selections": [reason.payload() for reason in selection.reasons],
        }
    )
    if not selection.pytest_targets:
        payload["status"] = "no-tests-selected"
        emit(payload)
        return 0
    collection = collect_errors(root, selection.pytest_targets, runner=text_runner)
    if collection:
        payload["manifest_errors"] = collection
        payload["status"] = "collection-invalid"
        emit(payload)
        return CONFIGURATION_EXIT_CODE
    result = text_runner(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *selection.pytest_targets,
        ],
        root,
    )
    pytest_payload: dict[str, object] = {
        "exit_code": result.returncode,
        "outcome": outcome_name(result.returncode),
    }
    if result.returncode != 0:
        pytest_payload["stderr"] = result.stderr
        pytest_payload["stdout"] = result.stdout
    payload["pytest"] = pytest_payload
    if result.returncode != 0:
        payload["status"] = "pytest-failed"
        emit(payload)
        return result.returncode if result.returncode > 0 else 1
    if selection.mapping_gaps:
        payload["status"] = "mapping-gap"
        emit(payload)
        return MAPPING_GAP_EXIT_CODE
    payload["status"] = "passed"
    emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(execute())
