#!/usr/bin/env python3
"""Prefer the installed lifecycle installer, with one independent fallback."""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile


INSTALLER_VERSION = 9
LIFECYCLE_SKILL = "ceratops-skill-lifecycle"
RUNTIME_INSTALLER_RELATIVE = pathlib.Path(
    "scripts/runtime/install-managed-skills.py"
)
INDEPENDENT_INSTALLER = (
    pathlib.Path(__file__).resolve().parents[1]
    / "skills"
    / LIFECYCLE_SKILL
    / "scripts/templates/install-skills-template.py"
)
CHECKOUT_ROOT = pathlib.Path(__file__).resolve().parents[1]


def codex_skills_root() -> pathlib.Path:
    """Return the installed runtime root without inspecting bundle metadata."""

    codex_home = os.environ.get("CODEX_HOME")
    root = (
        pathlib.Path(codex_home).expanduser()
        if codex_home
        else pathlib.Path.home() / ".codex"
    )
    return (root / "skills").resolve()


def run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    """Run one deterministic installer path without a shell."""

    return subprocess.run(
        arguments,
        capture_output=True,
        text=True,
        check=False,
    )


def detail(result: subprocess.CompletedProcess[str]) -> str:
    """Return the smallest available failure detail from one installer."""

    return (result.stderr or result.stdout).strip()


def installed_runtime_installer() -> pathlib.Path | None:
    """Return the installed lifecycle entrypoint when it is available."""

    installer = (
        codex_skills_root()
        / LIFECYCLE_SKILL
        / RUNTIME_INSTALLER_RELATIVE
    )
    return installer if installer.is_file() else None


def runtime_command(
    installer: pathlib.Path,
    repo_root: pathlib.Path,
    install_root: pathlib.Path | None,
    skills: list[str],
    removed_skills: list[str],
    base_revision: str | None,
) -> list[str]:
    """Build one installed lifecycle command from a selected entrypoint."""

    command = [
        sys.executable,
        str(installer),
        "--repo-root",
        str(repo_root),
        "--installer-version",
        str(INSTALLER_VERSION),
    ]
    if install_root is not None:
        command.extend(("--install-root", str(install_root)))
    for skill in skills:
        command.extend(("--skill", skill))
    for skill in removed_skills:
        command.extend(("--remove-skill", skill))
    if base_revision is not None:
        command.extend(("--base-revision", base_revision))
    return command


def run_installed_lifecycle(
    repo_root: pathlib.Path,
    install_root: pathlib.Path | None,
    skills: list[str],
    removed_skills: list[str],
    base_revision: str | None,
) -> subprocess.CompletedProcess[str] | None:
    """Run installed lifecycle behavior outside its managed destination.

    An all-managed Windows transaction may replace the lifecycle skill that
    owns this helper. Copying its complete runtime directory before launch
    prevents executable source files from blocking that transactional rename.
    """

    installer = installed_runtime_installer()
    if installer is None:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="installed-lifecycle-runtime-") as raw:
            detached_runtime = pathlib.Path(raw) / "runtime"
            shutil.copytree(installer.parent, detached_runtime)
            command = runtime_command(
                detached_runtime / installer.name,
                repo_root,
                install_root,
                skills,
                removed_skills,
                base_revision,
            )
            return run(command)
    except OSError as exc:
        return subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=str(exc)
        )


def independent_command(
    repo_root: pathlib.Path,
    install_root: pathlib.Path | None,
    skills: list[str],
) -> list[str]:
    """Build the one-shot independent reinstall command from checkout source."""

    if not INDEPENDENT_INSTALLER.is_file():
        raise FileNotFoundError("Independent installer is missing.")
    command = [
        sys.executable,
        str(INDEPENDENT_INSTALLER),
        "--repo-root",
        str(repo_root),
    ]
    if install_root is not None:
        command.extend(("--install-root", str(install_root)))
    for skill in skills:
        command.extend(("--skill", skill))
    return command


def main() -> int:
    """Use the installed lifecycle first, then one independent reinstall."""

    parser = argparse.ArgumentParser(description="Install AI-Agent-Skills.")
    parser.add_argument(
        "--repo-root",
        type=pathlib.Path,
        help="AI-Agent-Skills checkout; defaults to this script's repository.",
    )
    parser.add_argument(
        "--install-root",
        type=pathlib.Path,
        help="Runtime skills root; defaults to $CODEX_HOME/skills.",
    )
    parser.add_argument(
        "--skill",
        action="append",
        help="Install only this skill; repeat for multiple skills.",
    )
    parser.add_argument(
        "--remove-skill",
        action="append",
        help="Remove this absent source skill; repeat for multiple skills.",
    )
    parser.add_argument(
        "--base-revision",
        help="Calculate the exact runtime effect since this full Git revision.",
    )
    args = parser.parse_args()

    repo_root = (args.repo_root or CHECKOUT_ROOT).resolve()
    install_root = args.install_root.resolve() if args.install_root else None
    try:
        if repo_root != CHECKOUT_ROOT:
            raise RuntimeError(
                "This installer only installs the AI-Agent-Skills checkout "
                "that contains it."
            )
        lifecycle = run_installed_lifecycle(
            repo_root,
            install_root,
            args.skill or [],
            args.remove_skill or [],
            args.base_revision,
        )
        lifecycle_failure = ""
        if lifecycle is not None:
            if lifecycle.returncode == 0:
                print(lifecycle.stdout.strip() or "OK")
                return 0
            lifecycle_failure = detail(lifecycle)

        fallback = run(
            independent_command(repo_root, install_root, args.skill or [])
        )
        if fallback.returncode != 0:
            fallback_failure = detail(fallback) or "independent installer failed"
            if lifecycle is not None:
                first_failure = lifecycle_failure or "installed lifecycle failed"
                raise RuntimeError(
                    f"Installed lifecycle failed: {first_failure}; "
                    f"independent installer failed: {fallback_failure}"
                )
            raise RuntimeError(f"Independent installer failed: {fallback_failure}")
    except (FileNotFoundError, RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(fallback.stdout.strip() or "OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
