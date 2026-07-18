"""Narrow reversible repository remediation handlers."""

from __future__ import annotations

from typing import Any

from ..github_api import run_gh_api


def _slug(parameters: dict[str, Any]) -> str:
    return f"{parameters['owner']}/{parameters['repo']}"


def update_repository_settings(
    rules: list[dict[str, Any]], parameters: dict[str, Any]
) -> list[dict[str, Any]]:
    """Patch only mismatched boolean repository settings declared by rules."""

    body: dict[str, Any] = {}
    for rule in rules:
        mismatch_paths = set(rule.get("_mismatch_paths", []))
        for assertion in rule["assertions"]:
            path = str(assertion["path"])
            if (
                path in mismatch_paths
                and path.startswith("/repository/repo/")
                and assertion.get("operator") == "equal"
                and isinstance(assertion.get("expected"), bool)
            ):
                body[path.rsplit("/", 1)[-1]] = assertion["expected"]
    if not body:
        return []
    result = run_gh_api("PATCH", f"/repos/{_slug(parameters)}", body)
    return [
        {
            "check_id": rule["id"],
            "action": "repository.update_settings",
            "ok": result.ok,
            "status": result.status,
            "message": result.message,
        }
        for rule in rules
    ]


def enable_repository_endpoint(
    rules: list[dict[str, Any]], parameters: dict[str, Any]
) -> list[dict[str, Any]]:
    """Enable each rule's contract-declared GitHub feature endpoint."""

    applied = []
    for rule in rules:
        endpoint = str(rule["endpoint"])
        result = run_gh_api("PUT", endpoint)
        applied.append(
            {
                "check_id": rule["id"],
                "action": "repository.enable_endpoint",
                "ok": result.ok,
                "status": result.status,
                "message": result.message,
            }
        )
    return applied


def ensure_dependencies_label(
    rules: list[dict[str, Any]], parameters: dict[str, Any]
) -> list[dict[str, Any]]:
    """Create the fixed label referenced by the repository's Dependabot config."""

    result = run_gh_api(
        "POST",
        f"/repos/{_slug(parameters)}/labels",
        {
            "name": "dependencies",
            "color": "0366d6",
            "description": "Dependency updates",
        },
    )
    return [
        {
            "check_id": rule["id"],
            "action": "repository.ensure_dependencies_label",
            "ok": result.ok,
            "status": result.status,
            "message": result.message,
        }
        for rule in rules
    ]
