#!/usr/bin/env python3
"""Render copy-based runtime skill folders from Ceratops-compatible repos.

Source skill folders intentionally contain only the skill-specific delta in
`SKILL.md`. This script expands shared template sections into a complete runtime
`SKILL.md`, copies the skill folder plus declared runtime payload files, and
installs the result under a runtime skills directory such as
`$CODEX_HOME/skills`.

Called by skill-lifecycle runtime installers during local installs and runtime
branch preview rebuilds. It can also be run directly when a caller supplies the
source repo root and output directory. The renderer is the only script that
writes installed skill contents; PowerShell wrappers only choose paths and
Python execution.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from typing import cast


ROOT = pathlib.Path(__file__).resolve().parents[4]
SECTION_MANIFEST = ROOT / "templates" / "skill-sections.json"
SKILLS = ROOT / "skills"
START = "<!-- CERATOPS_SHARED_SECTIONS_START -->"
END = "<!-- CERATOPS_SHARED_SECTIONS_END -->"
SOURCE_PREFIX = "<!-- SECTION SOURCE: "
SOURCE_SUFFIX = " -->"
MANIFEST_NAME = ".runtime-manifest.json"
RUNTIME_MANIFEST_SCHEMA = "ceratops-runtime-skill.v2"
VALIDATION_PROFILES = {"ceratops", "ceratops-compatible"}
IGNORE_NAMES = {".git", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", "node_modules"}


def load_manifest() -> dict[str, object]:
    """Load the shared-section and payload manifest used by every build."""

    return json.loads(SECTION_MANIFEST.read_text(encoding="utf-8"))


def source_skill_names() -> list[str]:
    """Return source skill folder names that contain a `SKILL.md` file."""

    return sorted(path.parent.name for path in SKILLS.glob("*/SKILL.md"))


def validate_manifest(manifest: Mapping[str, object], skill_names: set[str]) -> list[str]:
    """Validate manifest shape before any runtime folders are written.

    The renderer fails before touching the install destination when a skill assignment,
    section path, or required core section is stale. This keeps install failures
    cheap and prevents partially refreshed runtime copies.
    """

    errors: list[str] = []
    source_id = manifest.get("runtime_source_id")
    profile = manifest.get("validation_profile")
    sections = manifest.get("sections")
    assignments = manifest.get("skills")
    if not isinstance(source_id, str) or not source_id.strip():
        errors.append("section manifest runtime_source_id must be a nonempty string")
    if profile not in VALIDATION_PROFILES:
        errors.append("section manifest validation_profile must be ceratops or ceratops-compatible")
    if not isinstance(sections, Mapping):
        errors.append("section manifest is missing a valid sections object")
    if not isinstance(assignments, Mapping):
        errors.append("section manifest is missing a valid skills object")
    if errors or not isinstance(sections, Mapping) or not isinstance(assignments, Mapping):
        return errors

    for section_name, rel_path in sections.items():
        if not isinstance(rel_path, str):
            errors.append(f"section {section_name!r} must map to a string path")
            continue
        if not (ROOT / rel_path).is_file():
            errors.append(f"missing section file for {section_name}: {rel_path}")

    for skill_name, section_names in assignments.items():
        if skill_name not in skill_names:
            errors.append(f"unknown skill section assignment: {skill_name}")
        if not isinstance(section_names, Sequence) or isinstance(section_names, str):
            errors.append(f"{skill_name}: section assignment must be a list")
            continue
        if "core" not in section_names:
            errors.append(f"{skill_name}: section assignment must include core")
        for section_name in section_names:
            if section_name not in sections:
                errors.append(f"{skill_name}: unknown section assignment {section_name}")
    for skill_name in skill_names:
        if skill_name not in assignments:
            errors.append(f"{skill_name}: missing section assignment")
    return errors


def section_text(rel_path: str) -> str:
    """Read one shared section and strip internal-only template comments."""

    lines = (ROOT / rel_path).read_text(encoding="utf-8").splitlines()
    visible = [line for line in lines if not line.strip().startswith("<!-- INTERNAL:")]
    return "\n".join(visible).strip("\n")


def rendered_sections_block(skill_name: str, manifest: Mapping[str, object]) -> str:
    """Render the generated shared-section block for one runtime skill."""

    sections = cast(Mapping[str, str], manifest["sections"])
    assignments = cast(Mapping[str, Sequence[str]], manifest["skills"])
    rendered: list[str] = []
    for name in assignments[skill_name]:
        rel_path = sections[name]
        rendered.append(f"{SOURCE_PREFIX}{rel_path}{SOURCE_SUFFIX}")
        rendered.append(section_text(rel_path))
    body = "\n\n".join(rendered)
    return f"{START}\n{body}\n{END}"


def compose_runtime_skill(source_text: str, shared_block: str, skill_name: str) -> str:
    """Insert generated shared sections after frontmatter and the H1 title.

    Source skills stay readable and delta-only. Runtime skills need the complete
    instruction contract inline because Codex loads each installed skill folder
    independently. Inserting after the H1 keeps the generated contract visible
    before skill-specific workflow details.
    """

    if START in source_text or END in source_text:
        raise ValueError(f"{skill_name}: source SKILL.md must be delta-only; shared section markers are runtime output")
    lines = source_text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0] != "---":
        raise ValueError(f"{skill_name}: missing frontmatter")
    try:
        frontmatter_end = lines[1:].index("---") + 1
    except ValueError as exc:
        raise ValueError(f"{skill_name}: missing closing frontmatter marker") from exc

    insert_after = frontmatter_end
    for index in range(frontmatter_end + 1, len(lines)):
        if not lines[index].strip():
            continue
        if lines[index].startswith("# "):
            insert_after = index
        break

    before = "\n".join(lines[: insert_after + 1]).rstrip()
    after = "\n".join(lines[insert_after + 1 :]).strip("\n")
    if after:
        return f"{before}\n\n{shared_block}\n\n{after}\n"
    return f"{before}\n\n{shared_block}\n"


def ignore_source_dir(_directory: str, names: list[str]) -> set[str]:
    """Filter cache and VCS folders out of copied source skill trees."""

    return {name for name in names if name in IGNORE_NAMES}


def copy_path(source: pathlib.Path, target: pathlib.Path) -> None:
    """Copy one manifest-declared payload while preserving its repo-relative path."""

    if source.is_dir():
        for child in source.rglob("*"):
            if any(part in IGNORE_NAMES for part in child.parts):
                continue
            rel = child.relative_to(source)
            destination = target / rel
            if child.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(child, destination)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def expand_payload_patterns(patterns: Sequence[str]) -> list[pathlib.Path]:
    """Expand runtime payload globs relative to the source checkout root.

    Payloads let a skill carry everything it needs into `$CODEX_HOME/skills`:
    scripts, contracts, templates, icons, or local references. Missing explicit
    paths fail fast; unmatched globs are allowed so optional payload families can
    be declared without breaking narrower checkouts.
    """

    paths: list[pathlib.Path] = []
    for pattern in patterns:
        matches = sorted(ROOT.glob(pattern))
        if not matches:
            if any(token in pattern for token in "*?["):
                continue
            raise FileNotFoundError(f"runtime payload path does not exist: {pattern}")
        paths.extend(path for path in matches if ".git" not in path.parts)
    unique: dict[str, pathlib.Path] = {}
    for path in paths:
        unique[path.relative_to(ROOT).as_posix()] = path
    return list(unique.values())


def payload_patterns_for(skill_name: str, manifest: Mapping[str, object]) -> list[str]:
    """Return global and skill-specific runtime payload patterns."""

    payloads = manifest.get("runtime_payloads", {})
    if not isinstance(payloads, Mapping):
        return []
    patterns: list[str] = []
    for key in ("*", skill_name):
        values = payloads.get(key, [])
        if isinstance(values, Sequence) and not isinstance(values, str):
            patterns.extend(str(value) for value in values)
    return patterns


def is_managed_runtime_dir(path: pathlib.Path) -> bool:
    """Identify runtime folders that this renderer is allowed to replace."""

    return (path / MANIFEST_NAME).is_file()


def read_runtime_manifest(path: pathlib.Path) -> dict[str, object]:
    """Read one installed runtime manifest used for ownership decisions."""

    data = json.loads((path / MANIFEST_NAME).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("runtime manifest must be a JSON object")
    return data


def is_windows_reparse_point(path: pathlib.Path) -> bool:
    """Return whether `path` is a Windows reparse-point directory entry."""

    if os.name != "nt":
        return False
    try:
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    except (AttributeError, FileNotFoundError, OSError):
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def install_target_error(path: pathlib.Path, source_id: str) -> str | None:
    """Return why an existing target cannot be replaced by this source repo."""

    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or is_windows_reparse_point(path):
        return f"refusing to replace unmanaged runtime skill link: {path}"
    if not is_managed_runtime_dir(path):
        return f"refusing to replace unmanaged runtime skill folder: {path}"
    try:
        runtime_manifest = read_runtime_manifest(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return f"refusing to replace runtime skill with invalid ownership manifest: {path}: {exc}"
    if runtime_manifest.get("schema") != RUNTIME_MANIFEST_SCHEMA:
        return f"refusing to replace runtime skill with unsupported ownership manifest: {path}"
    if runtime_manifest.get("skill") != path.name:
        return f"refusing to replace runtime skill with mismatched ownership manifest: {path}"
    owner = runtime_manifest.get("runtime_source_id")
    if owner != source_id:
        return f"refusing to replace runtime skill owned by {owner!r}: {path}"
    return None


def validate_install_targets(skill_names: Sequence[str], install_root: pathlib.Path, source_id: str) -> list[str]:
    """Preflight every selected target before any installed folder is changed."""

    return [
        error
        for skill_name in skill_names
        if (error := install_target_error(install_root / skill_name, source_id)) is not None
    ]


def remove_existing_runtime_target(path: pathlib.Path, source_id: str) -> None:
    """Remove only a managed target owned by the current source repository."""

    error = install_target_error(path, source_id)
    if error is not None:
        raise RuntimeError(error)
    if not path.exists() and not path.is_symlink():
        return
    shutil.rmtree(path)


def enable_windows_acl_inheritance(path: pathlib.Path) -> None:
    """Make generated runtime folders inherit the install root's Windows ACLs."""

    if os.name != "nt":
        return
    result = subprocess.run(
        ["icacls", str(path), "/inheritance:e", "/T", "/C"],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        message = f"could not enable ACL inheritance on generated runtime skill folder: {path}"
        if detail:
            message = f"{message}: {detail}"
        raise RuntimeError(message)


def build_skill(skill_name: str, install_root: pathlib.Path, manifest: Mapping[str, object]) -> pathlib.Path:
    """Build one skill atomically in a temporary folder, then move it in place."""

    source_dir = SKILLS / skill_name
    source_skill = source_dir / "SKILL.md"
    source_id = cast(str, manifest["runtime_source_id"])
    validation_profile = cast(str, manifest["validation_profile"])
    if not source_skill.is_file():
        raise FileNotFoundError(f"missing source skill: {source_skill}")

    install_root.mkdir(parents=True, exist_ok=True)
    temp_parent = pathlib.Path(tempfile.mkdtemp(prefix=f".{skill_name}.", dir=install_root))
    temp_skill = temp_parent / skill_name
    target_skill = install_root / skill_name

    try:
        shutil.copytree(source_dir, temp_skill, ignore=ignore_source_dir)
        shared_block = rendered_sections_block(skill_name, manifest)
        runtime_skill_text = compose_runtime_skill(source_skill.read_text(encoding="utf-8"), shared_block, skill_name)
        (temp_skill / "SKILL.md").write_text(runtime_skill_text, encoding="utf-8", newline="\n")

        for payload in expand_payload_patterns(payload_patterns_for(skill_name, manifest)):
            relative = payload.relative_to(ROOT)
            copy_path(payload, temp_skill / relative)

        runtime_manifest = {
            "schema": RUNTIME_MANIFEST_SCHEMA,
            "skill": skill_name,
            "runtime_source_id": source_id,
            "validation_profile": validation_profile,
            "source_path": str(source_dir.relative_to(ROOT)).replace("\\", "/"),
            "generated_from": str(SECTION_MANIFEST.relative_to(ROOT)).replace("\\", "/"),
            "payload_patterns": payload_patterns_for(skill_name, manifest),
        }
        (temp_skill / MANIFEST_NAME).write_text(json.dumps(runtime_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        remove_existing_runtime_target(target_skill, source_id)
        temp_skill.replace(target_skill)
        enable_windows_acl_inheritance(target_skill)
        return target_skill
    finally:
        shutil.rmtree(temp_parent, ignore_errors=True)


def remove_stale_managed_skills(install_root: pathlib.Path, expected: set[str], source_id: str) -> list[str]:
    """Remove only stale managed folders owned by the current source repo."""

    removed: list[str] = []
    if not install_root.is_dir():
        return removed
    for item in install_root.iterdir():
        if item.is_symlink() or is_windows_reparse_point(item):
            continue
        if not item.is_dir() or not is_managed_runtime_dir(item):
            continue
        if item.name in expected:
            continue
        try:
            runtime_manifest = read_runtime_manifest(item)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if runtime_manifest.get("schema") != RUNTIME_MANIFEST_SCHEMA:
            continue
        if runtime_manifest.get("skill") != item.name:
            continue
        if runtime_manifest.get("runtime_source_id") != source_id:
            continue
        shutil.rmtree(item)
        removed.append(item.name)
    return removed


def main() -> int:
    """Parse CLI arguments, validate source state, and build selected skills."""

    global ROOT, SECTION_MANIFEST, SKILLS

    parser = argparse.ArgumentParser(description="Render copy-based Ceratops runtime skill folders.")
    parser.add_argument("--repo-root", required=True, type=pathlib.Path, help="Source skills repository root.")
    parser.add_argument("--install-root", required=True, type=pathlib.Path)
    parser.add_argument("--skill", action="append", help="Render only this skill. Can be repeated.")
    parser.add_argument("--remove-stale", action="store_true", help="Remove runtime folders previously generated by this renderer but no longer present in source.")
    args = parser.parse_args()

    ROOT = args.repo_root.resolve()
    SECTION_MANIFEST = ROOT / "templates" / "skill-sections.json"
    SKILLS = ROOT / "skills"

    manifest = load_manifest()
    skill_names = source_skill_names()
    selected = sorted(set(args.skill or skill_names))
    unknown = sorted(set(selected) - set(skill_names))
    if unknown:
        print(f"unknown skill(s): {', '.join(unknown)}", file=sys.stderr)
        return 1

    errors = validate_manifest(manifest, set(skill_names))
    if errors:
        print(f"errors: {len(errors)}", file=sys.stderr)
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    source_id = cast(str, manifest["runtime_source_id"])
    target_errors = validate_install_targets(selected, args.install_root, source_id)
    if target_errors:
        print(f"errors: {len(target_errors)}", file=sys.stderr)
        for error in target_errors:
            print(error, file=sys.stderr)
        return 1

    built = [build_skill(skill_name, args.install_root, manifest) for skill_name in selected]
    removed = remove_stale_managed_skills(args.install_root, set(skill_names), source_id) if args.remove_stale else []
    print(json.dumps({"built": [path.name for path in built], "removed": removed}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
