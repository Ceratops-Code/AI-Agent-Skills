"""Run the GitHub PR workflow by module name or direct skill-local path."""

from __future__ import annotations

import importlib
import pathlib
import sys


if not __package__:
    # Direct execution keeps the caller's cwd outside the replaceable skill tree
    # while this stable script location supplies the package import root.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

main = importlib.import_module(
    f"{__package__ or 'github_pr_workflow'}.cli"
).main


if __name__ == "__main__":
    raise SystemExit(main())
