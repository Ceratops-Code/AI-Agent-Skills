from __future__ import annotations

import pathlib
import subprocess
import sys

COMPATIBILITY_ENGINE = "ceratops_repo_compatibility_engine"
# Isolated fixtures select a revision explicitly; they never resolve remote state.
CI_ACTION_REVISION = "1" * 40


def run_compatibility_engine(
    scripts_root: pathlib.Path,
    command: str,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    """Run one package command from its source or installed scripts folder."""

    if command == "apply" and "--ci-action-revision" not in arguments:
        arguments = (*arguments, "--ci-action-revision", CI_ACTION_REVISION)
    return subprocess.run(
        [sys.executable, "-m", COMPATIBILITY_ENGINE, command, *arguments],
        cwd=scripts_root,
        capture_output=True,
        text=True,
        check=False,
    )
