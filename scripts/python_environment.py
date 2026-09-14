"""Select the repository scripts project's locked Python before an entrypoint runs.

Entrypoints call ensure_environment before importing their dependencies. uv owns
the persistent scripts/.venv and its synchronization; the helper never activates
the caller shell, installs global packages, or resolves a changed lock. Nested
commands using the selected Python reuse the prepared environment. Application
modules imported by an entrypoint inherit that interpreter.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

PROJECT_MARKER = "CERATOPS_SCRIPTS_PROJECT"


def ensure_environment(script: str) -> None:
    """Relaunch a direct entrypoint through uv; retain cwd, argv, streams and status."""
    project = pathlib.Path(__file__).resolve().parent
    environment = project / ".venv"
    for target in (project, project / "pyproject.toml", project / "uv.lock", environment):
        for path in (target, *target.parents):
            junction = getattr(path, "is_junction", lambda: False)
            if path.is_symlink() or junction():
                raise SystemExit(f"error: scripts environment path must not be a link: {path}")
    for name in ("pyproject.toml", "uv.lock"):
        if not (project / name).is_file():
            raise SystemExit(f"error: missing scripts/{name}; apply repository environment setup first")
    if (os.environ.get(PROJECT_MARKER) == str(project)
            and pathlib.Path(sys.prefix).resolve() == environment.resolve()):
        return
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("error: uv is required to run repository Python scripts")
    child = os.environ.copy()
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT", "UV_WORKING_DIRECTORY",
                "UV_NO_SYNC", "UV_FROZEN", "UV_PYTHON", "UV_SYSTEM_PYTHON"):
        child.pop(key, None)
    child[PROJECT_MARKER] = str(project)
    child["UV_PROJECT_ENVIRONMENT"] = str(environment)
    child["PYTHONNOUSERSITE"] = "1"
    child["PYTHONDONTWRITEBYTECODE"] = "1"
    child["PYTHONUTF8"] = "1"
    command = [uv, "run", "--quiet", "--project", str(project), "--locked", "--exact",
               "--no-active", "python", str(pathlib.Path(script).resolve()), *sys.argv[1:]]
    try:
        result = subprocess.run(command, env=child, check=False)
    except OSError as exc:
        raise SystemExit(f"error: could not start the scripts environment: {exc}") from exc
    raise SystemExit(result.returncode)
