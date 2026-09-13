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
CURRENT_VERSION = 2
VERSION_SCHEMAS = {1: SCHEMA.with_name("sdlc.v1.schema.json"), 2: SCHEMA}
OPERATION_CATEGORIES = frozenset({
    "bootstrap", "validate", "test-selection", "deploy-local", "publish",
})
NAME = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
CURRENT_OPERATION_RE = re.compile(
    rf"^(?:repository\.(?P<repository>bootstrap|validate|test-selection)|"
    rf"deliverables\.{NAME}\.(?P<deliverable>validate|deploy-local|publish))\.{NAME}$"
)
V1_OPERATION_RE = re.compile(r"^(deploy|release)\.operations\.[a-z][a-z0-9_-]*$")


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
        if match := CURRENT_OPERATION_RE.fullmatch(location):
            return match.group("repository") or match.group("deliverable")
        if match := V1_OPERATION_RE.fullmatch(location):
            return {"deploy": "deploy-local", "release": "publish"}[match.group(1)]
    raise SdlcContractError(f"Invalid SDLC operation location: {location}")


def artifact_entries(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Adapt versioned artifact ownership without changing records or precedence."""

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
    if version == CURRENT_VERSION:
        return None
    return {
        "repository": repository,
        "current_version": version,
        "recommended_version": CURRENT_VERSION,
        "reason": (
            "Version 2 explicitly groups repository validation and deliverable "
            "capabilities; version 1 remains supported without migration."
        ),
    }


def _relative_path(value: str) -> bool:
    """Keep metadata file references portable and lexically repository-bounded."""

    path = pathlib.PurePosixPath(value)
    windows = pathlib.PureWindowsPath(value)
    return not (
        path.is_absolute() or windows.drive or "\\" in value or ".." in path.parts
    )


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
        return [f"unsupported SDLC version: {version!r}; supported versions: 1, 2"]
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
