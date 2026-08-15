"""Resolve repository-owned artifact identities for contract checks.

Repository-specific artifact identity belongs beside release publication in
``release/release.yml``. Explicit checker parameters remain available only for
repositories that have not declared artifact identities locally; accepting two
owners for the same facts would reintroduce configuration drift.
"""

from __future__ import annotations

import pathlib
from collections.abc import Mapping
from typing import Any

from ceratops_repo_compatibility_engine.deploy_contract_validation import (
    DeployContractError,
    load_contract,
)

RELEASE_CONTRACT = pathlib.Path("release/release.yml")
RELEASE_SCHEMA = (
    pathlib.Path(__file__).resolve().parents[2]
    / "references"
    / "schemas"
    / "release-contract.schema.json"
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


def resolve_repository_artifact_contracts(
    local_repo_path: object,
    explicit_contracts: object,
) -> list[dict[str, Any]]:
    """Prefer validated repository release identity over caller configuration."""

    explicit = _records(explicit_contracts)
    if not isinstance(local_repo_path, str) or not local_repo_path.strip():
        return explicit
    repo_root = pathlib.Path(local_repo_path).expanduser().resolve()
    if not repo_root.is_dir():
        return explicit
    contract_path = repo_root / RELEASE_CONTRACT
    if not contract_path.exists():
        return explicit
    if contract_path.is_symlink() or not contract_path.is_file():
        raise ValueError("release/release.yml must be a regular file")
    try:
        contract = load_contract(contract_path, schema_path=RELEASE_SCHEMA)
    except DeployContractError as exc:
        raise ValueError(f"invalid release/release.yml: {exc}") from exc
    repository_contracts = _records(contract.get("artifacts", []))
    if not repository_contracts:
        return explicit
    if explicit:
        raise ValueError(
            "artifact identity is declared both in release/release.yml and "
            "artifact_contracts"
        )
    return repository_contracts
