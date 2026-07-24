#!/usr/bin/env python3
"""Validate managed runtime skills for one source repository or selected skill.

Discovery never descends into plugin caches or unmanaged skill folders.
Repository identity filters well-formed manifests while malformed direct
manifests remain visible because their owner cannot be trusted. Validation then
compares each selected managed tree with the canonical builder output.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import pathlib
import sys
import tempfile
from collections.abc import Mapping

import managed_runtime_builder as runtime_builder


BUNDLE_ROOT = pathlib.Path(__file__).resolve().parents[2]
TEMPLATE = BUNDLE_ROOT / "scripts" / "templates" / "install-skills-template.py"
MANIFEST_NAME = ".runtime-manifest.json"
RUNTIME_MANIFEST_SCHEMA = "ceratops-runtime-skill.v3"
VALIDATION_PROFILES = {"ceratops", "ceratops-compatible"}
SECTION_MANIFEST = pathlib.Path("templates/skill-sections.json")
REQUIRED_FIELDS = {
    "schema",
    "skill",
    "runtime_source_id",
    "source_path",
    "source_repository_root",
    "validation_profile",
    "installer_version",
}
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


def managed_directories(
    runtime_root: pathlib.Path,
    selected_skill: str | None = None,
) -> list[pathlib.Path]:
    """Return selected direct runtime folders containing the managed manifest."""

    if not runtime_root.is_dir():
        return []
    if selected_skill is not None:
        selected = runtime_root / selected_skill
        return [selected] if selected.is_dir() and (selected / MANIFEST_NAME).is_file() else []
    return sorted(
        path for path in runtime_root.iterdir() if path.is_dir() and (path / MANIFEST_NAME).is_file()
    )


def source_context(
    repo_root: pathlib.Path,
) -> tuple[Mapping[str, object] | None, str | None, str | None, set[str], list[str]]:
    """Read the target manifest, identity, profile, and source skill names."""

    errors: list[str] = []
    manifest_path = repo_root / SECTION_MANIFEST
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, None, None, set(), [f"source section manifest is unreadable: {exc}"]
    if not isinstance(manifest, Mapping):
        return None, None, None, set(), ["source section manifest must be a JSON object"]
    source_id = manifest.get("runtime_source_id")
    profile = manifest.get("validation_profile")
    if not isinstance(source_id, str) or not source_id.strip():
        errors.append("source section manifest has invalid runtime_source_id")
        source_id = None
    if profile not in VALIDATION_PROFILES:
        errors.append("source section manifest has unsupported validation_profile")
        profile = None
    skills_root = repo_root / "skills"
    skill_names = {
        path.name
        for path in skills_root.iterdir()
        if skills_root.is_dir() and path.is_dir() and (path / "SKILL.md").is_file()
    } if skills_root.is_dir() else set()
    if not skill_names:
        errors.append("source repository has no skill directories")
    return manifest, source_id, profile, skill_names, errors


def discover_runtime(
    repo_root: pathlib.Path,
    runtime_root: pathlib.Path,
    selected_skill: str | None = None,
) -> tuple[list[dict[str, object]], list[str], Mapping[str, object] | None, str | None, set[str]]:
    """Discover selected repository-owned manifests and validate identity fields."""

    errors: list[str] = []
    records: list[dict[str, object]] = []
    source_manifest, source_id, source_profile, skill_names, source_errors = source_context(repo_root)
    errors.extend(source_errors)
    if selected_skill is not None:
        if pathlib.PurePath(selected_skill).name != selected_skill:
            errors.append("selected skill must be one direct runtime directory name")
            skill_names = set()
        elif selected_skill not in skill_names:
            errors.append(f"{selected_skill}: source repository has no matching skill")
            skill_names = set()
        else:
            skill_names = {selected_skill}
        selected_manifest = runtime_root / selected_skill / MANIFEST_NAME
        if not selected_manifest.is_file():
            errors.append(f"{selected_skill}: direct runtime manifest is missing")
    authoritative_version = installer_version(TEMPLATE)
    if authoritative_version is None:
        errors.append("authoritative installer version is missing or invalid")
        return records, errors, source_manifest, source_id, skill_names
    source_version = installer_version(repo_root / "scripts" / "install-skills.py")
    if source_version is None or source_version < authoritative_version:
        errors.append("source repository installer is missing or outdated")

    for skill_dir in managed_directories(runtime_root, selected_skill):
        manifest, error = read_manifest(skill_dir)
        if manifest is None:
            errors.append(f"{skill_dir.name}: unreadable runtime manifest: {error}")
            continue
        declared_source_id = manifest.get("runtime_source_id")
        declared_source_root = manifest.get("source_repository_root")
        root_matches = False
        if isinstance(declared_source_root, str) and pathlib.Path(declared_source_root).is_absolute():
            try:
                root_matches = pathlib.Path(declared_source_root).resolve() == repo_root
            except OSError:
                root_matches = False
        if declared_source_id != source_id and skill_dir.name not in skill_names and not root_matches:
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
        if manifest.get("runtime_source_id") != source_id:
            errors.append(f"{skill_dir.name}: runtime manifest belongs to another source")
            continue
        if manifest.get("validation_profile") != source_profile:
            errors.append(f"{skill_dir.name}: runtime validation profile does not match source")
            continue
        version = manifest.get("installer_version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            errors.append(f"{skill_dir.name}: installer_version must be a positive integer")
            continue
        if not pathlib.Path(str(manifest["source_repository_root"])).is_absolute():
            errors.append(f"{skill_dir.name}: source_repository_root must be an absolute local path")
            continue
        records.append({"directory": skill_dir.name, **dict(manifest)})

    roots = {str(record["source_repository_root"]) for record in records}
    if len(roots) > 1:
        errors.append(f"{source_id}: runtime manifests disagree on source_repository_root")
    versions: set[int] = set()
    for record in records:
        version = record["installer_version"]
        if isinstance(version, int) and not isinstance(version, bool):
            versions.add(version)
    if len(versions) > 1:
        errors.append(f"{source_id}: installed runtime manifests disagree on installer_version")
    elif versions and source_version is not None and next(iter(versions)) != source_version:
        errors.append(f"{source_id}: installed runtime installer_version does not match source")
    for source_root_text in roots:
        installed_source_version = installer_version(
            pathlib.Path(source_root_text) / "scripts" / "install-skills.py"
        )
        if installed_source_version is None or installed_source_version < authoritative_version:
            errors.append(f"{source_id}: installed source repository installer is missing or outdated")
    return records, errors, source_manifest, source_id, skill_names


def managed_files(root: pathlib.Path) -> dict[str, pathlib.Path]:
    """Return comparable managed files while ignoring runtime-generated caches."""

    return {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file()
        and not any(part in runtime_builder.IGNORE_NAMES for part in path.relative_to(root).parts)
    }


def compare_managed_tree(
    installed_root: pathlib.Path,
    expected_root: pathlib.Path,
) -> list[str]:
    """Compare complete builder-managed file sets and bytes."""

    errors: list[str] = []
    installed = managed_files(installed_root)
    expected = managed_files(expected_root)
    for relative in sorted(expected.keys() - installed.keys()):
        errors.append(f"missing managed file {relative}")
    for relative in sorted(installed.keys() - expected.keys()):
        errors.append(f"unexpected managed file {relative}")
    for relative in sorted(expected.keys() & installed.keys()):
        if installed[relative].read_bytes() != expected[relative].read_bytes():
            errors.append(f"managed file content differs: {relative}")
    return errors


def validate_runtime(
    records: list[dict[str, object]],
    repo_root: pathlib.Path,
    runtime_root: pathlib.Path,
    source_manifest: Mapping[str, object],
    source_id: str | None,
    skill_names: set[str],
) -> list[str]:
    """Validate installed identity and complete managed output after discovery."""

    errors: list[str] = []
    seen_sources: set[tuple[str, str]] = set()
    installed_skills = {str(record["skill"]) for record in records}
    for skill in sorted(skill_names - installed_skills):
        errors.append(f"{skill}: managed runtime skill is missing")

    runtime_builder.configure_repo(repo_root)
    for record in records:
        directory = str(record["directory"])
        skill = str(record["skill"])
        source_root = pathlib.Path(str(record["source_repository_root"]))
        source_path = str(record["source_path"])
        source_key = (str(record["runtime_source_id"]), source_path)
        if record["runtime_source_id"] != source_id:
            errors.append(f"{directory}: runtime source identity does not match repository")
        if directory != skill:
            errors.append(f"{directory}: manifest skill identity is {skill!r}")
        if skill not in skill_names:
            errors.append(f"{directory}: managed runtime skill has no matching source skill")
        if source_path != f"skills/{skill}":
            errors.append(f"{directory}: manifest source path does not match skill identity")
        if source_key in seen_sources:
            errors.append(f"{directory}: duplicate managed source path {source_path}")
        seen_sources.add(source_key)
        if not (source_root / source_path / "SKILL.md").is_file():
            errors.append(f"{directory}: source SKILL.md is unresolved")
        installed_skill_root = runtime_root / directory
        if not installed_skill_root.is_dir():
            errors.append(f"{directory}: installed managed folder is missing")
            continue
        try:
            version_value = record["installer_version"]
            if not isinstance(version_value, int) or isinstance(version_value, bool):
                errors.append(f"{directory}: installer_version is not usable")
                continue
            with tempfile.TemporaryDirectory(prefix=f"ceratops-{skill}-expected-") as temporary:
                expected_skill_root = pathlib.Path(temporary) / skill
                runtime_builder.write_expected_skill(
                    skill,
                    expected_skill_root,
                    source_manifest,
                    version_value,
                    source_repository_root=source_root,
                )
                errors.extend(
                    f"{directory}: {error}"
                    for error in compare_managed_tree(installed_skill_root, expected_skill_root)
                )
        except (OSError, UnicodeError, ValueError, KeyError) as exc:
            errors.append(f"{directory}: expected managed tree is unresolved: {exc}")
    return errors


def main() -> int:
    """Discover and validate one repository or selected installed skill."""

    parser = argparse.ArgumentParser(
        description="Validate managed runtime skills for one source repository or selected skill."
    )
    parser.add_argument("--repo-root", required=True, type=pathlib.Path)
    parser.add_argument("--runtime-root", type=pathlib.Path)
    parser.add_argument("--skill", help="Validate only this direct manifest-backed runtime skill.")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    runtime_root = (args.runtime_root or default_runtime_root()).resolve()
    records, errors, source_manifest, source_id, skill_names = discover_runtime(
        repo_root,
        runtime_root,
        args.skill,
    )
    if not errors and source_manifest is not None:
        errors.extend(
            validate_runtime(
                records,
                repo_root,
                runtime_root,
                source_manifest,
                source_id,
                skill_names,
            )
        )
    if errors:
        print(f"errors: {len(errors)}", file=sys.stderr)
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "managed": len(records),
                "runtime_source_id": source_id,
                "status": "valid",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
