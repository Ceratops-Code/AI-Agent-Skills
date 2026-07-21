#!/usr/bin/env python3
"""Synchronize the versioned bootstrap installer into a target task worktree.

Only the parsed integer ``INSTALLER_VERSION`` controls replacement. Missing or
lower-version targets are copied from the authoritative template; same- or
higher-version files are retained even when their contents differ. A full
target-repository validation follows every synchronization decision.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import shutil
import subprocess
import sys


BUNDLE_ROOT = pathlib.Path(__file__).resolve().parents[2]
TEMPLATE = BUNDLE_ROOT / "scripts" / "templates" / "install-skills-template.py"
VALIDATOR = BUNDLE_ROOT / "scripts" / "skills-consistency-source-validator.py"
TARGET_RELATIVE = pathlib.Path("scripts/install-skills.py")


def installer_version(path: pathlib.Path) -> int | None:
    """Parse one literal integer ``INSTALLER_VERSION`` assignment."""

    if not path.is_file():
        return None
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return None
    versions: list[int] = []
    for node in module.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if any(isinstance(target, ast.Name) and target.id == "INSTALLER_VERSION" for target in targets):
            if isinstance(value, ast.Constant) and isinstance(value.value, int) and not isinstance(value.value, bool):
                versions.append(value.value)
            else:
                return None
    return versions[0] if len(versions) == 1 and versions[0] > 0 else None


def require_linked_worktree(repo_root: pathlib.Path) -> None:
    """Reject primary checkouts so synchronization cannot bypass task isolation."""

    git_marker = repo_root / ".git"
    if not git_marker.is_file():
        raise RuntimeError(f"target repository must be a linked task worktree: {repo_root}")


def run_validation(repo_root: pathlib.Path) -> None:
    """Run full target validation after the installer decision."""

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo_root), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"full source-repository validation failed: {detail}")


def main() -> int:
    """Update one task-worktree installer when its parsed version is outdated."""

    parser = argparse.ArgumentParser(description="Synchronize a compatible-repo installer by version.")
    parser.add_argument("--target-repo-root", required=True, type=pathlib.Path)
    args = parser.parse_args()
    repo_root = args.target_repo_root.resolve()
    target = repo_root / TARGET_RELATIVE

    try:
        require_linked_worktree(repo_root)
        source_version = installer_version(TEMPLATE)
        if source_version is None:
            raise RuntimeError(f"authoritative installer has no valid INSTALLER_VERSION: {TEMPLATE}")
        target_version = installer_version(target)
        updated = target_version is None or target_version < source_version
        if updated:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(TEMPLATE, target)
        run_validation(repo_root)
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "installer_version": source_version,
                "previous_version": target_version,
                "status": "updated" if updated else "retained",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
