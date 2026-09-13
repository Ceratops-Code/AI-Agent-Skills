"""Bounded subprocess handling shared by PR merge and local sync workflows."""

from __future__ import annotations

import pathlib
import subprocess

from github_contract_engine.github_api import github_read_command, run_github_command

class CommandError(RuntimeError):
    """Raised when a required native command fails."""


def run_command(
    args: list[str],
    *,
    cwd: pathlib.Path,
) -> subprocess.CompletedProcess[str]:
    """Run one command without shell expansion or inherited noisy output."""

    return run_github_command(
        args,
        retry_safe=github_read_command(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _tail(completed: subprocess.CompletedProcess[str]) -> str:
    lines = [
        line
        for stream in (completed.stdout, completed.stderr)
        for line in stream.splitlines()
        if line.strip()
    ]
    return "\n".join(lines[-8:])


def require_output(args: list[str], *, cwd: pathlib.Path) -> str:
    """Return stdout or raise with only the command's final diagnostic lines."""

    completed = run_command(args, cwd=cwd)
    if completed.returncode:
        detail = _tail(completed)
        suffix = f"\n{detail}" if detail else ""
        raise CommandError(f"{' '.join(args)} failed{suffix}")
    return completed.stdout.strip()


def require_success(args: list[str], *, cwd: pathlib.Path) -> None:
    """Require a successful native command while suppressing routine output."""

    require_output(args, cwd=cwd)
