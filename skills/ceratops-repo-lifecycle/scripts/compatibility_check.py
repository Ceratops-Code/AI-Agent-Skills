"""Read-only generic repository compatibility postconditions.

The checker never runs the repository aggregate and never mutates the target.
Callers receive only the stable ``applicable``, ``valid``, and ``errors``
mapping; repository health owns aggregate execution separately.
"""

from __future__ import annotations

import json
import pathlib
import re
from collections.abc import Mapping
from typing import TypedDict

import yaml
from deploy_contract import read_contract


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


def _workflow_errors(path: pathlib.Path) -> list[str]:
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
        r"\bpython3?\s+(?:\./)?scripts/validate-repository\.py\b"
    )
    if not any(
        invocation.search(command) and "--evidence-file" in command
        for command in commands
    ):
        return [
            "CI validation workflow must call scripts/validate-repository.py "
            "with --evidence-file"
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


def _manifest_errors(
    root: pathlib.Path,
    path: pathlib.Path,
    source_skills: set[str],
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
    if manifest.get("validation_profile") not in {
        "ceratops",
        "ceratops-compatible",
    }:
        errors.append(
            "section manifest validation_profile must be ceratops or "
            "ceratops-compatible"
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
            errors.extend(_string_list_errors(items, f"{field}.{name}"))

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
    for skill_name in sorted(source_skills - set(assignments)):
        errors.append(f"{skill_name}: missing section assignment in manifest")
    return errors


def check_repository(repo_root: pathlib.Path) -> CompatibilityResult:
    """Return read-only compatibility status for one repository root."""

    root = repo_root.resolve()
    manifest = root / "skills" / "skill-sections.json"
    deploy = root / "deploy" / "deploy.yml"
    validator = pathlib.Path("scripts/validate-repository.py")
    workflow = pathlib.Path(".github/workflows/validate.yml")
    source_skills = {
        path.parent.name
        for path in (root / "skills").glob("*/SKILL.md")
        if path.is_file()
    } if (root / "skills").is_dir() else set()
    applicable = any(
        (
            manifest.exists() or manifest.is_symlink(),
            deploy.exists() or deploy.is_symlink(),
            (root / validator).exists() or (root / validator).is_symlink(),
            (root / workflow).exists() or (root / workflow).is_symlink(),
            bool(source_skills),
        )
    )
    if not applicable:
        return {"applicable": False, "valid": None, "errors": []}

    errors: list[str] = []
    for relative in (validator, workflow):
        if error := _regular_file_error(root, relative):
            errors.append(error)
    if not _regular_file_error(root, workflow):
        errors.extend(_workflow_errors(root / workflow))

    if manifest.exists() or manifest.is_symlink():
        errors.extend(_manifest_errors(root, manifest, source_skills))
    elif source_skills:
        errors.append("missing skills/skill-sections.json")

    if deploy.exists() or deploy.is_symlink():
        if deploy.is_symlink() or not deploy.is_file():
            errors.append("deploy/deploy.yml must be a regular file")
        else:
            _, deploy_errors = read_contract(deploy)
            errors.extend(deploy_errors)

    unique_errors = list(dict.fromkeys(error for error in errors if error))
    return {
        "applicable": True,
        "valid": not unique_errors,
        "errors": unique_errors,
    }
