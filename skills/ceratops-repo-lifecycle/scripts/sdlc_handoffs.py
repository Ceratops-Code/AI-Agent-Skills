"""Execute explicitly registered skill actions for skill callers, never CI.

SDLC contains only skill/action identities. Each installed skill owns its exact
executor binding. Missing bindings return a pending route; neither a route nor
successful command preparation constitutes evidence that an action completed.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys


def execute_handoff(route: str, repo_root: pathlib.Path) -> dict[str, object]:
    """Resolve a bounded installed-skill binding and execute shell-free argv."""

    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*", route):
        return {"status": "handoff_required", "handoff": route, "message": "No deterministic skill/action binding."}
    skill, action = route.split("/")
    skills = pathlib.Path(os.environ.get("CODEX_HOME", str(pathlib.Path.home() / ".codex"))) / "skills"
    root = skills / skill
    binding = root / "references" / "action-executors.json"
    if root.is_symlink() or binding.is_symlink() or not binding.is_file():
        return {"status": "handoff_required", "handoff": route, "message": "Installed skill has no executor binding."}
    try:
        document = json.loads(binding.read_text(encoding="utf-8"))
        if set(document) != {"version", "actions"} or document.get("version") != 1 or not isinstance(document["actions"], dict):
            raise ValueError("Unsupported executor binding document")
        entry = document.get("actions", {}).get(action)
        if entry is None:
            return {"status": "handoff_required", "handoff": route, "message": "This action requires skill judgment."}
        if not isinstance(entry, dict) or set(entry) not in ({"run"}, {"steps"}):
            raise ValueError("Executor must declare run or ordered steps")
        steps = [entry] if "run" in entry else entry["steps"]
        if not isinstance(steps, list) or not steps:
            raise ValueError("Executor steps must be nonempty")
        values = {"{python}": sys.executable, "{repo_root}": str(repo_root), "{skill_root}": str(root)}
        commands: list[list[str]] = []
        # Prepare every step before side effects. The skill owns the whole
        # deterministic action, including its preconditions and cleanup.
        for step in steps:
            if not isinstance(step, dict) or set(step) != {"run"} or not isinstance(step["run"], list) or not step["run"]:
                raise ValueError("Executor must declare nonempty argv")
            argv: list[str] = []
            for argument in step["run"]:
                if not isinstance(argument, str) or not argument or "\0" in argument:
                    raise ValueError("Executor arguments must be nonempty text")
                for token, value in values.items():
                    argument = argument.replace(token, value)
                argv.append(argument)
            commands.append(argv)
        for position, argv in enumerate(commands, 1):
            result = subprocess.run(argv, cwd=repo_root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
            if result.returncode:
                return {"status": "operation_failed", "handoff": route, "step": position, "exit_code": result.returncode, "stderr_tail": result.stderr[-4096:], "stdout_tail": result.stdout[-4096:]}
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return {"status": "operation_failed", "handoff": route, "message": str(exc)}
    return {"status": "completed", "handoff": route}
