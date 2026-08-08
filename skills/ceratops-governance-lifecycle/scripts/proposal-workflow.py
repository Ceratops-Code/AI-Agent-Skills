#!/usr/bin/env python3
"""Validate and orchestrate one governance proposal iteration run.

``prepare`` validates a closed request against exact current rule text and the
existing structured history lookup, writes detailed context evidence, records
exact task-temp cleanup ownership, and opens iteration one through
``iteration_controller.py``. ``advance`` delegates the controller's atomic
submit-and-open operation. After a completed run, ``finalize`` preflights every
recorded disposable artifact, delegates controller cleanup, and removes the
remaining owned request, inputs, and evidence. User-owned or undeclared inputs
are preserved. This helper never edits a governed rule source or makes semantic
judgments, and stdout contains only the pending/status payload needed for the
next decision or ``OK``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence

REQUEST_SCHEMA = "ceratops-governance-proposal-request.v2"
CONTEXT_SCHEMA = "ceratops-governance-proposal-context.v2"
CLEANUP_SCHEMA = "ceratops-governance-proposal-cleanup.v1"
REQUEST_FIELDS = {
    "schema",
    "task_temp_root",
    "iteration_artifacts",
    "disposable_artifacts",
    "state",
    "original",
    "regressions",
    "evidence_output",
    "max_iterations",
    "mutation_authorized",
    "expected_side_effects",
    "sources",
}
SOURCE_FIELDS = {
    "rules",
    "history",
    "rule_ids",
    "expected_text",
}
CLEANUP_FIELDS = {
    "schema",
    "task_temp_root",
    "owned_artifacts",
    "protected_artifacts",
    "governed_sources",
}
OWNED_ARTIFACT_FIELDS = {"role", "path", "sha256"}
DISPOSABLE_ROLES = {
    "request",
    "original",
    "regressions",
    "evidence",
    "state",
    "iterations",
}


class ProposalWorkflowError(RuntimeError):
    """One compact request, evidence, or delegated-controller failure."""


def _read_json(path: pathlib.Path, label: str) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProposalWorkflowError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ProposalWorkflowError(f"{label} must be a JSON object")
    return value


def _closed_fields(
    value: Mapping[str, object],
    expected: set[str],
    label: str,
) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append("missing " + ", ".join(missing))
    if extra:
        details.append("unknown " + ", ".join(extra))
    raise ProposalWorkflowError(f"{label} fields are invalid: {'; '.join(details)}")


def _strings(
    value: object,
    label: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or (not value and not allow_empty)
        or not all(isinstance(item, str) and item for item in value)
    ):
        qualifier = "string list" if allow_empty else "nonempty string list"
        raise ProposalWorkflowError(f"{label} must be a {qualifier}")
    result = list(value)
    if len(result) != len(set(result)):
        raise ProposalWorkflowError(f"{label} values must be unique")
    return result


def _absolute(path: pathlib.Path) -> pathlib.Path:
    """Return a lexical absolute path without resolving links."""

    return pathlib.Path(os.path.abspath(path.expanduser()))


def _is_link(path: pathlib.Path) -> bool:
    """Treat symbolic links and Windows junctions as cleanup escapes."""

    junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(junction and junction())


def _reject_link_chain(path: pathlib.Path, label: str) -> None:
    """Reject link-based escapes before a path is trusted or deleted."""

    for candidate in (path, *path.parents):
        if _is_link(candidate):
            raise ProposalWorkflowError(
                f"{label} uses a symlink or junction: {candidate}"
            )


def _inside_git_worktree(directory: pathlib.Path, label: str) -> bool:
    """Return whether Git classifies a cleanup location as repository state."""

    try:
        result = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--show-toplevel"],
            cwd=directory,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise ProposalWorkflowError(f"could not verify {label}: {exc}") from exc
    return result.returncode == 0


def _verified_task_temp_root(value: object) -> pathlib.Path:
    """Validate the caller-declared non-repository cleanup boundary."""

    if not isinstance(value, str) or not value:
        raise ProposalWorkflowError("task_temp_root must be nonempty text")
    raw = pathlib.Path(value).expanduser()
    if not raw.is_absolute():
        raise ProposalWorkflowError("task_temp_root must be absolute")
    lexical = _absolute(raw)
    _reject_link_chain(lexical, "task_temp_root")
    if not lexical.is_dir():
        raise ProposalWorkflowError("task_temp_root must be an existing directory")
    resolved = lexical.resolve(strict=True)
    if _inside_git_worktree(resolved, "task_temp_root"):
        raise ProposalWorkflowError("task_temp_root must not be inside a Git worktree")
    return resolved


def _task_file(
    path: pathlib.Path,
    task_temp_root: pathlib.Path,
    label: str,
    *,
    must_exist: bool,
) -> pathlib.Path:
    """Validate one exact file target beneath the task-temp boundary."""

    lexical = _absolute(path)
    try:
        relative = lexical.relative_to(task_temp_root)
    except ValueError as exc:
        raise ProposalWorkflowError(f"{label} escapes task_temp_root") from exc
    if not relative.parts:
        raise ProposalWorkflowError(f"{label} must be a file beneath task_temp_root")
    current = task_temp_root
    for part in relative.parts:
        current = current / part
        if _is_link(current):
            raise ProposalWorkflowError(
                f"{label} uses a symlink or junction: {current}"
            )
    if not lexical.parent.is_dir():
        raise ProposalWorkflowError(f"{label} directory does not exist: {lexical.parent}")
    if _inside_git_worktree(lexical.parent, label):
        raise ProposalWorkflowError(f"{label} must not be a repository file")
    if must_exist:
        if not lexical.is_file():
            raise ProposalWorkflowError(f"{label} must be a regular file: {lexical}")
    elif lexical.exists() and not lexical.is_file():
        raise ProposalWorkflowError(f"{label} must be a regular file target: {lexical}")
    resolved = lexical.resolve(strict=must_exist)
    try:
        resolved.relative_to(task_temp_root)
    except ValueError as exc:
        raise ProposalWorkflowError(f"{label} resolves outside task_temp_root") from exc
    return lexical


def _task_directory(
    path: pathlib.Path,
    task_temp_root: pathlib.Path,
    label: str,
    *,
    may_exist: bool,
) -> pathlib.Path:
    """Validate the exact controller artifact directory without naming inference."""

    lexical = _absolute(path)
    try:
        relative = lexical.relative_to(task_temp_root)
    except ValueError as exc:
        raise ProposalWorkflowError(f"{label} escapes task_temp_root") from exc
    if not relative.parts:
        raise ProposalWorkflowError(f"{label} must be beneath task_temp_root")
    current = task_temp_root
    for part in relative.parts:
        current = current / part
        if _is_link(current):
            raise ProposalWorkflowError(
                f"{label} uses a symlink or junction: {current}"
            )
    if not lexical.parent.is_dir():
        raise ProposalWorkflowError(f"{label} parent does not exist: {lexical.parent}")
    if lexical.exists():
        if not may_exist:
            raise ProposalWorkflowError(f"refusing existing {label}: {lexical}")
        if not lexical.is_dir():
            raise ProposalWorkflowError(f"{label} must be a directory: {lexical}")
    probe = lexical if lexical.is_dir() else lexical.parent
    if _inside_git_worktree(probe, label):
        raise ProposalWorkflowError(f"{label} must not be inside a Git worktree")
    return lexical


def _input_path(value: object, label: str) -> pathlib.Path:
    if not isinstance(value, str) or not value:
        raise ProposalWorkflowError(f"{label} must be nonempty text")
    path = _absolute(pathlib.Path(value))
    _reject_link_chain(path, label)
    if not path.is_file():
        raise ProposalWorkflowError(f"{label} must be a regular file: {path}")
    return path.resolve(strict=True)


def _file_hash(path: pathlib.Path) -> str:
    """Hash one owned artifact without loading it all into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_sha256(value: object) -> bool:
    """Recognize the lowercase digest form written by this workflow."""

    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _run_helper(script: str, arguments: Sequence[str]) -> str:
    path = pathlib.Path(__file__).with_name(script)
    if not path.is_file():
        raise ProposalWorkflowError(f"required helper is missing: {script}")
    try:
        result = subprocess.run(
            [sys.executable, str(path), *arguments],
            cwd=path.parent,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise ProposalWorkflowError(f"could not run {script}: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        if detail.startswith("ERROR: "):
            detail = detail[7:]
        raise ProposalWorkflowError(
            f"{script} failed: {detail}" if detail else f"{script} failed"
        )
    return result.stdout.strip()


def _write_json_atomic(path: pathlib.Path, value: Mapping[str, object]) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, separators=(",", ":"))
            handle.write("\n")
        os.replace(temp_name, path)
    except OSError as exc:
        raise ProposalWorkflowError(f"could not write workflow JSON: {exc}") from exc
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _validated_request(path: pathlib.Path) -> dict[str, object]:
    request_path = _input_path(str(path), "request")
    request = _read_json(request_path, "request")
    _closed_fields(request, REQUEST_FIELDS, "request")
    if request.get("schema") != REQUEST_SCHEMA:
        raise ProposalWorkflowError(f"request schema must be {REQUEST_SCHEMA}")
    task_temp_root = _verified_task_temp_root(request["task_temp_root"])
    state_value = request["state"]
    evidence_value = request["evidence_output"]
    iterations_value = request["iteration_artifacts"]
    if not isinstance(state_value, str) or not state_value:
        raise ProposalWorkflowError("state must be nonempty text")
    if not isinstance(evidence_value, str) or not evidence_value:
        raise ProposalWorkflowError("evidence_output must be nonempty text")
    if not isinstance(iterations_value, str) or not iterations_value:
        raise ProposalWorkflowError("iteration_artifacts must be nonempty text")
    state = _task_file(
        pathlib.Path(state_value),
        task_temp_root,
        "state output",
        must_exist=False,
    )
    evidence = _task_file(
        pathlib.Path(evidence_value),
        task_temp_root,
        "evidence output",
        must_exist=False,
    )
    iterations = _task_directory(
        pathlib.Path(iterations_value),
        task_temp_root,
        "iteration artifacts",
        may_exist=False,
    )
    if state.exists() or evidence.exists():
        existing = state if state.exists() else evidence
        raise ProposalWorkflowError(f"refusing to overwrite workflow output: {existing}")
    if iterations != _absolute(state.parent / "iterations"):
        raise ProposalWorkflowError(
            "iteration_artifacts must match the controller artifact directory"
        )
    disposable = set(
        _strings(request["disposable_artifacts"], "disposable_artifacts")
    )
    unknown_disposable = sorted(disposable - DISPOSABLE_ROLES)
    if unknown_disposable:
        raise ProposalWorkflowError(
            f"unknown disposable artifact role: {unknown_disposable[0]}"
        )
    missing_outputs = sorted({"state", "evidence", "iterations"} - disposable)
    if missing_outputs:
        raise ProposalWorkflowError(
            f"workflow output is not declared disposable: {missing_outputs[0]}"
        )
    if "request" in disposable:
        _task_file(
            request_path,
            task_temp_root,
            "request",
            must_exist=True,
        )
    original = _input_path(request["original"], "original")
    regression_value = request["regressions"]
    regressions = (
        None
        if regression_value is None
        else _input_path(regression_value, "regressions")
    )
    if "original" in disposable:
        _task_file(original, task_temp_root, "original", must_exist=True)
    if "regressions" in disposable:
        if regressions is None:
            raise ProposalWorkflowError(
                "regressions cannot be disposable when no regressions input exists"
            )
        _task_file(regressions, task_temp_root, "regressions", must_exist=True)
    max_iterations = request["max_iterations"]
    if (
        not isinstance(max_iterations, int)
        or isinstance(max_iterations, bool)
        or max_iterations < 1
    ):
        raise ProposalWorkflowError("max_iterations must be a positive integer")
    mutation_authorized = request["mutation_authorized"]
    if not isinstance(mutation_authorized, bool):
        raise ProposalWorkflowError("mutation_authorized must be boolean")
    side_effects = _strings(request["expected_side_effects"], "expected_side_effects")
    collisions = [request_path, state, evidence, iterations, original]
    if regressions is not None:
        collisions.append(regressions)
    if len(collisions) != len(set(collisions)):
        raise ProposalWorkflowError("state, evidence, and input paths must differ")

    raw_sources = request["sources"]
    if (
        not isinstance(raw_sources, Sequence)
        or isinstance(raw_sources, (str, bytes))
        or not raw_sources
    ):
        raise ProposalWorkflowError("sources must be a nonempty list")
    sources: list[dict[str, object]] = []
    seen_rules: set[pathlib.Path] = set()
    history_backed = 0
    for index, raw in enumerate(raw_sources, start=1):
        if not isinstance(raw, Mapping):
            raise ProposalWorkflowError(f"source {index} must be an object")
        _closed_fields(raw, SOURCE_FIELDS, f"source {index}")
        rules = _input_path(raw["rules"], f"source {index} rules")
        history_value = raw["history"]
        if history_value is None:
            history = None
            rule_ids = _strings(
                raw["rule_ids"],
                f"source {index} rule_ids",
                allow_empty=True,
            )
            if rule_ids:
                raise ProposalWorkflowError(
                    f"source {index} without history must not declare rule_ids"
                )
        else:
            history = _input_path(history_value, f"source {index} history")
            rule_ids = _strings(raw["rule_ids"], f"source {index} rule_ids")
            history_backed += 1
        if rules in seen_rules:
            raise ProposalWorkflowError(f"duplicate rules source: {rules}")
        seen_rules.add(rules)
        expected_text = _strings(
            raw["expected_text"],
            f"source {index} expected_text",
        )
        try:
            current = rules.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ProposalWorkflowError(
                f"source {index} rules are unreadable: {exc}"
            ) from exc
        text_records: list[dict[str, object]] = []
        for text in expected_text:
            count = current.count(text)
            if count != 1:
                raise ProposalWorkflowError(
                    f"source {index} expected_text must occur exactly once; found {count}"
                )
            text_records.append(
                {
                    "sha256": _hash_text(text),
                    "characters": len(text),
                }
            )
        sources.append(
            {
                "rules": str(rules),
                "history": str(history) if history is not None else None,
                "rule_ids": rule_ids,
                "expected_text": expected_text,
                "text_records": text_records,
            }
        )
    if history_backed == 0:
        raise ProposalWorkflowError(
            "at least one applicable source must include structured history"
        )
    all_inputs = {original}
    all_inputs.update(pathlib.Path(str(source["rules"])) for source in sources)
    all_inputs.update(
        pathlib.Path(str(source["history"]))
        for source in sources
        if source["history"] is not None
    )
    if regressions is not None:
        all_inputs.add(regressions)
    if state in all_inputs or evidence in all_inputs:
        raise ProposalWorkflowError("outputs must not overwrite proposal inputs")
    for source in sources:
        source_paths = [pathlib.Path(str(source["rules"]))]
        if source["history"] is not None:
            source_paths.append(pathlib.Path(str(source["history"])))
        for source_path in source_paths:
            try:
                source_path.relative_to(task_temp_root)
            except ValueError:
                continue
            raise ProposalWorkflowError(
                "task_temp_root must not contain a governed source"
            )
        rules_parent = pathlib.Path(str(source["rules"])).parent
        for output in (state, evidence):
            try:
                output.relative_to(rules_parent)
            except ValueError:
                continue
            raise ProposalWorkflowError(
                "state and evidence outputs must stay outside governed source trees"
            )
    return {
        "state": state,
        "evidence": evidence,
        "request": request_path,
        "task_temp_root": task_temp_root,
        "iterations": iterations,
        "disposable_artifacts": disposable,
        "original": original,
        "regressions": regressions,
        "max_iterations": max_iterations,
        "mutation_authorized": mutation_authorized,
        "expected_side_effects": side_effects,
        "sources": sources,
    }


def command_prepare(request_path: pathlib.Path) -> str:
    request = _validated_request(request_path)
    sources = request["sources"]
    assert isinstance(sources, list)
    lookup_arguments = ["lookup"]
    rule_ids: list[str] = []
    for source in sources:
        assert isinstance(source, Mapping)
        if source["history"] is None:
            continue
        lookup_arguments.extend(("--history", str(source["history"])))
        lookup_arguments.extend(("--rules", str(source["rules"])))
        source_ids = source["rule_ids"]
        assert isinstance(source_ids, list)
        rule_ids.extend(source_ids)
    lookup_arguments.extend(dict.fromkeys(rule_ids))
    lookup_raw = _run_helper("rule_history.py", lookup_arguments)
    try:
        lookup = json.loads(lookup_raw)
    except json.JSONDecodeError as exc:
        raise ProposalWorkflowError("rule_history.py returned invalid JSON") from exc
    if not isinstance(lookup, Mapping) or not isinstance(lookup.get("unknown"), list):
        raise ProposalWorkflowError("rule_history.py returned invalid lookup evidence")
    if lookup["unknown"]:
        raise ProposalWorkflowError(
            f"unknown target rule ID: {lookup['unknown'][0]}"
        )
    disposable = request["disposable_artifacts"]
    assert isinstance(disposable, set)
    evidence = {
        "schema": CONTEXT_SCHEMA,
        "request_schema": REQUEST_SCHEMA,
        "disposable_artifacts": sorted(disposable),
        "mutation_authorized": request["mutation_authorized"],
        "expected_side_effects": request["expected_side_effects"],
        "sources": [
            {
                "rules": source["rules"],
                "history": source["history"],
                "rule_ids": source["rule_ids"],
                "expected_text": source["text_records"],
            }
            for source in sources
        ],
        "history_lookup": lookup,
    }
    evidence_path = request["evidence"]
    state_path = request["state"]
    original = request["original"]
    regressions = request["regressions"]
    owned_request_path = request["request"]
    task_temp_root = request["task_temp_root"]
    iterations_path = request["iterations"]
    assert isinstance(evidence_path, pathlib.Path)
    assert isinstance(state_path, pathlib.Path)
    assert isinstance(original, pathlib.Path)
    assert isinstance(owned_request_path, pathlib.Path)
    assert isinstance(task_temp_root, pathlib.Path)
    assert isinstance(iterations_path, pathlib.Path)
    assert regressions is None or isinstance(regressions, pathlib.Path)
    _write_json_atomic(evidence_path, evidence)
    arguments = [
        "init",
        "--state",
        str(state_path),
        "--original",
        str(original),
        "--max-iterations",
        str(request["max_iterations"]),
        "--open-first",
    ]
    if regressions is not None:
        arguments.extend(("--regressions", str(regressions)))
    try:
        payload = _run_helper("iteration_controller.py", arguments)
    except ProposalWorkflowError:
        evidence_path.unlink(missing_ok=True)
        raise
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ProposalWorkflowError(
            "iteration_controller.py returned invalid pending JSON"
        ) from exc
    if not isinstance(parsed, Mapping):
        raise ProposalWorkflowError("iteration controller pending payload is invalid")
    for field in ("candidate", "assessment"):
        raw_pending = parsed.get(field)
        if not isinstance(raw_pending, str) or not raw_pending:
            raise ProposalWorkflowError(
                f"iteration controller pending {field} path is invalid"
            )
        pending_path = _task_file(
            pathlib.Path(raw_pending),
            task_temp_root,
            f"pending {field}",
            must_exist=False,
        )
        if pending_path.parent != iterations_path:
            raise ProposalWorkflowError(
                f"pending {field} is outside declared iteration artifacts"
            )
    controller_state = dict(_read_json(state_path, "controller state"))
    role_paths: dict[str, pathlib.Path | None] = {
        "request": owned_request_path,
        "original": original,
        "regressions": regressions,
        "evidence": evidence_path,
        "state": state_path,
        "iterations": iterations_path,
    }
    owned_artifacts: list[dict[str, object]] = []
    protected_artifacts: list[str] = []
    for role, artifact_path in role_paths.items():
        if artifact_path is None:
            continue
        if role in disposable:
            owned_artifacts.append(
                {
                    "role": role,
                    "path": str(artifact_path),
                    "sha256": (
                        None
                        if role in {"state", "iterations"}
                        else _file_hash(artifact_path)
                    ),
                }
            )
        elif role in {"request", "original", "regressions"}:
            protected_artifacts.append(str(artifact_path))
    governed_sources: list[str] = []
    for source in sources:
        assert isinstance(source, Mapping)
        governed_sources.append(str(source["rules"]))
        if source["history"] is not None:
            governed_sources.append(str(source["history"]))
    controller_state["proposal_cleanup"] = {
        "schema": CLEANUP_SCHEMA,
        "task_temp_root": str(task_temp_root),
        "owned_artifacts": owned_artifacts,
        "protected_artifacts": protected_artifacts,
        "governed_sources": governed_sources,
    }
    _write_json_atomic(state_path, controller_state)
    return json.dumps(parsed, separators=(",", ":"))


def command_advance(
    state: pathlib.Path,
    outcome: str,
    regressions: str,
) -> str:
    resolved_state = _input_path(str(state), "state")
    payload = _run_helper(
        "iteration_controller.py",
        [
            "advance",
            "--state",
            str(resolved_state),
            "--outcome",
            outcome,
            "--regressions",
            regressions,
        ],
    )
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ProposalWorkflowError(
            "iteration_controller.py returned invalid status JSON"
        ) from exc
    if not isinstance(parsed, Mapping):
        raise ProposalWorkflowError("iteration controller status payload is invalid")
    return json.dumps(parsed, separators=(",", ":"))


def _validated_cleanup(
    raw: object,
    *,
    state_path: pathlib.Path,
) -> dict[str, object]:
    """Revalidate prepare-time ownership before any finalization deletion."""

    if not isinstance(raw, Mapping):
        raise ProposalWorkflowError("proposal cleanup must be an object")
    _closed_fields(raw, CLEANUP_FIELDS, "proposal cleanup")
    if raw.get("schema") != CLEANUP_SCHEMA:
        raise ProposalWorkflowError(f"proposal cleanup schema must be {CLEANUP_SCHEMA}")
    task_temp_root = _verified_task_temp_root(raw["task_temp_root"])
    artifacts = raw["owned_artifacts"]
    if (
        not isinstance(artifacts, Sequence)
        or isinstance(artifacts, (str, bytes))
        or not artifacts
    ):
        raise ProposalWorkflowError("owned_artifacts must be a nonempty list")
    owned: list[dict[str, object]] = []
    roles: set[str] = set()
    paths: set[pathlib.Path] = set()
    for index, artifact in enumerate(artifacts, start=1):
        if not isinstance(artifact, Mapping):
            raise ProposalWorkflowError(f"owned artifact {index} must be an object")
        _closed_fields(artifact, OWNED_ARTIFACT_FIELDS, f"owned artifact {index}")
        role = artifact["role"]
        if not isinstance(role, str) or role not in DISPOSABLE_ROLES:
            raise ProposalWorkflowError(f"owned artifact {index} role is invalid")
        if role in roles:
            raise ProposalWorkflowError(f"duplicate owned artifact role: {role}")
        raw_path = artifact["path"]
        if not isinstance(raw_path, str) or not raw_path:
            raise ProposalWorkflowError(f"owned artifact {index} path is invalid")
        if role == "iterations":
            artifact_path = _task_directory(
                pathlib.Path(raw_path),
                task_temp_root,
                "owned iterations",
                may_exist=True,
            )
        else:
            artifact_path = _task_file(
                pathlib.Path(raw_path),
                task_temp_root,
                f"owned {role}",
                must_exist=role == "state",
            )
        if artifact_path in paths:
            raise ProposalWorkflowError("owned artifact paths must be unique")
        expected_hash = artifact["sha256"]
        if role in {"state", "iterations"}:
            if expected_hash is not None:
                raise ProposalWorkflowError(f"owned {role} hash must be null")
        elif not _valid_sha256(expected_hash):
            raise ProposalWorkflowError(f"owned {role} hash is invalid")
        roles.add(role)
        paths.add(artifact_path)
        owned.append(
            {"role": role, "path": artifact_path, "sha256": expected_hash}
        )
    if not {"state", "evidence", "iterations"}.issubset(roles):
        raise ProposalWorkflowError("proposal cleanup lacks owned workflow outputs")
    state_record = next(item for item in owned if item["role"] == "state")
    if state_record["path"] != state_path:
        raise ProposalWorkflowError("proposal cleanup state path is inconsistent")
    iterations_record = next(
        item for item in owned if item["role"] == "iterations"
    )
    if iterations_record["path"] != _absolute(state_path.parent / "iterations"):
        raise ProposalWorkflowError("proposal cleanup iteration path is inconsistent")
    protected = raw["protected_artifacts"]
    governed = raw["governed_sources"]
    for values, label in (
        (protected, "protected_artifacts"),
        (governed, "governed_sources"),
    ):
        if (
            not isinstance(values, Sequence)
            or isinstance(values, (str, bytes))
            or not all(isinstance(item, str) and item for item in values)
        ):
            raise ProposalWorkflowError(f"{label} must be a string list")
    protected_paths = [_absolute(pathlib.Path(item)) for item in protected]
    governed_paths = [_absolute(pathlib.Path(item)) for item in governed]
    if len(protected_paths) != len(set(protected_paths)):
        raise ProposalWorkflowError("protected_artifacts must be unique")
    if len(governed_paths) != len(set(governed_paths)):
        raise ProposalWorkflowError("governed_sources must be unique")
    if paths.intersection(protected_paths) or paths.intersection(governed_paths):
        raise ProposalWorkflowError("owned cleanup path overlaps a protected path")
    for governed_path in governed_paths:
        try:
            governed_path.relative_to(task_temp_root)
        except ValueError:
            continue
        raise ProposalWorkflowError("task_temp_root contains a governed source")
    return {
        "task_temp_root": task_temp_root,
        "owned_artifacts": owned,
        "protected_artifacts": protected_paths,
        "governed_sources": governed_paths,
    }


def _preflight_iteration_artifacts(
    state: Mapping[str, object],
    iteration_directory: pathlib.Path,
) -> None:
    """Reject changed or undeclared controller artifacts before delegation."""

    records = state.get("records")
    if not isinstance(records, list):
        raise ProposalWorkflowError("controller records must be a list")
    expected: set[pathlib.Path] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise ProposalWorkflowError("controller record must be an object")
        for field in ("candidate", "assessment"):
            raw_path = record.get(field)
            expected_hash = record.get(f"{field}_sha256")
            if not isinstance(raw_path, str) or not raw_path:
                raise ProposalWorkflowError(f"controller {field} path is invalid")
            if not _valid_sha256(expected_hash):
                raise ProposalWorkflowError(f"controller {field} hash is invalid")
            artifact = _absolute(pathlib.Path(raw_path))
            if artifact.parent != iteration_directory:
                raise ProposalWorkflowError(
                    f"controller {field} is outside declared iteration artifacts"
                )
            if artifact in expected:
                raise ProposalWorkflowError("controller artifact paths are duplicated")
            expected.add(artifact)
            if artifact.exists():
                if _is_link(artifact) or not artifact.is_file():
                    raise ProposalWorkflowError(
                        f"controller {field} is not a regular file: {artifact}"
                    )
                if _file_hash(artifact) != expected_hash:
                    raise ProposalWorkflowError(
                        f"controller {field} changed after submission"
                    )
    if iteration_directory.exists():
        for child in iteration_directory.iterdir():
            if child not in expected or _is_link(child) or not child.is_file():
                raise ProposalWorkflowError(
                    f"undeclared iteration artifact: {child}"
                )


def command_finalize(state: pathlib.Path) -> str:
    resolved_state = _input_path(str(state), "state")
    controller_state = _read_json(resolved_state, "controller state")
    if controller_state.get("complete") is not True:
        raise ProposalWorkflowError("refusing to finalize incomplete proposal")
    if controller_state.get("pending") is not None:
        raise ProposalWorkflowError("refusing to finalize a pending iteration")
    cleanup = _validated_cleanup(
        controller_state.get("proposal_cleanup"),
        state_path=resolved_state,
    )
    artifacts = cleanup["owned_artifacts"]
    assert isinstance(artifacts, list)
    iterations = next(
        artifact["path"]
        for artifact in artifacts
        if artifact["role"] == "iterations"
    )
    assert isinstance(iterations, pathlib.Path)
    _preflight_iteration_artifacts(controller_state, iterations)
    for artifact in artifacts:
        role = artifact["role"]
        path = artifact["path"]
        assert isinstance(role, str)
        assert isinstance(path, pathlib.Path)
        if role in {"state", "iterations"} or not path.exists():
            continue
        if _is_link(path) or not path.is_file():
            raise ProposalWorkflowError(f"owned {role} is not a regular file: {path}")
        if _file_hash(path) != artifact["sha256"]:
            raise ProposalWorkflowError(f"owned {role} changed after prepare")
    for artifact in artifacts:
        if artifact["role"] in {"state", "iterations"}:
            continue
        path = artifact["path"]
        assert isinstance(path, pathlib.Path)
        path.unlink(missing_ok=True)
    payload = _run_helper(
        "iteration_controller.py",
        ["finalize", "--state", str(resolved_state)],
    )
    if payload != "OK":
        raise ProposalWorkflowError("iteration_controller.py returned invalid finalization")
    return "OK"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--request", required=True, type=pathlib.Path)
    advance = commands.add_parser("advance")
    advance.add_argument("--state", required=True, type=pathlib.Path)
    advance.add_argument(
        "--outcome",
        required=True,
        choices=("improved", "no-improvement"),
    )
    advance.add_argument(
        "--regressions",
        required=True,
        choices=("passed", "failed"),
    )
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--state", required=True, type=pathlib.Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            output = command_prepare(args.request)
        elif args.command == "advance":
            output = command_advance(args.state, args.outcome, args.regressions)
        else:
            output = command_finalize(args.state)
    except (ProposalWorkflowError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
