#!/usr/bin/env python3
"""Materialize shared-section compatibility sources in one task worktree.

The lifecycle bundle owns the reusable template and canonical shared sections.
This helper derives repository identity and skill assignments, removes only
generated marker blocks from source skills, delegates installer ownership to
``runtime/synchronize-installers.py``, and emits one compact JSON result.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass


BUNDLE_ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = BUNDLE_ROOT / "scripts" / "templates" / "skill-sections-template.json"
SOURCE_REPO_ROOT = BUNDLE_ROOT.parents[1]
SOURCE_CANONICAL_SECTIONS = SOURCE_REPO_ROOT / "skills" / "sections"
INSTALLED_CANONICAL_SECTIONS = BUNDLE_ROOT / "skills" / "sections"
SYNCHRONIZER = BUNDLE_ROOT / "scripts" / "runtime" / "synchronize-installers.py"
MANIFEST_RELATIVE = pathlib.Path("skills/skill-sections.json")
INSTALLER_RELATIVE = pathlib.Path("scripts/install-skills.py")
START = "<!-- CERATOPS_SHARED_SECTIONS_START -->"
END = "<!-- CERATOPS_SHARED_SECTIONS_END -->"
SOURCE_RE = re.compile(r"<!-- SECTION SOURCE: skills/sections/([^ ]+) -->")
GITHUB_REMOTE_RE = re.compile(
    r"(?:github\.com[:/])(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FileSnapshot:
    """Exact recoverable state for one file the helper may change."""

    path: pathlib.Path
    content: bytes | None
    mode: int | None


@dataclass(frozen=True)
class MaterializationPlan:
    """Validated target writes ready for rollback-protected application."""

    manifest: dict[str, object]
    skill_updates: dict[pathlib.Path, tuple[str, str]]
    canonical_sources: dict[str, pathlib.Path]
    skills: list[str]
    updated_markers: list[str]


def require_linked_worktree(repo_root: pathlib.Path) -> None:
    """Reject primary checkouts so compatibility writes stay task-isolated."""

    if not (repo_root / ".git").is_file():
        raise RuntimeError(f"target repository must be a linked task worktree: {repo_root}")


def runtime_source_id(
    repo_root: pathlib.Path,
    explicit: str | None,
    existing: Mapping[str, object],
) -> str:
    """Resolve explicit, existing, then origin-derived runtime identity."""

    if explicit and explicit.strip():
        return explicit.strip()
    existing_id = existing.get("runtime_source_id")
    if isinstance(existing_id, str) and existing_id.strip():
        return existing_id.strip()
    if existing_id not in (None, ""):
        raise RuntimeError("existing runtime_source_id must be a string")
    result = subprocess.run(
        ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    match = GITHUB_REMOTE_RE.search(result.stdout.strip()) if result.returncode == 0 else None
    if not match:
        raise RuntimeError("runtime_source_id is not derivable; pass --runtime-source-id")
    return f"{match.group('owner')}/{match.group('repo')}"


def load_mapping(path: pathlib.Path) -> dict[str, object]:
    """Load one JSON object with compact failure semantics."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root must be an object: {path}")
    return value


def validate_template(template: Mapping[str, object]) -> None:
    """Require the closed repository-neutral compatibility skeleton."""

    expected = {
        "runtime_source_id": "",
        "validation_profile": "ceratops-compatible",
        "sections": {"core": "skills/sections/core.md"},
        "maintenance_workflows": {},
        "runtime_payloads": {},
        "skills": {},
    }
    if template != expected:
        raise RuntimeError("skill-sections template is not repository-neutral")


def portable_section_path(repo_root: pathlib.Path, value: object) -> pathlib.Path:
    """Resolve one existing portable section source inside the target repo."""

    if not isinstance(value, str) or not value:
        raise RuntimeError(f"section path must be a nonempty string: {value!r}")
    normalized = value.replace("\\", "/")
    pure = pathlib.PurePosixPath(normalized)
    windows = pathlib.PureWindowsPath(value)
    if pure.is_absolute() or windows.is_absolute() or windows.drive or ".." in pure.parts:
        raise RuntimeError(f"section path must be repository-relative: {value}")
    path = repo_root.joinpath(*pure.parts)
    try:
        path.resolve().relative_to(repo_root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"section path escapes repository: {value}") from exc
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"section source is missing or unsafe: {value}")
    return path


def existing_custom_sections(
    repo_root: pathlib.Path,
    existing: Mapping[str, object],
) -> dict[str, str]:
    """Validate and return target-owned noncanonical section declarations."""

    raw = existing.get("sections", {})
    if not isinstance(raw, Mapping):
        raise RuntimeError("existing sections must be an object")
    sections: dict[str, str] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not name:
            raise RuntimeError("existing section names must be nonempty strings")
        if name in {"core", "multi-action-skill"}:
            continue
        path = portable_section_path(repo_root, value)
        sections[name] = path.relative_to(repo_root).as_posix()
    return sections


def existing_skill_assignments(
    existing: Mapping[str, object],
    skill_names: set[str],
    custom_sections: Mapping[str, str],
) -> dict[str, list[str]]:
    """Validate assignments for current skills without retaining stale skills."""

    raw = existing.get("skills", {})
    if not isinstance(raw, Mapping):
        raise RuntimeError("existing skills assignments must be an object")
    assignments: dict[str, list[str]] = {}
    for skill_name in sorted(skill_names):
        value = raw.get(skill_name, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise RuntimeError(f"{skill_name}: existing assignment must be a list of strings")
        unknown = sorted(
            item
            for item in value
            if item not in {"core", "multi-action-skill"} and item not in custom_sections
        )
        if unknown:
            raise RuntimeError(
                f"{skill_name}: unknown existing section assignments: {', '.join(unknown)}"
            )
        assignments[skill_name] = list(dict.fromkeys(value))
    return assignments


def canonical_sections_root() -> pathlib.Path:
    """Resolve canonical sections from source checkout or installed payload."""

    for candidate in (SOURCE_CANONICAL_SECTIONS, INSTALLED_CANONICAL_SECTIONS):
        if (candidate / "core.md").is_file():
            return candidate
    raise RuntimeError("canonical shared sections are missing from lifecycle bundle")


def rendered_delta(path: pathlib.Path) -> tuple[str | None, set[str], str]:
    """Return marker-free text, declared section files, and original newline."""

    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8").replace("\r\n", "\n")
    start_count = text.count(START)
    end_count = text.count(END)
    if start_count == end_count == 0:
        return None, set(), newline
    if start_count != 1 or end_count != 1 or text.index(START) > text.index(END):
        raise RuntimeError(f"{path}: malformed shared-section markers")
    start = text.index(START)
    end = text.index(END) + len(END)
    declared = set(SOURCE_RE.findall(text[start:end]))
    updated = (text[:start].rstrip() + "\n\n" + text[end:].lstrip()).rstrip() + "\n"
    return updated, declared, newline


def snapshot_file(path: pathlib.Path) -> FileSnapshot:
    """Capture bytes and mode before the first target mutation."""

    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise RuntimeError(f"mutable target path is not a regular file: {path}")
    if not path.exists():
        return FileSnapshot(path, None, None)
    stat = path.stat()
    return FileSnapshot(path, path.read_bytes(), stat.st_mode)


def restore_snapshots(
    snapshots: list[FileSnapshot],
    created_dirs: list[pathlib.Path],
) -> None:
    """Restore exact file bytes and modes, then remove helper-created empty dirs."""

    errors: list[str] = []
    for snapshot in reversed(snapshots):
        try:
            if snapshot.content is None:
                if snapshot.path.exists() or snapshot.path.is_symlink():
                    if snapshot.path.is_symlink() or not snapshot.path.is_file():
                        raise RuntimeError("replacement is not a regular file")
                    snapshot.path.unlink()
                continue
            if snapshot.path.is_symlink() or (
                snapshot.path.exists() and not snapshot.path.is_file()
            ):
                raise RuntimeError("replacement is not a regular file")
            snapshot.path.parent.mkdir(parents=True, exist_ok=True)
            snapshot.path.write_bytes(snapshot.content)
            if snapshot.mode is not None:
                os.chmod(snapshot.path, snapshot.mode)
        except (OSError, RuntimeError) as exc:
            errors.append(f"{snapshot.path}: {exc}")
    for directory in reversed(created_dirs):
        try:
            if directory.is_dir():
                directory.rmdir()
        except OSError as exc:
            errors.append(f"{directory}: {exc}")
    if errors:
        raise RuntimeError("; ".join(errors))


def plan_materialization(
    repo_root: pathlib.Path,
    source_id: str,
    template: Mapping[str, object],
    existing: Mapping[str, object],
) -> MaterializationPlan:
    """Validate target evidence and compose writes without changing files."""

    skill_paths = sorted((repo_root / "skills").glob("*/SKILL.md"))
    if not skill_paths:
        raise RuntimeError("target repository has no skills/*/SKILL.md sources")

    skill_names = {path.parent.name for path in skill_paths}
    custom_sections = existing_custom_sections(repo_root, existing)
    prior_assignments = existing_skill_assignments(
        existing,
        skill_names,
        custom_sections,
    )
    maintenance_workflows = existing.get("maintenance_workflows", {})
    runtime_payloads = existing.get("runtime_payloads", {})
    if not isinstance(maintenance_workflows, Mapping):
        raise RuntimeError("existing maintenance_workflows must be an object")
    if not isinstance(runtime_payloads, Mapping):
        raise RuntimeError("existing runtime_payloads must be an object")

    assignments: dict[str, list[str]] = {}
    required_sections = {"core"}
    updated_markers: list[str] = []
    skill_updates: dict[pathlib.Path, tuple[str, str]] = {}
    for skill_path in skill_paths:
        updated, declared, newline = rendered_delta(skill_path)
        if declared:
            updated_markers.append(skill_path.parent.name)
        text = (
            updated
            if updated is not None
            else skill_path.read_text(encoding="utf-8")
        )
        if updated is not None:
            skill_updates[skill_path] = (updated, newline)
        selected = ["core"]
        if "multi-action-skill.md" in declared or "### Action References" in text:
            selected.append("multi-action-skill")
            required_sections.add("multi-action-skill")
        for section_name in prior_assignments[skill_path.parent.name]:
            if section_name not in {"core", "multi-action-skill"}:
                selected.append(section_name)
        for filename in sorted(declared):
            if filename in {"core.md", "multi-action-skill.md"}:
                continue
            rel_path = f"skills/sections/{filename}"
            marker_section_name: str | None = next(
                (
                    name
                    for name, path in custom_sections.items()
                    if path == rel_path
                ),
                None,
            )
            if marker_section_name is None:
                source_path = portable_section_path(repo_root, rel_path)
                candidate_name = pathlib.PurePosixPath(filename).stem
                if not candidate_name or candidate_name in {
                    "core",
                    "multi-action-skill",
                }:
                    raise RuntimeError(
                        f"cannot derive section name from marker source: {rel_path}"
                    )
                collision = custom_sections.get(candidate_name)
                if collision is not None and collision != rel_path:
                    raise RuntimeError(
                        f"section name {candidate_name} maps to multiple sources"
                    )
                custom_sections[candidate_name] = source_path.relative_to(
                    repo_root
                ).as_posix()
                marker_section_name = candidate_name
            selected.append(marker_section_name)
        assignments[skill_path.parent.name] = list(dict.fromkeys(selected))

    sections: dict[str, str] = {"core": "skills/sections/core.md"}
    if "multi-action-skill" in required_sections:
        sections["multi-action-skill"] = (
            "skills/sections/multi-action-skill.md"
        )
    sections.update(
        {name: custom_sections[name] for name in sorted(custom_sections)}
    )
    profile = existing.get("validation_profile", template["validation_profile"])
    if profile not in {"ceratops", "ceratops-compatible"}:
        raise RuntimeError(f"unsupported validation_profile: {profile!r}")
    canonical_sections = canonical_sections_root()
    canonical_sources = {
        section_name: canonical_sections / f"{section_name}.md"
        for section_name in required_sections
    }
    for source in canonical_sources.values():
        if not source.is_file():
            raise RuntimeError(f"canonical shared section is missing: {source}")

    manifest = dict(template)
    manifest.update(
        {
            "runtime_source_id": source_id,
            "validation_profile": profile,
            "sections": sections,
            "maintenance_workflows": dict(maintenance_workflows),
            "runtime_payloads": dict(runtime_payloads),
            "skills": assignments,
        }
    )
    return MaterializationPlan(
        manifest=manifest,
        skill_updates=skill_updates,
        canonical_sources=canonical_sources,
        skills=sorted(assignments),
        updated_markers=sorted(updated_markers),
    )


def apply_materialization(
    repo_root: pathlib.Path,
    plan: MaterializationPlan,
) -> None:
    """Apply one fully validated plan inside the caller's rollback boundary."""

    sections_dir = repo_root / "skills" / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)
    for section_name, source in sorted(plan.canonical_sources.items()):
        shutil.copy2(source, sections_dir / f"{section_name}.md")
    for skill_path, (updated, newline) in plan.skill_updates.items():
        skill_path.write_text(
            updated,
            encoding="utf-8",
            newline=newline,
        )
    existing_path = repo_root / MANIFEST_RELATIVE
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text(
        json.dumps(plan.manifest, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    """Materialize compatibility inputs, synchronize installer, and validate."""

    parser = argparse.ArgumentParser(
        description="Materialize Ceratops-compatible shared-section sources."
    )
    parser.add_argument("--target-repo-root", required=True, type=pathlib.Path)
    parser.add_argument("--runtime-source-id")
    args = parser.parse_args()
    repo_root = args.target_repo_root.resolve()
    phase = "preflight"
    rollback = "not_started"
    snapshots: list[FileSnapshot] = []
    created_dirs: list[pathlib.Path] = []
    mutation_started = False
    try:
        require_linked_worktree(repo_root)
        template = load_mapping(TEMPLATE)
        validate_template(template)
        existing_path = repo_root / MANIFEST_RELATIVE
        existing = load_mapping(existing_path) if existing_path.is_file() else {}
        source_id = runtime_source_id(
            repo_root,
            args.runtime_source_id,
            existing,
        )
        phase = "materialization_planning"
        plan = plan_materialization(
            repo_root,
            source_id,
            template,
            existing,
        )
        skill_paths = sorted((repo_root / "skills").glob("*/SKILL.md"))
        mutable_paths = [
            *skill_paths,
            existing_path,
            repo_root / "skills" / "sections" / "core.md",
            repo_root / "skills" / "sections" / "multi-action-skill.md",
            repo_root / INSTALLER_RELATIVE,
        ]
        snapshots = [snapshot_file(path) for path in dict.fromkeys(mutable_paths)]
        created_dirs = [
            path
            for path in (
                repo_root / "skills" / "sections",
                repo_root / "scripts",
            )
            if not path.exists()
        ]
        phase = "materialization"
        mutation_started = True
        apply_materialization(repo_root, plan)
        phase = "installer_validation"
        result = subprocess.run(
            [sys.executable, str(SYNCHRONIZER), "--target-repo-root", str(repo_root)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip())
        installer = json.loads(result.stdout)
        if not isinstance(installer, Mapping) or not isinstance(
            installer.get("status"), str
        ):
            raise RuntimeError("installer synchronizer returned invalid JSON")
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        reason = str(exc)
        if mutation_started:
            try:
                restore_snapshots(snapshots, created_dirs)
                rollback = "completed"
            except RuntimeError as rollback_exc:
                rollback = "failed"
                reason = f"{reason}; rollback failed: {rollback_exc}"
        print(
            json.dumps(
                {
                    "phase": phase,
                    "reason": reason,
                    "rollback": rollback,
                    "status": "blocked",
                },
                sort_keys=True,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "installer": installer["status"],
                "markers_removed": plan.updated_markers,
                "rollback": "not_needed",
                "runtime_source_id": source_id,
                "skills": plan.skills,
                "status": "ok",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
