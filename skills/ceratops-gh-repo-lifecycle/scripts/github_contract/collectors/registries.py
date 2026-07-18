"""Collect read-only package and image registry metadata."""

from __future__ import annotations

import re
import urllib.parse
import urllib.error
import urllib.request
from typing import Any, Callable

from ..github_api import http_json, run_gh_api


def _record(
    fetch: Callable[[], Any], url: str, project: Callable[[Any], dict[str, Any]]
) -> dict[str, Any]:
    try:
        payload = fetch()
        return {"ok": True, "url": url, **project(payload)}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "url": url, "status": exc.code, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "url": url, "error": str(exc)}


def _pypi(name: str) -> dict[str, Any]:
    url = f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json"
    return _record(
        lambda: http_json(url),
        url,
        lambda data: {
            "name": data.get("info", {}).get("name"),
            "version": data.get("info", {}).get("version"),
            "files": data.get("urls", []),
        },
    )


def _npm(name: str) -> dict[str, Any]:
    url = f"https://registry.npmjs.org/{urllib.parse.quote(name, safe='@')}"
    return _record(
        lambda: http_json(url),
        url,
        lambda data: {
            "name": data.get("name"),
            "latest": data.get("dist-tags", {}).get("latest"),
            "dist_tags": data.get("dist-tags", {}),
        },
    )


def _dockerhub(name: str) -> dict[str, Any]:
    clean = (
        re.sub(r"^(?:(?:registry-1\.)?docker\.io/|hub\.docker\.com/)?", "", name)
        .split("@", 1)[0]
        .split(":", 1)[0]
    )
    namespace, repository = clean.split("/", 1) if "/" in clean else ("library", clean)
    repo_url = f"https://hub.docker.com/v2/namespaces/{urllib.parse.quote(namespace)}/repositories/{urllib.parse.quote(repository)}"
    tags_url = f"{repo_url}/tags?page_size=1&ordering=last_updated"
    return _record(
        lambda: (http_json(repo_url), http_json(tags_url)),
        f"https://hub.docker.com/r/{namespace}/{repository}",
        lambda values: {
            "name": clean,
            "description": values[0].get("description"),
            "last_updated": values[0].get("last_updated"),
            "latest_tag": (values[1].get("results") or [None])[0],
        },
    )


def _maven(name: str) -> dict[str, Any]:
    group, artifact = name.split(":", 1)
    query = urllib.parse.quote(f'g:"{group}" AND a:"{artifact}"')
    url = f"https://search.maven.org/solrsearch/select?q={query}&rows=1&wt=json"
    return _record(
        lambda: http_json(url),
        url,
        lambda data: {
            "coordinate": name,
            "results": data.get("response", {}).get("docs", []),
        },
    )


def _nuget(name: str) -> dict[str, Any]:
    url = f"https://api.nuget.org/v3-flatcontainer/{urllib.parse.quote(name.lower())}/index.json"
    return _record(
        lambda: http_json(url),
        url,
        lambda data: {"name": name, "versions": data.get("versions", [])},
    )


def _crates(name: str) -> dict[str, Any]:
    url = f"https://crates.io/api/v1/crates/{urllib.parse.quote(name)}"
    return _record(
        lambda: http_json(url),
        url,
        lambda data: {
            "name": name,
            "version": data.get("crate", {}).get("newest_version"),
        },
    )


def _rubygems(name: str) -> dict[str, Any]:
    url = f"https://rubygems.org/api/v1/gems/{urllib.parse.quote(name)}.json"
    return _record(
        lambda: http_json(url),
        url,
        lambda data: {"name": data.get("name"), "version": data.get("version")},
    )


def _powershell(name: str) -> dict[str, Any]:
    escaped = name.replace("'", "''")
    url = f"https://www.powershellgallery.com/api/v2/Packages?$filter=Id%20eq%20'{urllib.parse.quote(escaped)}'&$orderby=Version%20desc&$top=1"
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "ceratops-github-contract-validator"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
        return {"ok": True, "url": url, "name": name, "entry_present": "<entry" in body}
    except Exception as exc:
        return {"ok": False, "url": url, "name": name, "error": str(exc)}


FETCHERS: dict[str, tuple[str, Callable[[str], dict[str, Any]]]] = {
    "pypi_python_package": ("pypi", _pypi),
    "npm_package": ("npm", _npm),
    "docker_oci_image": ("dockerhub", _dockerhub),
    "maven_package": ("maven", _maven),
    "gradle_maven_package": ("maven", _maven),
    "nuget_package": ("nuget", _nuget),
    "crates_package": ("crates", _crates),
    "rubygems_package": ("rubygems", _rubygems),
    "powershell_gallery_module": ("powershell_gallery", _powershell),
}


def _manifest_identities(local: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    pypi = local.get("manifests", {}).get("pypi", {})
    pyproject = local.get("texts", {}).get("pyproject.toml", "")
    match = (
        re.search(r'(?m)^\s*name\s*=\s*["\']([^"\']+)', pyproject)
        if pypi.get("name_present")
        else None
    )
    if match:
        result["pypi_python_package"] = [match.group(1)]
    npm = local.get("manifests", {}).get("npm", {})
    if npm.get("name"):
        result["npm_package"] = [str(npm["name"])]
    return result


def collect_registries(
    parameters: dict[str, Any],
    local: dict[str, Any],
    artifact_types: list[str],
    rules: list[dict[str, Any]],
    repository: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch only selected, identified registry surfaces; never mutate them."""

    identities = _manifest_identities(local)
    explicit_registries: dict[tuple[str, str], str] = {}
    for item in parameters.get("artifact_contracts", []):
        if not isinstance(item, dict):
            continue
        artifact_type = str(item.get("artifact_type") or "")
        name = item.get("package_or_image_name") or item.get("name")
        if artifact_type and name:
            identity = str(name)
            identities.setdefault(artifact_type, []).append(identity)
            explicit_registries[(artifact_type, identity)] = str(
                item.get("registry") or ""
            ).lower()
    needed_paths = {
        str(assertion.get("path", ""))
        for rule in rules
        for assertion in rule.get("assertions", [])
    }
    live_metadata_needed = "/artifact/live_metadata/all_resolved" in needed_paths
    state: dict[str, Any] = {name: {} for name, _fetcher in FETCHERS.values()}
    for artifact_type in artifact_types:
        if artifact_type not in FETCHERS:
            continue
        registry, fetcher = FETCHERS[artifact_type]
        if not live_metadata_needed and not any(
            path.startswith(f"/registries/{registry}") for path in needed_paths
        ):
            continue
        for name in sorted(set(identities.get(artifact_type, []))):
            if artifact_type == "docker_oci_image":
                registry_host = explicit_registries.get((artifact_type, name), "")
                if registry_host not in {
                    "docker.io",
                    "hub.docker.com",
                    "registry-1.docker.io",
                    "dockerhub",
                }:
                    continue
            state[registry][name] = fetcher(name)
    for registry, values in state.items():
        state[registry] = {
            "packages": values,
            "identity_count": len(values),
            "failed": [
                name for name, metadata in values.items() if not metadata.get("ok")
            ],
            "all_resolved": bool(values)
            and all(metadata.get("ok") for metadata in values.values()),
        }
    github_types = {
        "github_container_registry_image": "container",
        "github_packages_container": "container",
        "github_packages_npm": "npm",
        "github_packages_maven": "maven",
        "github_packages_gradle": "maven",
        "github_packages_nuget": "nuget",
        "github_packages_rubygems": "rubygems",
    }
    package_types = {
        github_types[item] for item in artifact_types if item in github_types
    }
    github_identities: dict[str, set[str]] = {}
    for (artifact_type, name), registry_host in explicit_registries.items():
        if registry_host == "ghcr.io":
            package_types.add("container")
            github_identities.setdefault("container", set()).add(name)
        elif (
            registry_host in {"github", "github_packages"}
            and artifact_type in github_types
        ):
            package_types.add(github_types[artifact_type])
            github_identities.setdefault(github_types[artifact_type], set()).add(name)
        elif (
            registry_host.endswith(".pkg.github.com") and artifact_type in github_types
        ):
            package_types.add(github_types[artifact_type])
            github_identities.setdefault(github_types[artifact_type], set()).add(name)
    github_results: list[dict[str, Any]] = []
    github_packages: dict[str, dict[str, Any]] = {}
    queried_package_types = (
        sorted(package_types)
        if package_types
        and (
            live_metadata_needed
            or any(
                path.startswith("/registries/github_packages") for path in needed_paths
            )
        )
        else []
    )
    if queried_package_types:
        owner_kind = str(
            ((repository or {}).get("repo", {}).get("owner") or {}).get("type") or ""
        ).lower()
        owner_route = "orgs" if owner_kind == "organization" else "users"
        for package_type in queried_package_types:
            response = run_gh_api(
                "GET",
                f"/{owner_route}/{parameters['owner']}/packages?package_type={package_type}",
            )
            state_result = response.state()
            github_results.append(state_result)
            available = {
                str(item.get("name"))
                for item in response.data or []
                if isinstance(item, dict) and item.get("name")
            }
            expected = {
                re.sub(
                    rf"^(?:ghcr\.io/)?(?:{re.escape(str(parameters['owner']))}/)?",
                    "",
                    name,
                    flags=re.IGNORECASE,
                )
                .split("@", 1)[0]
                .split(":", 1)[0]
                for name in github_identities.get(package_type, set())
            }
            github_packages[package_type] = {
                "ok": response.ok and bool(expected) and expected.issubset(available),
                "endpoint": response.endpoint,
                "status": response.status,
                "message": response.message,
                "expected_names": sorted(expected),
                "available_names": sorted(available),
            }
    state["github_packages"] = {
        "packages": github_packages,
        "responses": github_results,
        "identity_count": sum(
            len(item.get("expected_names", [])) for item in github_packages.values()
        ),
        "all_resolved": bool(github_packages)
        and all(item.get("ok") for item in github_packages.values()),
    }
    return state
