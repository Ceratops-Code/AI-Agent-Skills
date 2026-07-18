"""Compose selected deterministic contracts into one desired-state document."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import fnmatch
from typing import Any

from .collect_observed_states import state_producer
from .compare_states import OPERATORS
from .github_api import load_json, substitute


REPO_SURFACES = ("repo", "code", "artifact")


def check_ids(contract: dict[str, Any]) -> set[str]:
    """Return the declared check IDs in one contract."""

    return {str(check["id"]) for check in contract.get("checks", [])}


def _prefixes(ids: set[str], *prefixes: str) -> set[str]:
    return {check_id for check_id in ids if check_id.startswith(prefixes)}


def repo_subset_ids(
    contracts: dict[str, dict[str, Any]], subset: str
) -> dict[str, set[str] | None]:
    """Select the workflow-oriented repository slice requested by callers."""

    ids = {surface: check_ids(contract) for surface, contract in contracts.items()}
    if subset in {"all", "health"}:
        return {surface: None for surface in REPO_SURFACES}
    if subset == "settings":
        return {
            "repo": _prefixes(
                ids["repo"], "repo.", "process.", "actions.", "security.", "content."
            ),
            "code": set(),
            "artifact": set(),
        }
    if subset == "dependency":
        return {
            "repo": {
                item
                for item in ids["repo"]
                if item.startswith("security.")
                or item == "content.dependencies_label_when_dependabot_uses_it"
            },
            "code": {
                item
                for item in ids["code"]
                if item == "security.dependabot_config_file"
            },
            "artifact": set(),
        }
    if subset == "content":
        return {
            "repo": _prefixes(ids["repo"], "content."),
            "code": _prefixes(ids["code"], "content.", "actions."),
            "artifact": set(),
        }
    if subset == "artifact":
        return {
            "repo": set(),
            "code": _prefixes(ids["code"], "type.", "actions."),
            "artifact": None,
        }
    if subset == "create":
        return {
            "repo": {
                item for item in ids["repo"] if not item.startswith("stale_state.")
            },
            "code": {
                item
                for item in ids["code"]
                if not item.startswith("stale_state.") and item != "local.git_state"
            },
            "artifact": None,
        }
    raise ValueError(f"unknown repository subset: {subset}")


def org_subset_ids(contract: dict[str, Any], subset: str) -> set[str] | None:
    """Select one organization settings family."""

    if subset == "all":
        return None
    prefixes = {
        "settings": ("org.", "organization.", "custom_properties."),
        "actions": ("actions.",),
        "dependabot": ("dependabot.",),
        "security": ("code_security.", "dependabot.", "private_registries."),
    }[subset]
    return _prefixes(check_ids(contract), *prefixes)


def _selected_checks(
    contract: dict[str, Any], selected: set[str] | None
) -> list[dict[str, Any]]:
    checks = contract.get("checks", [])
    return (
        checks
        if selected is None
        else [check for check in checks if check["id"] in selected]
    )


def _request_plan(
    contract: dict[str, Any], selected: set[str] | None, bundles: set[str] | None
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    if selected == set():
        return requests
    fetch_bundles = contract.get("fetch_bundles", [])
    if isinstance(fetch_bundles, dict):
        for bundle_id, bundle in fetch_bundles.items():
            if bundles is not None and bundle_id not in bundles:
                continue
            feeds = bundle.get("feeds_checks", [])
            covered = {
                check_id
                for check_id in (check_ids(contract) if selected is None else selected)
                if any(fnmatch.fnmatch(check_id, pattern) for pattern in feeds)
            }
            if selected is not None and not covered:
                continue
            for specification in bundle.get("endpoints", []):
                if bundle_id == "github_packages_bundle":
                    continue
                if isinstance(specification, dict):
                    method = str(specification.get("method", "GET")).upper()
                    endpoint = str(specification.get("endpoint", ""))
                    paginate = bool(specification.get("paginate"))
                    separator = " "
                else:
                    method, separator, endpoint = str(specification).partition(" ")
                    paginate = False
                if not separator or not endpoint.startswith("/"):
                    continue
                requests.append(
                    {
                        "method": method,
                        "endpoint": endpoint,
                        "paginate": paginate,
                        "covers_checks": sorted(covered),
                    }
                )
        return requests
    if not isinstance(fetch_bundles, list):
        return requests
    for bundle in fetch_bundles:
        if bundles is not None and bundle.get("id") not in bundles:
            continue
        for request in bundle.get("requests", []):
            covered = set(
                request.get("covers_checks") or bundle.get("covers_checks") or []
            )
            if selected is not None and covered and not covered.intersection(selected):
                continue
            requests.append(request)
    return requests


def _known_bundle_ids(contracts: Iterable[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for contract in contracts:
        bundles = contract.get("fetch_bundles", [])
        if isinstance(bundles, dict):
            result.update(str(item) for item in bundles)
        else:
            result.update(
                str(item["id"])
                for item in bundles
                if isinstance(item, dict) and item.get("id")
            )
    return result


def compose_desired_state(
    contract_paths: dict[str, str],
    parameters: dict[str, Any],
    selected_ids: Mapping[str, set[str] | None],
    *,
    explicit_check_ids: Iterable[str] | None = None,
    bundle_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Load, select, parameterize, and combine contract state assertions.

    This function performs no I/O beyond reading contract JSON. Applicability is
    deliberately left for comparison because it depends on observed facts.
    """

    contracts = {surface: load_json(path) for surface, path in contract_paths.items()}
    requested = set(explicit_check_ids or [])
    known_ids = {
        item for contract in contracts.values() for item in check_ids(contract)
    }
    unknown = requested - known_ids
    if unknown:
        raise ValueError(f"unknown check id(s): {', '.join(sorted(unknown))}")
    bundles = set(bundle_ids) if bundle_ids else None
    if bundles:
        unknown_bundles = bundles - _known_bundle_ids(contracts.values())
        if unknown_bundles:
            raise ValueError(
                f"unknown fetch bundle id(s): {', '.join(sorted(unknown_bundles))}"
            )

    rules: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    selected_by_surface: dict[str, list[str]] = {}
    for surface, contract in contracts.items():
        selected = selected_ids.get(surface)
        if requested:
            selected = (
                requested if selected is None else selected.intersection(requested)
            )
        checks = _selected_checks(contract, selected)
        selected_by_surface[surface] = [str(check["id"]) for check in checks]
        for check in checks:
            if not check.get("assertions"):
                raise ValueError(
                    f"deterministic check has no state assertions: {check['id']}"
                )
            parameterized = substitute(check, parameters)
            for assertion in parameterized["assertions"]:
                operator = assertion.get("operator")
                if operator not in OPERATORS:
                    raise ValueError(
                        f"unsupported comparison operator {operator!r} in {check['id']}"
                    )
                if state_producer(str(assertion.get("path", ""))) is None:
                    raise ValueError(
                        f"no state producer registered for {assertion.get('path')!r} in {check['id']}"
                    )
            rules.append({**parameterized, "surface": surface})
        requests.extend(_request_plan(contract, selected, bundles))

    excluded = requested - {str(rule["id"]) for rule in rules}
    if excluded:
        raise ValueError(
            f"check id(s) excluded by current selection: {', '.join(sorted(excluded))}"
        )

    unique_requests: dict[tuple[str, str], dict[str, Any]] = {}
    for request in requests:
        key = (str(request.get("method", "GET")).upper(), str(request["endpoint"]))
        existing = unique_requests.setdefault(key, {**request, "covers_checks": []})
        existing["covers_checks"] = sorted(
            set(existing.get("covers_checks", []))
            | set(request.get("covers_checks", []))
        )
    return {
        "parameters": parameters,
        "contracts": list(contracts.values()),
        "contract_paths": contract_paths,
        "rules": rules,
        "requests": list(unique_requests.values()),
        "selected_ids": selected_by_surface,
        "bundle_ids": sorted(bundles) if bundles else None,
    }
