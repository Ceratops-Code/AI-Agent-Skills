"""Compact machine and human reporting for GitHub contract validators."""

from __future__ import annotations

import json
from typing import Any

from validator_levels import count_by_level


def _compact(value: Any, limit: int = 5) -> Any:
    if isinstance(value, list):
        return {"count": len(value), "sample": value[:limit]}
    if isinstance(value, dict) and len(json.dumps(value, default=str)) > 1000:
        keys = sorted(value)
        return {"keys": keys, "sample": {key: value[key] for key in keys[:limit]}}
    return value


def compact_finding(finding: dict[str, Any], limit: int = 5) -> dict[str, Any]:
    """Bound evidence size while preserving the actionable comparison."""

    return {
        key: (
            _compact(value, limit)
            if key in {"actual", "expected", "source_error"}
            else value
        )
        for key, value in finding.items()
        if key
        in {
            "level",
            "check_id",
            "path",
            "message",
            "actual",
            "expected",
            "kind",
            "source_error",
            "approved_by",
        }
    }


def _inventory_sample(name: str, value: Any) -> Any:
    """Project large GitHub objects to stable identity and stale-review fields."""

    if not isinstance(value, dict):
        return value
    fields = {
        "pull_requests": ("number", "title", "draft", "updated_at", "html_url"),
        "branches": ("name", "protected", "stale_reason"),
        "tags": ("name", "stale_reason"),
        "releases": (
            "tag_name",
            "name",
            "draft",
            "prerelease",
            "published_at",
            "html_url",
            "stale_reason",
        ),
    }.get(name, tuple(value))
    result = {key: value[key] for key in fields if key in value}
    if name == "releases" and isinstance(value.get("assets"), list):
        result["asset_names"] = [
            str(item.get("name"))
            for item in value["assets"]
            if isinstance(item, dict) and item.get("name")
        ]
    return result


def _stale_inventory(observed_states: dict[str, Any], limit: int = 5) -> dict[str, Any]:
    stale = observed_states.get("repository", {}).get("stale", {})
    local_matches = (
        observed_states.get("local", {})
        .get("scans", {})
        .get("stale_state.local_path_references", {})
        .get("matches", [])
    )
    result = {
        name: {
            "count": len(value.get("inventory", [])),
            "sample": [
                _inventory_sample(name, item)
                for item in value.get("inventory", [])[:limit]
            ],
        }
        for name, value in stale.items()
    }
    if local_matches or "stale_state.local_path_references" in observed_states.get(
        "local", {}
    ).get("scans", {}):
        result["local_path_references"] = {
            "count": len(local_matches),
            "sample": local_matches[:limit],
        }
    return result


def build_report(
    desired_state: dict[str, Any],
    observed_states: dict[str, Any],
    comparison: dict[str, Any],
    *,
    applied: list[dict[str, Any]] | None = None,
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose the full machine-readable report."""

    findings = comparison["findings"]
    approved = comparison["approved_drift"]
    return {
        "target": desired_state["parameters"].get("org_login")
        or f"{desired_state['parameters'].get('owner')}/{desired_state['parameters'].get('repo')}",
        "contract_paths": desired_state["contract_paths"],
        "selection": selection or {},
        "selected_check_ids": sorted(rule["id"] for rule in desired_state["rules"]),
        "selected_counts": {
            surface: len(ids) for surface, ids in desired_state["selected_ids"].items()
        },
        "result_counts": count_by_level(findings + approved),
        "applied": applied or [],
        "approved_drift": approved,
        "findings": findings,
        "observed_states": observed_states,
    }


def build_summary_report(
    report: dict[str, Any], levels: list[str], *, sample_limit: int = 5
) -> dict[str, Any]:
    """Return the credit-efficient report used by default automation paths."""

    selected = set(levels)
    return {
        "target": report["target"],
        "selection": report["selection"],
        "levels": levels,
        "result_counts": report["result_counts"],
        "selected_counts": report["selected_counts"],
        "findings": [
            compact_finding(item, sample_limit)
            for item in report["findings"]
            if item.get("level") in selected
        ],
        "approved_drift": [
            compact_finding(item, sample_limit)
            for item in report["approved_drift"]
            if item.get("level") in selected
        ],
        "stale_state_inventory": _stale_inventory(
            report["observed_states"], sample_limit
        ),
        "local_scan": {
            key: report["observed_states"].get("local", {}).get(key)
            for key in ("available", "root", "errors")
        },
    }


def print_human(report: dict[str, Any], levels: list[str]) -> None:
    """Print only selected findings and compact counts."""

    summary = build_summary_report(report, levels)
    print(f"Target: {report['target']}")
    print(
        f"Selected checks: {sum(report['selected_counts'].values())}; result counts: {report['result_counts']}"
    )
    if report["applied"]:
        print("Applied:")
        for item in report["applied"]:
            print(f"  {item['check_id']}: {'ok' if item.get('ok') else 'failed'}")
    if summary["findings"]:
        print("Findings:")
        for item in summary["findings"][:80]:
            print(
                f"  {item['level']} {item['check_id']} {item.get('path', '/')}: {item['message']}"
            )
