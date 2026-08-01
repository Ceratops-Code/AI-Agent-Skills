#!/usr/bin/env python3
"""Bootstrap this source repository through its checked-out lifecycle bundle."""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys


INSTALLER_VERSION = 8
LIFECYCLE_SKILL = "ceratops-skill-lifecycle"
RESOLVER_RELATIVE = pathlib.Path("scripts/runtime/resolve-lifecycle-bundle.py")
INSTALLER_RELATIVE = pathlib.Path("scripts/runtime/install-managed-skills.py")
VALIDATOR_RELATIVE = pathlib.Path("scripts/skills-consistency-source-validator.py")
CHECKOUT_ROOT = pathlib.Path(__file__).resolve().parents[1]


def resolver_path(repo_root: pathlib.Path) -> pathlib.Path:
    """Require the lifecycle resolver from this exact source checkout."""

    checkout = repo_root / "skills" / LIFECYCLE_SKILL / RESOLVER_RELATIVE
    if checkout.is_file():
        return checkout
    raise FileNotFoundError("The source checkout lifecycle resolver is missing.")


def run_checked(arguments: list[str], failure: str) -> str:
    """Run one helper and preserve compact failure evidence."""

    result = subprocess.run(arguments, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"{failure}: {detail}" if detail else failure)
    return result.stdout.strip()


def main() -> int:
    """Run the checked-out lifecycle bundle's full managed installation."""

    parser = argparse.ArgumentParser(description="Install managed Ceratops-compatible skills.")
    parser.add_argument("--repo-root", type=pathlib.Path, help="Source repository root; defaults to this script's repository.")
    parser.add_argument("--install-root", type=pathlib.Path, help="Runtime skills root; defaults to $CODEX_HOME/skills.")
    parser.add_argument("--skill", action="append", help="Install only this skill; repeat for multiple skills.")
    parser.add_argument("--remove-skill", action="append", help="Remove this absent source skill; repeat for multiple skills.")
    parser.add_argument("--base-revision", help="Calculate the exact runtime effect since this full Git revision.")
    args = parser.parse_args()

    repo_root = (args.repo_root or CHECKOUT_ROOT).resolve()
    try:
        if repo_root != CHECKOUT_ROOT:
            raise RuntimeError(
                "This bootstrap only installs the AI-Agent-Skills checkout "
                "that contains it."
            )
        resolver = resolver_path(repo_root)
        validator = repo_root / "skills" / LIFECYCLE_SKILL / VALIDATOR_RELATIVE
        if not validator.is_file():
            raise FileNotFoundError("The source checkout validator is missing.")
        run_checked(
            [sys.executable, str(validator), "--repo-root", str(repo_root), "--mode", "full"],
            "Source validation failed",
        )
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
