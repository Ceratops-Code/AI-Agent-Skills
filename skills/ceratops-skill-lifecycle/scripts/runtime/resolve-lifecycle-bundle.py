#!/usr/bin/env python3
"""Resolve the lifecycle helper bundle for one repository installation.

An installed schema-compatible bundle is authoritative. The target checkout is
accepted only when it is the Ceratops source repository bootstrapping its first
supported runtime copy.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from collections.abc import Mapping


LIFECYCLE_SKILL = "ceratops-skill-lifecycle"
MANIFEST_NAME = ".runtime-manifest.json"
RUNTIME_MANIFEST_SCHEMA = "ceratops-runtime-skill.v3"
REQUIRED_BUNDLE_PATHS = (
    pathlib.Path("scripts/runtime/install-managed-skills.py"),
    pathlib.Path("scripts/runtime/managed_runtime_builder.py"),
    pathlib.Path("scripts/runtime/synchronize-installers.py"),
    pathlib.Path("scripts/runtime/skills-consistency-runtime-validator.py"),
    pathlib.Path("scripts/skills-consistency-source-validator.py"),
    pathlib.Path("scripts/templates/install-skills-template.py"),
)


def codex_skills_root() -> pathlib.Path:
    """Return the direct personal runtime skills root."""

    codex_home = os.environ.get("CODEX_HOME")
    return pathlib.Path(codex_home).expanduser() / "skills" if codex_home else pathlib.Path.home() / ".codex" / "skills"


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


def installed_bundle_supported(bundle_root: pathlib.Path, installer_version: int) -> bool:
    """Check installed identity, schema, helper payload, and version support."""

    manifest = read_json(bundle_root / MANIFEST_NAME)
    if manifest is None:
        return False
    manifest_installer_version = manifest.get("installer_version")
    return (
        manifest.get("schema") == RUNTIME_MANIFEST_SCHEMA
        and manifest.get("skill") == LIFECYCLE_SKILL
        and manifest.get("validation_profile") == "ceratops"
        and isinstance(manifest_installer_version, int)
        and not isinstance(manifest_installer_version, bool)
        and manifest_installer_version >= installer_version
        and bundle_files_present(bundle_root)
    )


def checkout_is_ceratops(repo_root: pathlib.Path) -> bool:
    """Allow checkout fallback only for the Ceratops source repository."""

    manifest = read_json(repo_root / "templates" / "skill-sections.json")
    return manifest is not None and manifest.get("validation_profile") == "ceratops"


def resolve_bundle(repo_root: pathlib.Path, installer_version: int) -> pathlib.Path:
    """Select the installed bundle or the single permitted bootstrap fallback."""

    installed = codex_skills_root() / LIFECYCLE_SKILL
    if installed_bundle_supported(installed, installer_version):
        return installed.resolve()

    checkout = repo_root / "skills" / LIFECYCLE_SKILL
    if checkout_is_ceratops(repo_root) and bundle_files_present(checkout):
        return checkout.resolve()

    raise RuntimeError(
        "The installed ceratops-skill-lifecycle bundle does not support this installer version, "
        "and checkout fallback is allowed only for the initial Ceratops installation."
    )


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
