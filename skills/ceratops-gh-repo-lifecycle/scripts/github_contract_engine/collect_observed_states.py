"""Collect observed state for the GitHub contract engine."""

from __future__ import annotations

import fnmatch
from typing import Any

from .collectors import (
    collect_local_repository,
    collect_organization,
    collect_registries,
    collect_repository,
)
from .compare_states import condition_matches
from .github_api import ApiResult, run_gh_api, substitute


PRODUCER_REGISTRY = {
    "github_api": ("/api/*",),
    "organization": ("/organization/avatar/*",),
    "repository": (
        "/repository/repo/*",
        "/repository/actions/*",
        "/repository/content/*",
        "/repository/enforcement",
        "/repository/paths",
        "/repository/protection_facts/*",
        "/repository/rulesets/*",
        "/repository/security/*",
        "/repository/stale/*",
        "/repository/topics",
        "/repository/types*",
    ),
    "local_repository": (
        "/local/available",
        "/local/git/*",
        "/local/manifests/*",
        "/local/scans/*",
        "/local/workflows/*",
    ),
    "registries": ("/registries/*/all_resolved",),
    "artifact_state": (
        "/artifact/contracts",
        "/artifact/live_metadata/all_resolved",
        "/artifact/publish_requested",
        "/artifact/recorded_checks/*",
        "/artifact/release_assets",
        "/artifact/types",
    ),
}


def state_producer(path: str) -> str | None:
    """Return the exact registered collector family for one assertion path."""

    return next(
        (
            name
            for name, patterns in PRODUCER_REGISTRY.items()
            if any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)
        ),
        None,
    )


def _planned_requests(desired_state: dict[str, Any]) -> list[dict[str, Any]]:
    """Combine declared fetch bundles with directly declared rule endpoints."""

    parameters = desired_state["parameters"]
    requests = list(desired_state.get("requests", []))
    covered = {
        (
            str(item.get("method", "GET")).upper(),
            str(substitute(item["endpoint"], parameters)),
        )
        for item in requests
    }
    for rule in desired_state["rules"]:
        if not rule.get("endpoint"):
            continue
        key = (
            str(rule.get("method", "GET")).upper(),
            str(substitute(rule["endpoint"], parameters)),
        )
        if key not in covered:
            requests.append(
                {
                    "method": key[0],
                    "endpoint": key[1],
                    "applies_when": rule.get("applies_when"),
                    "covers_checks": [rule["id"]],
                }
            )
            covered.add(key)
    return requests


def _fetch_all(desired_state: dict[str, Any]) -> dict[tuple[str, str], ApiResult]:
    parameters = desired_state["parameters"]
    fetched: dict[tuple[str, str], ApiResult] = {}
    repository_seed: dict[str, Any] | None = None
    if parameters.get("owner") and parameters.get("repo"):
        endpoint = f"/repos/{parameters['owner']}/{parameters['repo']}"
        seed = run_gh_api("GET", endpoint)
        fetched[("GET", endpoint)] = seed
        if seed.ok and isinstance(seed.data, dict):
            repository_seed = seed.data
            parameters.setdefault("default_branch", seed.data.get("default_branch"))
    if parameters.get("org_login"):
        endpoint = f"/orgs/{parameters['org_login']}"
        fetched[("GET", endpoint)] = run_gh_api("GET", endpoint)
    condition_context: dict[str, Any] = {
        **parameters,
        "repo": repository_seed or {},
    }
    for request in _planned_requests(desired_state):
        # Request conditions may depend only on parameters and the repository seed,
        # which is fetched first so inapplicable paid or visibility-bound APIs are
        # never called. If the seed failed, keep collecting to preserve the error.
        if (
            repository_seed is not None
            and request.get("applies_when")
            and not condition_matches(
                str(request["applies_when"]),
                condition_context,
            )
        ):
            continue
        method = str(request.get("method", "GET")).upper()
        endpoint = str(substitute(request["endpoint"], parameters))
        key = (method, endpoint)
        if key not in fetched:
            fetched[key] = run_gh_api(
                method, endpoint, paginate=bool(request.get("paginate"))
            )
        if (
            endpoint == f"/orgs/{parameters.get('owner')}"
            and fetched[key].ok
            and isinstance(fetched[key].data, dict)
        ):
            condition_context["owner"] = fetched[key].data
    return fetched


def _api_state(
    desired_state: dict[str, Any], fetched: dict[tuple[str, str], ApiResult]
) -> dict[str, Any]:
    """Expose each selected rule's primary response under its stable check ID."""

    parameters = desired_state["parameters"]
    state: dict[str, Any] = {}
    for rule in desired_state["rules"]:
        endpoint = rule.get("endpoint")
        if not endpoint:
            continue
        method = str(rule.get("method", "GET")).upper()
        resolved = str(substitute(endpoint, parameters))
        result = fetched.get(
            (method, resolved),
            ApiResult(False, method, resolved, message="response was not collected"),
        )
        state[rule["id"]] = result.state()
    if parameters.get("org_login"):
        endpoint = f"/orgs/{parameters['org_login']}"
        state.setdefault(
            "org.settings",
            fetched.get(
                ("GET", endpoint),
                ApiResult(False, "GET", endpoint, message="response was not collected"),
            ).state(),
        )
    return state


def _artifact_state(
    parameters: dict[str, Any],
    repository: dict[str, Any],
    local: dict[str, Any],
    registries: dict[str, Any],
) -> dict[str, Any]:
    types = repository.get("types", {})
    artifact_types = list(types.get("artifact_surface", ["no_artifact"]))
    external = [item for item in artifact_types if item != "no_artifact"]
    contracts = [
        item
        for item in parameters.get("artifact_contracts", [])
        if isinstance(item, dict)
    ]
    releases = repository.get("stale", {}).get("releases", {}).get("inventory", [])
    release_assets = [
        asset
        for release in releases
        if isinstance(release, dict)
        for asset in release.get("assets", [])
        if isinstance(asset, dict)
    ]
    registry_resolutions = [
        metadata
        for registry in registries.values()
        for metadata in registry.get("packages", {}).values()
    ]
    registry_hosts = sorted(
        {str(item.get("registry")) for item in contracts if item.get("registry")}
    )
    return {
        "types": artifact_types,
        "external_count": len(external),
        "contracts": contracts,
        "contract_count": len(contracts),
        "audit_only": bool(parameters.get("audit_only", True)),
        "publish_requested": bool(parameters.get("publish_requested", False)),
        "publish_workflow_detected": bool(
            local.get("workflows", {}).get("publish_detected")
        ),
        "attestation_detected": bool(
            local.get("workflows", {}).get("attestation_detected")
        ),
        "release_assets": release_assets,
        "live_metadata": {
            "identity_count": len(registry_resolutions),
            "all_resolved": bool(registry_resolutions)
            and all(item.get("ok") for item in registry_resolutions),
        },
        "registry_hosts": registry_hosts,
        "recorded_checks": {
            "local_build": bool(parameters.get("local_build_succeeded")),
            "consumer_smoke": bool(parameters.get("consumer_smoke_succeeded")),
            "publish_authorized": bool(parameters.get("publish_authorized")),
        },
    }


def collect_observed_states(desired_state: dict[str, Any]) -> dict[str, Any]:
    """Collect selected external and local facts once, then compose one JSON state."""

    parameters = desired_state["parameters"]
    rules = desired_state["rules"]
    fetched = _fetch_all(desired_state)
    local = collect_local_repository(
        parameters.get("local_repo_path"), rules, parameters.get("default_branch")
    )
    if parameters.get("owner") and parameters.get("repo"):
        artifact_type_system = next(
            (
                contract.get("artifact_type_system")
                for contract in desired_state["contracts"]
                if contract.get("kind") == "artifact_registry_contract"
            ),
            None,
        )
        repository = collect_repository(
            fetched, parameters, local, rules, artifact_type_system
        )
    else:
        repository = {
            "repo": {},
            "owner": {},
            "types": {},
            "paths": local.get("files", []),
        }
    organization = (
        collect_organization(fetched, parameters, rules)
        if parameters.get("org_login")
        else {}
    )
    artifact_types = repository.get("types", {}).get("artifact_surface", [])
    registries = (
        collect_registries(parameters, local, artifact_types, rules, repository)
        if artifact_types
        else {}
    )
    artifact = _artifact_state(parameters, repository, local, registries)
    api = _api_state(desired_state, fetched)
    observed_states = {
        "parameters": parameters,
        "api": api,
        "organization": organization,
        "repository": repository,
        "local": local,
        "registries": registries,
        "artifact": artifact,
        "repo": repository.get("repo", {}),
        "owner": repository.get("owner", {}),
        "type": repository.get("types", {}),
        "artifact_type": artifact_types,
        "artifact_type_system": artifact_types,
        "artifact_category": [
            category
            for category, members in {
                "github_packages": {
                    "github_packages_container",
                    "github_packages_npm",
                    "github_packages_maven",
                    "github_packages_gradle",
                    "github_packages_nuget",
                    "github_packages_rubygems",
                },
                "release_assets": {
                    "github_release_binary",
                    "generic_binary_archive",
                    "installer_or_cli_binary",
                },
            }.items()
            if set(artifact_types).intersection(members)
        ],
        "registry_hosts": artifact["registry_hosts"],
        "detected_external_artifact_count": artifact["external_count"],
        "audit_only": artifact["audit_only"],
        "publish_workflow_detected": artifact["publish_workflow_detected"],
        "workflow_emits_attestation_or_provenance": artifact["attestation_detected"],
        "workflow_contains_artifact_metadata_write": bool(
            local.get("workflows", {}).get("any_write", {}).get("artifact-metadata")
        ),
        "linked_artifacts_claimed": bool(parameters.get("linked_artifacts_claimed")),
        "artifact_was_published": bool(parameters.get("artifact_was_published")),
        "final_answer_makes_artifact_claim": bool(
            parameters.get("final_answer_makes_artifact_claim")
        ),
        "final_answer_makes_no_artifact_claim": bool(
            parameters.get("final_answer_makes_no_artifact_claim")
        ),
        "current_change_affects_artifact": bool(
            parameters.get("current_change_affects_artifact")
        ),
        "merged_change_requires_release": bool(
            parameters.get("merged_change_requires_release")
        ),
        "docker_build_push_action_default_provenance_applies": bool(
            parameters.get("docker_build_push_action_default_provenance_applies")
        ),
        "package_manifests_present": bool(
            set(repository.get("types", {}).get("language_or_iac", []))
        ),
        "local_repo_path": parameters.get("local_repo_path"),
        "expected_maintainer_bypass_actors": parameters.get(
            "expected_maintainer_bypass_actors", []
        ),
    }
    observed_states.update(
        {f"api.{check_id}.ok": value.get("ok") for check_id, value in api.items()}
    )
    for name, value in parameters.items():
        observed_states.setdefault(name, value)
    return observed_states
