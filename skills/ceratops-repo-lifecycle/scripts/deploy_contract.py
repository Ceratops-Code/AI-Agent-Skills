"""Load and validate repository deployment contracts against the owned schema.

This module is the single schema-validation owner for deployment execution,
repository compatibility, and health collection. It reads data only; callers
retain repository-boundary checks and decide whether a missing contract is
allowed.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Mapping
from typing import Any, cast

import jsonschema
import yaml


SCHEMA = (
    pathlib.Path(__file__).resolve().parent.parent
    / "references"
    / "schemas"
    / "deploy-contract.schema.json"
)


class DeployContractError(RuntimeError):
    """Raised when a deployment contract or its schema is invalid."""


def _schema_validator(
    schema_path: pathlib.Path = SCHEMA,
) -> jsonschema.Draft202012Validator:
    """Load and validate the lifecycle-owned deployment schema."""

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        jsonschema.SchemaError,
    ) as exc:
        raise DeployContractError(f"invalid deployment schema: {exc}") from exc
    return jsonschema.Draft202012Validator(schema)


def validation_errors(
    value: object,
    *,
    schema_path: pathlib.Path = SCHEMA,
) -> list[str]:
    """Return stable schema errors for one already-loaded contract value."""

    validator = _schema_validator(schema_path)
    errors: list[str] = []
    for error in sorted(
        validator.iter_errors(value),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    ):
        location = ".".join(str(part) for part in error.absolute_path)
        suffix = f" at {location}" if location else ""
        errors.append(f"schema validation failed{suffix}: {error.message}")
    return errors


def read_contract(
    path: pathlib.Path,
    *,
    schema_path: pathlib.Path = SCHEMA,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Read one YAML contract and return its mapping plus compact errors."""

    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return None, [f"invalid YAML: {exc}"]
    try:
        errors = validation_errors(value, schema_path=schema_path)
    except DeployContractError as exc:
        return None, [str(exc)]
    if errors:
        return None, errors
    if not isinstance(value, Mapping):
        return None, ["schema-validated contract is not a mapping"]
    return dict(cast(Mapping[str, Any], value)), []


def load_contract(
    path: pathlib.Path,
    *,
    schema_path: pathlib.Path = SCHEMA,
) -> Mapping[str, Any]:
    """Load one valid contract or raise one compact deterministic error."""

    value, errors = read_contract(path, schema_path=schema_path)
    if errors or value is None:
        raise DeployContractError("; ".join(errors) or "invalid deployment contract")
    return value
