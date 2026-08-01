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
import pathlib
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping


BUNDLE_ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = BUNDLE_ROOT / "scripts" / "templates" / "skill-sections-template.json"
SOURCE_REPO_ROOT = BUNDLE_ROOT.parents[1]
SOURCE_CANONICAL_SECTIONS = SOURCE_REPO_ROOT / "skills" / "sections"
INSTALLED_CANONICAL_SECTIONS = BUNDLE_ROOT / "skills" / "sections"
SYNCHRONIZER = BUNDLE_ROOT / "scripts" / "runtime" / "synchronize-installers.py"
MANIFEST_RELATIVE = pathlib.Path("skills/skill-sections.json")
START = "<!-- CERATOPS_SHARED_SECTIONS_START -->"
END = "<!-- CERATOPS_SHARED_SECTIONS_END -->"
SOURCE_RE = re.compile(r"<!-- SECTION SOURCE: skills/sections/([^ ]+) -->")
GITHUB_REMOTE_RE = re.compile(
    r"(?:github\.com[:/])(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
    re.IGNORECASE,
)


def require_linked_worktree(repo_root: pathlib.Path) -> None:
    """Reject primary checkouts so compatibility writes stay task-isolated."""

    if not (repo_root / ".git").is_file():
        raise RuntimeError(f"target repository must be a linked task worktree: {repo_root}")


def runtime_source_id(repo_root: pathlib.Path, explicit: str | None) -> str:
    """Return an explicit identity or derive owner/repository from origin."""

    if explicit and explicit.strip():
        return explicit.strip()
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


def canonical_sections_root() -> pathlib.Path:
    """Resolve canonical sections from source checkout or installed payload."""

    for candidate in (SOURCE_CANONICAL_SECTIONS, INSTALLED_CANONICAL_SECTIONS):
        if (candidate / "core.md").is_file():
            return candidate
    raise RuntimeError("canonical shared sections are missing from lifecycle bundle")


def strip_generated_block(path: pathlib.Path) -> set[str]:
    """Remove one complete generated block and return its declared sections."""

    text = path.read_text(encoding="utf-8")
    start_count = text.count(START)
    end_count = text.count(END)
    if start_count == end_count == 0:
        return set()
    if start_count != 1 or end_count != 1 or text.index(START) > text.index(END):
        raise RuntimeError(f"{path}: malformed shared-section markers")
    start = text.index(START)
    end = text.index(END) + len(END)
    declared = set(SOURCE_RE.findall(text[start:end]))
    updated = (text[:start].rstrip() + "\n\n" + text[end:].lstrip()).rstrip() + "\n"
    path.write_text(updated, encoding="utf-8", newline="\n")
    return declared


def materialize(repo_root: pathlib.Path, source_id: str) -> tuple[list[str], list[str]]:
    """Create the live manifest and canonical sections from target evidence."""

    template = load_mapping(TEMPLATE)
    existing_path = repo_root / MANIFEST_RELATIVE
    existing = load_mapping(existing_path) if existing_path.is_file() else {}
    skill_paths = sorted((repo_root / "skills").glob("*/SKILL.md"))
    if not skill_paths:
        raise RuntimeError("target repository has no skills/*/SKILL.md sources")

    assignments: dict[str, list[str]] = {}
    required_sections = {"core"}
    updated_markers: list[str] = []
    for skill_path in skill_paths:
        declared = strip_generated_block(skill_path)
        if declared:
            updated_markers.append(skill_path.parent.name)
        text = skill_path.read_text(encoding="utf-8")
        selected = ["core"]
        if "multi-action-skill.md" in declared or "### Action References" in text:
            selected.append("multi-action-skill")
            required_sections.add("multi-action-skill")
        assignments[skill_path.parent.name] = selected

    sections_dir = repo_root / "skills" / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)
    sections: dict[str, str] = {}
    canonical_sections = canonical_sections_root()
    for section_name in sorted(required_sections):
        filename = f"{section_name}.md"
        source = canonical_sections / filename
        if not source.is_file():
            raise RuntimeError(f"canonical shared section is missing: {source}")
        shutil.copy2(source, sections_dir / filename)
        sections[section_name] = f"skills/sections/{filename}"

    profile = existing.get("validation_profile", template["validation_profile"])
    if profile not in {"ceratops", "ceratops-compatible"}:
        raise RuntimeError(f"unsupported validation_profile: {profile!r}")
    manifest = dict(template)
    manifest.update(
        {
            "runtime_source_id": source_id,
            "validation_profile": profile,
            "sections": sections,
            "maintenance_workflows": existing.get("maintenance_workflows", {}),
            "runtime_payloads": existing.get("runtime_payloads", {}),
            "skills": assignments,
        }
    )
    for key in ("maintenance_workflows", "runtime_payloads"):
        if not isinstance(manifest[key], Mapping):
            raise RuntimeError(f"existing {key} must be an object")
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return sorted(assignments), sorted(updated_markers)


def main() -> int:
    """Materialize compatibility inputs, synchronize installer, and validate."""

    parser = argparse.ArgumentParser(
        description="Materialize Ceratops-compatible shared-section sources."
    )
    parser.add_argument("--target-repo-root", required=True, type=pathlib.Path)
    parser.add_argument("--runtime-source-id")
    args = parser.parse_args()
    repo_root = args.target_repo_root.resolve()
    try:
        require_linked_worktree(repo_root)
        source_id = runtime_source_id(repo_root, args.runtime_source_id)
        skills, updated_markers = materialize(repo_root, source_id)
        result = subprocess.run(
            [sys.executable, str(SYNCHRONIZER), "--target-repo-root", str(repo_root)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip())
        installer = json.loads(result.stdout)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        return 1

    print(
        json.dumps(
            {
                "installer": installer["status"],
                "markers_removed": updated_markers,
                "runtime_source_id": source_id,
                "skills": skills,
                "status": "ok",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
