"""Collect normalized GitHub repository facts from shared API responses."""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

from ..github_api import ApiResult, run_gh_api, run_json_command, substitute
from .local_repository import classify_repository


COLLECTION_KEYS = {
    "report_open_prs_older_than_days",
    "ignored_branch_names",
    "retained_branch_name_patterns",
    "draft_review_after_days",
    "prerelease_review_after_days",
    "required_asset_name_patterns",
}


def _result(
    fetched: dict[tuple[str, str], ApiResult],
    endpoint: str,
    parameters: dict[str, Any],
    method: str = "GET",
) -> ApiResult:
    resolved = str(substitute(endpoint, parameters))
    return fetched.get(
        (method.upper(), resolved),
        ApiResult(
            False, method.upper(), resolved, message="response was not collected"
        ),
    )


def _items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("items", "alerts", "repositories", "workflow_runs"):
            if isinstance(value.get(key), list):
                return value[key]
    return []


def _tree_paths(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return sorted(
        str(item["path"])
        for item in value.get("tree", [])
        if isinstance(item, dict) and item.get("type") == "blob" and item.get("path")
    )


def _parse_datetime(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _older_than(value: Any, days: int, now: dt.datetime | None = None) -> bool:
    parsed = _parse_datetime(value)
    if not parsed:
        return False
    current = now or dt.datetime.now(dt.timezone.utc)
    return current - parsed.astimezone(dt.timezone.utc) > dt.timedelta(days=days)


def _with_reason(item: dict[str, Any], reason: str) -> dict[str, Any]:
    return {**item, "stale_reason": reason}


def stale_pull_request_candidates(
    open_prs: list[Any], expected: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return old open PRs as factual stale candidates."""

    days = int(expected.get("report_open_prs_older_than_days", 30))
    return [
        _with_reason(item, f"open PR is older than {days} days")
        for item in open_prs
        if isinstance(item, dict) and _older_than(item.get("updated_at"), days)
    ]


def stale_branch_candidates(
    branches: list[Any],
    open_prs: list[Any],
    default_branch: str,
    expected: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return unprotected non-default branches without open PR heads."""

    ignored = set(expected.get("ignored_branch_names", []))
    retained_patterns = expected.get("retained_branch_name_patterns", [])
    heads = {
        str((item.get("head") or {}).get("ref"))
        for item in open_prs
        if isinstance(item, dict)
    }
    return [
        _with_reason(item, "non-default unprotected branch has no open pull request")
        for item in branches
        if isinstance(item, dict)
        and item.get("name") not in ignored | {default_branch}
        and not any(
            re.search(pattern, str(item.get("name"))) for pattern in retained_patterns
        )
        and item.get("protected") is not True
        and item.get("name") not in heads
    ]


def stale_tag_candidates(tags: list[Any], releases: list[Any]) -> list[dict[str, Any]]:
    """Return tags with no matching GitHub release."""

    released = {
        str(item.get("tag_name")) for item in releases if isinstance(item, dict)
    }
    return [
        _with_reason(item, "tag has no matching GitHub release")
        for item in tags
        if isinstance(item, dict) and str(item.get("name")) not in released
    ]


def stale_release_candidates(
    releases: list[Any], tags: list[Any], expected: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return draft, old prerelease, tag-mismatched, or incomplete release candidates."""

    tag_names = {str(item.get("name")) for item in tags if isinstance(item, dict)}
    draft_days = int(expected.get("draft_review_after_days", 7))
    prerelease_days = int(expected.get("prerelease_review_after_days", 30))
    required_patterns = expected.get("required_asset_name_patterns", [])
    result: list[dict[str, Any]] = []
    for item in releases:
        if not isinstance(item, dict):
            continue
        reasons: list[str] = []
        if item.get("draft") and _older_than(
            item.get("published_at") or item.get("created_at"), draft_days
        ):
            reasons.append(f"draft release older than {draft_days} days")
        if item.get("prerelease") and _older_than(
            item.get("published_at") or item.get("created_at"), prerelease_days
        ):
            reasons.append(f"prerelease older than {prerelease_days} days")
        tag = str(item.get("tag_name") or "")
        if tag and tag not in tag_names:
            reasons.append("release tag is missing from tag inventory")
        asset_names = [
            str(asset.get("name") or "")
            for asset in _items(item.get("assets"))
            if isinstance(asset, dict)
        ]
        missing = [
            pattern
            for pattern in required_patterns
            if not any(re.search(pattern, name) for name in asset_names)
        ]
        if missing:
            reasons.append(
                f"missing required release assets matching: {', '.join(missing)}"
            )
        if reasons:
            result.append(_with_reason(item, "; ".join(reasons)))
    return result


def _active_rulesets(value: Any) -> list[dict[str, Any]]:
    return [
        item
        for item in _items(value)
        if isinstance(item, dict)
        and item.get("target") == "branch"
        and item.get("enforcement") == "active"
    ]


def _ruleset_facts(
    active: list[dict[str, Any]], expected_actors: list[Any], default_branch: str
) -> dict[str, Any]:
    text = json.dumps(active, sort_keys=True)
    return {
        "active": active,
        "expected_actors_present": all(str(actor) in text for actor in expected_actors),
        "pull_request_only_visible": bool(
            re.search(r"pull[_-]?request", text, re.IGNORECASE)
        ),
        "default_branch_target_visible": bool(
            re.search(
                r"(~DEFAULT_BRANCH|refs/heads/|ref_name|"
                + re.escape(default_branch)
                + r")",
                text,
                re.IGNORECASE,
            )
        ),
        "enforcement_rule_visible": bool(
            re.search(
                r"(required_status_checks|pull_request|required_deployments)",
                text,
                re.IGNORECASE,
            )
        ),
    }


def _search_dependabot_prs(parameters: dict[str, Any]) -> ApiResult:
    slug = f"{parameters['owner']}/{parameters['repo']}"
    return run_json_command(
        [
            "gh",
            "search",
            "prs",
            "--repo",
            slug,
            "--state",
            "open",
            "--app",
            "dependabot",
            "--limit",
            "1000",
            "--json",
            "number,title,isDraft,url,updatedAt",
        ],
        f"dependabot PRs for {slug}",
    )


def _uses_state_path(rules: list[dict[str, Any]], prefix: str) -> bool:
    return any(
        str(assertion.get("path", "")).startswith(prefix)
        for rule in rules
        for assertion in rule.get("assertions", [])
    )


def collect_repository(
    fetched: dict[tuple[str, str], ApiResult],
    parameters: dict[str, Any],
    local: dict[str, Any],
    rules: list[dict[str, Any]],
    artifact_type_system: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one repository fact tree; no function dispatches on check IDs."""

    repo_response = _result(fetched, "/repos/${owner}/${repo}", parameters)
    repo = (
        repo_response.data
        if repo_response.ok and isinstance(repo_response.data, dict)
        else {}
    )
    default_branch = str(
        parameters.get("default_branch") or repo.get("default_branch") or ""
    )
    parameters["default_branch"] = default_branch
    owner_response = _result(fetched, "/orgs/${owner}", parameters)
    owner = (
        owner_response.data
        if owner_response.ok and isinstance(owner_response.data, dict)
        else {}
    )
    topics_response = _result(fetched, "/repos/${owner}/${repo}/topics", parameters)
    topics = (
        [str(item).lower() for item in (topics_response.data or {}).get("names", [])]
        if topics_response.ok and isinstance(topics_response.data, dict)
        else []
    )
    tree_response = _result(
        fetched,
        "/repos/${owner}/${repo}/git/trees/${default_branch}?recursive=1",
        parameters,
    )
    paths = local.get("files") or _tree_paths(tree_response.data)
    local_for_types = {**local, "files": paths}
    releases = _items(
        _result(
            fetched, "/repos/${owner}/${repo}/releases?per_page=100", parameters
        ).data
    )
    release_assets_count = sum(
        len(release.get("assets", []))
        for release in releases
        if isinstance(release, dict)
    )
    types = classify_repository(
        repo, local_for_types, topics, artifact_type_system, release_assets_count
    )

    protection = _result(
        fetched,
        "/repos/${owner}/${repo}/branches/${default_branch}/protection",
        parameters,
    )
    protection_data = (
        protection.data if protection.ok and isinstance(protection.data, dict) else {}
    )
    required_status_checks = protection_data.get("required_status_checks") or {}
    pull_request_reviews = protection_data.get("required_pull_request_reviews") or {}
    rulesets_response = _result(fetched, "/repos/${owner}/${repo}/rulesets", parameters)
    active_rulesets = _active_rulesets(rulesets_response.data)
    if active_rulesets and _uses_state_path(rules, "/repository/rulesets/"):
        details = []
        for ruleset in active_rulesets:
            ruleset_id = ruleset.get("id")
            if not ruleset_id:
                continue
            response = run_gh_api(
                "GET",
                f"/repos/{parameters['owner']}/{parameters['repo']}/rulesets/{ruleset_id}",
            )
            details.append(
                response.data
                if response.ok and isinstance(response.data, dict)
                else ruleset
            )
        active_rulesets = details or active_rulesets

    dependabot_prs = (
        _search_dependabot_prs(parameters)
        if _uses_state_path(rules, "/repository/security/dependabot_prs")
        else ApiResult(True, "CLI", "not requested", data=[])
    )
    dependabot_alerts = _items(
        _result(
            fetched,
            "/repos/${owner}/${repo}/dependabot/alerts?state=open&per_page=100",
            parameters,
        ).data
    )
    code_alerts = _items(
        _result(
            fetched,
            "/repos/${owner}/${repo}/code-scanning/alerts?state=open&per_page=100",
            parameters,
        ).data
    )
    secret_alerts = _items(
        _result(
            fetched,
            "/repos/${owner}/${repo}/secret-scanning/alerts?state=open&per_page=100",
            parameters,
        ).data
    )
    high_severities = {"critical", "high"}

    pulls = _items(
        _result(
            fetched, "/repos/${owner}/${repo}/pulls?state=open&per_page=100", parameters
        ).data
    )
    branches = _items(
        _result(
            fetched, "/repos/${owner}/${repo}/branches?per_page=100", parameters
        ).data
    )
    tags = _items(
        _result(fetched, "/repos/${owner}/${repo}/tags?per_page=100", parameters).data
    )
    detected_artifacts = set(types.get("artifact_surface", [])) - {"no_artifact"}
    detected_artifacts.update(
        str(item.get("artifact_type"))
        for item in parameters.get("artifact_contracts", [])
        if isinstance(item, dict) and item.get("artifact_type")
    )
    types["artifact_surface"] = sorted(detected_artifacts or {"no_artifact"})
    checks = {rule["id"]: rule for rule in rules}
    stale_expected = {
        key: checks.get(key, {}).get("collection", {})
        for key in (
            "stale_state.pull_requests",
            "stale_state.branches",
            "stale_state.releases",
        )
    }

    runs_response = _result(
        fetched,
        "/repos/${owner}/${repo}/actions/runs?branch=${default_branch}&per_page=20",
        parameters,
    )
    runs = _items(runs_response.data)
    relevant_runs = [
        item
        for item in runs
        if isinstance(item, dict)
        and item.get("status") == "completed"
        and item.get("conclusion") not in {"skipped", "neutral"}
    ]
    workflow_text = local.get("workflows", {}).get("text", "")
    dependabot_path = local.get("dependabot", {}).get("config_path")
    dependabot_text = (
        local.get("texts", {}).get(dependabot_path, "") if dependabot_path else ""
    )
    ecosystems = local.get("dependabot", {}).get("ecosystems", {})
    community = _result(
        fetched, "/repos/${owner}/${repo}/community/profile", parameters
    )
    community_data = (
        community.data if community.ok and isinstance(community.data, dict) else {}
    )
    codeowners = _result(
        fetched, "/repos/${owner}/${repo}/codeowners/errors", parameters
    )
    codeowners_errors = (
        codeowners.data.get("errors", [])
        if codeowners.ok and isinstance(codeowners.data, dict)
        else None
    )
    dependency_label = _result(
        fetched, "/repos/${owner}/${repo}/labels/dependencies", parameters
    )
    security_value = repo.get("security_and_analysis")
    security: dict[str, Any] = (
        security_value if isinstance(security_value, dict) else {}
    )
    security_settings: dict[str, Any] = {
        name: (
            security.get(name)
            if isinstance(security.get(name), dict)
            else {"status": None}
        )
        for name in (
            "dependency_graph",
            "dependabot_alerts",
            "secret_scanning",
            "secret_scanning_push_protection",
        )
    }
    security_settings.update(
        {
            name: value
            for name, value in security.items()
            if name not in security_settings
        }
    )
    default_setup = _result(
        fetched, "/repos/${owner}/${repo}/code-scanning/default-setup", parameters
    )
    private_reporting = _result(
        fetched, "/repos/${owner}/${repo}/private-vulnerability-reporting", parameters
    )
    dependency_review = _result(
        fetched,
        "/repos/${owner}/${repo}/dependency-graph/compare/${default_branch}...${default_branch}",
        parameters,
    )

    return {
        "repo": repo,
        "owner": owner,
        "topics": topics,
        "paths": paths,
        "types": types,
        "codeowners_present": any(
            path in paths
            for path in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
        ),
        "private_fork_enabled": bool(
            (
                _result(
                    fetched,
                    "/repos/${owner}/${repo}/actions/permissions/fork-pr-workflows-private-repos",
                    parameters,
                ).data
                or {}
            ).get("run_workflows_from_fork_pull_requests")
        ),
        "enforcement": {
            "classic_protection": protection.ok,
            "active_ruleset": bool(active_rulesets),
        },
        "protection": protection_data,
        "protection_facts": {
            "strict": required_status_checks.get("strict"),
            "required_checks": required_status_checks.get("checks")
            or required_status_checks.get("contexts")
            or [],
            "approving_reviews": pull_request_reviews.get(
                "required_approving_review_count"
            ),
            "dismiss_stale_reviews": pull_request_reviews.get("dismiss_stale_reviews"),
            "code_owner_reviews": pull_request_reviews.get(
                "require_code_owner_reviews"
            ),
            "conversation_resolution": (
                protection_data.get("required_conversation_resolution") or {}
            ).get("enabled"),
            "enforce_admins": (protection_data.get("enforce_admins") or {}).get(
                "enabled"
            ),
            "allow_force_pushes": (protection_data.get("allow_force_pushes") or {}).get(
                "enabled"
            ),
            "allow_deletions": (protection_data.get("allow_deletions") or {}).get(
                "enabled"
            ),
        },
        "rulesets": _ruleset_facts(
            active_rulesets,
            parameters.get("expected_maintainer_bypass_actors", []),
            default_branch,
        ),
        "actions": {
            "permissions": (
                _result(
                    fetched, "/repos/${owner}/${repo}/actions/permissions", parameters
                ).data
                or {}
            ),
            "workflow_permissions": (
                _result(
                    fetched,
                    "/repos/${owner}/${repo}/actions/permissions/workflow",
                    parameters,
                ).data
                or {}
            ),
            "retention": (
                _result(
                    fetched,
                    "/repos/${owner}/${repo}/actions/permissions/artifact-and-log-retention",
                    parameters,
                ).data
                or {}
            ),
            "fork_approval": (
                _result(
                    fetched,
                    "/repos/${owner}/${repo}/actions/permissions/fork-pr-contributor-approval",
                    parameters,
                ).data
                or {}
            ),
            "private_fork": (
                _result(
                    fetched,
                    "/repos/${owner}/${repo}/actions/permissions/fork-pr-workflows-private-repos",
                    parameters,
                ).data
                or {}
            ),
            "runs": {
                "available": runs_response.ok,
                "count": len(relevant_runs),
                "failed": [
                    item
                    for item in relevant_runs
                    if item.get("conclusion") != "success"
                ],
            },
        },
        "security": {
            "settings": security_settings,
            "vulnerability_alerts_enabled": _result(
                fetched, "/repos/${owner}/${repo}/vulnerability-alerts", parameters
            ).ok,
            "dependabot_security_updates_enabled": _result(
                fetched, "/repos/${owner}/${repo}/automated-security-fixes", parameters
            ).ok,
            "dependabot_alerts": {
                "all": dependabot_alerts,
                "high": [
                    item
                    for item in dependabot_alerts
                    if str(
                        ((item.get("security_advisory") or {}).get("severity"))
                    ).lower()
                    in high_severities
                ],
            },
            "dependabot_prs": {
                "available": dependabot_prs.ok,
                "items": dependabot_prs.data
                if isinstance(dependabot_prs.data, list)
                else [],
                "saturated": isinstance(dependabot_prs.data, list)
                and len(dependabot_prs.data) >= 1000,
            },
            "code_scanning_alerts": {
                "all": code_alerts,
                "high": [
                    item
                    for item in code_alerts
                    if str(
                        ((item.get("rule") or {}).get("security_severity_level"))
                    ).lower()
                    in high_severities
                ],
            },
            "secret_scanning_alerts": secret_alerts,
            "code_security_configuration_available": _result(
                fetched,
                "/repos/${owner}/${repo}/code-security-configuration",
                parameters,
            ).ok,
            "code_scanning": {
                "default_setup_configured": bool(
                    default_setup.ok
                    and isinstance(default_setup.data, dict)
                    and default_setup.data.get("state") == "configured"
                ),
                "custom_alerts_endpoint_available": _result(
                    fetched,
                    "/repos/${owner}/${repo}/code-scanning/alerts?state=open&per_page=100",
                    parameters,
                ).ok,
            },
            "private_vulnerability_reporting": {
                "api_enabled": bool(
                    private_reporting.ok
                    and isinstance(private_reporting.data, dict)
                    and private_reporting.data.get("enabled")
                ),
                "security_file_present": any(
                    path in paths for path in ("SECURITY.md", ".github/SECURITY.md")
                ),
            },
            "dependency_review_available": dependency_review.ok,
        },
        "content": {
            "community_profile_available": community.ok,
            "community_profile": community_data,
            "codeowners_errors_available": codeowners.ok,
            "codeowners_errors": codeowners_errors,
            "dependabot_label_referenced": "dependencies" in dependabot_text,
            "dependabot_label_exists": dependency_label.ok,
            "dependabot": {
                "config_present": bool(dependabot_path),
                "text_available": bool(dependabot_text),
                "ecosystems": sorted(ecosystems),
                "missing_ecosystems": [
                    name for name in ecosystems if name not in dependabot_text
                ],
                "updates_present": "updates:" in dependabot_text,
                "schedule_present": "schedule:" in dependabot_text
                and "interval:" in dependabot_text,
            },
            "workflow_write_all": local.get("workflows", {}).get(
                "permissions_write_all", []
            ),
            "workflow_text": workflow_text,
        },
        "stale": {
            "pull_requests": {
                "inventory": pulls,
                "candidates": stale_pull_request_candidates(
                    pulls, stale_expected["stale_state.pull_requests"]
                ),
            },
            "branches": {
                "inventory": branches,
                "candidates": stale_branch_candidates(
                    branches,
                    pulls,
                    default_branch,
                    stale_expected["stale_state.branches"],
                ),
            },
            "tags": {
                "inventory": tags,
                "candidates": stale_tag_candidates(tags, releases),
            },
            "releases": {
                "inventory": releases,
                "candidates": stale_release_candidates(
                    releases, tags, stale_expected["stale_state.releases"]
                ),
            },
        },
    }
