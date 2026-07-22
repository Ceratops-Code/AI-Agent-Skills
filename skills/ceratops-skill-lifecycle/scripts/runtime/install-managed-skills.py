#!/usr/bin/env python3
"""Validate and install managed runtime skills from a compatible repository.

Full installs validate the complete source repository before building and
same-source stale cleanup. Explicit skill lists validate only those source
skills before targeted building and never remove stale runtime folders.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys


BUNDLE_ROOT = pathlib.Path(__file__).resolve().parents[2]
VALIDATOR = BUNDLE_ROOT / "scripts" / "skills-consistency-source-validator.py"
BUILDER = BUNDLE_ROOT / "scripts" / "runtime" / "managed_runtime_builder.py"


def default_install_root() -> pathlib.Path:
    """Return the direct personal runtime skills root."""

    codex_home = os.environ.get("CODEX_HOME")
    return pathlib.Path(codex_home).expanduser() / "skills" if codex_home else pathlib.Path.home() / ".codex" / "skills"


def source_skill_names(repo_root: pathlib.Path) -> list[str]:
    """Return source skill directory names that contain ``SKILL.md``."""

    return sorted(path.parent.name for path in (repo_root / "skills").glob("*/SKILL.md"))


def run_checked(arguments: list[str], failure: str) -> str:
    """Run one helper and preserve its bounded diagnostic output on failure."""

    result = subprocess.run(arguments, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"{failure}: {detail}" if detail else failure)
    return result.stdout.strip()


def main() -> int:
    """Validate the target repository and invoke the managed runtime builder."""

    parser = argparse.ArgumentParser(description="Validate and install managed runtime skills.")
    parser.add_argument("--repo-root", required=True, type=pathlib.Path)
    parser.add_argument("--install-root", type=pathlib.Path)
    parser.add_argument("--installer-version", required=True, type=int)
    parser.add_argument("--skill", action="append")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    install_root = (args.install_root or default_install_root()).resolve()
    if args.installer_version < 1:
        print("installer version must be a positive integer", file=sys.stderr)
        return 1
    if not (repo_root / "skills").is_dir():
        print(f"missing skills directory: {repo_root / 'skills'}", file=sys.stderr)
        return 1
    if not VALIDATOR.is_file() or not BUILDER.is_file():
        print("installed lifecycle bundle is incomplete", file=sys.stderr)
        return 1

    known_skills = source_skill_names(repo_root)
    selected = sorted(set(args.skill or known_skills))
    unknown = sorted(set(selected) - set(known_skills))
    if unknown:
        print(f"unknown skill(s): {', '.join(unknown)}", file=sys.stderr)
        return 1

    try:
        validation_mode = "skill" if args.skill is not None else "full"
        validation_command = [
            sys.executable,
            str(VALIDATOR),
            "--repo-root",
            str(repo_root),
            "--mode",
            validation_mode,
        ]
        if validation_mode == "skill":
            for skill_name in selected:
                validation_command.extend(("--skill", skill_name))
        run_checked(
            validation_command,
            "Targeted skill validation failed" if validation_mode == "skill" else "Full source-repository validation failed",
        )
        command = [
            sys.executable,
            str(BUILDER),
            "--repo-root",
            str(repo_root),
            "--install-root",
            str(install_root),
            "--installer-version",
            str(args.installer_version),
        ]
        for skill_name in selected:
            command.extend(("--skill", skill_name))
        if args.skill is None:
            command.append("--remove-stale")
        run_checked(command, "Managed runtime build failed")
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
