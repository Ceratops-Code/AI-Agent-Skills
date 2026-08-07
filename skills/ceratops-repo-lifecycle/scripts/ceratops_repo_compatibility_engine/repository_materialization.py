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
import re
import shutil
import subprocess
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


def _package_scripts(repo_root: pathlib.Path) -> set[str]:
    path = repo_root / "package.json"
    if not path.is_file() or path.is_symlink():
        return set()
    payload = load_mapping(path)
    scripts = payload.get("scripts", {})
    if not isinstance(scripts, Mapping):
        raise RuntimeError("package.json scripts must be an object")
    return {str(name) for name in scripts}


def _catalog_condition_matches(
    repo_root: pathlib.Path,
    condition: Mapping[str, object],
    package_scripts: set[str],
) -> bool:
    kind = condition.get("kind")
    if kind == "package-script" and set(condition) == {"kind", "value"}:
        value = condition["value"]
        if not isinstance(value, str) or not value:
            raise RuntimeError("catalog package-script value must be text")
        return value in package_scripts
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
    scripts = _package_scripts(repo_root)
    selected: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in entries:
        if not isinstance(raw, Mapping) or set(raw) != {
            "id",
            "when",
            "command",
            "cwd",
        }:
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
        seen.add(check_id)
        if any(
            _catalog_condition_matches(repo_root, condition, scripts)
            for condition in conditions
        ):
            selected.append(
                {"id": check_id, "command": list(command), "cwd": cwd.as_posix()}
            )
    return selected


def _validation_setup_step(
    repo_root: pathlib.Path, checks: list[dict[str, object]]
) -> str:
    commands: list[str] = []
    for check in checks:
        command = check["command"]
        if not isinstance(command, list):
            raise RuntimeError("catalog check command must be a list")
        for value in command:
            if not isinstance(value, str):
                raise RuntimeError("catalog check command values must be text")
            commands.append(value)
    setup: list[str] = []
    if "{python}" in commands:
        if (repo_root / "requirements-dev.txt").is_file():
            setup.append("python -m pip install -r requirements-dev.txt")
        elif (repo_root / "requirements.txt").is_file():
            setup.append("python -m pip install -r requirements.txt")
    if "{npm}" in commands:
        if not (repo_root / "package-lock.json").is_file():
            raise RuntimeError(
                "npm validation checks require package-lock.json for "
                "deterministic npm ci setup"
            )
        setup.append("npm ci")
    if not setup:
        return ""
    lines = [
        "      - name: Install validation dependencies",
        "        run: |",
        *(f"          {command}" for command in setup),
        "",
    ]
    return "\n".join(lines)


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
        validator_text = template.replace(marker, repr(checks))
    workflow_text = None
    if not workflow.is_file():
        template = WORKFLOW_TEMPLATE.read_text(encoding="utf-8")
        marker = "      # __SETUP_STEP__"
        if template.count(marker) != 1:
            raise RuntimeError("CI validation template marker is invalid")
        workflow_text = template.replace(
            marker,
            _validation_setup_step(repo_root, checks),
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
