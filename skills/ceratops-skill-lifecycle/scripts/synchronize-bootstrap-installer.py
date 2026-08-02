#!/usr/bin/env python3
"""Synchronize the versioned first-install bootstrap installer into a task worktree.

Only the parsed integer ``INSTALLER_VERSION`` controls replacement. Missing or
lower-version targets are copied from the authoritative template; same- or
higher-version files are retained even when their contents differ. Repository
validation belongs to the caller.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import sys


BUNDLE_ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = (
    BUNDLE_ROOT
    / "references"
    / "templates"
    / "install-skills-bootstrap-template.py"
)
TARGET_RELATIVE = pathlib.Path("scripts/install-skills-bootstrap.py")
INSTALLER_VERSION_RE = re.compile(
    r"^[ \t]*INSTALLER_VERSION[ \t]*=[ \t]*"
    r"(?P<version>[1-9][0-9]*)[ \t]*(?:#.*)?$",
    re.MULTILINE,
)


def installer_version(path: pathlib.Path) -> int | None:
    """Parse one literal integer ``INSTALLER_VERSION`` assignment."""

    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    versions = [
        int(match.group("version"))
        for match in INSTALLER_VERSION_RE.finditer(text)
    ]
    return versions[0] if len(versions) == 1 and versions[0] > 0 else None


def require_linked_worktree(repo_root: pathlib.Path) -> None:
    """Reject primary checkouts so synchronization cannot bypass task isolation."""

    git_marker = repo_root / ".git"
    if not git_marker.is_file():
        raise RuntimeError(f"target repository must be a linked task worktree: {repo_root}")


def main() -> int:
    """Update one task-worktree installer when its parsed version is outdated."""

    parser = argparse.ArgumentParser(
        description="Synchronize a compatible-repo bootstrap by version."
    )
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
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "bootstrap_version": source_version,
                "previous_version": target_version,
                "status": "updated" if updated else "retained",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
