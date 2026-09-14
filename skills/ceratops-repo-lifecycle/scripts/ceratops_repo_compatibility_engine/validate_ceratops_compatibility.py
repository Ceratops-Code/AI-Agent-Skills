"""Read-only generic repository compatibility postconditions.

The checker never runs the repository aggregate and never mutates the target.
Callers receive only the stable ``applicable``, ``valid``, and ``errors``
mapping; repository health owns aggregate execution separately.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import runpy
import tomllib
from collections.abc import Mapping
from typing import Any, TypedDict

import yaml

from .compatibility_contract import load_compatibility_contract, template_path
from .python_tests import discover_python_tests
from .sdlc_contract_validation import operation_entries, read_contract


class CompatibilityResult(TypedDict):
    applicable: bool
    valid: bool | None
    errors: list[str]


def _regular_file_error(root: pathlib.Path, relative: pathlib.Path) -> str | None:
    path = root / relative
    if not (path.exists() or path.is_symlink()):
        return f"missing {relative.as_posix()}"
    if path.is_symlink() or not path.is_file():
        return f"{relative.as_posix()} must be a regular file"
    return None


def _workflow_errors(
    path: pathlib.Path, validator: str, required_arguments: list[str],
) -> list[str]:
    """Validate the CI-to-repository-validator edge from parsed YAML."""

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return [f"invalid CI validation workflow: {exc}"]
    if not isinstance(payload, Mapping) or not isinstance(payload.get("jobs"), Mapping):
        return ["CI validation workflow must declare jobs"]
    commands: list[str] = []
    for job in payload["jobs"].values():
        if not isinstance(job, Mapping) or not isinstance(job.get("steps"), list):
            continue
        for step in job["steps"]:
            if isinstance(step, Mapping) and isinstance(step.get("run"), str):
                commands.append(step["run"])
    invocation = re.compile(
        rf"\b(?:python3?|uv\s+run\s+--locked)\s+(?:\./)?{re.escape(validator)}\b"
    )
    if not any(
        invocation.search(command)
        and all(argument in command for argument in required_arguments)
        for command in commands
    ):
        return [
            f"CI validation workflow must call {validator} "
            f"with {' '.join(required_arguments)}"
        ]
    return []


def _manifest_file_errors(
    root: pathlib.Path,
    value: object,
    label: str,
) -> list[str]:
    """Require one portable repository-relative regular-file reference."""

    if not isinstance(value, str) or not value:
        return [f"{label} must be a nonempty path string"]
    normalized = value.replace("\\", "/")
    relative = pathlib.PurePosixPath(normalized)
    windows = pathlib.PureWindowsPath(value)
    if (
        relative.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or ".." in relative.parts
    ):
        return [f"{label} must be repository-relative"]
    target = root.joinpath(*relative.parts)
    if target.is_symlink() or not target.is_file():
        return [f"{label} must reference a regular file: {value}"]
    return []


def _string_list_errors(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        return [f"{label} must be a list of nonempty strings"]
    return []


def _runtime_payload_list_errors(value: object, label: str) -> list[str]:
    """Accept portable payload paths and exact source-target mappings."""

    if not isinstance(value, list):
        return [f"{label} must be a list of payload declarations"]
    errors: list[str] = []
    for index, item in enumerate(value):
        if isinstance(item, str) and item:
            continue
        if (
            isinstance(item, Mapping)
            and set(item) == {"source", "target"}
            and all(isinstance(item[key], str) and item[key] for key in item)
        ):
            continue
        errors.append(
            f"{label}[{index}] must be a nonempty path or source-target mapping"
        )
    return errors


def action_assignment_errors(
    root: pathlib.Path, manifest: Mapping[str, object],
) -> list[str]:
    """Use this bundle's standalone parser without importing another skill.

    The template is trusted bundle code, never executable input from the target
    repository. Parsing has no installation or target mutation side effects.
    """

    template = template_path("skill_bootstrap")
    bootstrap = runpy.run_path(str(template))
    try:
        bootstrap["action_assignments"](root, manifest)
    except (OSError, ValueError) as exc:
        return [str(exc)]
    return []


def _manifest_errors(
    root: pathlib.Path,
    path: pathlib.Path,
    source_skills: set[str],
    profiles: list[str],
) -> list[str]:
    """Validate only generic compatibility-manifest structure and wiring."""

    if path.is_symlink() or not path.is_file():
        return ["skills/skill-sections.json must be a regular file"]
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"invalid skills/skill-sections.json: {exc}"]
    if not isinstance(manifest, Mapping):
        return ["skills/skill-sections.json root must be an object"]

    errors: list[str] = []
    source_id = manifest.get("runtime_source_id")
    if not isinstance(source_id, str) or not source_id.strip():
        errors.append("section manifest runtime_source_id must be a nonempty string")
    if manifest.get("validation_profile") not in profiles:
        errors.append(
            "section manifest validation_profile must be " + " or ".join(profiles)
        )

    sections = manifest.get("sections")
    assignments = manifest.get("skills")
    if not isinstance(sections, Mapping):
        errors.append("section manifest sections must be an object")
        sections = {}
    if not isinstance(assignments, Mapping):
        errors.append("section manifest skills must be an object")
        assignments = {}
    for field in ("maintenance_workflows", "runtime_payloads"):
        value = manifest.get(field, {})
        if not isinstance(value, Mapping):
            errors.append(f"section manifest {field} must be an object")
            continue
        for name, items in value.items():
            validator = (
                _runtime_payload_list_errors
                if field == "runtime_payloads"
                else _string_list_errors
            )
            errors.extend(validator(items, f"{field}.{name}"))

    if source_skills and "core" not in sections:
        errors.append("section manifest must define core when source skills exist")
    for section_name, relative in sections.items():
        errors.extend(
            _manifest_file_errors(
                root,
                relative,
                f"section manifest section {section_name}",
            )
        )
    for skill_name, selected in assignments.items():
        if skill_name not in source_skills:
            errors.append(
                f"{skill_name}: section assignment points to a missing skill directory"
            )
        selection_errors = _string_list_errors(
            selected,
            f"{skill_name}: section assignment",
        )
        errors.extend(selection_errors)
        if selection_errors:
            continue
        assert isinstance(selected, list)
        if "core" not in selected:
            errors.append(f"{skill_name}: section assignment must include core")
        for section_name in selected:
            if section_name not in sections:
                errors.append(f"{skill_name}: unknown section assignment {section_name}")
    errors.extend(action_assignment_errors(root, manifest))
    for skill_name in sorted(source_skills - set(assignments)):
        errors.append(f"{skill_name}: missing section assignment in manifest")
    return errors



def _environment_errors(root: pathlib.Path, contract: Mapping[str, Any]) -> list[str]:
    """Check declarations and the installed runtime without installing or running it.

    uv sync/run enforces Python and dependency resolution. Structural health
    checks only assert the declared locked project and local interpreter exist.
    """

    errors: list[str] = []
    runtime = contract["runtime"]
    project = root / runtime["project"]
    try:
        declaration = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
        metadata = declaration.get("project", {})
        if not isinstance(metadata.get("requires-python"), str) or not metadata["requires-python"].strip():
            errors.append("validator project must declare requires-python")
        if not isinstance(metadata.get("dependencies"), list):
            errors.append("validator project must declare dependencies")
        lock = tomllib.loads((root / runtime["lockfile"]).read_text(encoding="utf-8"))
        if not isinstance(lock.get("version"), int) or not lock.get("package"):
            errors.append("validator uv.lock must contain resolved packages")
    except (OSError, ValueError, TypeError) as exc:
        errors.append("invalid validator project or lock: " + str(exc))
    environment = root / runtime["environment"]
    interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if environment.is_symlink() or not (environment / "pyvenv.cfg").is_file() or not interpreter.is_file():
        errors.append("validator environment must contain its own Python interpreter; apply compatibility or run uv sync")
    try:
        dependabot = yaml.safe_load((root / ".github/dependabot.yml").read_text(encoding="utf-8"))
        registration = contract["dependency_updates"]
        if not isinstance(dependabot, Mapping) or not any(
            isinstance(item, Mapping) and item.get("package-ecosystem") == registration["package-ecosystem"]
            and (item.get("directory") == registration["directory"] or registration["directory"] in item.get("directories", []))
            for item in dependabot.get("updates", [])
        ):
            errors.append("Dependabot must include the isolated validator project")
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        errors.append("invalid validator dependency-update registration: " + str(exc))
    return errors


def validate_ceratops_compatibility(repo_root: pathlib.Path) -> CompatibilityResult:
    """Return read-only compatibility status for one repository root."""

    root = repo_root.resolve()
    try:
        contract = load_compatibility_contract()
    except RuntimeError as exc:
        return {"applicable": True, "valid": False, "errors": [str(exc)]}
    surfaces = contract["surfaces"]
    paths = {name: pathlib.Path(surface["path"]) for name, surface in surfaces.items()}
    source_skills = {
        path.parent.name
        for path in (root / "skills").glob("*/SKILL.md")
        if path.is_file()
    } if (root / "skills").is_dir() else set()
    present = {
        name for name, path in paths.items()
        if (root / path).exists() or (root / path).is_symlink()
    }
    if not present and not source_skills:
        return {"applicable": False, "valid": None, "errors": []}

    errors: list[str] = []
    python_tests = discover_python_tests(root, contract["python_test_detection"])
    for name, surface in surfaces.items():
        required = surface["required"] == "always" or (
            surface["required"] == "with_skills" and bool(source_skills)
        ) or (surface["required"] == "with_python_tests" and bool(python_tests))
        if required or name in present:
            if error := _regular_file_error(root, paths[name]):
                errors.append(error)
    if not _regular_file_error(root, paths["workflow"]):
        errors.extend(_workflow_errors(
            root / paths["workflow"], surfaces["sdlc_runner"]["path"],
            contract["ci_required_arguments"],
        ))
    if "skill_manifest" in present and not _regular_file_error(root, paths["skill_manifest"]):
        errors.extend(_manifest_errors(
            root, root / paths["skill_manifest"], source_skills, contract["manifest_profiles"],
        ))
    if "sdlc" in present and not _regular_file_error(root, paths["sdlc"]):
        sdlc, sdlc_errors = read_contract(root / paths["sdlc"])
        errors.extend(sdlc_errors)
        if sdlc and sdlc["version"] != contract["sdlc_version"]:
            errors.append("current Ceratops compatibility requires SDLC version " + str(contract["sdlc_version"]))
        elif sdlc:
            entries = operation_entries(sdlc)
            expected = load_compatibility_contract()["runtime"]["project"]
            # uv supports project discovery from the script path and explicit
            # project selection for existing repository commands.
            validator_commands = [
                ["uv", "run", "--locked", surfaces["validator"]["path"]],
                ["uv", "run", "--project", expected, "--locked", "python", surfaces["validator"]["path"]],
            ]
            commands = [step["run"] for name, entry in entries.items() if ".validate." in name for step in entry.get("steps", [])]
            if not any(command in commands for command in validator_commands):
                errors.append("SDLC must invoke the repository validator through its locked uv project")
            if not sdlc.get("repository", {}).get("tests"):
                errors.append("SDLC must declare repository tests or an explicit no-op")
            if python_tests and not any(".tests." in name and (entry.get("steps") or entry.get("handoff")) for name, entry in entries.items()):
                errors.append("detected Python tests require an executable SDLC tests operation")
    errors.extend(_environment_errors(root, contract))
    for relative in [contract["runtime"]["lockfile"], *[contract["runtime"]["payload_root"] + "/" + path for path in contract["runtime"]["payloads"]]]:
        if error := _regular_file_error(root, pathlib.Path(relative)):
            errors.append(error)

    unique_errors = list(dict.fromkeys(error for error in errors if error))
    return {
        "applicable": True,
        "valid": not unique_errors,
        "errors": unique_errors,
    }
