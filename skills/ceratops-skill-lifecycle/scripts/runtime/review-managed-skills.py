#!/usr/bin/env python3
"""Inventory and review direct manifest-managed runtime skill folders.

The inventory is intentionally source-neutral and never descends into plugin
caches or unmanaged skill folders. Installer inventory runs before the managed
skill consistency phase so callers can synchronize outdated repositories in
task worktrees and validate them before continuing.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import pathlib
import re
import sys
from collections import defaultdict
from collections.abc import Mapping


BUNDLE_ROOT = pathlib.Path(__file__).resolve().parents[2]
TEMPLATE = BUNDLE_ROOT / "scripts" / "templates" / "install-skills-template.py"
MANIFEST_NAME = ".runtime-manifest.json"
RUNTIME_MANIFEST_SCHEMA = "ceratops-runtime-skill.v3"
VALIDATION_PROFILES = {"ceratops", "ceratops-compatible"}
REQUIRED_FIELDS = {
    "schema",
    "skill",
    "runtime_source_id",
    "source_path",
    "source_repository_root",
    "validation_profile",
    "installer_version",
}
FRONTMATTER_NAME = re.compile(r"^name:\s*(.+?)\s*$", re.MULTILINE)
FRONTMATTER_DESCRIPTION = re.compile(r"^description:\s*(.+?)\s*$", re.MULTILINE)


def default_runtime_root() -> pathlib.Path:
    """Return the direct personal runtime skills root."""

    codex_home = os.environ.get("CODEX_HOME")
    return pathlib.Path(codex_home).expanduser() / "skills" if codex_home else pathlib.Path.home() / ".codex" / "skills"


def installer_version(path: pathlib.Path) -> int | None:
    """Parse only the literal integer installer version from a Python file."""

    if not path.is_file():
        return None
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return None
    values: list[int] = []
    for node in module.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == "INSTALLER_VERSION" for target in targets):
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, int) and not isinstance(value.value, bool):
                values.append(value.value)
            else:
                return None
    return values[0] if len(values) == 1 and values[0] > 0 else None


def read_manifest(skill_dir: pathlib.Path) -> tuple[Mapping[str, object] | None, str | None]:
    """Read one runtime manifest with a compact error string."""

    try:
        value = json.loads((skill_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)
    return (value, None) if isinstance(value, Mapping) else (None, "manifest must be a JSON object")


def managed_directories(runtime_root: pathlib.Path) -> list[pathlib.Path]:
    """Return only direct runtime folders containing the managed manifest."""

    if not runtime_root.is_dir():
        return []
    return sorted(
        path for path in runtime_root.iterdir() if path.is_dir() and (path / MANIFEST_NAME).is_file()
    )


def inventory(runtime_root: pathlib.Path) -> tuple[list[dict[str, object]], list[str]]:
    """Collect manifest groups and installer-version findings."""

    errors: list[str] = []
    records: list[dict[str, object]] = []
    authoritative_version = installer_version(TEMPLATE)
    if authoritative_version is None:
        return records, ["authoritative installer version is missing or invalid"]

    for skill_dir in managed_directories(runtime_root):
        manifest, error = read_manifest(skill_dir)
        if manifest is None:
            errors.append(f"{skill_dir.name}: unreadable runtime manifest: {error}")
            continue
        missing = sorted(REQUIRED_FIELDS - set(manifest))
        if missing:
            errors.append(f"{skill_dir.name}: runtime manifest missing {', '.join(missing)}")
            continue
        string_fields = ("skill", "runtime_source_id", "source_path", "source_repository_root")
        invalid_strings = [field for field in string_fields if not isinstance(manifest.get(field), str) or not str(manifest[field]).strip()]
        if invalid_strings:
            errors.append(f"{skill_dir.name}: runtime manifest has invalid {', '.join(invalid_strings)}")
            continue
        if manifest.get("schema") != RUNTIME_MANIFEST_SCHEMA:
            errors.append(f"{skill_dir.name}: unsupported runtime manifest schema")
            continue
        if manifest.get("validation_profile") not in VALIDATION_PROFILES:
            errors.append(f"{skill_dir.name}: unsupported validation profile")
            continue
        version = manifest.get("installer_version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            errors.append(f"{skill_dir.name}: installer_version must be a positive integer")
            continue
        if not pathlib.Path(str(manifest["source_repository_root"])).is_absolute():
            errors.append(f"{skill_dir.name}: source_repository_root must be an absolute local path")
            continue
        records.append({"directory": skill_dir.name, **dict(manifest)})

    groups: defaultdict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    roots_by_source: defaultdict[str, set[str]] = defaultdict(set)
    for record in records:
        source_id = str(record["runtime_source_id"])
        source_root = str(record["source_repository_root"])
        groups[(source_id, source_root)].append(record)
        roots_by_source[source_id].add(source_root)
    for source_id, roots in roots_by_source.items():
        if len(roots) > 1:
            errors.append(f"{source_id}: runtime manifests disagree on source_repository_root")
    for (source_id, source_root_text), group in groups.items():
        version_values: list[int] = []
        for record in group:
            value = record["installer_version"]
            assert isinstance(value, int) and not isinstance(value, bool)
            version_values.append(value)
        versions = set(version_values)
        if len(versions) != 1:
            errors.append(f"{source_id}: installed runtime manifests disagree on installer_version")
        elif next(iter(versions)) < authoritative_version:
            errors.append(f"{source_id}: installed runtime installer_version is outdated")
        source_version = installer_version(pathlib.Path(source_root_text) / "scripts" / "install-skills.py")
        if source_version is None or source_version < authoritative_version:
            errors.append(f"{source_id}: source repository installer is missing or outdated")
    return records, errors


def consistency(records: list[dict[str, object]], runtime_root: pathlib.Path) -> list[str]:
    """Check installed identity and resolvable source ownership after version gates."""

    errors: list[str] = []
    seen_sources: set[tuple[str, str]] = set()
    for record in records:
        directory = str(record["directory"])
        skill = str(record["skill"])
        source_root = pathlib.Path(str(record["source_repository_root"]))
        source_path = str(record["source_path"])
        source_key = (str(record["runtime_source_id"]), source_path)
        if directory != skill:
            errors.append(f"{directory}: manifest skill identity is {skill!r}")
        if source_key in seen_sources:
            errors.append(f"{directory}: duplicate managed source path {source_path}")
        seen_sources.add(source_key)
        if not (source_root / source_path / "SKILL.md").is_file():
            errors.append(f"{directory}: source SKILL.md is unresolved")
        installed_skill = runtime_root / directory / "SKILL.md"
        if not installed_skill.is_file():
            errors.append(f"{directory}: installed SKILL.md is missing")
            continue
        installed_text = installed_skill.read_text(encoding="utf-8")
        match = FRONTMATTER_NAME.search(installed_text)
        description = FRONTMATTER_DESCRIPTION.search(installed_text)
        if match is None or match.group(1).strip() != skill:
            errors.append(f"{directory}: installed frontmatter name does not match")
        if description is None or not description.group(1).strip():
            errors.append(f"{directory}: installed frontmatter description is missing")
    return errors


def main() -> int:
    """Run installer inventory first, then optional managed consistency checks."""

    parser = argparse.ArgumentParser(description="Review direct manifest-managed runtime skills.")
    parser.add_argument("--runtime-root", type=pathlib.Path)
    parser.add_argument("--mode", choices=("inventory", "consistency"), default="consistency")
    args = parser.parse_args()
    runtime_root = (args.runtime_root or default_runtime_root()).resolve()
    records, errors = inventory(runtime_root)
    if args.mode == "consistency" and not errors:
        errors.extend(consistency(records, runtime_root))
    if errors:
        print(f"errors: {len(errors)}", file=sys.stderr)
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    grouped: defaultdict[str, int] = defaultdict(int)
    for record in records:
        grouped[str(record["runtime_source_id"])] += 1
    print(json.dumps({"groups": dict(sorted(grouped.items())), "managed": len(records), "mode": args.mode}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
