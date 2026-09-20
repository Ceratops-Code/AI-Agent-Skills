"""Validate versioned SDLC data and adapt its structure for shared consumers.

This module is the single schema-validation owner for operation execution,
repository compatibility, artifact identity, and health collection. It reads
data only; callers retain repository-boundary checks and decide whether a
missing contract or contract section is allowed.
"""

from __future__ import annotations

import json
import pathlib
import re
from collections.abc import Mapping
from typing import Any, cast

import jsonschema
import yaml

SKILL_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = SKILL_ROOT / "references" / "schemas" / "sdlc.yml.schema.json"
# Compatibility application still owns v3. V4 is an independently supported
# typed-deliverable format and must not silently convert existing contracts.
V4_SCHEMA = SCHEMA.with_name("sdlc.v4.schema.json")
CURRENT_VERSION = 3
VERSION_SCHEMAS = {
    1: SCHEMA.with_name("sdlc.v1.schema.json"),
    2: SCHEMA.with_name("sdlc.v2.schema.json"),
    3: SCHEMA,
    4: V4_SCHEMA,
}
OPERATION_CATEGORIES = frozenset({"bootstrap", "validate", "tests", "test-selection", "deploy-local", "publish"})
NAME = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
CURRENT_OPERATION_RE = re.compile(
    rf"^(?:repository\.(?P<repository>bootstrap|validate|tests|test-selection)|"
    rf"deliverables\.{NAME}\.(?P<deliverable>validate|tests|deploy-local|publish))\.{NAME}$"
)
V1_OPERATION_RE = re.compile(r"^(deploy|release)\.operations\.[a-z][a-z0-9_-]*$")
V4_OPERATION_RE = re.compile(
    rf"^(?:repository\.actions\.(?P<repository>bootstrap|validate|test|test-selection)|"
    rf"deliverables\.(?P<kind>packages|apps|tools|skills|hooks)\."
    rf"(?P<name>{NAME})\.actions\.(?P<action>validate|test|build|install|publish|verify-publish))$"
)
V4_ACTIONS_BY_KIND = {
    "packages": frozenset({"validate", "test", "build", "publish", "verify-publish"}),
    "apps": frozenset({"validate", "test", "install", "publish", "verify-publish"}),
    "tools": frozenset({"validate", "test", "install", "publish", "verify-publish"}),
    "skills": frozenset({"validate", "test", "install"}),
    "hooks": frozenset({"validate", "test", "install"}),
}
V4_ACTION_CATEGORIES = {
    "bootstrap": "bootstrap",
    "test-selection": "test-selection",
    "validate": "validate",
    "test": "tests",
    "build": "build",
    "install": "deploy-local",
    "publish": "publish",
    "verify-publish": "verify-publish",
}


class SdlcContractError(RuntimeError):
    """Raised when an SDLC contract or its schema is invalid."""


class _ContractLoader(yaml.SafeLoader):
    """Reject duplicate declarations instead of silently replacing their commands."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        self.flatten_mapping(node)
        result: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise yaml.constructor.ConstructorError(
                    None, None, "SDLC mapping keys must be unique strings", key_node.start_mark,
                )
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def operation_entries(contract: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Adapt validated version-specific groups to the executor's operation index.

    Locations stay native to the declared version. Version 1 has no category
    metadata: names such as bootstrap or preflight must never imply validation
    or setup. Operation bodies, including step IDs, remain unchanged.
    """

    entries: dict[str, Mapping[str, Any]] = {}
    if contract.get("version") == 1:
        for section, group in contract.items():
            if section in {"deploy", "release"}:
                for name, operation in group["operations"].items():
                    entries[f"{section}.operations.{name}"] = operation
        return entries
    if contract.get("version") == 4:
        for action, operation in contract.get("repository", {}).get("actions", {}).items():
            entries[f"repository.actions.{action}"] = operation
        for kind, deliverables in contract.get("deliverables", {}).items():
            for name, deliverable in deliverables.items():
                for action, operation in deliverable.get("actions", {}).items():
                    entries[
                        f"deliverables.{kind}.{name}.actions.{action}"
                    ] = operation
        return entries
    groups = [("repository", contract.get("repository", {}))]
    groups.extend(
        (f"deliverables.{name}", value)
        for name, value in contract.get("deliverables", {}).items()
    )
    for prefix, group in groups:
        for category, operations in group.items():
            if category in OPERATION_CATEGORIES:
                for name, operation in operations.items():
                    entries[f"{prefix}.{category}.{name}"] = operation
    return entries


def operation_category(location: str) -> str:
    """Classify a native versioned location without guessing from operation names."""

    if isinstance(location, str):
        if match := V4_OPERATION_RE.fullmatch(location):
            action = match.group("repository") or match.group("action")
            kind = match.group("kind")
            if kind is None or action in V4_ACTIONS_BY_KIND[kind]:
                return V4_ACTION_CATEGORIES[action]
        if match := CURRENT_OPERATION_RE.fullmatch(location):
            return match.group("repository") or match.group("deliverable")
        if match := V1_OPERATION_RE.fullmatch(location):
            return {"deploy": "deploy-local", "release": "publish"}[match.group(1)]
    raise SdlcContractError(f"Invalid SDLC operation location: {location}")


def artifact_entries(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Adapt versioned artifact ownership without changing records or precedence."""

    # V4 package build outputs are prerequisites for local lifecycle actions,
    # not the external publication-identity records consumed by this adapter.
    if contract.get("version") == 4:
        return []
    groups = (
        [contract.get("release", {})]
        if contract.get("version") == 1
        else contract.get("deliverables", {}).values()
    )
    return [dict(record) for group in groups for record in group.get("artifacts", [])]


def migration_proposal(
    contract: Mapping[str, Any], repository: str,
) -> dict[str, Any] | None:
    """Describe an optional upgrade for already-validated supported older data.

    This is health-report annotation only. Execution and materialization never
    consume it, and installer release numbers are deliberately unrelated.
    """

    version = contract["version"]
    if version >= CURRENT_VERSION:
        return None
    return {
        "repository": repository,
        "current_version": version,
        "recommended_version": CURRENT_VERSION,
        "reason": (
            "Version 3 separates validation and tests, requires deliverable tests, "
            "and supports explicit no-op operations; versions 1 and 2 remain executable."
        ),
    }


def _relative_path(value: str) -> bool:
    """Keep metadata file references portable and lexically repository-bounded."""

    path = pathlib.PurePosixPath(value)
    windows = pathlib.PureWindowsPath(value)
    return not (
        path.is_absolute() or windows.drive or "\\" in value or ".." in path.parts
    )


def _v4_package_records(
    contract: Mapping[str, Any], direct: list[str],
) -> dict[str, dict[str, Any]]:
    """Return dependency-first package metadata without executing its actions."""

    packages = contract.get("deliverables", {}).get("packages", {})
    records: dict[str, dict[str, Any]] = {}

    def add(name: str) -> None:
        if name in records:
            return
        package = packages[name]
        for prerequisite in package.get("prerequisites", []):
            add(prerequisite)
        metadata = {
            key: value for key, value in package.items() if key != "actions"
        }
        metadata["action-locations"] = {
            action: f"deliverables.packages.{name}.actions.{action}"
            for action in package.get("actions", {})
        }
        records[name] = metadata

    for package_name in direct:
        add(package_name)
    return records


def operation_prerequisites(
    contract: Mapping[str, Any], location: str,
) -> dict[str, Any]:
    """Expose declared setup metadata for one native operation location.

    V1-v3 retain the flat executable record shape. V4 distinguishes executable
    capabilities from package prerequisites and includes transitive package
    metadata plus selectable action locations. Nothing in this adapter runs a
    prerequisite action.
    """

    operation = operation_entries(contract).get(location, {})
    if contract.get("version") != 4:
        requirements = contract.get("repository", {}).get("prerequisites", {})
        return {
            name: requirements[name]
            for name in operation.get("prerequisites", [])
        }
    match = V4_OPERATION_RE.fullmatch(location)
    if match is None:
        raise SdlcContractError(f"Invalid SDLC operation location: {location}")
    capabilities = contract.get("repository", {}).get("capabilities", {})
    required_capabilities = operation.get("requires", {}).get("capabilities", [])
    direct_packages: list[str] = []
    if match.group("kind") is not None:
        deliverable = (
            contract["deliverables"][match.group("kind")][match.group("name")]
        )
        direct_packages = list(deliverable.get("prerequisites", []))
    return {
        "capabilities": {
            name: capabilities[name] for name in required_capabilities
        },
        "packages": _v4_package_records(contract, direct_packages),
    }


def _v4_semantic_errors(value: Mapping[str, Any]) -> list[str]:
    """Validate references and lifecycle separation that JSON Schema cannot."""

    errors: list[str] = []
    repository = value["repository"]
    capabilities = repository["capabilities"]
    for name, capability in capabilities.items():
        version_source = capability.get("version-from")
        if version_source and not _relative_path(version_source["file"]):
            errors.append(f"capability {name} version-from.file must be repository-relative")
        if sum(key in capability for key in ("version", "version-from", "channel")) > 1:
            errors.append(f"capability {name} has multiple version authorities")
    deliverables = value.get("deliverables", {})
    packages = deliverables.get("packages", {})
    owners: list[tuple[str, Mapping[str, Any]]] = [("repository", repository)]
    for kind, group in deliverables.items():
        owners.extend(
            (f"{kind}.{name}", deliverable)
            for name, deliverable in group.items()
        )
    for owner, record in owners:
        for action_name, action in record["actions"].items():
            for capability in action["requires"]["capabilities"]:
                if capability not in capabilities:
                    errors.append(
                        f"unknown capability {capability} at {owner}.actions.{action_name}"
                    )
            handoff_positions = [
                position
                for position, step in enumerate(action.get("steps", []), start=1)
                if "handoff" in step
            ]
            if handoff_positions and handoff_positions != [len(action["steps"])]:
                errors.append(
                    f"handoff must be the single final step at {owner}.actions.{action_name}"
                )
    path_fields = {
        "packages": ("source", "project"),
        "apps": ("source", "manifest"),
        "tools": ("source", "manifest"),
        "skills": ("source",),
        "hooks": ("source",),
    }
    for kind, fields in path_fields.items():
        for name, record in deliverables.get(kind, {}).items():
            for field in fields:
                if field in record and not _relative_path(record[field]):
                    errors.append(f"{kind}.{name}.{field} must be repository-relative")
            artifact = record.get("artifact")
            if artifact and not _relative_path(artifact["output-directory"]):
                errors.append(
                    f"{kind}.{name}.artifact.output-directory must be repository-relative"
                )
            if artifact and (
                "/" in artifact["filename-pattern"]
                or "\\" in artifact["filename-pattern"]
                or artifact["filename-pattern"] in {".", ".."}
            ):
                errors.append(
                    f"{kind}.{name}.artifact.filename-pattern must be a filename pattern"
                )
            unknown = sorted(set(record.get("prerequisites", [])) - set(packages))
            if unknown:
                errors.append(f"{kind}.{name} requires unknown package {unknown[0]}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            errors.append(f"package prerequisite cycle includes {name}")
            return
        if name in visited or name not in packages:
            return
        visiting.add(name)
        for prerequisite in packages[name].get("prerequisites", []):
            visit(prerequisite)
        visiting.remove(name)
        visited.add(name)

    for name in packages:
        visit(name)
    lifecycle_by_kind = {
        "tools": "ceratops-tool-lifecycle",
        "skills": "ceratops-skill-lifecycle",
    }
    for kind, lifecycle in lifecycle_by_kind.items():
        for name, record in deliverables.get(kind, {}).items():
            for action_name in ("validate", "install"):
                action = record["actions"][action_name]
                # A tool may have no separate validation step. Installation
                # may use a repository-owned script or a tool-lifecycle handoff.
                if kind == "tools" and action_name == "validate" and "no-op" in action:
                    continue
                handoffs = [
                    step["handoff"]
                    for step in action.get("steps", [])
                    if "handoff" in step
                ]
                if not handoffs:
                    if kind == "tools" and action_name == "install" and action.get("steps"):
                        continue
                    errors.append(
                        f"{kind}.{name}.actions.{action_name} must end with a handoff"
                    )
                    continue
                if handoffs[0]["lifecycle"] != lifecycle:
                    errors.append(
                        f"{kind}.{name}.actions.{action_name} must hand off to {lifecycle}"
                    )
                identity = "tool" if kind == "tools" else "skill"
                if handoffs[0]["inputs"].get(identity) != name:
                    errors.append(
                        f"{kind}.{name}.actions.{action_name} must identify {identity} {name}"
                    )
                declared = handoffs[0]["inputs"].get("prerequisite-packages")
                if declared is not None and declared != record["prerequisites"]:
                    errors.append(
                        f"{kind}.{name}.actions.{action_name} prerequisite-packages differ from prerequisites"
                    )
    return errors


def _schema_validator(
    schema_path: pathlib.Path = SCHEMA,
) -> jsonschema.Draft202012Validator:
    """Load and validate the lifecycle-owned SDLC schema."""

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        jsonschema.SchemaError,
    ) as exc:
        raise SdlcContractError(f"invalid SDLC schema: {exc}") from exc
    return jsonschema.Draft202012Validator(schema)


def validation_errors(
    value: object,
    *,
    schema_path: pathlib.Path | None = None,
) -> list[str]:
    """Return stable schema errors for one already-loaded contract value."""

    if not isinstance(value, Mapping):
        return ["SDLC contract must be a mapping"]
    version = value.get("version")
    if type(version) is not int or version not in VERSION_SCHEMAS:
        supported = ", ".join(str(item) for item in sorted(VERSION_SCHEMAS))
        return [
            f"unsupported SDLC version: {version!r}; supported versions: {supported}"
        ]
    selected_schema = (
        VERSION_SCHEMAS[version] if schema_path in (None, SCHEMA) else schema_path
    )
    validator = _schema_validator(selected_schema)
    errors: list[str] = []
    for error in sorted(
        validator.iter_errors(value),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    ):
        location = ".".join(str(part) for part in error.absolute_path)
        suffix = f" at {location}" if location else ""
        errors.append(f"schema validation failed{suffix}: {error.message}")
    if errors or version == 1:
        return errors
    if version == 4:
        return _v4_semantic_errors(value)
    prerequisites = value.get("repository", {}).get("prerequisites", {})
    for name, requirement in prerequisites.items():
        version_source = requirement.get("version-from")
        if version_source and not _relative_path(version_source["file"]):
            errors.append(f"prerequisite {name} version-from.file must be repository-relative")
        if sum(key in requirement for key in ("version", "version-from", "channel")) > 1:
            errors.append(f"prerequisite {name} has multiple version authorities")
    for location, operation in operation_entries(value).items():
        for name in operation.get("prerequisites", []):
            if name not in prerequisites:
                errors.append(f"unknown prerequisite {name} at {location}")
    return errors


def read_contract(
    path: pathlib.Path,
    *,
    schema_path: pathlib.Path | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate one YAML contract, retaining its version and data without writes."""

    try:
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=_ContractLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return None, [f"invalid YAML: {exc}"]
    try:
        errors = validation_errors(value, schema_path=schema_path)
    except SdlcContractError as exc:
        return None, [str(exc)]
    if errors:
        return None, errors
    if not isinstance(value, Mapping):
        return None, ["schema-validated contract is not a mapping"]
    return dict(cast(Mapping[str, Any], value)), []


def load_contract(
    path: pathlib.Path,
    *,
    schema_path: pathlib.Path | None = None,
) -> Mapping[str, Any]:
    """Load one valid contract or raise one compact deterministic error."""

    value, errors = read_contract(path, schema_path=schema_path)
    if errors or value is None:
        raise SdlcContractError(("; ".join(errors[:8]) or "invalid SDLC contract")[:4096])
    return value
