#!/usr/bin/env python3
"""Resolve the lifecycle helper bundle from the AI-Agent-Skills checkout."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections.abc import Mapping


LIFECYCLE_SKILL = "ceratops-skill-lifecycle"
REQUIRED_BUNDLE_PATHS = (
    pathlib.Path("scripts/fast-change.py"),
    pathlib.Path("scripts/materialize-compatible-repo.py"),
    pathlib.Path("scripts/runtime/install-managed-skills.py"),
    pathlib.Path("scripts/runtime/managed_runtime_builder.py"),
    pathlib.Path("scripts/runtime/synchronize-installers.py"),
    pathlib.Path("scripts/skills-consistency-source-validator.py"),
    pathlib.Path("scripts/templates/install-skills-template.py"),
    pathlib.Path("scripts/templates/skill-sections-template.json"),
)


def read_json(path: pathlib.Path) -> Mapping[str, object] | None:
    """Return one JSON object, or ``None`` when it is unavailable or invalid."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def bundle_files_present(bundle_root: pathlib.Path) -> bool:
    """Check the complete helper surface required by supported installers."""

    return all((bundle_root / relative).is_file() for relative in REQUIRED_BUNDLE_PATHS)


def checkout_is_ceratops(repo_root: pathlib.Path) -> bool:
    """Identify the Ceratops source repository from its section manifest."""

    manifest = read_json(repo_root / "skills" / "skill-sections.json")
    return manifest is not None and manifest.get("validation_profile") == "ceratops"


def resolve_bundle(repo_root: pathlib.Path, installer_version: int) -> pathlib.Path:
    """Select the complete source checkout and reject every other repository."""

    checkout = repo_root / "skills" / LIFECYCLE_SKILL
    if checkout_is_ceratops(repo_root):
        if bundle_files_present(checkout):
            return checkout.resolve()
        raise RuntimeError(
            "The Ceratops source repository lifecycle bundle is incomplete."
        )

    raise RuntimeError("The lifecycle resolver only supports the AI-Agent-Skills checkout.")


def main() -> int:
    """Print the selected lifecycle bundle path for the bootstrap installer."""

    parser = argparse.ArgumentParser(description="Resolve a supported lifecycle helper bundle.")
    parser.add_argument("--repo-root", required=True, type=pathlib.Path)
    parser.add_argument("--installer-version", required=True, type=int)
    args = parser.parse_args()
    if args.installer_version < 1:
        print("installer version must be a positive integer", file=sys.stderr)
        return 1
    try:
        bundle = resolve_bundle(args.repo_root.resolve(), args.installer_version)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
