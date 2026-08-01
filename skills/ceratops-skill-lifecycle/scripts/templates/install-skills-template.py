#!/usr/bin/env python3
"""Install this repository's declared skills without Ceratops runtime dependencies."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import stat
import sys
import tempfile
from collections.abc import Mapping, Sequence
from typing import cast


INSTALLER_VERSION = 8
MANIFEST_NAME = ".runtime-manifest.json"
RUNTIME_MANIFEST_SCHEMA = "ceratops-runtime-skill.v3"
START = "<!-- CERATOPS_SHARED_SECTIONS_START -->"
END = "<!-- CERATOPS_SHARED_SECTIONS_END -->"
SOURCE_PREFIX = "<!-- SECTION SOURCE: "
SOURCE_SUFFIX = " -->"
SKILL_NAME_RE = re.compile(r"^(?![a-z0-9-]*--)[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
IGNORED_NAMES = {".git", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", "node_modules"}


def fail(message: str) -> int:
    """Emit one concise fatal error."""
    print(message, file=sys.stderr)
    return 1


def safe_relative(value: str) -> bool:
    """Accept only repository-relative manifest paths and patterns."""
    posix = pathlib.PurePosixPath(value.replace("\\", "/"))
    windows = pathlib.PureWindowsPath(value)
    return bool(value and not posix.is_absolute() and not windows.is_absolute() and not windows.drive and ".." not in posix.parts)


def unsafe_link(path: pathlib.Path) -> bool:
    """Reject links and Windows reparse points from copied input."""
    if path.is_symlink():
        return True
    if os.name != "nt":
        return False
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def require_inside(path: pathlib.Path, root: pathlib.Path) -> None:
    """Reject any resolved path that escapes the source repository."""
    path.resolve(strict=False).relative_to(root.resolve())


def read_manifest(repo_root: pathlib.Path) -> dict[str, object]:
    """Read the minimal declarations required to render skills."""
    path = repo_root / "skills" / "skill-sections.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("skill-sections.json must contain an object")
    source_id = value.get("runtime_source_id")
    sections = value.get("sections")
    skills = value.get("skills")
    payloads = value.get("runtime_payloads", {})
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("runtime_source_id must be a nonempty string")
    if not isinstance(sections, dict) or not isinstance(skills, dict):
        raise ValueError("sections and skills must be objects")
    if not isinstance(payloads, dict):
        raise ValueError("runtime_payloads must be an object")
    return value


def declared_skills(manifest: Mapping[str, object], requested: Sequence[str]) -> list[str]:
    """Resolve the exact declared skill set before staging output."""
    assignments = cast(Mapping[str, object], manifest["skills"])
    names = list(requested) if requested else sorted(assignments)
    if len(names) != len(set(names)):
        raise ValueError("duplicate --skill selection")
    for name in names:
        if not isinstance(name, str) or not SKILL_NAME_RE.fullmatch(name):
            raise ValueError(f"invalid skill name: {name!r}")
        if name not in assignments:
            raise ValueError(f"undeclared skill: {name}")
    return names


def section_block(repo_root: pathlib.Path, manifest: Mapping[str, object], skill: str) -> str:
    """Resolve one skill's shared sections without lifecycle validation."""
    sections = cast(Mapping[str, object], manifest["sections"])
    assignments = cast(Mapping[str, object], manifest["skills"])
    selected = assignments[skill]
    if not isinstance(selected, list) or not selected:
        raise ValueError(f"{skill}: section assignment must be a nonempty list")
    rendered: list[str] = []
    for name in selected:
        if not isinstance(name, str) or name not in sections:
            raise ValueError(f"{skill}: unresolved section {name!r}")
        relative = sections[name]
        if not isinstance(relative, str) or not safe_relative(relative):
            raise ValueError(f"{skill}: invalid section path {relative!r}")
        path = repo_root / relative
        require_inside(path, repo_root)
        if not path.is_file() or unsafe_link(path):
            raise ValueError(f"{skill}: unavailable section {relative}")
        lines = path.read_text(encoding="utf-8").splitlines()
        text = "\n".join(line for line in lines if not line.strip().startswith("<!-- INTERNAL:")).strip("\n")
        rendered.extend((f"{SOURCE_PREFIX}{relative}{SOURCE_SUFFIX}", text))
    return f"{START}\n" + "\n\n".join(rendered) + f"\n{END}"


def render_skill(source: str, shared: str, skill: str) -> str:
    """Insert resolved shared text after frontmatter and an optional H1."""
    if START in source or END in source:
        raise ValueError(f"{skill}: source SKILL.md must not contain generated sections")
    lines = source.replace("\r\n", "\n").split("\n")
    if not lines or lines[0] != "---":
        raise ValueError(f"{skill}: missing frontmatter")
    try:
        frontmatter_end = lines[1:].index("---") + 1
    except ValueError as exc:
        raise ValueError(f"{skill}: missing closing frontmatter marker") from exc
    insert_after = frontmatter_end
    for index in range(frontmatter_end + 1, len(lines)):
        if not lines[index].strip():
            continue
        if lines[index].startswith("# "):
            insert_after = index
        break
    before = "\n".join(lines[: insert_after + 1]).rstrip()
    after = "\n".join(lines[insert_after + 1 :]).strip("\n")
    return f"{before}\n\n{shared}\n\n{after}\n" if after else f"{before}\n\n{shared}\n"


def payload_patterns(manifest: Mapping[str, object], skill: str) -> list[str]:
    """Return only globally and directly declared payload patterns."""
    payloads = cast(Mapping[str, object], manifest.get("runtime_payloads", {}))
    result: list[str] = []
    for key in ("*", skill):
        values = payloads.get(key, [])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError(f"runtime_payloads.{key} must be a string list")
        result.extend(cast(list[str], values))
    return result


def copy_payload(repo_root: pathlib.Path, pattern: str, target: pathlib.Path) -> None:
    """Copy one resolved payload pattern into a staged skill tree."""
    if not safe_relative(pattern):
        raise ValueError(f"unsafe runtime payload pattern: {pattern!r}")
    matches = sorted(repo_root.glob(pattern))
    if not matches and not any(token in pattern for token in "*?["):
        raise ValueError(f"runtime payload does not exist: {pattern}")
    for source in matches:
        require_inside(source, repo_root)
        if unsafe_link(source):
            raise ValueError(f"runtime payload cannot be a link: {source}")
        relative = source.relative_to(repo_root)
        destination = target / relative
        if source.is_dir():
            shutil.copytree(source, destination, ignore=shutil.ignore_patterns(*IGNORED_NAMES), dirs_exist_ok=True)
        elif source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def build_skill(repo_root: pathlib.Path, staging: pathlib.Path, manifest: Mapping[str, object], skill: str) -> None:
    """Fully resolve and stage one skill without touching its destination."""
    source = repo_root / "skills" / skill
    skill_md = source / "SKILL.md"
    if not skill_md.is_file() or unsafe_link(source) or unsafe_link(skill_md):
        raise ValueError(f"{skill}: missing or unsafe source SKILL.md")
    for path in source.rglob("*"):
        if unsafe_link(path):
            raise ValueError(f"{skill}: source tree contains a link")
    target = staging / skill
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*IGNORED_NAMES))
    rendered = render_skill(skill_md.read_text(encoding="utf-8"), section_block(repo_root, manifest, skill), skill)
    (target / "SKILL.md").write_text(rendered, encoding="utf-8", newline="\n")
    for pattern in payload_patterns(manifest, skill):
        copy_payload(repo_root, pattern, target)
    metadata = {
        "schema": RUNTIME_MANIFEST_SCHEMA,
        "skill": skill,
        "runtime_source_id": manifest["runtime_source_id"],
        "validation_profile": manifest.get("validation_profile", "ceratops-compatible"),
        "source_path": f"skills/{skill}",
        "source_repository_root": str(repo_root),
        "installer_version": INSTALLER_VERSION,
        "generated_from": "skills/skill-sections.json",
        "payload_patterns": payload_patterns(manifest, skill),
    }
    (target / MANIFEST_NAME).write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def replace_skill(staged: pathlib.Path, destination: pathlib.Path, source_id: str, skill: str) -> None:
    """Replace only a destination already owned by this source repository."""
    target = destination / skill
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_dir():
            raise ValueError(f"refusing to replace unmanaged destination: {target}")
        try:
            owner = json.loads((target / MANIFEST_NAME).read_text(encoding="utf-8")).get("runtime_source_id")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid destination ownership: {target}") from exc
        if owner != source_id:
            raise ValueError(f"destination is owned by {owner!r}: {target}")
        shutil.rmtree(target)
    shutil.copytree(staged / skill, target)


def main() -> int:
    """Stage every selected skill, then perform the ordinary reinstall writes."""
    parser = argparse.ArgumentParser(description="Install declared repository skills.")
    parser.add_argument("--repo-root", type=pathlib.Path, help="Source repository root; defaults to this script's repository.")
    parser.add_argument("--install-root", type=pathlib.Path, help="Destination; defaults to $CODEX_HOME/skills.")
    parser.add_argument("--skill", action="append", default=[], help="Install only this declared skill; repeat as needed.")
    args = parser.parse_args()
    repo_root = (args.repo_root or pathlib.Path(__file__).resolve().parents[1]).resolve()
    default_root = pathlib.Path(os.environ.get("CODEX_HOME", pathlib.Path.home() / ".codex")) / "skills"
    destination = (args.install_root or default_root).expanduser().resolve()
    try:
        manifest = read_manifest(repo_root)
        skills = declared_skills(manifest, args.skill)
        with tempfile.TemporaryDirectory(prefix="skills-install-") as temporary:
            staging = pathlib.Path(temporary)
            for skill in skills:
                build_skill(repo_root, staging, manifest, skill)
            destination.mkdir(parents=True, exist_ok=True)
            source_id = cast(str, manifest["runtime_source_id"])
            for skill in skills:
                replace_skill(staging, destination, source_id, skill)
    except (OSError, UnicodeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return fail(str(exc))
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
