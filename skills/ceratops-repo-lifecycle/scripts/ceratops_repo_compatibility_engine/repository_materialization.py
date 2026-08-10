#!/usr/bin/env python3
"""Make one repository Ceratops-compatible in its task worktree.

The lifecycle bundle owns the reusable template and canonical shared sections.
This module derives repository identity and skill assignments, removes only
generated marker blocks from source skills, synchronizes the bootstrap through
the package-owned helper, and emits one compact JSON result.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import pprint
import re
import shutil
import subprocess
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass

import yaml

from .compatibility_check import check_repository
from .deploy_contract_validation import DeployContractError, validation_errors

BUNDLE_ROOT = pathlib.Path(__file__).resolve().parents[2]
TEMPLATE = BUNDLE_ROOT / "references" / "templates" / "skill-sections-template.json"
DEPLOY_TEMPLATE = BUNDLE_ROOT / "references" / "templates" / "deploy-template.yml"
SOURCE_REPO_ROOT = BUNDLE_ROOT.parents[1]
SOURCE_CANONICAL_SECTIONS = SOURCE_REPO_ROOT / "skills" / "sections"
INSTALLED_CANONICAL_SECTIONS = BUNDLE_ROOT / "skills" / "sections"
VALIDATION_CATALOG = BUNDLE_ROOT / "references" / "repository-validation-catalog.json"
VALIDATOR_TEMPLATE = BUNDLE_ROOT / "references" / "templates" / "validate-repository.py.tmpl"
WORKFLOW_TEMPLATE = BUNDLE_ROOT / "references" / "templates" / "validate.yml.tmpl"
MANIFEST_RELATIVE = pathlib.Path("skills/skill-sections.json")
INSTALLER_RELATIVE = pathlib.Path("scripts/install-skills-bootstrap.py")
DEPLOY_RELATIVE = pathlib.Path("deploy/deploy.yml")
VALIDATOR_RELATIVE = pathlib.Path("scripts/validate-repository.py")
WORKFLOW_RELATIVE = pathlib.Path(".github/workflows/validate.yml")
MANAGED_SKILL_HANDOFF = "ceratops-skill-lifecycle/deploy"
START = "<!-- CERATOPS_SHARED_SECTIONS_START -->"
END = "<!-- CERATOPS_SHARED_SECTIONS_END -->"
SOURCE_RE = re.compile(r"<!-- SECTION SOURCE: skills/sections/([^ ]+) -->")
GITHUB_REMOTE_RE = re.compile(
    r"(?:github\.com[:/])(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
    re.IGNORECASE,
)
SETUP_PYTHON = "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0"
SETUP_NODE = "actions/setup-node@2028fbc5c25fe9cf00d9f06a71cc4710d4507903 # v6.0.0"
SETUP_UV = "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9 # v9.0.0"


class IndentedSafeDumper(yaml.SafeDumper):
    """Emit block sequences indented beneath their mapping keys."""

    def increase_indent(
        self, flow: bool = False, indentless: bool = False
    ) -> object:
        return super().increase_indent(flow, False)


@dataclass(frozen=True)
class FileSnapshot:
    """Exact recoverable state for one file the helper may change."""

    path: pathlib.Path
    content: bytes | None
    mode: int | None


@dataclass(frozen=True)
class MaterializationPlan:
    """Validated target writes ready for rollback-protected application."""

    manifest: dict[str, object]
    skill_updates: dict[pathlib.Path, tuple[str, str]]
    canonical_sources: dict[str, pathlib.Path]
    deploy_contract: dict[str, object] | None
    validator_text: str | None
    workflow_text: str | None
    validation_checks: list[str]
    skills: list[str]
    updated_markers: list[str]


def require_linked_worktree(repo_root: pathlib.Path) -> None:
    """Reject primary checkouts so compatibility writes stay task-isolated."""

    if not (repo_root / ".git").is_file():
        raise RuntimeError(f"target repository must be a linked task worktree: {repo_root}")


def runtime_source_id(
    repo_root: pathlib.Path,
    explicit: str | None,
    existing: Mapping[str, object],
) -> str:
    """Resolve explicit, existing, then origin-derived runtime identity."""

    if explicit and explicit.strip():
        return explicit.strip()
    existing_id = existing.get("runtime_source_id")
    if isinstance(existing_id, str) and existing_id.strip():
        return existing_id.strip()
    if existing_id not in (None, ""):
        raise RuntimeError("existing runtime_source_id must be a string")
    result = subprocess.run(
        ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    match = GITHUB_REMOTE_RE.search(result.stdout.strip()) if result.returncode == 0 else None
    if not match:
        raise RuntimeError("runtime_source_id is not derivable; pass --runtime-source-id")
    return f"{match.group('owner')}/{match.group('repo')}"


def load_mapping(path: pathlib.Path) -> dict[str, object]:
    """Load one JSON object with compact failure semantics."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root must be an object: {path}")
    return value


def _safe_catalog_path(value: object, label: str) -> pathlib.PurePosixPath:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{label} must be a nonempty relative path")
    path = pathlib.PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"{label} must stay inside the target repository")
    return path


def _package_manifest(repo_root: pathlib.Path) -> dict[str, object]:
    path = repo_root / "package.json"
    if not path.is_file() or path.is_symlink():
        return {}
    return load_mapping(path)


def _package_scripts(payload: Mapping[str, object]) -> set[str]:
    scripts = payload.get("scripts", {})
    if not isinstance(scripts, Mapping):
        raise RuntimeError("package.json scripts must be an object")
    return {str(name) for name in scripts}


def _package_manager(repo_root: pathlib.Path, payload: Mapping[str, object]) -> tuple[str | None, str | None]:
    """Resolve the declared or lockfile-owned JavaScript package manager."""

    declaration = payload.get("packageManager")
    declared_name: str | None = None
    declared_version: str | None = None
    if declaration is not None:
        if not isinstance(declaration, str) or "@" not in declaration:
            raise RuntimeError("packageManager must declare a name and version")
        declared_name, declared_version = declaration.split("@", 1)
        if declared_name not in {"npm", "pnpm"} or not declared_version:
            raise RuntimeError(f"unsupported packageManager declaration: {declaration}")
    lock_managers = [
        name
        for name, filename in (("npm", "package-lock.json"), ("pnpm", "pnpm-lock.yaml"))
        if (repo_root / filename).is_file()
    ]
    if len(lock_managers) > 1:
        raise RuntimeError("multiple JavaScript package-manager lockfiles are unsupported")
    lock_manager = lock_managers[0] if lock_managers else None
    if declared_name and lock_manager and declared_name != lock_manager:
        raise RuntimeError("packageManager conflicts with the repository lockfile")
    return declared_name or lock_manager or ("npm" if payload else None), declared_version


def _pyproject(repo_root: pathlib.Path) -> dict[str, object]:
    path = repo_root / "pyproject.toml"
    if not path.is_file() or path.is_symlink():
        return {}
    value = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("pyproject.toml root must be an object")
    return value


def _declared_python_dependencies(repo_root: pathlib.Path) -> str:
    """Return only install declarations, excluding tool configuration tables."""

    declared: list[str] = []
    for name in ("requirements-dev.txt", "requirements.txt"):
        path = repo_root / name
        if path.is_file() and not path.is_symlink():
            declared.append(path.read_text(encoding="utf-8"))
    pyproject = _pyproject(repo_root)
    project = pyproject.get("project", {})
    if isinstance(project, Mapping):
        dependencies = project.get("dependencies", [])
        if isinstance(dependencies, list):
            declared.extend(str(value) for value in dependencies)
        optional = project.get("optional-dependencies", {})
        if isinstance(optional, Mapping):
            for values in optional.values():
                if isinstance(values, list):
                    declared.extend(str(value) for value in values)
    groups = pyproject.get("dependency-groups", {})
    if isinstance(groups, Mapping):
        for values in groups.values():
            if isinstance(values, list):
                declared.extend(str(value) for value in values)
    return "\n".join(declared).lower()


def _catalog_condition_matches(
    repo_root: pathlib.Path,
    condition: Mapping[str, object],
    package_scripts: set[str],
    package_manager: str | None,
) -> bool:
    kind = condition.get("kind")
    if kind == "package-script" and set(condition) in (
        {"kind", "value"},
        {"kind", "manager", "value"},
    ):
        value = condition["value"]
        if not isinstance(value, str) or not value:
            raise RuntimeError("catalog package-script value must be text")
        manager = condition.get("manager")
        if manager is not None and manager not in {"npm", "pnpm"}:
            raise RuntimeError("catalog package-script manager is unsupported")
        return value in package_scripts and (manager is None or manager == package_manager)
    if kind == "path-any" and set(condition) == {"kind", "value"}:
        patterns = condition["value"]
        if (
            not isinstance(patterns, list)
            or not patterns
            or not all(isinstance(pattern, str) and pattern for pattern in patterns)
        ):
            raise RuntimeError("catalog path-any value must be a string list")
        return any(
            candidate.is_file() and not candidate.is_symlink()
            for pattern in patterns
            for candidate in repo_root.glob(pattern)
        )
    if kind == "file-contains" and set(condition) == {"kind", "path", "value"}:
        relative = _safe_catalog_path(condition["path"], "catalog condition path")
        value = condition["value"]
        if not isinstance(value, str) or not value:
            raise RuntimeError("catalog file-contains value must be text")
        path = repo_root.joinpath(*relative.parts)
        return (
            path.is_file()
            and not path.is_symlink()
            and value in path.read_text(encoding="utf-8")
        )
    raise RuntimeError(f"unsupported repository-validation condition: {kind!r}")


def catalog_checks(repo_root: pathlib.Path) -> list[dict[str, object]]:
    """Select fully declared checks from the closed lifecycle catalog."""

    catalog = load_mapping(VALIDATION_CATALOG)
    if set(catalog) != {"version", "checks"} or catalog.get("version") != 1:
        raise RuntimeError("repository-validation catalog must be version 1")
    entries = catalog.get("checks")
    if not isinstance(entries, list):
        raise RuntimeError("repository-validation catalog checks must be a list")
    package = _package_manifest(repo_root)
    scripts = _package_scripts(package)
    package_manager, _ = _package_manager(repo_root, package)
    selected: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in entries:
        required_fields = {"id", "when", "command", "cwd"}
        optional_fields = {"exclusive", "python_packages", "unless"}
        if (
            not isinstance(raw, Mapping)
            or not required_fields.issubset(raw)
            or not set(raw).issubset(required_fields | optional_fields)
        ):
            raise RuntimeError("repository-validation catalog entry is invalid")
        check_id = raw["id"]
        conditions = raw["when"]
        command = raw["command"]
        if (
            not isinstance(check_id, str)
            or re.fullmatch(r"[a-z0-9][a-z0-9-]*", check_id) is None
            or check_id in seen
        ):
            raise RuntimeError(f"invalid or duplicate catalog check id: {check_id!r}")
        if not isinstance(conditions, list) or not conditions or not all(
            isinstance(condition, Mapping) for condition in conditions
        ):
            raise RuntimeError(f"catalog check {check_id} has invalid conditions")
        if not isinstance(command, list) or not command or not all(
            isinstance(value, str) and value for value in command
        ):
            raise RuntimeError(f"catalog check {check_id} has invalid command")
        cwd = _safe_catalog_path(raw["cwd"], f"catalog check {check_id} cwd")
        unless = raw.get("unless", [])
        if not isinstance(unless, list) or not all(
            isinstance(condition, Mapping) for condition in unless
        ):
            raise RuntimeError(f"catalog check {check_id} unless must be a condition list")
        exclusive = raw.get("exclusive", False)
        if not isinstance(exclusive, bool):
            raise RuntimeError(f"catalog check {check_id} exclusive must be boolean")
        python_packages = raw.get("python_packages", [])
        if (
            not isinstance(python_packages, list)
            or not all(isinstance(value, str) and value for value in python_packages)
        ):
            raise RuntimeError(f"catalog check {check_id} python_packages must be text")
        seen.add(check_id)
        if any(
            _catalog_condition_matches(repo_root, condition, scripts, package_manager)
            for condition in conditions
        ) and not any(
            _catalog_condition_matches(repo_root, condition, scripts, package_manager)
            for condition in unless
        ):
            selected.append(
                {
                    "id": check_id,
                    "command": list(command),
                    "cwd": cwd.as_posix(),
                    "exclusive": exclusive,
                    "python_packages": list(python_packages),
                }
            )
    exclusive_checks = [check for check in selected if check["exclusive"]]
    if len(exclusive_checks) > 1:
        raise RuntimeError("multiple exclusive repository validators matched")
    return exclusive_checks or selected


def _validation_workflow(
    repo_root: pathlib.Path, checks: list[dict[str, object]]
) -> tuple[str, str, str]:
    """Render generated CI while delegating project Python ranges to setup-python."""

    commands: list[str] = []
    for check in checks:
        command = check["command"]
        if not isinstance(command, list):
            raise RuntimeError("catalog check command must be a list")
        for value in command:
            if not isinstance(value, str):
                raise RuntimeError("catalog check command values must be text")
            commands.append(value)
    pyproject = _pyproject(repo_root)
    project = pyproject.get("project", {})
    requires_python = (
        project.get("requires-python") if isinstance(project, Mapping) else None
    )
    if requires_python is not None and (
        not isinstance(requires_python, str) or not requires_python.strip()
    ):
        raise RuntimeError("project.requires-python must be nonempty text")
    python_selector = (
        'python-version-file: "pyproject.toml"'
        if requires_python is not None
        else 'python-version: "3.12"'
    )
    setup: list[str] = [
        "      - name: Set up Python",
        f"        uses: {SETUP_PYTHON}",
        "        with:",
        f"          {python_selector}",
    ]
    validation_python = "python"
    dependency_sources = _declared_python_dependencies(repo_root)
    python_setup: list[str] = []
    if (repo_root / "uv.lock").is_file() and "{python}" in commands:
        setup.extend(
            [
                "      - name: Set up uv",
                f"        uses: {SETUP_UV}",
            ]
        )
        optional = project.get("optional-dependencies", {}) if isinstance(project, Mapping) else {}
        groups = pyproject.get("dependency-groups", {})
        if isinstance(optional, Mapping) and "dev" in optional:
            python_setup.append("uv sync --extra dev --frozen")
        elif isinstance(groups, Mapping) and "dev" in groups:
            python_setup.append("uv sync --group dev --frozen")
        else:
            python_setup.append("uv sync --frozen")
        validation_python = "uv run --no-sync python"
    elif "{python}" in commands:
        if (repo_root / "requirements-dev.txt").is_file():
            python_setup.append("python -m pip install -r requirements-dev.txt")
        elif (repo_root / "requirements.txt").is_file():
            python_setup.append("python -m pip install -r requirements.txt")
        elif (repo_root / "pyproject.toml").is_file():
            optional = project.get("optional-dependencies", {}) if isinstance(project, Mapping) else {}
            if isinstance(optional, Mapping) and "dev" in optional:
                python_setup.append('python -m pip install -e ".[dev]"')
            elif isinstance(project, Mapping) and project:
                python_setup.append('python -m pip install -e "."')
    fallback_candidates: list[str] = []
    for check in checks:
        packages = check.get("python_packages", [])
        if isinstance(packages, list):
            fallback_candidates.extend(
                package for package in packages if isinstance(package, str)
            )
    fallback_packages = sorted(
        {
            package
            for package in fallback_candidates
            if re.split(r"[<>=!~]", package, maxsplit=1)[0].lower()
            not in dependency_sources
        }
    )
    if fallback_packages:
        installer = "uv pip install" if validation_python.startswith("uv ") else "python -m pip install"
        python_setup.append(f"{installer} {' '.join(fallback_packages)}")
    if python_setup:
        setup.extend(
            [
                "      - name: Install Python validation dependencies",
                "        run: |",
                *(f"          {command}" for command in python_setup),
            ]
        )
    package = _package_manifest(repo_root)
    manager, manager_version = _package_manager(repo_root, package)
    if "{npm}" in commands and "{pnpm}" in commands:
        raise RuntimeError("one validation workflow cannot mix npm and pnpm checks")
    if "{npm}" in commands:
        if manager != "npm":
            raise RuntimeError("npm validation checks require npm repository ownership")
        if not (repo_root / "package-lock.json").is_file():
            raise RuntimeError(
                "npm validation checks require package-lock.json for "
                "deterministic npm ci setup"
            )
        setup.extend(
            [
                "      - name: Set up Node.js",
                f"        uses: {SETUP_NODE}",
                "        with:",
                '          node-version: "20"',
                "      - name: Install npm validation dependencies",
                "        run: npm ci",
            ]
        )
    if "{pnpm}" in commands:
        if manager != "pnpm" or not manager_version:
            raise RuntimeError("pnpm validation checks require packageManager pnpm@<version>")
        if not (repo_root / "pnpm-lock.yaml").is_file():
            raise RuntimeError("pnpm validation checks require pnpm-lock.yaml")
        setup.extend(
            [
                "      - name: Set up Node.js",
                f"        uses: {SETUP_NODE}",
                "        with:",
                '          node-version: "20"',
                "      - name: Install pnpm validation dependencies",
                "        run: |",
                "          corepack enable",
                f"          corepack prepare pnpm@{manager_version} --activate",
                "          pnpm install --frozen-lockfile",
            ]
        )
    if any(check["id"] == "powershell-lint" for check in checks):
        setup.extend(
            [
                "      - name: Install PSScriptAnalyzer",
                "        shell: pwsh",
                "        run: |",
                "          Set-PSRepository PSGallery -InstallationPolicy Trusted",
                "          Install-Module PSScriptAnalyzer -Scope CurrentUser -RequiredVersion 1.25.0 -Force -ErrorAction Stop",
            ]
        )
    runner = "windows-latest" if "{pwsh}" in commands else "ubuntu-latest"
    return runner, "\n".join(setup), validation_python


def validation_surfaces(
    repo_root: pathlib.Path,
) -> tuple[str | None, str | None, list[str]]:
    """Render only missing validation files and preserve existing files exactly."""

    validator = repo_root / VALIDATOR_RELATIVE
    workflow = repo_root / WORKFLOW_RELATIVE
    for path, label in (
        (validator, "repository validator"),
        (workflow, "CI validation workflow"),
    ):
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(f"existing {label} must be a regular file: {path}")
    if validator.is_file() and workflow.is_file():
        return None, None, []

    checks = catalog_checks(repo_root)
    validator_text = None
    if not validator.is_file():
        template = VALIDATOR_TEMPLATE.read_text(encoding="utf-8")
        marker = "__CHECK_DEFINITIONS__"
        if template.count(marker) != 1:
            raise RuntimeError("repository validator template marker is invalid")
        validator_text = template.replace(
            marker,
            pprint.pformat(checks, sort_dicts=False, width=72),
        )
    workflow_text = None
    if not workflow.is_file():
        template = WORKFLOW_TEMPLATE.read_text(encoding="utf-8")
        markers = ("__RUNNER__", "      # __SETUP_STEPS__", "__VALIDATOR_PYTHON__")
        if any(template.count(marker) != 1 for marker in markers):
            raise RuntimeError("CI validation template markers are invalid")
        runner, setup, validation_python = _validation_workflow(repo_root, checks)
        workflow_text = (
            template.replace("__RUNNER__", runner)
            .replace("      # __SETUP_STEPS__", setup)
            .replace("__VALIDATOR_PYTHON__", validation_python)
        )
    return validator_text, workflow_text, [str(check["id"]) for check in checks]


def load_yaml_mapping(path: pathlib.Path) -> dict[str, object]:
    """Load one YAML mapping without constructing custom objects."""

    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise RuntimeError(f"YAML root must be a string-keyed object: {path}")
    return value


def validate_template(template: Mapping[str, object]) -> None:
    """Require the closed repository-neutral compatibility skeleton."""

    expected = {
        "runtime_source_id": "",
        "validation_profile": "ceratops-compatible",
        "sections": {"core": "skills/sections/core.md"},
        "maintenance_workflows": {},
        "runtime_payloads": {},
        "skills": {},
    }
    if template != expected:
        raise RuntimeError("skill-sections template is not repository-neutral")


def build_deploy_contract_candidate(
    repo_root: pathlib.Path,
    *,
    has_skills: bool,
    materialize: bool,
) -> dict[str, object] | None:
    """Preserve operations and own default skill bootstrap and handoff entries."""

    if not materialize:
        return None
    reusable = load_yaml_mapping(DEPLOY_TEMPLATE)
    expected = {
        "version": 1,
        "kind": "ceratops-deploy",
        "operations": {},
    }
    if reusable != expected:
        raise RuntimeError("deploy template is not the empty version 1 skeleton")
    target = repo_root / DEPLOY_RELATIVE
    contract = load_yaml_mapping(target) if target.is_file() else dict(reusable)
    if contract.get("version") != 1:
        raise RuntimeError("existing deploy contract version must remain 1")
    if contract.get("kind") != "ceratops-deploy":
        raise RuntimeError("existing deploy contract kind must be ceratops-deploy")
    operations = contract.get("operations")
    if not isinstance(operations, Mapping) or not all(
        isinstance(name, str) and isinstance(operation, Mapping)
        for name, operation in operations.items()
    ):
        raise RuntimeError("existing deploy contract operations must be objects")
    updated_operations = dict(operations)
    if has_skills:
        existing_deploy = updated_operations.get("deploy")
        updated_deploy = (
            dict(existing_deploy)
            if isinstance(existing_deploy, Mapping)
            else {}
        )
        updated_deploy.setdefault("handoff", MANAGED_SKILL_HANDOFF)
        updated_operations["deploy"] = updated_deploy
        updated_operations["bootstrap"] = {
            "steps": [
                {
                    "id": "bootstrap-skills",
                    "run": ["python", "scripts/install-skills-bootstrap.py"],
                }
            ]
        }
    else:
        updated_operations.pop("bootstrap", None)
        existing_deploy = updated_operations.get("deploy")
        if (
            isinstance(existing_deploy, Mapping)
            and existing_deploy.get("handoff") == MANAGED_SKILL_HANDOFF
        ):
            updated_deploy = dict(existing_deploy)
            updated_deploy.pop("handoff")
            if updated_deploy:
                updated_operations["deploy"] = updated_deploy
            else:
                updated_operations.pop("deploy")
    candidate = {
        "version": 1,
        "kind": "ceratops-deploy",
        "operations": updated_operations,
    }
    try:
        errors = validation_errors(candidate)
    except DeployContractError as exc:
        raise RuntimeError(str(exc)) from exc
    if errors:
        raise RuntimeError(f"invalid deploy contract: {errors[0]}")
    return candidate


def portable_section_path(repo_root: pathlib.Path, value: object) -> pathlib.Path:
    """Resolve one existing portable section source inside the target repo."""

    if not isinstance(value, str) or not value:
        raise RuntimeError(f"section path must be a nonempty string: {value!r}")
    normalized = value.replace("\\", "/")
    pure = pathlib.PurePosixPath(normalized)
    windows = pathlib.PureWindowsPath(value)
    if pure.is_absolute() or windows.is_absolute() or windows.drive or ".." in pure.parts:
        raise RuntimeError(f"section path must be repository-relative: {value}")
    path = repo_root.joinpath(*pure.parts)
    try:
        path.resolve().relative_to(repo_root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"section path escapes repository: {value}") from exc
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"section source is missing or unsafe: {value}")
    return path


def existing_custom_sections(
    repo_root: pathlib.Path,
    existing: Mapping[str, object],
) -> dict[str, str]:
    """Validate and return target-owned noncanonical section declarations."""

    raw = existing.get("sections", {})
    if not isinstance(raw, Mapping):
        raise RuntimeError("existing sections must be an object")
    sections: dict[str, str] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not name:
            raise RuntimeError("existing section names must be nonempty strings")
        if name in {"core", "multi-action-skill"}:
            continue
        path = portable_section_path(repo_root, value)
        sections[name] = path.relative_to(repo_root).as_posix()
    return sections


def existing_skill_assignments(
    existing: Mapping[str, object],
    skill_names: set[str],
    custom_sections: Mapping[str, str],
) -> dict[str, list[str]]:
    """Validate assignments for current skills without retaining stale skills."""

    raw = existing.get("skills", {})
    if not isinstance(raw, Mapping):
        raise RuntimeError("existing skills assignments must be an object")
    assignments: dict[str, list[str]] = {}
    for skill_name in sorted(skill_names):
        value = raw.get(skill_name, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise RuntimeError(f"{skill_name}: existing assignment must be a list of strings")
        unknown = sorted(
            item
            for item in value
            if item not in {"core", "multi-action-skill"} and item not in custom_sections
        )
        if unknown:
            raise RuntimeError(
                f"{skill_name}: unknown existing section assignments: {', '.join(unknown)}"
            )
        assignments[skill_name] = list(dict.fromkeys(value))
    return assignments


def canonical_sections_root() -> pathlib.Path:
    """Resolve canonical sections from source checkout or installed payload."""

    for candidate in (SOURCE_CANONICAL_SECTIONS, INSTALLED_CANONICAL_SECTIONS):
        if (candidate / "core.md").is_file():
            return candidate
    raise RuntimeError("canonical shared sections are missing from lifecycle bundle")


def rendered_delta(path: pathlib.Path) -> tuple[str | None, set[str], str]:
    """Return marker-free text, declared section files, and original newline."""

    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8").replace("\r\n", "\n")
    start_count = text.count(START)
    end_count = text.count(END)
    if start_count == end_count == 0:
        return None, set(), newline
    if start_count != 1 or end_count != 1 or text.index(START) > text.index(END):
        raise RuntimeError(f"{path}: malformed shared-section markers")
    start = text.index(START)
    end = text.index(END) + len(END)
    declared = set(SOURCE_RE.findall(text[start:end]))
    updated = (text[:start].rstrip() + "\n\n" + text[end:].lstrip()).rstrip() + "\n"
    return updated, declared, newline


def snapshot_file(path: pathlib.Path) -> FileSnapshot:
    """Capture bytes and mode before the first target mutation."""

    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise RuntimeError(f"mutable target path is not a regular file: {path}")
    if not path.exists():
        return FileSnapshot(path, None, None)
    stat = path.stat()
    return FileSnapshot(path, path.read_bytes(), stat.st_mode)


def restore_snapshots(
    snapshots: list[FileSnapshot],
    created_dirs: list[pathlib.Path],
) -> None:
    """Restore exact file bytes and modes, then remove helper-created empty dirs."""

    errors: list[str] = []
    for snapshot in reversed(snapshots):
        try:
            if snapshot.content is None:
                if snapshot.path.exists() or snapshot.path.is_symlink():
                    if snapshot.path.is_symlink() or not snapshot.path.is_file():
                        raise RuntimeError("replacement is not a regular file")
                    snapshot.path.unlink()
                continue
            if snapshot.path.is_symlink() or (
                snapshot.path.exists() and not snapshot.path.is_file()
            ):
                raise RuntimeError("replacement is not a regular file")
            snapshot.path.parent.mkdir(parents=True, exist_ok=True)
            snapshot.path.write_bytes(snapshot.content)
            if snapshot.mode is not None:
                os.chmod(snapshot.path, snapshot.mode)
        except (OSError, RuntimeError) as exc:
            errors.append(f"{snapshot.path}: {exc}")
    for directory in reversed(created_dirs):
        try:
            if directory.is_dir():
                directory.rmdir()
        except OSError as exc:
            errors.append(f"{directory}: {exc}")
    if errors:
        raise RuntimeError("; ".join(errors))


def plan_materialization(
    repo_root: pathlib.Path,
    source_id: str,
    template: Mapping[str, object],
    existing: Mapping[str, object],
    *,
    materialize_deploy: bool,
) -> MaterializationPlan:
    """Validate target evidence and compose writes without changing files."""

    skill_paths = sorted((repo_root / "skills").glob("*/SKILL.md"))
    skill_names = {path.parent.name for path in skill_paths}
    custom_sections = existing_custom_sections(repo_root, existing)
    prior_assignments = existing_skill_assignments(
        existing,
        skill_names,
        custom_sections,
    )
    maintenance_workflows = existing.get("maintenance_workflows", {})
    runtime_payloads = existing.get("runtime_payloads", {})
    if not isinstance(maintenance_workflows, Mapping):
        raise RuntimeError("existing maintenance_workflows must be an object")
    if not isinstance(runtime_payloads, Mapping):
        raise RuntimeError("existing runtime_payloads must be an object")

    assignments: dict[str, list[str]] = {}
    required_sections: set[str] = {"core"} if skill_paths else set()
    updated_markers: list[str] = []
    skill_updates: dict[pathlib.Path, tuple[str, str]] = {}
    for skill_path in skill_paths:
        updated, declared, newline = rendered_delta(skill_path)
        if declared:
            updated_markers.append(skill_path.parent.name)
        text = (
            updated
            if updated is not None
            else skill_path.read_text(encoding="utf-8")
        )
        if updated is not None:
            skill_updates[skill_path] = (updated, newline)
        selected = ["core"]
        if "multi-action-skill.md" in declared or "### Action References" in text:
            selected.append("multi-action-skill")
            required_sections.add("multi-action-skill")
        for section_name in prior_assignments[skill_path.parent.name]:
            if section_name not in {"core", "multi-action-skill"}:
                selected.append(section_name)
        for filename in sorted(declared):
            if filename in {"core.md", "multi-action-skill.md"}:
                continue
            rel_path = f"skills/sections/{filename}"
            marker_section_name: str | None = next(
                (
                    name
                    for name, path in custom_sections.items()
                    if path == rel_path
                ),
                None,
            )
            if marker_section_name is None:
                source_path = portable_section_path(repo_root, rel_path)
                candidate_name = pathlib.PurePosixPath(filename).stem
                if not candidate_name or candidate_name in {
                    "core",
                    "multi-action-skill",
                }:
                    raise RuntimeError(
                        f"cannot derive section name from marker source: {rel_path}"
                    )
                collision = custom_sections.get(candidate_name)
                if collision is not None and collision != rel_path:
                    raise RuntimeError(
                        f"section name {candidate_name} maps to multiple sources"
                    )
                custom_sections[candidate_name] = source_path.relative_to(
                    repo_root
                ).as_posix()
                marker_section_name = candidate_name
            selected.append(marker_section_name)
        assignments[skill_path.parent.name] = list(dict.fromkeys(selected))

    sections: dict[str, str] = {}
    if "core" in required_sections:
        sections["core"] = "skills/sections/core.md"
    if "multi-action-skill" in required_sections:
        sections["multi-action-skill"] = (
            "skills/sections/multi-action-skill.md"
        )
    sections.update(
        {name: custom_sections[name] for name in sorted(custom_sections)}
    )
    profile = existing.get("validation_profile", template["validation_profile"])
    if profile not in {"ceratops", "ceratops-compatible"}:
        raise RuntimeError(f"unsupported validation_profile: {profile!r}")
    canonical_sources: dict[str, pathlib.Path] = {}
    if required_sections:
        canonical_sections = canonical_sections_root()
        canonical_sources = {
            section_name: canonical_sections / f"{section_name}.md"
            for section_name in required_sections
        }
    for source in canonical_sources.values():
        if not source.is_file():
            raise RuntimeError(f"canonical shared section is missing: {source}")

    manifest = dict(template)
    manifest.update(
        {
            "runtime_source_id": source_id,
            "validation_profile": profile,
            "sections": sections,
            "maintenance_workflows": dict(maintenance_workflows),
            "runtime_payloads": dict(runtime_payloads),
            "skills": assignments,
        }
    )
    validator_text, workflow_text, validation_checks = validation_surfaces(repo_root)
    return MaterializationPlan(
        manifest=manifest,
        skill_updates=skill_updates,
        canonical_sources=canonical_sources,
        deploy_contract=build_deploy_contract_candidate(
            repo_root,
            has_skills=bool(skill_names),
            materialize=materialize_deploy,
        ),
        validator_text=validator_text,
        workflow_text=workflow_text,
        validation_checks=validation_checks,
        skills=sorted(assignments),
        updated_markers=sorted(updated_markers),
    )


def apply_materialization(
    repo_root: pathlib.Path,
    plan: MaterializationPlan,
) -> None:
    """Apply one fully validated plan inside the caller's rollback boundary."""

    if plan.canonical_sources:
        sections_dir = repo_root / "skills" / "sections"
        sections_dir.mkdir(parents=True, exist_ok=True)
        for section_name, source in sorted(plan.canonical_sources.items()):
            destination = sections_dir / f"{section_name}.md"
            if source.resolve() != destination.resolve():
                shutil.copy2(source, destination)
    for skill_path, (updated, newline) in plan.skill_updates.items():
        skill_path.write_text(
            updated,
            encoding="utf-8",
            newline=newline,
        )
    existing_path = repo_root / MANIFEST_RELATIVE
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text(
        json.dumps(plan.manifest, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if plan.deploy_contract is not None:
        deploy_path = repo_root / DEPLOY_RELATIVE
        deploy_path.parent.mkdir(parents=True, exist_ok=True)
        deploy_path.write_text(
            yaml.dump(
                plan.deploy_contract,
                Dumper=IndentedSafeDumper,
                sort_keys=False,
            ),
            encoding="utf-8",
            newline="\n",
        )
    if plan.validator_text is not None:
        validator_path = repo_root / VALIDATOR_RELATIVE
        validator_path.parent.mkdir(parents=True, exist_ok=True)
        validator_path.write_text(
            plan.validator_text,
            encoding="utf-8",
            newline="\n",
        )
    if plan.workflow_text is not None:
        workflow_path = repo_root / WORKFLOW_RELATIVE
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_path.write_text(
            plan.workflow_text,
            encoding="utf-8",
            newline="\n",
        )


def main(argv: list[str] | None = None) -> int:
    """Run repository materialization as the package CLI subcommand."""

    parser = argparse.ArgumentParser(
        description="Make repository sources Ceratops-compatible."
    )
    parser.add_argument("--target-repo-root", required=True, type=pathlib.Path)
    parser.add_argument("--runtime-source-id")
    parser.add_argument(
        "--no-deploy-contract",
        action="store_true",
        help="Leave deploy/deploy.yml absent or unchanged.",
    )
    args = parser.parse_args(argv)
    repo_root = args.target_repo_root.resolve()
    phase = "preflight"
    rollback = "not_started"
    snapshots: list[FileSnapshot] = []
    created_dirs: list[pathlib.Path] = []
    mutation_started = False
    try:
        require_linked_worktree(repo_root)
        template = load_mapping(TEMPLATE)
        validate_template(template)
        existing_path = repo_root / MANIFEST_RELATIVE
        existing = load_mapping(existing_path) if existing_path.is_file() else {}
        source_id = runtime_source_id(
            repo_root,
            args.runtime_source_id,
            existing,
        )
        phase = "materialization_planning"
        plan = plan_materialization(
            repo_root,
            source_id,
            template,
            existing,
            materialize_deploy=not args.no_deploy_contract,
        )
        skill_paths = sorted((repo_root / "skills").glob("*/SKILL.md"))
        mutable_paths = [*skill_paths, existing_path]
        mutable_paths.extend(
            repo_root / "skills" / "sections" / f"{section_name}.md"
            for section_name in plan.canonical_sources
        )
        if plan.skills:
            mutable_paths.append(repo_root / INSTALLER_RELATIVE)
        if plan.deploy_contract is not None:
            mutable_paths.append(repo_root / DEPLOY_RELATIVE)
        if plan.validator_text is not None:
            mutable_paths.append(repo_root / VALIDATOR_RELATIVE)
        if plan.workflow_text is not None:
            mutable_paths.append(repo_root / WORKFLOW_RELATIVE)
        snapshots = [snapshot_file(path) for path in dict.fromkeys(mutable_paths)]
        created_dirs = [
            path
            for path in (
                repo_root / "skills",
                repo_root / "skills" / "sections",
                repo_root / "scripts",
                repo_root / "deploy",
                repo_root / ".github",
                repo_root / ".github" / "workflows",
            )
            if not path.exists()
            and (
                path.name != "sections" or bool(plan.canonical_sources)
            )
            and (
                path.name not in {"scripts"}
                or bool(plan.skills)
                or plan.validator_text is not None
            )
            and (
                path.name not in {"deploy"}
                or plan.deploy_contract is not None
            )
            and (
                path.name not in {".github", "workflows"}
                or plan.workflow_text is not None
            )
        ]
        phase = "materialization"
        mutation_started = True
        apply_materialization(repo_root, plan)
        bootstrap_status = "skipped"
        if plan.skills:
            phase = "bootstrap_synchronization"
            from .bootstrap_installer_synchronization import (
                synchronize_bootstrap_installer,
            )

            bootstrap = synchronize_bootstrap_installer(repo_root)
            bootstrap_status_value = (
                bootstrap.get("status") if isinstance(bootstrap, Mapping) else None
            )
            if not isinstance(bootstrap_status_value, str):
                raise RuntimeError("bootstrap synchronizer returned an invalid result")
            bootstrap_status = bootstrap_status_value

        phase = "compatibility_validation"
        compatibility = check_repository(repo_root)
        if (
            not compatibility["applicable"]
            or compatibility["valid"] is not True
            or compatibility["errors"]
        ):
            detail = "; ".join(compatibility["errors"]) or "not applicable"
            raise RuntimeError(f"repository compatibility failed: {detail}")
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        reason = str(exc)
        if mutation_started:
            try:
                restore_snapshots(snapshots, created_dirs)
                rollback = "completed"
            except RuntimeError as rollback_exc:
                rollback = "failed"
                reason = f"{reason}; rollback failed: {rollback_exc}"
        print(
            json.dumps(
                {
                    "phase": phase,
                    "reason": reason,
                    "rollback": rollback,
                    "status": "blocked",
                },
                sort_keys=True,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "bootstrap": bootstrap_status,
                "deploy_contract": (
                    "materialized"
                    if plan.deploy_contract is not None
                    else "unchanged"
                ),
                "repository_validation": {
                    "checks": plan.validation_checks,
                    "validator": (
                        "materialized"
                        if plan.validator_text is not None
                        else "preserved"
                    ),
                    "workflow": (
                        "materialized"
                        if plan.workflow_text is not None
                        else "preserved"
                    ),
                },
                "markers_removed": plan.updated_markers,
                "rollback": "not_needed",
                "runtime_source_id": source_id,
                "skills": plan.skills,
                "status": "ok",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
