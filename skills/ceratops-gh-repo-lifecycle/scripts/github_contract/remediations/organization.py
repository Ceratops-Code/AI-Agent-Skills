"""Reversible organization remediation handlers."""

from __future__ import annotations

from typing import Any

from ..github_api import run_gh_api


def apply_organization_desired(
    rules: list[dict[str, Any]], _parameters: dict[str, Any]
) -> list[dict[str, Any]]:
    """Write each contract-declared desired API object to its declared endpoint."""

    applied = []
    for rule in rules:
        method = str(rule.get("remediation_method", "PUT")).upper()
        result = run_gh_api(method, str(rule["endpoint"]), rule.get("desired"))
        applied.append(
            {
                "check_id": rule["id"],
                "action": "organization.write_desired",
                "ok": result.ok,
                "status": result.status,
                "message": result.message,
            }
        )
    return applied
