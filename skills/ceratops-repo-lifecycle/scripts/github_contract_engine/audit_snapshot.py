"""Emit compact local evidence for one GitHub contract audit.

The snapshot replaces repeated local discovery only. It performs no network
requests or repository mutation and intentionally leaves semantic contract
judgment to the caller.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
from typing import Any

from .format_report import write_json
from .operations import TOP_LEVEL_COMMANDS, VALIDATION_TARGETS


class SnapshotError(RuntimeError):
    """Report one compact, caller-actionable local snapshot blocker."""


def _load_object(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SnapshotError(f"cannot read valid JSON: {path.name}") from error
    if not isinstance(value, dict):
        raise SnapshotError(f"expected a JSON object: {path.name}")
    return value


def _git(repo_root: pathlib.Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise SnapshotError(f"local git command failed: {' '.join(arguments[:2])}")
    return process.stdout.strip()


def _contract_summary(repo_root: pathlib.Path) -> list[dict[str, Any]]:
    contracts_root = (
        repo_root
        / "skills"
        / "ceratops-repo-lifecycle"
        / "references"
        / "contracts"
    )
    if not contracts_root.is_dir():
        raise SnapshotError("missing GitHub lifecycle contract directory")

    result: list[dict[str, Any]] = []
    for path in sorted(contracts_root.glob("*.json")):
        contract = _load_object(path)
        checks = contract.get("checks", [])
        if not isinstance(checks, list):
            raise SnapshotError(f"expected checks array: {path.name}")
        result.append(
            {
                "path": path.relative_to(repo_root).as_posix(),
                "kind": contract.get("kind"),
                "captured_on": contract.get("captured_on"),
                "check_count": len(checks),
                "check_ids": sorted(
                    str(check["id"])
                    for check in checks
                    if isinstance(check, dict) and "id" in check
                ),
                "missing_source_lines": sum(
                    1
                    for check in checks
                    if isinstance(check, dict) and not check.get("source_lines")
                ),
            }
        )
    return result


def _document_summary(repo_root: pathlib.Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for name in ("README.md", "CONTRIBUTING.md", "CHANGELOG.md"):
        path = repo_root / name
        if not path.is_file():
            result.append({"path": name, "exists": False})
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        result.append(
            {
                "path": name,
                "exists": True,
                "contract_reference_lines": sum(
                    1 for line in lines if "contract" in line.lower()
                ),
                "github_lifecycle_reference_lines": sum(
                    1 for line in lines if "ceratops-repo-lifecycle" in line
                ),
            }
        )
    return result


def _recent_history(repo_root: pathlib.Path) -> list[dict[str, str]]:
    output = _git(
        repo_root,
        "log",
        "-n",
        "3",
        "--format=%h%x1f%ad%x1f%s",
        "--date=short",
        "--",
        "skills/ceratops-repo-lifecycle/references/contracts/"
        "github-contract-source-docs.json",
        "skills/ceratops-repo-lifecycle/references/contracts",
        "skills/ceratops-repo-lifecycle/references/contracts-review.md",
        "skills/ceratops-repo-lifecycle/scripts/github_contract_engine",
    )
    result: list[dict[str, str]] = []
    for line in output.splitlines():
        fields = line.split("\x1f", 2)
        if len(fields) == 3:
            result.append(
                {"commit": fields[0], "date": fields[1], "subject": fields[2]}
            )
    return result


def build_snapshot(repo_root: pathlib.Path) -> dict[str, Any]:
    """Collect bounded local facts from one compatible skills checkout."""

    root = repo_root.resolve()
    references = (
        root / "skills" / "ceratops-repo-lifecycle" / "references"
    )
    registry_path = (
        references / "contracts" / "github-contract-source-docs.json"
    )
    if not registry_path.is_file():
        raise SnapshotError("selected root is not a compatible skills checkout")

    registry = _load_object(registry_path)
    docs = registry.get("docs", [])
    reference_repos = registry.get("reference_repos", [])
    policy = registry.get("policy", {})
    if not isinstance(policy, dict):
        policy = {}
    status_lines = _git(root, "status", "--porcelain").splitlines()
    return {
        "schema": "ceratops-github-contract-audit-snapshot.v1",
        "git": {
            "branch": _git(root, "branch", "--show-current"),
            "clean": not status_lines,
            "changed_path_count": len(status_lines),
            "recent_contract_history": _recent_history(root),
        },
        "source_registry": {
            "captured_on": registry.get("captured_on"),
            "source_count": len(docs) if isinstance(docs, list) else 0,
            "reference_repo_count": (
                len(reference_repos) if isinstance(reference_repos, list) else 0
            ),
            "policy_use_order": policy.get("use_order", []),
        },
        "contracts": _contract_summary(root),
        "repo_docs": _document_summary(root),
        "commands": {
            "top_level": list(TOP_LEVEL_COMMANDS),
            "validation_targets": list(VALIDATION_TARGETS),
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m github_contract_engine audit-snapshot",
        description="Emit one compact report-only local contract-audit snapshot.",
    )
    parser.add_argument(
        "--repo-root",
        required=True,
        type=pathlib.Path,
        help="active Ceratops skills repository checkout or worktree",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Write one compact sanitized snapshot or blocker."""

    args = _parser().parse_args(argv)
    try:
        snapshot = build_snapshot(args.repo_root)
    except SnapshotError as error:
        write_json({"status": "blocked", "error": str(error)}, compact=True)
        return 1
    write_json(snapshot, compact=True)
    return 0
