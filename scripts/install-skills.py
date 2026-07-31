#!/usr/bin/env python3
"""Bootstrap managed skill installation through the lifecycle runtime bundle.

The Ceratops lifecycle bundle owns the authoritative template for this
bootstrap. Compatible repositories carry it as ``scripts/install-skills.py``.
Keep repository-specific behavior out of this file: validation, rendering,
ownership checks, and stale cleanup belong to the selected lifecycle bundle.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys


INSTALLER_VERSION = 7
LIFECYCLE_SKILL = "ceratops-skill-lifecycle"
RESOLVER_RELATIVE = pathlib.Path("scripts/runtime/resolve-lifecycle-bundle.py")
INSTALLER_RELATIVE = pathlib.Path("scripts/runtime/install-managed-skills.py")


def codex_skills_root() -> pathlib.Path:
    """Return the personal runtime skill root used to discover the bundle."""

    codex_home = os.environ.get("CODEX_HOME")
    return pathlib.Path(codex_home).expanduser() / "skills" if codex_home else pathlib.Path.home() / ".codex" / "skills"


def checkout_is_ceratops(repo_root: pathlib.Path) -> bool:
    """Identify the Ceratops source repository from its section manifest."""

    try:
        manifest = json.loads(
            (repo_root / "skills" / "skill-sections.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(manifest, dict) and manifest.get("validation_profile") == "ceratops"


def resolver_path(repo_root: pathlib.Path) -> pathlib.Path:
    """Resolve the lifecycle bundle from source or the installed runtime."""

    checkout = repo_root / "skills" / LIFECYCLE_SKILL / RESOLVER_RELATIVE
    if checkout_is_ceratops(repo_root):
        if checkout.is_file():
            return checkout
        raise FileNotFoundError(
            "The Ceratops source repository lifecycle resolver is missing."
        )

    installed_bundle = codex_skills_root() / LIFECYCLE_SKILL
    installed = installed_bundle / RESOLVER_RELATIVE
    installed_version = 0
    try:
        manifest = json.loads(
            (installed_bundle / ".runtime-manifest.json").read_text(encoding="utf-8")
        )
        value = manifest.get("installer_version") if isinstance(manifest, dict) else None
        if isinstance(value, int) and not isinstance(value, bool):
            installed_version = value
    except (OSError, json.JSONDecodeError):
        pass
    if installed.is_file() and installed_version >= INSTALLER_VERSION:
        return installed

    if installed.is_file():
        return installed

    raise FileNotFoundError(
        "A supported installed ceratops-skill-lifecycle bundle is required."
    )


def run_checked(arguments: list[str], failure: str) -> str:
    """Run one helper and preserve compact failure evidence."""

    result = subprocess.run(arguments, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"{failure}: {detail}" if detail else failure)
    return result.stdout.strip()


def main() -> int:
    """Resolve one lifecycle bundle and install its managed skills."""

    parser = argparse.ArgumentParser(description="Install managed Ceratops-compatible skills.")
    parser.add_argument("--repo-root", type=pathlib.Path, help="Source repository root; defaults to this script's repository.")
    parser.add_argument("--install-root", type=pathlib.Path, help="Runtime skills root; defaults to $CODEX_HOME/skills.")
    parser.add_argument("--skill", action="append", help="Install only this skill; repeat for multiple skills.")
    parser.add_argument("--remove-skill", action="append", help="Remove this absent source skill; repeat for multiple skills.")
    parser.add_argument("--base-revision", help="Calculate the exact runtime effect since this full Git revision.")
    args = parser.parse_args()

    repo_root = (args.repo_root or pathlib.Path(__file__).resolve().parents[1]).resolve()
    try:
        resolver = resolver_path(repo_root)
        bundle_text = run_checked(
            [
                sys.executable,
                str(resolver),
                "--repo-root",
                str(repo_root),
                "--installer-version",
                str(INSTALLER_VERSION),
            ],
            "Lifecycle bundle resolution failed",
        )
        bundle_root = pathlib.Path(bundle_text).resolve()
        runtime_installer = bundle_root / INSTALLER_RELATIVE
        if not runtime_installer.is_file():
            raise FileNotFoundError(f"Missing lifecycle runtime installer: {runtime_installer}")

        command = [
            sys.executable,
            str(runtime_installer),
            "--repo-root",
            str(repo_root),
            "--installer-version",
            str(INSTALLER_VERSION),
        ]
        if args.install_root is not None:
            command.extend(("--install-root", str(args.install_root.resolve())))
        for skill_name in args.skill or []:
            command.extend(("--skill", skill_name))
        for skill_name in args.remove_skill or []:
            command.extend(("--remove-skill", skill_name))
        if args.base_revision is not None:
            command.extend(("--base-revision", args.base_revision))
        output = run_checked(command, "Managed skill installation failed")
    except (FileNotFoundError, RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(output or "OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
