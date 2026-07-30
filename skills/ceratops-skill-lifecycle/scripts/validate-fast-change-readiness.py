#!/usr/bin/env python3
"""Validate one complete direct-release skill-change scope without mutating it.

The helper verifies the clean release checkout, selected existing source
skills, declared target files, and repository targeted-installer availability.
It deliberately does not judge semantic risk or run installation; the
fast-change action owns those decisions after this deterministic preflight.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys


class ReadinessError(RuntimeError):
    """Raised when direct-release fast-change prerequisites are not satisfied."""


def _git(repo_root: pathlib.Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ReadinessError(detail or f"git failed: {' '.join(args)}")
    return result.stdout


def _unique(values: list[str], label: str) -> list[str]:
    selected = list(dict.fromkeys(values))
    if len(selected) != len(values):
        raise ReadinessError(f"{label} values must be unique.")
    return selected


def validate(args: argparse.Namespace) -> dict[str, object]:
    """Return the compact verified branch, skill, and target scope."""

    repo_root = args.repo_root.expanduser().resolve(strict=True)
    if not repo_root.is_dir():
        raise ReadinessError("Repository root is not a directory.")
    if _git(repo_root, "rev-parse", "--is-inside-work-tree").strip() != "true":
        raise ReadinessError("Repository root is not inside a Git worktree.")
    branch = _git(repo_root, "branch", "--show-current").strip()
    if branch != args.release_branch:
        raise ReadinessError(
            f"Expected branch {args.release_branch}, got {branch or 'detached HEAD'}."
        )
    if _git(repo_root, "status", "--porcelain").strip():
        raise ReadinessError("Expected a clean worktree before fast-change.")

    skill_names = _unique(args.skill, "Skill")
    target_values = _unique(args.target, "Target")
    skills_root = (repo_root / "skills").resolve()
    skill_roots: dict[str, pathlib.Path] = {}
    for skill_name in skill_names:
        skill_root = (skills_root / skill_name).resolve()
        if skill_root.parent != skills_root or not (
            skill_root / "SKILL.md"
        ).is_file():
            raise ReadinessError(
                f"Selected skill must identify an existing source skill: {skill_name}"
            )
        skill_roots[skill_name] = skill_root

    relative_targets: list[str] = []
    affected_skills: set[str] = set()
    for value in target_values:
        raw_path = pathlib.Path(value)
        target = (
            raw_path if raw_path.is_absolute() else repo_root / raw_path
        ).resolve(strict=True)
        if not target.is_file():
            raise ReadinessError(f"Target must be an existing file: {value}")
        try:
            relative_target = target.relative_to(repo_root)
        except ValueError as exc:
            raise ReadinessError(f"Target must stay inside the repository: {value}") from exc
        owners = [
            skill_name
            for skill_name, skill_root in skill_roots.items()
            if target.is_relative_to(skill_root)
        ]
        if len(owners) != 1:
            raise ReadinessError(
                f"Target must stay inside one selected skill root: {value}"
            )
        affected_skills.add(owners[0])
        relative_targets.append(relative_target.as_posix())

    missing_targets = sorted(set(skill_names) - affected_skills)
    if missing_targets:
        raise ReadinessError(
            "Every selected skill requires at least one target: "
            + ", ".join(missing_targets)
        )
    if not (repo_root / "scripts" / "install-skills.py").is_file():
        raise ReadinessError("Missing repository targeted skill installer.")

    return {
        "status": "ready",
        "branch": branch,
        "skills": sorted(skill_names),
        "targets": sorted(relative_targets),
    }


def build_parser() -> argparse.ArgumentParser:
    """Create the fast-change readiness parser."""

    parser = argparse.ArgumentParser(
        description="Validate a complete direct-release fast-change scope."
    )
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--release-branch", default="release/local")
    parser.add_argument("--skill", action="append", required=True)
    parser.add_argument("--target", action="append", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Validate readiness and emit one compact JSON result."""

    try:
        result = validate(build_parser().parse_args(argv))
    except (OSError, ReadinessError, subprocess.SubprocessError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "error", "message": str(exc)},
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
