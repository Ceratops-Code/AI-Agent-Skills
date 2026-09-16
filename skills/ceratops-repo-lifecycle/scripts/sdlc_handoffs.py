"""Execute explicitly registered skill actions for skill callers, never CI.

SDLC contains only skill/action identities. An installed executor binding may
authorize the identical binding in the repository's owning source bundle so
source maintenance validates and deploys the candidate helper. Missing or
divergent bindings return a pending route; neither a route nor successful
command preparation constitutes evidence that an action completed.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

from sdlc_results import capture_step_result


def execute_handoff(route: str, repo_root: pathlib.Path) -> dict[str, object]:
    """Resolve an installed-authorized source binding and execute shell-free argv."""

    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*", route):
        return {"status": "handoff_required", "handoff": route, "message": "No deterministic skill/action binding."}
    skill, action = route.split("/")
    skills = pathlib.Path(os.environ.get("CODEX_HOME", str(pathlib.Path.home() / ".codex"))) / "skills"
    installed_root = skills / skill
    installed_binding = installed_root / "references" / "action-executors.json"
    if (
        installed_root.is_symlink()
        or installed_binding.is_symlink()
        or not installed_binding.is_file()
    ):
        return {"status": "handoff_required", "handoff": route, "message": "Installed skill has no executor binding."}
    root = installed_root
    binding = installed_binding
    uses_source_bundle = False
    source_root = repo_root / "skills" / skill
    source_binding = source_root / "references" / "action-executors.json"
    if source_binding.exists():
        if source_root.is_symlink() or source_binding.is_symlink() or not source_binding.is_file():
            return {"status": "handoff_required", "handoff": route, "message": "Source skill executor binding is unsafe."}
        if source_binding.read_bytes() != installed_binding.read_bytes():
            return {"status": "handoff_required", "handoff": route, "message": "Source skill executor binding differs from the installed authorization."}
        root = source_root
        binding = source_binding
        uses_source_bundle = True
    completed: list[int] = []
    receipts: list[dict[str, object]] = []
    evidence: dict[str, object] = {"handoff": route, "steps": completed}
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
            if step["run"][0] == "{python}" and not uses_source_bundle:
                launcher = installed_root / "scripts/run-skill.py"
                uv = shutil.which("uv")
                if launcher.is_symlink() or not launcher.is_file() or uv is None:
                    return {**evidence, "status": "handoff_required", "message": "Python action requires uv and the installed run-skill.py launcher."}
                # The bootstrap has no package dependencies. The launcher selects
                # this skill's locked environment before the real helper starts.
                argv = [uv, "run", "--no-project", "--python", "3.14", "python", str(launcher), *argv[1:]]
            commands.append(argv)
        for position, argv in enumerate(commands, 1):
            result = subprocess.run(argv, cwd=repo_root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
            if result.returncode:
                return {**evidence, "status": "operation_failed", "step": position, "exit_code": result.returncode, "stderr_tail": result.stderr[-4096:], "stdout_tail": result.stdout[-4096:]}
            completed.append(position)
            captured = capture_step_result(result.stdout)
            if captured:
                receipts.append({"step": position, **captured})
                evidence["step_results"] = receipts
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return {**evidence, "status": "operation_failed", "message": str(exc)}
    return {**evidence, "status": "completed"}
