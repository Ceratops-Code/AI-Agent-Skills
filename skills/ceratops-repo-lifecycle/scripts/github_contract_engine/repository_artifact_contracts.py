"""Resolve repository-owned artifact identities for contract checks.

Repository-specific artifact identity belongs under its owning deliverable in
``sdlc/sdlc.yml``. Explicit checker parameters remain available only for
repositories that have not declared artifact identities locally; accepting two
owners for the same facts would reintroduce configuration drift.
"""

from __future__ import annotations

import pathlib
from collections.abc import Mapping
from typing import Any

from ceratops_repo_compatibility_engine.sdlc_contract_validation import (
    SdlcContractError,
    load_contract,
    validation_errors,
)

SDLC_CONTRACT = pathlib.Path("sdlc/sdlc.yml")
SDLC_SCHEMA = (
    pathlib.Path(__file__).resolve().parents[2]
    / "references"
    / "schemas"
    / "sdlc.yml.schema.json"
)


def _records(value: object) -> list[dict[str, Any]]:
    """Return detached artifact records or reject malformed explicit input."""

    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, Mapping) for item in value
    ):
        raise ValueError("artifact_contracts must be a list of objects")
    return [dict(item) for item in value]


def _validated_explicit_records(value: object) -> list[dict[str, Any]]:
    """Validate explicit artifact records through the SDLC schema owner."""

    records = _records(value)
    if not records:
        return records
    document = {
        "version": 2,
        "kind": "ceratops-sdlc",
        "deliverables": {"explicit": {"artifacts": records}},
    }
    try:
        errors = validation_errors(document, schema_path=SDLC_SCHEMA)
    except SdlcContractError as exc:
        raise ValueError(f"invalid artifact_contracts schema: {exc}") from exc
    if errors:
        raise ValueError("invalid artifact_contracts: " + "; ".join(errors))
    return records


def resolve_repository_artifact_contracts(
    local_repo_path: object,
    explicit_contracts: object,
) -> list[dict[str, Any]]:
    """Prefer validated repository SDLC identity over caller configuration."""

    explicit = _validated_explicit_records(explicit_contracts)
    if not isinstance(local_repo_path, str) or not local_repo_path.strip():
        return explicit
    repo_root = pathlib.Path(local_repo_path).expanduser().resolve()
    if not repo_root.is_dir():
        return explicit
    contract_path = repo_root / SDLC_CONTRACT
    if not contract_path.exists():
        return explicit
    if contract_path.is_symlink() or not contract_path.is_file():
        raise ValueError("sdlc/sdlc.yml must be a regular file")
    try:
        contract = load_contract(contract_path, schema_path=SDLC_SCHEMA)
    except SdlcContractError as exc:
        raise ValueError(f"invalid sdlc/sdlc.yml: {exc}") from exc
    repository_contracts = [
        record
        for deliverable in contract.get("deliverables", {}).values()
        for record in _records(deliverable.get("artifacts", []))
    ]
    if not repository_contracts:
        return explicit
    if explicit:
        raise ValueError(
            "artifact identity is declared both in sdlc/sdlc.yml and "
            "artifact_contracts"
        )
    return repository_contracts
