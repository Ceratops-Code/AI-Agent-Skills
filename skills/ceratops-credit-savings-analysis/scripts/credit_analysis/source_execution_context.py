"""Resolve and freeze source execution locations and effective Codex rules.

Recorded source directories normally remain authoritative. A shipped Codex
worktree may legitimately be deleted, so a missing canonical worktree can map
to the repository's primary checkout only when the retained repository URL and
the live checkout's ``origin`` identify the same repository. The mapping is
retained in controller evidence and revalidated before any model child starts.
Arbitrary missing paths, repository scans, and unverified fallbacks are never
allowed.

Effective instruction files are read once during planning. Their exact text and
hashes remain the analysis context for every later task; resume validates that
retained snapshot internally and does not reopen live instruction files.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import subprocess
from collections.abc import Mapping, Sequence
from typing import Any

from .single_surface_analysis import (
    CreditAnalysisError,
    _content_hash,
)


def _instruction_file(directory: pathlib.Path) -> pathlib.Path | None:
    """Resolve the standard Codex instruction file for one directory."""

    for name in ("AGENTS.override.md", "AGENTS.md"):
        candidate = directory / name
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def _instruction_chain(cwd: pathlib.Path) -> dict[str, Any]:
    """Freeze the global and root-to-cwd project AGENTS chain used by Codex."""

    resolved = cwd.expanduser().resolve(strict=True)
    if not resolved.is_dir() or resolved.is_symlink():
        raise CreditAnalysisError(f"source cwd is not a regular directory: {resolved}")
    configured_home = os.environ.get("CODEX_HOME")
    codex_home = (
        pathlib.Path(configured_home).expanduser()
        if configured_home
        else pathlib.Path.home() / ".codex"
    )
    files: list[pathlib.Path] = []
    global_file = _instruction_file(codex_home)
    if global_file is not None:
        files.append(global_file.resolve(strict=True))
    project_root = resolved
    try:
        completed = subprocess.run(
            ["git", "-C", str(resolved), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        completed = None
    if completed is not None and completed.returncode == 0 and completed.stdout.strip():
        candidate_root = pathlib.Path(completed.stdout.strip()).resolve(strict=True)
        try:
            resolved.relative_to(candidate_root)
        except ValueError:
            pass
        else:
            project_root = candidate_root
    directories = [project_root]
    if resolved != project_root:
        relative = resolved.relative_to(project_root)
        current = project_root
        for part in relative.parts:
            current = current / part
            directories.append(current)
    for directory in directories:
        local_file = _instruction_file(directory)
        if local_file is not None:
            resolved_file = local_file.resolve(strict=True)
            if resolved_file not in files:
                files.append(resolved_file)
    records: list[dict[str, Any]] = []
    for path in files:
        try:
            payload = path.read_bytes()
            text = payload.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise CreditAnalysisError(
                f"could not snapshot source instruction file: {path}"
            ) from exc
        records.append(
            {
                "path": str(path),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "text": text,
            }
        )
    return {
        "cwd": str(resolved),
        "project_root": str(project_root),
        "codex_home": str(codex_home.resolve()),
        "files": records,
        "chain_sha256": _content_hash(records),
        "total_bytes": sum(int(record["bytes"]) for record in records),
    }


def _normalize_repository_url(value: str) -> str:
    """Normalize retained and live Git repository identities for comparison."""

    normalized = value.strip().rstrip("/")
    if normalized.casefold().endswith(".git"):
        normalized = normalized[:-4]
    return normalized.casefold()


def _git_stdout(cwd: pathlib.Path, *arguments: str) -> str:
    """Return one bounded Git query or reject an unverifiable checkout."""

    try:
        completed = subprocess.run(
            ["git", "-C", str(cwd), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CreditAnalysisError(
            f"could not verify primary checkout at {cwd}: {exc}"
        ) from exc
    value = completed.stdout.strip()
    if completed.returncode or not value:
        detail = " ".join((completed.stderr or completed.stdout).split())
        raise CreditAnalysisError(
            f"could not verify primary checkout at {cwd}"
            + (f": {detail[:500]}" if detail else "")
        )
    return value


def _session_repository_url(rows: Sequence[Mapping[str, Any]]) -> str | None:
    """Return the single retained repository identity declared by a session."""

    repository_urls: dict[str, str] = {}
    for row in rows:
        if row.get("type") != "session_meta":
            continue
        payload = row.get("payload")
        if not isinstance(payload, Mapping):
            continue
        git = payload.get("git")
        if not isinstance(git, Mapping):
            continue
        value = git.get("repository_url")
        if isinstance(value, str) and value.strip():
            repository_urls.setdefault(_normalize_repository_url(value), value.strip())
    if len(repository_urls) > 1:
        raise CreditAnalysisError("source session declares conflicting repository URLs")
    return next(iter(repository_urls.values()), None)


def _verified_primary_checkout(
    recorded_cwd: pathlib.Path,
    repository_url: str,
) -> pathlib.Path:
    """Map canonical worktree topology to an identity-matched primary checkout."""

    parts = recorded_cwd.parts
    indexes = [
        index
        for index, part in enumerate(parts)
        if part.casefold() == "worktrees" and 0 < index and index + 2 < len(parts)
    ]
    if not indexes:
        raise CreditAnalysisError(
            f"missing source cwd is not a canonical worktree path: {recorded_cwd}"
        )
    worktrees_index = indexes[-1]
    repository_parent = pathlib.Path(*parts[:worktrees_index])
    repository_name = parts[worktrees_index + 1]
    relative_cwd = parts[worktrees_index + 3 :]
    primary_root = repository_parent / repository_name
    if primary_root.is_symlink():
        raise CreditAnalysisError(
            f"primary checkout cannot be a symlink: {primary_root}"
        )
    try:
        resolved_root = primary_root.resolve(strict=True)
    except OSError as exc:
        raise CreditAnalysisError(
            f"primary checkout is unavailable for missing source cwd: {recorded_cwd}"
        ) from exc
    if not resolved_root.is_dir():
        raise CreditAnalysisError(f"primary checkout is not a directory: {resolved_root}")
    git_root = pathlib.Path(
        _git_stdout(resolved_root, "rev-parse", "--show-toplevel")
    ).resolve(strict=True)
    if git_root != resolved_root:
        raise CreditAnalysisError(
            f"primary checkout topology does not match repository root: {resolved_root}"
        )
    live_url = _git_stdout(resolved_root, "config", "--get", "remote.origin.url")
    if _normalize_repository_url(live_url) != _normalize_repository_url(repository_url):
        raise CreditAnalysisError(
            "primary checkout repository identity does not match retained session "
            f"identity for {recorded_cwd}"
        )
    candidate = resolved_root.joinpath(*relative_cwd)
    if candidate.is_symlink():
        raise CreditAnalysisError(f"recovered source cwd cannot be a symlink: {candidate}")
    try:
        resolved_candidate = candidate.resolve(strict=True)
        resolved_candidate.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise CreditAnalysisError(
            f"recovered source cwd is unavailable in primary checkout: {candidate}"
        ) from exc
    if not resolved_candidate.is_dir():
        raise CreditAnalysisError(
            f"recovered source cwd is not a directory: {resolved_candidate}"
        )
    return resolved_candidate


def _resolve_source_cwd(
    raw_cwd: str,
    *,
    repository_url: str | None,
    substitutions: dict[str, dict[str, str]],
) -> pathlib.Path:
    """Resolve an existing cwd or record one verified shipped-worktree recovery."""

    recorded = pathlib.Path(raw_cwd).expanduser().resolve(strict=False)
    if recorded.is_symlink():
        raise CreditAnalysisError(f"source cwd cannot be a symlink: {recorded}")
    try:
        return recorded.resolve(strict=True)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise CreditAnalysisError(f"source cwd could not be resolved: {recorded}") from exc
    if repository_url is None:
        raise CreditAnalysisError(
            f"missing source cwd has no retained repository identity: {recorded}"
        )
    resolved = _verified_primary_checkout(recorded, repository_url)
    record = {
        "recorded_cwd": str(recorded),
        "resolved_cwd": str(resolved),
        "repository_url": repository_url,
        "reason": "missing-canonical-worktree",
    }
    prior = substitutions.setdefault(str(recorded), record)
    if prior != record:
        raise CreditAnalysisError(
            f"source cwd recovery conflicts for recorded path: {recorded}"
        )
    return resolved


def _source_execution_context(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Resolve every run cwd and retain verified shipped-worktree substitutions."""

    session_cwd: str | None = None
    current_cwd: str | None = None
    run_cwds: dict[str, str] = {}
    for row in rows:
        payload = row.get("payload")
        if not isinstance(payload, Mapping):
            continue
        if row.get("type") == "session_meta":
            value = payload.get("cwd")
            if isinstance(value, str) and value.strip():
                session_cwd = value.strip()
                current_cwd = session_cwd
        elif row.get("type") == "turn_context":
            value = payload.get("cwd")
            if isinstance(value, str) and value.strip():
                current_cwd = value.strip()
            turn_id = payload.get("turn_id")
            if isinstance(turn_id, str) and turn_id and current_cwd:
                run_cwds[turn_id] = current_cwd
    if session_cwd is None:
        raise CreditAnalysisError("source session does not declare a cwd")
    repository_url = _session_repository_url(rows)
    substitutions: dict[str, dict[str, str]] = {}
    primary_path = _resolve_source_cwd(
        session_cwd,
        repository_url=repository_url,
        substitutions=substitutions,
    )
    primary = _instruction_chain(primary_path)
    chains: dict[str, dict[str, Any]] = {primary["cwd"]: primary}
    normalized_run_cwds: dict[str, str] = {}
    for turn_id, raw_cwd in run_cwds.items():
        resolved_path = _resolve_source_cwd(
            raw_cwd,
            repository_url=repository_url,
            substitutions=substitutions,
        )
        resolved_cwd = str(resolved_path)
        normalized_run_cwds[turn_id] = resolved_cwd
        if resolved_cwd not in chains:
            chains[resolved_cwd] = _instruction_chain(resolved_path)
    return {
        "primary_cwd": primary["cwd"],
        "run_cwds": normalized_run_cwds,
        "instruction_chains": [chains[key] for key in sorted(chains)],
        "cwd_substitutions": [substitutions[key] for key in sorted(substitutions)],
    }


def _validate_execution_context(value: Mapping[str, Any]) -> None:
    """Validate frozen rule evidence and current execution locations."""

    chains = value.get("instruction_chains")
    if not isinstance(chains, list) or not chains:
        raise CreditAnalysisError("frozen instruction context is missing")
    chain_cwds: set[str] = set()
    for frozen in chains:
        if not isinstance(frozen, Mapping) or set(frozen) != {
            "cwd",
            "project_root",
            "codex_home",
            "files",
            "chain_sha256",
            "total_bytes",
        }:
            raise CreditAnalysisError("frozen instruction chain is invalid")
        cwd = str(frozen["cwd"])
        cwd_path = pathlib.Path(cwd)
        if cwd_path.is_symlink() or not cwd_path.is_dir():
            raise CreditAnalysisError(f"source execution cwd is unavailable: {cwd}")
        if cwd in chain_cwds:
            raise CreditAnalysisError(f"duplicate frozen instruction cwd: {cwd}")
        files = frozen["files"]
        if not isinstance(files, list):
            raise CreditAnalysisError("frozen instruction files are invalid")
        seen_paths: set[str] = set()
        total_bytes = 0
        for item in files:
            if not isinstance(item, Mapping) or set(item) != {
                "path",
                "sha256",
                "bytes",
                "text",
            }:
                raise CreditAnalysisError("frozen instruction file is invalid")
            path = item["path"]
            text = item["text"]
            byte_count = item["bytes"]
            digest = item["sha256"]
            if not isinstance(path, str) or not path or path in seen_paths:
                raise CreditAnalysisError("frozen instruction file path is invalid")
            if not isinstance(text, str):
                raise CreditAnalysisError("frozen instruction file text is invalid")
            payload = text.encode("utf-8")
            if (
                not isinstance(byte_count, int)
                or isinstance(byte_count, bool)
                or byte_count != len(payload)
                or digest != hashlib.sha256(payload).hexdigest()
            ):
                raise CreditAnalysisError("frozen instruction file identity changed")
            seen_paths.add(path)
            total_bytes += byte_count
        if (
            frozen["total_bytes"] != total_bytes
            or frozen["chain_sha256"] != _content_hash(files)
        ):
            raise CreditAnalysisError("frozen instruction chain identity changed")
        chain_cwds.add(cwd)
    substitutions = value.get("cwd_substitutions")
    if not isinstance(substitutions, list):
        raise CreditAnalysisError("frozen cwd substitutions are invalid")
    recorded_paths: set[str] = set()
    for record in substitutions:
        if not isinstance(record, Mapping) or set(record) != {
            "recorded_cwd",
            "resolved_cwd",
            "repository_url",
            "reason",
        }:
            raise CreditAnalysisError("frozen cwd substitution is invalid")
        recorded = str(record["recorded_cwd"])
        resolved = str(record["resolved_cwd"])
        repository_url = str(record["repository_url"])
        if record["reason"] != "missing-canonical-worktree":
            raise CreditAnalysisError("frozen cwd substitution reason is invalid")
        if recorded in recorded_paths:
            raise CreditAnalysisError(f"duplicate frozen cwd substitution: {recorded}")
        recorded_paths.add(recorded)
        current_checkout = _verified_primary_checkout(
            pathlib.Path(recorded), repository_url
        )
        if str(current_checkout) != resolved or resolved not in chain_cwds:
            raise CreditAnalysisError(
                f"source cwd substitution changed after planning: {recorded}"
            )


def _instruction_chain_for_cwd(
    execution_context: Mapping[str, Any], cwd: str
) -> Mapping[str, Any]:
    """Return the frozen effective instruction chain for one child cwd."""

    for chain in execution_context.get("instruction_chains", []):
        if isinstance(chain, Mapping) and str(chain.get("cwd")) == cwd:
            return chain
    raise CreditAnalysisError(f"source instruction chain is missing for cwd: {cwd}")


def _execution_rule_handoff(
    state: Mapping[str, Any], task: Mapping[str, Any]
) -> dict[str, Any]:
    """Return frozen hashes and text needed across differing source cwds."""

    context = state["execution_context"]
    primary_cwd = str(context["primary_cwd"])
    task_cwd = str(task.get("execution_cwd") or primary_cwd)
    task_chain = _instruction_chain_for_cwd(context, task_cwd)
    primary_chain = _instruction_chain_for_cwd(context, primary_cwd)
    primary_files = {
        (str(item["path"]), str(item["sha256"])) for item in primary_chain["files"]
    }
    chains: list[dict[str, Any]] = []
    for chain in context["instruction_chains"]:
        differing_files: list[dict[str, Any]] = []
        for item in chain["files"]:
            identity = (str(item["path"]), str(item["sha256"]))
            if identity in primary_files:
                continue
            differing_files.append(
                {
                    "path": identity[0],
                    "sha256": identity[1],
                    "bytes": int(item["bytes"]),
                    "text": str(item["text"]),
                }
            )
        chains.append(
            {
                "cwd": str(chain["cwd"]),
                "chain_sha256": str(chain["chain_sha256"]),
                "files": [
                    {
                        "path": str(item["path"]),
                        "sha256": str(item["sha256"]),
                        "bytes": int(item["bytes"]),
                    }
                    for item in chain["files"]
                ],
                "differing_from_primary": differing_files,
            }
        )
    return {
        "task_execution_cwd": task_cwd,
        "task_chain_sha256": str(task_chain["chain_sha256"]),
        "primary_cwd": primary_cwd,
        "primary_chain_sha256": str(primary_chain["chain_sha256"]),
        "source_chains": chains,
    }


__all__ = (
    "_execution_rule_handoff",
    "_instruction_chain",
    "_instruction_chain_for_cwd",
    "_source_execution_context",
    "_validate_execution_context",
)
