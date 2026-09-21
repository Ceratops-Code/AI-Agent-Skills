#!/usr/bin/env python3
"""Prepare, amend, verify, and finalize one declared skill update workflow.

The helper records the caller's pre-existing Git baseline before source edits,
then verifies that only declared paths changed and that undeclared dirty state
was preserved. Selected skills may own shared sources through the repository's
section assignments and runtime payload mappings. A failed preparation may
accept monotonic request expansions without replacing that baseline or cleanup
ownership. Deterministic search evidence is reused only while its declared
inputs still match; other checks rerun. One changed in-scope snapshot may start
a correction generation after success; it invalidates the earlier success
before checks and cannot be reopened after passing. Tests belong to the
repository-declared SDLC test phase. Preparation never imports test modules.
Git whitespace preflight includes tracked and new files before declared
non-test checks, which use closed structured forms and run without a shell.
Verification owns temporary check folders and removes them on exit.
Source files are never patched, staged, committed, installed, promoted, or
rolled back. Prepare records exact cleanup ownership and an active-update
retention marker beneath the verified task temp root, verify retains detailed
evidence, and finalize is the caller's explicit signal that successful
verification and requested deployment/use are complete. Finalize removes only
recorded workflow-owned request, state, evidence, and retention-marker files,
then removes the verified task-temp root only when empty.
Supersede validates a revised request after failure, preserves the original
source baseline, and transfers cleanup ownership without deleting failed records.
Stdout is only ``OK`` and failures are one compact stderr line.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
from collections.abc import Mapping, Sequence

from runtime.managed_runtime_builder import IGNORE_NAMES, payload_parts
from skill_update_checks import (
    CheckFailure,
    UpdateExecutionError,
    _run,
    _run_check,
    validate_non_test_command,
)
from skill_update_scratch import check_environment
from skill_update_state import (
    CHECK_FIELDS,
    CLEANUP_SCHEMA,
    DISPOSABLE_ROLES,
    EVIDENCE_SCHEMA,
    GROUP_FIELDS,
    REQUEST_FIELDS,
    REQUEST_SCHEMA,
    RETENTION_MARKER,
    RETENTION_SCHEMA,
    SKILL_NAME_RE,
    STATE_SCHEMA,
    _absolute,
    _cleanup_payload,
    _closed_fields,
    _dirty_paths,
    _file_sha256,
    _finalize_primary_root,
    _git,
    _inherited_artifacts,
    _is_link,
    _is_tracked,
    _prepared_request_path,
    _read_json,
    _reject_link_chain,
    _run_bytes,
    _safe_relative,
    _snapshot,
    _string_list,
    _target,
    _task_artifact,
    _valid_sha256,
    _validate_state_fields,
    _validated_cleanup,
    _validated_evidence,
    _validated_verification,
    _verified_task_temp_root,
    _verify_task_worktree,
    _write_json_atomic,
)


def _snapshot_at_head(
    repo_root: pathlib.Path,
    head: str,
    path: str,
) -> dict[str, object]:
    """Reconstruct a clean path snapshot from the original prepared HEAD."""

    tree = _run_bytes(
        ["git", "-C", str(repo_root), "ls-tree", "-z", head, "--", path],
        cwd=repo_root,
    )
    if tree.returncode:
        detail = (tree.stderr or tree.stdout).decode("utf-8", errors="replace").strip()
        raise UpdateExecutionError(
            f"could not reconstruct original baseline for {path}: {detail}"
        )
    if not tree.stdout:
        return {
            "content": {"kind": "missing"},
            "index": "",
            "status": "",
        }
    entries = [entry for entry in tree.stdout.split(b"\0") if entry]
    if len(entries) != 1 or b"\t" not in entries[0]:
        raise UpdateExecutionError(f"original baseline is ambiguous: {path}")
    metadata, recorded_path = entries[0].split(b"\t", 1)
    try:
        mode, kind, object_id = metadata.decode("ascii").split()
    except (UnicodeDecodeError, ValueError) as exc:
        raise UpdateExecutionError(
            f"original baseline metadata is invalid: {path}"
        ) from exc
    if recorded_path != os.fsencode(path) or kind != "blob" or mode == "120000":
        raise UpdateExecutionError(
            f"added allowed path was not a regular file at prepared HEAD: {path}"
        )
    blob = _run_bytes(
        ["git", "-C", str(repo_root), "cat-file", "blob", object_id],
        cwd=repo_root,
    )
    if blob.returncode:
        detail = (blob.stderr or blob.stdout).decode("utf-8", errors="replace").strip()
        raise UpdateExecutionError(
            f"could not read original baseline for {path}: {detail}"
        )
    return {
        "content": {
            "kind": "file",
            "size": len(blob.stdout),
            "sha256": hashlib.sha256(blob.stdout).hexdigest(),
        },
        "index": f"{mode} {object_id} 0\t{path}\0",
        "status": "",
    }


def _validate_checks(
    raw_checks: object,
    repo_root: pathlib.Path,
    allowed_paths: set[str],
) -> list[dict[str, object]]:
    if (
        not isinstance(raw_checks, Sequence)
        or isinstance(raw_checks, (str, bytes))
    ):
        raise UpdateExecutionError("checks must be a list")
    checks: list[dict[str, object]] = []
    for index, raw in enumerate(raw_checks, start=1):
        if not isinstance(raw, Mapping):
            raise UpdateExecutionError(f"check {index} must be an object")
        kind = raw.get("kind")
        if kind == "pytest":
            raise UpdateExecutionError("test checks belong to repository SDLC tests")
        if not isinstance(kind, str) or kind not in CHECK_FIELDS:
            raise UpdateExecutionError(f"check {index} kind is invalid")
        _closed_fields(raw, CHECK_FIELDS[kind], f"check {index}")
        check = dict(raw)
        if kind == "command":
            # Repeated arguments are meaningful and must reach the process intact.
            argv = _string_list(raw["argv"], f"check {index} argv", unique=False)
            if any("\0" in value for value in argv):
                raise UpdateExecutionError(f"check {index} argv contains NUL")
            validate_non_test_command(argv)
            check["argv"] = argv
        else:
            pattern = raw["pattern"]
            expected = raw["expected_matches"]
            if not isinstance(pattern, str) or not pattern:
                raise UpdateExecutionError(f"check {index} pattern must be text")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise UpdateExecutionError(f"check {index} pattern is invalid: {exc}") from exc
            paths = _string_list(raw["paths"], f"check {index} paths")
            if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
                raise UpdateExecutionError(
                    f"check {index} expected_matches must be a nonnegative integer"
                )
            for path in paths:
                target = _target(repo_root, path)
                if path not in allowed_paths and (target.is_symlink() or not target.is_file()):
                    raise UpdateExecutionError(f"search path does not exist: {path}")
            check["paths"] = paths
        checks.append(check)
    return checks


def _shared_source_owners(
    repo_root: pathlib.Path, allowed: list[str], selected: set[str],
) -> set[str]:
    """Resolve selected consumers without expanding the caller's allowed paths.

    Match declarations, not existing files, so a declared new file or a staged
    deletion retains its ownership. Payload parents model recursive directory
    copies; exact source-target mappings only own their source file. The normal
    baseline checks still reject undeclared manifest or source changes.
    """

    if not selected:
        return set()
    manifest_path = _target(repo_root, "skills/skill-sections.json")
    if not manifest_path.exists():
        return set()
    manifest = _read_json(manifest_path, "section manifest")

    def mapping(name: str) -> Mapping[str, object]:
        value = manifest.get(name, {})
        if not isinstance(value, Mapping):
            raise UpdateExecutionError(f"section manifest {name} must be an object")
        return value

    sections, assignments = mapping("sections"), mapping("skills")
    actions, payloads = mapping("actions"), mapping("runtime_payloads")
    paths = {pathlib.PurePosixPath(value) for value in allowed}
    owners: set[str] = set()
    for skill in sorted(selected.intersection(assignments)):
        if "skills/skill-sections.json" in allowed:
            owners.add(skill)
        skill_actions = actions.get(skill, {})
        if not isinstance(skill_actions, Mapping):
            raise UpdateExecutionError(f"section manifest actions.{skill} must be an object")
        for names in (assignments[skill], *skill_actions.values()):
            if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
                raise UpdateExecutionError(f"section assignments for {skill} must be string lists")
            for name in names:
                source = sections.get(name)
                if not isinstance(source, str):
                    raise UpdateExecutionError(f"unknown section assignment for {skill}: {name}")
                if _safe_relative(source, "section source") in paths:
                    owners.add(skill)
        for key in ("*", skill):
            declarations = payloads.get(key, [])
            if not isinstance(declarations, list):
                raise UpdateExecutionError(f"runtime_payloads.{key} must be a list")
            for index, declaration in enumerate(declarations):
                try:
                    pattern, mapped_target = payload_parts(declaration, f"runtime_payloads.{key}[{index}]")
                except ValueError as exc:
                    raise UpdateExecutionError(str(exc)) from exc
                pattern = pattern.replace("\\", "/")
                for path in paths:
                    candidates = (path,) if mapped_target is not None else (path, *path.parents)
                    if any(
                        source != pathlib.PurePosixPath(".")
                        and ".git" not in source.parts
                        and source.full_match(pattern, case_sensitive=os.name != "nt")
                        and not any(part in IGNORE_NAMES for part in path.relative_to(source).parts)
                        for source in candidates
                    ):
                        owners.add(skill)
    return owners


def _validated_request(
    path: pathlib.Path,
    *,
    carried_paths: Sequence[str] = (),
) -> tuple[
    dict[str, object],
    pathlib.Path,
    pathlib.Path,
    pathlib.Path,
    set[str],
]:
    request_path = _absolute(path)
    _reject_link_chain(request_path, "request")
    if not request_path.is_file():
        raise UpdateExecutionError(f"request must be a regular file: {request_path}")
    request = _read_json(request_path, "request")
    _closed_fields(request, REQUEST_FIELDS, "request")
    if request.get("schema") != REQUEST_SCHEMA:
        raise UpdateExecutionError(f"request schema must be {REQUEST_SCHEMA}")
    repo_value = request["repo_root"]
    if not isinstance(repo_value, str) or not repo_value:
        raise UpdateExecutionError("repo_root must be nonempty text")
    repo_root = pathlib.Path(repo_value).expanduser().resolve(strict=True)
    if not repo_root.is_dir():
        raise UpdateExecutionError("repo_root must be a directory")
    branch, head = _verify_task_worktree(repo_root)
    task_temp_root = _verified_task_temp_root(request["task_temp_root"], repo_root)
    evidence_value = request["evidence_output"]
    if not isinstance(evidence_value, str) or not evidence_value:
        raise UpdateExecutionError("evidence_output must be nonempty text")
    evidence_path = _task_artifact(
        pathlib.Path(evidence_value),
        task_temp_root,
        "evidence output",
        must_exist=False,
    )
    disposable = set(
        _string_list(request["disposable_artifacts"], "disposable_artifacts")
    )
    unknown_disposable = sorted(disposable - DISPOSABLE_ROLES)
    if unknown_disposable:
        raise UpdateExecutionError(
            f"unknown disposable artifact role: {unknown_disposable[0]}"
        )
    missing_outputs = sorted({"state", "evidence"} - disposable)
    if missing_outputs:
        raise UpdateExecutionError(
            f"workflow output is not declared disposable: {missing_outputs[0]}"
        )
    if "request" in disposable:
        _task_artifact(
            request_path,
            task_temp_root,
            "request",
            must_exist=True,
        )

    selected = _string_list(request["selected_skills"], "selected_skills")
    for skill in selected:
        if SKILL_NAME_RE.fullmatch(skill) is None:
            raise UpdateExecutionError(f"selected skill name is unsafe: {skill}")
        root = repo_root / "skills" / skill
        if root.is_symlink() or not (root / "SKILL.md").is_file():
            raise UpdateExecutionError(f"selected skill is not an existing source: {skill}")

    allowed = _string_list(request["allowed_paths"], "allowed_paths")
    allowed_set = set(allowed)
    owners: set[str] = set()
    for value in allowed:
        pure = _safe_relative(value, "allowed path")
        target = _target(repo_root, value)
        matches = [
            skill
            for skill in selected
            if pure.is_relative_to(pathlib.PurePosixPath("skills") / skill)
        ]
        if matches:
            owners.update(matches)
        existing_ancillary = target.is_file() and _is_tracked(repo_root, value)
        shared_source = pure.is_relative_to(
            pathlib.PurePosixPath("skills/sections")
        )
        new_shared_source = (
            shared_source and not target.exists() and target.parent.is_dir()
        )
        # Explicitly declared repository tooling belongs to the same update as
        # its skill-owned templates. Missing files still get a baseline snapshot.
        new_maintenance = (
            pure.is_relative_to(pathlib.PurePosixPath("scripts"))
            and not target.exists() and target.parent.is_dir()
        )
        if (not matches and not existing_ancillary and not new_shared_source
                and not new_maintenance and value not in carried_paths):
            raise UpdateExecutionError(
                "allowed path must be selected-skill source, an existing "
                "tracked ancillary file, or declared new shared/maintenance source: "
                + value
            )
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise UpdateExecutionError(f"allowed path must be a regular file target: {value}")
        if not target.exists() and not target.parent.is_dir():
            raise UpdateExecutionError(f"allowed path parent does not exist: {value}")
    owners.update(_shared_source_owners(repo_root, allowed, set(selected) - owners))
    missing_owners = sorted(set(selected) - owners)
    if missing_owners:
        raise UpdateExecutionError(
            f"selected skill has no allowed source path: {missing_owners[0]}"
        )

    raw_groups = request["change_groups"]
    if (
        not isinstance(raw_groups, Sequence)
        or isinstance(raw_groups, (str, bytes))
        or not raw_groups
    ):
        raise UpdateExecutionError("change_groups must be a nonempty list")
    groups: list[dict[str, object]] = []
    covered: list[str] = []
    names: set[str] = set()
    for index, raw in enumerate(raw_groups, start=1):
        if not isinstance(raw, Mapping):
            raise UpdateExecutionError(f"change group {index} must be an object")
        _closed_fields(raw, GROUP_FIELDS, f"change group {index}")
        name = raw["name"]
        if not isinstance(name, str) or not name.strip() or name in names:
            raise UpdateExecutionError(f"change group {index} name is invalid")
        paths = _string_list(raw["paths"], f"change group {index} paths")
        unknown = sorted(set(paths) - allowed_set)
        if unknown:
            raise UpdateExecutionError(f"change group path is not allowed: {unknown[0]}")
        names.add(name)
        covered.extend(paths)
        groups.append({"name": name, "paths": paths})
    if len(covered) != len(set(covered)) or set(covered) != allowed_set:
        raise UpdateExecutionError(
            "change groups must cover every allowed path exactly once"
        )

    checks = _validate_checks(request["checks"], repo_root, allowed_set)
    dirty = sorted(_dirty_paths(repo_root))
    baseline_dirty = {path: _snapshot(repo_root, path) for path in dirty}
    baseline_targets = {path: _snapshot(repo_root, path) for path in allowed}
    state: dict[str, object] = {
        "schema": STATE_SCHEMA,
        "repo_root": str(repo_root),
        "branch": branch,
        "head": head,
        "selected_skills": selected,
        "allowed_paths": allowed,
        "change_groups": groups,
        "checks": checks,
        "baseline_dirty": baseline_dirty,
        "baseline_targets": baseline_targets,
    }
    return state, repo_root, task_temp_root, evidence_path, disposable


def command_prepare(request_path: pathlib.Path, state_path: pathlib.Path) -> None:
    state, _repo_root, task_temp_root, evidence_path, disposable = _validated_request(
        request_path
    )
    resolved_request = _absolute(request_path)
    resolved_state = _task_artifact(
        state_path,
        task_temp_root,
        "state output",
        must_exist=False,
    )
    retention_path = _task_artifact(
        task_temp_root / RETENTION_MARKER,
        task_temp_root,
        "retention marker",
        must_exist=False,
    )
    if len({resolved_request, resolved_state, evidence_path, retention_path}) != 4:
        raise UpdateExecutionError(
            "request, state, evidence, and retention paths must differ"
        )
    if resolved_state.exists():
        raise UpdateExecutionError(f"refusing to overwrite state output: {resolved_state}")
    if evidence_path.exists():
        raise UpdateExecutionError(
            f"refusing to overwrite evidence output: {evidence_path}"
        )
    if retention_path.exists():
        raise UpdateExecutionError(
            f"refusing to overwrite retention marker: {retention_path}"
        )
    try:
        _write_json_atomic(
            retention_path,
            {"schema": RETENTION_SCHEMA, "state": str(resolved_state)},
            "retention marker",
        )
        owned_artifacts: list[dict[str, object]] = [
            {
                "role": "retention",
                "path": str(retention_path),
                "sha256": _file_sha256(retention_path),
            },
            {"role": "state", "path": str(resolved_state), "sha256": None},
            {"role": "evidence", "path": str(evidence_path), "sha256": None},
        ]
        protected_artifacts: list[str] = []
        if "request" in disposable:
            owned_artifacts.insert(
                0,
                {
                    "role": "request",
                    "path": str(resolved_request),
                    "sha256": _file_sha256(resolved_request),
                },
            )
        else:
            protected_artifacts.append(str(resolved_request))
        state["cleanup"] = {
            "schema": CLEANUP_SCHEMA,
            "task_temp_root": str(task_temp_root),
            "owned_artifacts": owned_artifacts,
            "protected_artifacts": protected_artifacts,
        }
        state["verification"] = None
        _write_json_atomic(resolved_state, state, "state output")
    except (OSError, UpdateExecutionError):
        retention_path.unlink(missing_ok=True)
        raise


def _validated_state(
    path: pathlib.Path,
    *,
    mutable_request_path: pathlib.Path | None = None,
) -> dict[str, object]:
    state_path = _absolute(path)
    _reject_link_chain(state_path, "state")
    if not state_path.is_file():
        raise UpdateExecutionError(f"state must be a regular file: {state_path}")
    raw = _read_json(state_path, "state")
    _validate_state_fields(raw)
    if raw.get("schema") != STATE_SCHEMA:
        raise UpdateExecutionError(f"state schema must be {STATE_SCHEMA}")
    repo_value = raw["repo_root"]
    if not isinstance(repo_value, str) or not repo_value:
        raise UpdateExecutionError("state repo_root is invalid")
    repo_root = pathlib.Path(repo_value).resolve(strict=True)
    branch, head = _verify_task_worktree(repo_root)
    if raw["branch"] != branch:
        raise UpdateExecutionError("task branch changed after prepare")
    if raw["head"] != head and raw["verification"] is None:
        raise UpdateExecutionError("task HEAD changed before successful verification")
    allowed = _string_list(raw["allowed_paths"], "state allowed_paths")
    selected = _string_list(raw["selected_skills"], "state selected_skills")
    for skill in selected:
        if SKILL_NAME_RE.fullmatch(skill) is None:
            raise UpdateExecutionError(f"state selected skill is unsafe: {skill}")
        root = repo_root / "skills" / skill
        if root.is_symlink() or not (root / "SKILL.md").is_file():
            raise UpdateExecutionError(f"selected skill source changed after prepare: {skill}")
    baseline_targets_value = raw["baseline_targets"]
    if not isinstance(baseline_targets_value, Mapping):
        raise UpdateExecutionError("state target baseline is invalid")
    owners: set[str] = set()
    for value in allowed:
        pure = _safe_relative(value, "state allowed path")
        _target(repo_root, value)
        matches = [
            skill
            for skill in selected
            if pure.is_relative_to(pathlib.PurePosixPath("skills") / skill)
        ]
        owners.update(matches)
        snapshot = baseline_targets_value.get(value)
        content = snapshot.get("content") if isinstance(snapshot, Mapping) else None
        new_shared_source = (
            (pure.is_relative_to(pathlib.PurePosixPath("skills/sections"))
             or pure.is_relative_to(pathlib.PurePosixPath("scripts")))
            and isinstance(content, Mapping)
            and content.get("kind") == "missing"
        )
        # The index loses a staged deletion; its prepared commit retains ownership.
        if not matches and not new_shared_source and not _is_tracked(repo_root, value):
            prepared_paths = _git(
                repo_root, "ls-tree", "--name-only", "-z", str(raw["head"]), "--", value,
            ).split("\0")
            if value not in prepared_paths:
                raise UpdateExecutionError(
                    f"state ancillary path is not tracked at the prepared commit: {value}"
                )
    owners.update(_shared_source_owners(repo_root, allowed, set(selected) - owners))
    if owners != set(selected):
        raise UpdateExecutionError("state selected skills lack allowed source paths")
    cleanup = _validated_cleanup(
        raw["cleanup"],
        state_path=state_path,
        repo_root=repo_root,
    )
    if mutable_request_path is not None:
        expected_request = _prepared_request_path(cleanup)
        if _absolute(mutable_request_path) != expected_request:
            raise UpdateExecutionError("amend request differs from prepared ownership")
    verification = _validated_verification(raw["verification"])
    _inherited_artifacts(raw, cleanup, required=True)
    owned_cleanup = cleanup["owned_artifacts"]
    assert isinstance(owned_cleanup, list)
    for artifact in owned_cleanup:
        role = artifact["role"]
        if role not in {"request", "retention"}:
            continue
        owned_path = artifact["path"]
        expected_hash = artifact["sha256"]
        assert isinstance(role, str)
        assert isinstance(owned_path, pathlib.Path)
        if role == "request" and mutable_request_path is not None:
            continue
        if not owned_path.is_file() or _file_sha256(owned_path) != expected_hash:
            raise UpdateExecutionError(f"owned {role} changed after prepare")
    if verification is not None and verification["evidence_sha256"] is not None:
        evidence_record = next(
            artifact for artifact in owned_cleanup if artifact["role"] == "evidence"
        )
        evidence_path = evidence_record["path"]
        assert isinstance(evidence_path, pathlib.Path)
        _validated_evidence(
            evidence_path,
            str(verification["evidence_sha256"]),
        )
    baseline_dirty = raw["baseline_dirty"]
    baseline_targets = raw["baseline_targets"]
    if not isinstance(baseline_dirty, Mapping) or not isinstance(baseline_targets, Mapping):
        raise UpdateExecutionError("state baselines must be objects")
    if not all(
        isinstance(path, str) and isinstance(snapshot, Mapping)
        for path, snapshot in baseline_dirty.items()
    ):
        raise UpdateExecutionError("state dirty baseline is invalid")
    for raw_path in baseline_dirty:
        assert isinstance(raw_path, str)
        _target(repo_root, raw_path)
    if not all(
        isinstance(path, str) and isinstance(snapshot, Mapping)
        for path, snapshot in baseline_targets.items()
    ):
        raise UpdateExecutionError("state target baseline is invalid")
    if set(baseline_targets) != set(allowed):
        raise UpdateExecutionError("state target baseline does not match allowed_paths")
    raw_groups = raw["change_groups"]
    if not isinstance(raw_groups, list) or not raw_groups:
        raise UpdateExecutionError("state change_groups must be a nonempty list")
    groups: list[dict[str, object]] = []
    covered: list[str] = []
    names: set[str] = set()
    for index, group in enumerate(raw_groups, start=1):
        if not isinstance(group, Mapping):
            raise UpdateExecutionError(f"state change group {index} is invalid")
        _closed_fields(group, GROUP_FIELDS, f"state change group {index}")
        name = group["name"]
        paths = _string_list(group["paths"], f"state change group {index} paths")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise UpdateExecutionError(f"state change group {index} name is invalid")
        if not set(paths).issubset(allowed):
            raise UpdateExecutionError(f"state change group {index} path is not allowed")
        names.add(name)
        covered.extend(paths)
        groups.append({"name": name, "paths": paths})
    if len(covered) != len(set(covered)) or set(covered) != set(allowed):
        raise UpdateExecutionError(
            "state change groups must cover every allowed path exactly once"
        )
    checks = _validate_checks(raw["checks"], repo_root, set(allowed))
    return {
        **raw,
        "repo_root": str(repo_root),
        "selected_skills": selected,
        "allowed_paths": allowed,
        "baseline_dirty": dict(baseline_dirty),
        "baseline_targets": dict(baseline_targets),
        "change_groups": groups,
        "checks": checks,
        "cleanup": cleanup,
        "verification": verification,
    }


def _baseline_changes(state: Mapping[str, object]) -> tuple[list[str], list[dict[str, object]]]:
    repo_root = pathlib.Path(str(state["repo_root"]))
    allowed_paths = state["allowed_paths"]
    assert isinstance(allowed_paths, list)
    allowed = {str(path) for path in allowed_paths}
    baseline_dirty = state["baseline_dirty"]
    baseline_targets = state["baseline_targets"]
    assert isinstance(baseline_dirty, Mapping)
    assert isinstance(baseline_targets, Mapping)
    current_dirty = _dirty_paths(repo_root)
    undeclared_new = sorted(current_dirty - set(baseline_dirty) - allowed)
    if undeclared_new:
        raise UpdateExecutionError(f"undeclared working-tree change: {undeclared_new[0]}")
    for path, snapshot in baseline_dirty.items():
        if path in allowed:
            continue
        if _snapshot(repo_root, path) != snapshot:
            raise UpdateExecutionError(f"pre-existing dirty path changed: {path}")
    changed = sorted(
        path
        for path, snapshot in baseline_targets.items()
        if _snapshot(repo_root, path) != snapshot
    )
    if not changed:
        raise UpdateExecutionError("no declared path changed after prepare")
    group_results: list[dict[str, object]] = []
    change_groups = state["change_groups"]
    assert isinstance(change_groups, list)
    for raw_group in change_groups:
        if not isinstance(raw_group, Mapping):
            raise UpdateExecutionError("state change group is invalid")
        paths = raw_group.get("paths")
        name = raw_group.get("name")
        if not isinstance(name, str) or not isinstance(paths, list):
            raise UpdateExecutionError("state change group is invalid")
        group_changed = [path for path in paths if path in changed]
        if not group_changed:
            raise UpdateExecutionError(f"change group has no changed path: {name}")
        group_results.append({"name": name, "changed_paths": group_changed})
    return changed, group_results


def _verification_surface_sha256(state: Mapping[str, object]) -> str:
    """Hash HEAD plus every prepared or currently dirty path without judging scope."""

    repo_root = pathlib.Path(str(state["repo_root"]))
    allowed_paths = state["allowed_paths"]
    assert isinstance(allowed_paths, list)
    observed = sorted(set(allowed_paths) | _dirty_paths(repo_root))
    payload = {
        "head": _git(repo_root, "rev-parse", "HEAD").strip(),
        "paths": {path: _snapshot(repo_root, path) for path in observed},
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_descendant_scope(
    repo_root: pathlib.Path,
    prepared_head: str,
    allowed_paths: Sequence[str],
) -> None:
    """Accept only descendants whose committed paths stay in declared scope."""

    head = _git(repo_root, "rev-parse", "HEAD").strip()
    if head == prepared_head:
        return
    ancestor = _run(
        [
            "git",
            "-C",
            str(repo_root),
            "merge-base",
            "--is-ancestor",
            prepared_head,
            head,
        ],
        cwd=repo_root,
    )
    if ancestor.returncode:
        raise UpdateExecutionError("task HEAD is not a descendant of prepared HEAD")
    committed = {
        path
        for path in _git(
            repo_root,
            "diff",
            "--name-only",
            "--no-renames",
            f"{prepared_head}..{head}",
        ).splitlines()
        if path
    }
    broadened = sorted(committed - set(allowed_paths))
    if broadened:
        raise UpdateExecutionError(
            f"committed path is outside prepared scope: {broadened[0]}"
        )


def _verification_input(
    state: Mapping[str, object],
) -> tuple[str, list[str], list[dict[str, object]]]:
    """Validate and hash one complete prepared verification surface."""

    changed, groups = _baseline_changes(state)
    repo_root = pathlib.Path(str(state["repo_root"]))
    allowed_paths = state["allowed_paths"]
    assert isinstance(allowed_paths, list)
    _validate_descendant_scope(
        repo_root,
        str(state["head"]),
        [str(path) for path in allowed_paths],
    )
    return _verification_surface_sha256(state), changed, groups


def _require_monotonic_prefix(
    original: Sequence[object],
    amended: Sequence[object],
    label: str,
) -> None:
    if len(amended) < len(original) or list(amended[: len(original)]) != list(original):
        raise UpdateExecutionError(f"amendment changed existing {label}")


def _validate_amended_groups(
    original: Sequence[Mapping[str, object]],
    amended: Sequence[Mapping[str, object]],
) -> None:
    if len(amended) < len(original):
        raise UpdateExecutionError("amendment removed an existing change group")
    for index, prior in enumerate(original):
        candidate = amended[index]
        if candidate.get("name") != prior.get("name"):
            raise UpdateExecutionError("amendment changed an existing change group")
        prior_paths = prior.get("paths")
        candidate_paths = candidate.get("paths")
        if not isinstance(prior_paths, list) or not isinstance(candidate_paths, list):
            raise UpdateExecutionError("amendment change group is invalid")
        _require_monotonic_prefix(
            prior_paths,
            candidate_paths,
            "change-group paths",
        )


def command_amend(request_path: pathlib.Path, state_path: pathlib.Path) -> None:
    """Monotonically expand one failed preparation without replacing its baseline."""

    resolved_request = _absolute(request_path)
    state = _validated_state(
        state_path,
        mutable_request_path=resolved_request,
    )
    verification = state["verification"]
    if not isinstance(verification, Mapping) or verification.get("status") != "pending":
        raise UpdateExecutionError("amend requires recorded pending verification")
    evidence_sha256 = verification.get("evidence_sha256")
    if not _valid_sha256(evidence_sha256):
        raise UpdateExecutionError("pending verification lacks trusted failed evidence")
    assert isinstance(evidence_sha256, str)
    cleanup = state["cleanup"]
    assert isinstance(cleanup, Mapping)
    owned_artifacts = cleanup["owned_artifacts"]
    assert isinstance(owned_artifacts, list)
    evidence_record = next(
        artifact for artifact in owned_artifacts if artifact["role"] == "evidence"
    )
    evidence_path = evidence_record["path"]
    assert isinstance(evidence_path, pathlib.Path)
    evidence = _validated_evidence(evidence_path, evidence_sha256)
    if (
        evidence["status"] != "failed"
        or evidence["branch"] != state["branch"]
        or evidence["generation"] != verification["generation"]
        or evidence["input_sha256"] != verification["input_sha256"]
        or evidence["selected_skills"] != state["selected_skills"]
        or not evidence["failures"]
    ):
        raise UpdateExecutionError("pending evidence does not match prepared failure")

    # Prepared new paths may now exist without being staged; retain their ownership.
    carried = _string_list(state["allowed_paths"], "prepared allowed paths")
    candidate, repo_root, task_temp_root, candidate_evidence, disposable = (
        _validated_request(resolved_request, carried_paths=carried)
    )
    cleanup_root = cleanup["task_temp_root"]
    assert isinstance(cleanup_root, pathlib.Path)
    if repo_root != pathlib.Path(str(state["repo_root"])):
        raise UpdateExecutionError("amendment changed repo_root")
    if task_temp_root != cleanup_root:
        raise UpdateExecutionError("amendment changed task_temp_root")
    if candidate_evidence != evidence_path:
        raise UpdateExecutionError("amendment changed evidence ownership")
    expected_disposable = {
        str(artifact["role"])
        for artifact in owned_artifacts
        if artifact["role"] in DISPOSABLE_ROLES
    }
    if disposable != expected_disposable:
        raise UpdateExecutionError("amendment changed disposable artifact ownership")
    if candidate["branch"] != state["branch"]:
        raise UpdateExecutionError("amendment changed task branch")

    original_selected = state["selected_skills"]
    original_allowed = state["allowed_paths"]
    original_checks = state["checks"]
    original_groups = state["change_groups"]
    amended_selected = candidate["selected_skills"]
    amended_allowed = candidate["allowed_paths"]
    amended_checks = candidate["checks"]
    amended_groups = candidate["change_groups"]
    assert isinstance(original_selected, list)
    assert isinstance(original_allowed, list)
    assert isinstance(original_checks, list)
    assert isinstance(original_groups, list)
    assert isinstance(amended_selected, list)
    assert isinstance(amended_allowed, list)
    assert isinstance(amended_checks, list)
    assert isinstance(amended_groups, list)
    _require_monotonic_prefix(original_selected, amended_selected, "selected skills")
    _require_monotonic_prefix(original_allowed, amended_allowed, "allowed paths")
    _require_monotonic_prefix(original_checks, amended_checks, "checks")
    _validate_amended_groups(original_groups, amended_groups)
    if (
        amended_selected == original_selected
        and amended_allowed == original_allowed
        and amended_checks == original_checks
        and amended_groups == original_groups
    ):
        raise UpdateExecutionError("amendment does not expand prepared scope")
    _validate_descendant_scope(
        repo_root,
        str(state["head"]),
        [str(path) for path in amended_allowed],
    )

    baseline_dirty = state["baseline_dirty"]
    baseline_targets = state["baseline_targets"]
    assert isinstance(baseline_dirty, Mapping)
    assert isinstance(baseline_targets, Mapping)
    amended_targets = dict(baseline_targets)
    for path in amended_allowed[len(original_allowed) :]:
        assert isinstance(path, str)
        if path in baseline_dirty:
            amended_targets[path] = baseline_dirty[path]
        else:
            amended_targets[path] = _snapshot_at_head(
                repo_root,
                str(state["head"]),
                path,
            )

    amended_state = {
        **state,
        "selected_skills": amended_selected,
        "allowed_paths": amended_allowed,
        "change_groups": amended_groups,
        "checks": amended_checks,
        "baseline_targets": amended_targets,
    }
    amended_state["verification"] = {
        "status": "pending",
        "evidence_sha256": evidence_sha256,
        "input_sha256": _verification_surface_sha256(amended_state),
        "generation": verification["generation"],
    }
    for artifact in owned_artifacts:
        if artifact["role"] == "request":
            artifact["sha256"] = _file_sha256(resolved_request)
    amended_state["cleanup"] = _cleanup_payload(cleanup)
    _write_json_atomic(_absolute(state_path), amended_state, "state output")


def _check_whitespace(
    repo_root: pathlib.Path, prepared_head: str, changed: Sequence[str],
) -> None:
    """Check Git whitespace before tests, without staging or rewriting files."""

    for options in ([], ["--cached"]):
        _git(repo_root, "diff", "--check", *options, prepared_head, "--", *changed)
    # Ordinary diffs omit new files. Git's no-index check preserves its native
    # whitespace policy; exit 1 denotes a clean difference, while errors use 2+.
    untracked = _git(repo_root, "ls-files", "--others", "-z", "--", *changed)
    for path in filter(None, untracked.split("\0")):
        result = _run(
            ["git", "diff", "--no-index", "--check", "--", "/dev/null", path],
            cwd=repo_root,
        )
        if result.returncode not in (0, 1):
            detail = (result.stdout or result.stderr).strip()
            raise UpdateExecutionError(f"Git whitespace check failed for {path}: {detail}")


def _search_applicability_sha256(
    repo_root: pathlib.Path,
    check: Mapping[str, object],
) -> str:
    """Hash every deterministic input consumed by one declared search."""

    paths = check.get("paths")
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise UpdateExecutionError("state search check is invalid")
    payload = {
        "check": dict(check),
        "paths": {path: _snapshot(repo_root, path) for path in paths},
        "python": list(sys.version_info[:3]),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _result_matches_check(
    check: Mapping[str, object],
    result: Mapping[str, object],
) -> bool:
    """Match successful evidence to the exact structured check that produced it."""

    kind = check.get("kind")
    if result.get("kind") != kind or result.get("returncode") != 0:
        return False
    if kind == "command":
        return result.get("argv") == check.get("argv")
    if kind != "search":
        return False
    return (
        result.get("pattern") == check.get("pattern")
        and result.get("paths") == check.get("paths")
        and result.get("expected_matches") == check.get("expected_matches")
        and result.get("actual_matches") == check.get("expected_matches")
        and _valid_sha256(result.get("applicability_sha256"))
    )


def _reusable_check_results(
    state: Mapping[str, object],
    evidence_path: pathlib.Path,
) -> dict[int, dict[str, object]]:
    """Reuse only successful searches whose exact declared inputs still match."""

    verification = state["verification"]
    if not isinstance(verification, Mapping):
        return {}
    evidence_sha256 = verification.get("evidence_sha256")
    if (
        verification.get("status") != "pending"
        or not _valid_sha256(evidence_sha256)
    ):
        return {}
    evidence = _validated_evidence(evidence_path, str(evidence_sha256))
    if (
        evidence["status"] != "failed"
        or evidence["branch"] != state["branch"]
        or evidence["generation"] != verification["generation"]
    ):
        return {}
    recorded_skills = evidence["selected_skills"]
    selected_skills = state["selected_skills"]
    if not isinstance(recorded_skills, list) or not isinstance(selected_skills, list):
        return {}
    if selected_skills[: len(recorded_skills)] != recorded_skills:
        return {}
    checks = state["checks"]
    recorded_results = evidence["checks"]
    assert isinstance(checks, list)
    assert isinstance(recorded_results, list)
    reusable: dict[int, dict[str, object]] = {}
    for index, raw_result in enumerate(recorded_results):
        if index >= len(checks) or not isinstance(raw_result, Mapping):
            break
        raw_check = checks[index]
        if not isinstance(raw_check, Mapping) or not _result_matches_check(
            raw_check,
            raw_result,
        ):
            continue
        if raw_check.get("kind") != "search":
            continue
        if _search_applicability_sha256(
            pathlib.Path(str(state["repo_root"])),
            raw_check,
        ) != raw_result.get("applicability_sha256"):
            continue
        reused = dict(raw_result)
        reused["reused"] = True
        reused["source_evidence_sha256"] = evidence_sha256
        reusable[index] = reused
    return reusable


def command_verify(state_path: pathlib.Path, evidence_path: pathlib.Path) -> None:
    state = _validated_state(state_path)
    repo_root = pathlib.Path(str(state["repo_root"]))
    cleanup = state["cleanup"]
    assert isinstance(cleanup, Mapping)
    owned_artifacts = cleanup["owned_artifacts"]
    assert isinstance(owned_artifacts, list)
    evidence_record = next(
        artifact for artifact in owned_artifacts if artifact["role"] == "evidence"
    )
    resolved_evidence = _absolute(evidence_path)
    if resolved_evidence != evidence_record["path"]:
        raise UpdateExecutionError("evidence output differs from prepared ownership")
    input_sha256 = _verification_surface_sha256(state)
    verification = state["verification"]
    generation = 0
    terminal_error: str | None = None
    reusable: dict[int, dict[str, object]] = {}
    if verification is not None:
        assert isinstance(verification, Mapping)
        status = verification["status"]
        generation = int(verification["generation"])
        if status == "invalidated":
            raise UpdateExecutionError("state is permanently invalidated")
        if status == "passed":
            if input_sha256 == verification["input_sha256"]:
                raise UpdateExecutionError(
                    "prepared scope has not changed since successful verification"
                )
            if generation == 1:
                status = "invalidated"
                terminal_error = "prepared scope changed after the correction generation"
            else:
                status = "pending"
                generation = 1
            state["verification"] = {
                "status": status,
                "evidence_sha256": None,
                "input_sha256": input_sha256,
                "generation": 1,
            }
            state["cleanup"] = _cleanup_payload(cleanup)
            _write_json_atomic(_absolute(state_path), state, "state output")
        else:
            reusable = _reusable_check_results(state, resolved_evidence)
            state["verification"] = {
                "status": "pending",
                "evidence_sha256": None,
                "input_sha256": input_sha256,
                "generation": generation,
            }
            state["cleanup"] = _cleanup_payload(cleanup)
            _write_json_atomic(_absolute(state_path), state, "state output")
    else:
        state["verification"] = {
            "status": "pending",
            "evidence_sha256": None,
            "input_sha256": input_sha256,
            "generation": 0,
        }
        state["cleanup"] = _cleanup_payload(cleanup)
        _write_json_atomic(_absolute(state_path), state, "state output")
    changed: list[str] = []
    groups: list[dict[str, object]] = []
    results: list[dict[str, object]] = []
    failures: list[str] = [terminal_error] if terminal_error else []
    if not failures:
        try:
            validated_input, changed, groups = _verification_input(state)
            if validated_input != input_sha256:
                failures.append("prepared scope changed before checks started")
            else:
                _check_whitespace(repo_root, str(state["head"]), changed)
        except UpdateExecutionError as exc:
            failures.append(str(exc))
    checks = state["checks"]
    assert isinstance(checks, list)
    try:
        if not failures:
            with check_environment(pathlib.Path(str(cleanup["task_temp_root"]))) as environment:
                for index, raw_check in enumerate(checks):
                    if not isinstance(raw_check, Mapping):
                        failures.append("state check is invalid")
                        break
                    if index in reusable:
                        results.append(reusable[index])
                        continue
                    try:
                        results.append(_run_check(
                            repo_root,
                            raw_check,
                            environment,
                            resolve_target=_target,
                            search_applicability=lambda value: (
                                _search_applicability_sha256(repo_root, value)
                            ),
                        ))
                    except CheckFailure as exc:
                        results.append(exc.evidence)
                        failures.append(str(exc))
                        break
                    except UpdateExecutionError as exc:
                        results.append({
                            "kind": raw_check.get("kind", "unknown"),
                            "error": str(exc),
                            "reused": False,
                        })
                        failures.append(str(exc))
                        break
    except OSError as exc:
        failures.append(str(exc))
    if not failures or results:
        try:
            final_input_sha256, final_changed, final_groups = _verification_input(state)
            if (
                final_input_sha256 != input_sha256
                or final_changed != changed
                or final_groups != groups
            ):
                failures.append("prepared scope changed while checks were running")
        except UpdateExecutionError as exc:
            failures.append(str(exc))
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "status": "failed" if failures else "passed",
        "branch": state["branch"],
        "head": _git(repo_root, "rev-parse", "HEAD").strip(),
        "generation": generation,
        "input_sha256": input_sha256,
        "selected_skills": state["selected_skills"],
        "changed_paths": changed,
        "change_groups": groups,
        "checks": results,
        "failures": failures,
    }
    _write_json_atomic(resolved_evidence, evidence, "evidence output")
    state["failure_evidence_sha256"] = _file_sha256(resolved_evidence) if failures else None
    if failures:
        verification = state["verification"]
        if not (
            isinstance(verification, Mapping)
            and verification.get("status") == "invalidated"
        ):
            state["verification"] = {
                "status": "pending",
                "evidence_sha256": _file_sha256(resolved_evidence),
                "input_sha256": input_sha256,
                "generation": generation,
            }
            state["cleanup"] = _cleanup_payload(cleanup)
            _write_json_atomic(_absolute(state_path), state, "state output")
        raise UpdateExecutionError(failures[0])
    state["verification"] = {
        "status": "passed",
        "evidence_sha256": _file_sha256(resolved_evidence),
        "input_sha256": input_sha256,
        "generation": generation,
    }
    state["cleanup"] = _cleanup_payload(cleanup)
    _write_json_atomic(_absolute(state_path), state, "state output")


def command_supersede(state_path: pathlib.Path, request_path: pathlib.Path, new_state_path: pathlib.Path) -> None:
    """Transfer an intact failed attempt to a revised request, without source edits.

    Validate all inputs before publishing the successor. Publish its state first
    and pivot the active marker last; rollback a caught marker-write failure.
    The predecessor's state, request and evidence remain unchanged until the
    successfully verified successor is explicitly finalized.
    """
    old = _validated_state(state_path)
    cleanup = old["cleanup"]
    assert isinstance(cleanup, Mapping)
    verification = old["verification"]
    if verification is not None:
        assert isinstance(verification, Mapping)
        if verification["status"] != "pending":
            raise UpdateExecutionError("only failed verification can be superseded")
    owned = cleanup["owned_artifacts"]
    assert isinstance(owned, list)
    if not any(item["role"] == "retention" for item in owned):
        raise UpdateExecutionError("supersede requires an active retention marker")
    evidence = next(item["path"] for item in owned if item["role"] == "evidence")
    if not old.get("failure_evidence_sha256") or not evidence.is_file():
        raise UpdateExecutionError("supersede requires recorded failed verification")
    if _file_sha256(evidence) != old["failure_evidence_sha256"]:
        raise UpdateExecutionError("failed evidence changed after recording")
    failed = _read_json(evidence, "failed evidence")
    input_hash, _, _ = _verification_input(old)
    generation = verification["generation"] if verification is not None else 0
    if (failed.get("schema") != EVIDENCE_SCHEMA or failed.get("status") != "failed"
            or failed.get("branch") != old["branch"]
            or failed.get("generation") != generation or failed.get("selected_skills") != old["selected_skills"]):
        raise UpdateExecutionError("failed evidence does not match the prepared request")
    # In-scope fixes after failure are allowed, just as for verify retries. The
    # original baseline, not the earlier failure's source snapshot, owns scope.
    # Already-created maintenance files retain their validated original owner.
    carried = _string_list(old["allowed_paths"], "prepared allowed paths")
    state, repo, root, new_evidence, disposable = _validated_request(
        request_path, carried_paths=carried,
    )
    if (state["repo_root"] != old["repo_root"] or state["branch"] != old["branch"]
            or root != cleanup["task_temp_root"]):
        raise UpdateExecutionError("successor must use the same repository, branch and task temp")
    for key in ("allowed_paths", "selected_skills"):
        previous_scope, revised_scope = old[key], state[key]
        assert isinstance(previous_scope, list) and isinstance(revised_scope, list)
        if not set(previous_scope).issubset(revised_scope):
            raise UpdateExecutionError("supersede cannot remove prepared scope")
    if all(state[key] == old[key] for key in ("allowed_paths", "selected_skills", "change_groups", "checks")):
        raise UpdateExecutionError("supersede requires a revised request; retry unchanged scope with verify")
    request = _absolute(request_path)
    destination = _task_artifact(new_state_path, root, "successor state", must_exist=False)
    inherited = _inherited_artifacts(old, cleanup, required=True)
    previous = [*inherited, *[item for item in owned if item["role"] != "retention"]]
    marker = next(item["path"] for item in owned if item["role"] == "retention")
    reserved = {item["path"] for item in previous} | set(cleanup["protected_artifacts"]) | {marker}
    if len({request, destination, new_evidence}) != 3 or reserved & {request, destination, new_evidence}:
        raise UpdateExecutionError("successor artifact paths overlap existing ownership")
    if destination.exists() or new_evidence.exists():
        raise UpdateExecutionError("refusing to overwrite successor outputs")
    # The old baseline is authoritative for carried paths and unrelated dirt.
    state["head"] = old["head"]
    state["baseline_dirty"] = old["baseline_dirty"]
    targets, previous_targets = state["baseline_targets"], old["baseline_targets"]
    assert isinstance(targets, dict) and isinstance(previous_targets, dict)
    targets.update(previous_targets)
    # The previous evidence remains inherited cleanup-owned data. It cannot
    # identify the successor's still-unwritten evidence or revised checks.
    state["verification"] = {
        "status": "pending",
        "evidence_sha256": None,
        "input_sha256": _verification_surface_sha256(state),
        "generation": generation,
    }
    state["failure_evidence_sha256"] = None
    state["superseded_artifacts"] = [
        {"path": str(item["path"]), "sha256": _file_sha256(item["path"])} for item in previous
    ]
    marker_payload = {"schema": RETENTION_SCHEMA, "state": str(destination)}
    marker_bytes = (json.dumps(marker_payload, separators=(",", ":")) + "\n").encode("utf-8")
    new_owned = [
        {"role": "retention", "path": str(marker), "sha256": hashlib.sha256(marker_bytes).hexdigest()},
        {"role": "state", "path": str(destination), "sha256": None},
        {"role": "evidence", "path": str(new_evidence), "sha256": None},
    ]
    protected = [str(path) for path in cleanup["protected_artifacts"]]
    if "request" in disposable:
        new_owned.append({"role": "request", "path": str(request), "sha256": _file_sha256(request)})
    else:
        protected.append(str(request))
    state["cleanup"] = {"schema": CLEANUP_SCHEMA, "task_temp_root": str(root),
                        "owned_artifacts": new_owned, "protected_artifacts": protected}
    # Recheck source and old ownership after collection before the marker pivot.
    _validated_state(state_path)
    if _verification_input(old)[0] != input_hash:
        raise UpdateExecutionError("prepared scope changed while supersede was preparing")
    _write_json_atomic(destination, state, "successor state")
    try:
        _write_json_atomic(marker, marker_payload, "retention marker")
    except (OSError, UpdateExecutionError):
        destination.unlink()
        raise


def command_finalize(state_path: pathlib.Path) -> None:
    """Remove exact owned artifacts after the caller signals completed use."""

    resolved_state = _absolute(state_path)
    _reject_link_chain(resolved_state, "state")
    if not resolved_state.is_file():
        raise UpdateExecutionError(f"state must be a regular file: {resolved_state}")
    raw = _read_json(resolved_state, "state")
    _validate_state_fields(raw)
    if raw.get("schema") != STATE_SCHEMA:
        raise UpdateExecutionError(f"state schema must be {STATE_SCHEMA}")
    repo_value = raw["repo_root"]
    if not isinstance(repo_value, str) or not repo_value:
        raise UpdateExecutionError("state repo_root is invalid")
    repo_path = pathlib.Path(repo_value).expanduser()
    if not repo_path.is_absolute():
        raise UpdateExecutionError("state repo_root must be absolute")
    lexical_repo = _absolute(repo_path)
    _reject_link_chain(lexical_repo, "state repo_root")
    if lexical_repo.exists() and not lexical_repo.is_dir():
        raise UpdateExecutionError("state repo_root must be a directory")
    if lexical_repo.is_dir() and any(lexical_repo.iterdir()):
        repo_root = lexical_repo.resolve(strict=True)
    else:
        # Git may unregister a worktree while Windows retains its empty directory.
        repo_root = _finalize_primary_root(raw["cleanup"])
    cleanup = _validated_cleanup(
        raw["cleanup"],
        state_path=resolved_state,
        repo_root=repo_root,
    )
    verification = _validated_verification(raw["verification"])
    if verification is None or verification["status"] != "passed":
        raise UpdateExecutionError("refusing to finalize before successful verification")
    artifacts = cleanup["owned_artifacts"]
    assert isinstance(artifacts, list)
    artifacts = [*_inherited_artifacts(raw, cleanup), *artifacts]
    for artifact in artifacts:
        role = artifact["role"]
        path = artifact["path"]
        assert isinstance(role, str)
        assert isinstance(path, pathlib.Path)
        if not path.exists():
            continue
        if _is_link(path) or not path.is_file():
            raise UpdateExecutionError(f"owned {role} is not a regular file: {path}")
        expected_hash = artifact["sha256"]
        if role == "evidence":
            expected_hash = verification["evidence_sha256"]
        if expected_hash is not None and _file_sha256(path) != expected_hash:
            raise UpdateExecutionError(f"owned {role} changed after recording")
    for artifact in artifacts:
        if artifact["role"] == "state":
            continue
        path = artifact["path"]
        assert isinstance(path, pathlib.Path)
        path.unlink(missing_ok=True)
    task_temp_root = cleanup["task_temp_root"]
    assert isinstance(task_temp_root, pathlib.Path)
    remove_task_temp_root = set(task_temp_root.iterdir()) == {resolved_state}
    resolved_state.unlink()
    if remove_task_temp_root:
        try:
            task_temp_root.rmdir()
        except OSError:
            # Preserve retryable verified state if an empty-root removal fails
            # after its preflight, such as when a concurrent file appears.
            _write_json_atomic(resolved_state, raw, "state output")
            raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--request", required=True, type=pathlib.Path)
    prepare.add_argument("--state", required=True, type=pathlib.Path)
    amend = commands.add_parser("amend")
    amend.add_argument("--request", required=True, type=pathlib.Path)
    amend.add_argument("--state", required=True, type=pathlib.Path)
    verify = commands.add_parser("verify")
    verify.add_argument("--state", required=True, type=pathlib.Path)
    verify.add_argument("--evidence-output", required=True, type=pathlib.Path)
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--state", required=True, type=pathlib.Path)
    supersede = commands.add_parser("supersede")
    supersede.add_argument("--state", required=True, type=pathlib.Path)
    supersede.add_argument("--request", required=True, type=pathlib.Path)
    supersede.add_argument("--new-state", required=True, type=pathlib.Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            command_prepare(args.request, args.state)
        elif args.command == "amend":
            command_amend(args.request, args.state)
        elif args.command == "verify":
            command_verify(args.state, args.evidence_output)
        elif args.command == "supersede":
            command_supersede(args.state, args.request, args.new_state)
        else:
            command_finalize(args.state)
    except (UpdateExecutionError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
