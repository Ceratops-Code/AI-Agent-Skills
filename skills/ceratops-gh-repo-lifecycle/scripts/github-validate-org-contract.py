#!/usr/bin/env python3
"""
Check and optionally remediate a GitHub organization contract.

Design notes for maintainers:

* The JSON contract is the source of truth. This script should stay generic
  enough to evaluate contract-declared API checks without baking Ceratops
  policy into Python unless the comparison needs custom interpretation.
* The script deliberately uses the GitHub CLI (`gh api`) instead of managing
  tokens itself. Auth, SSO, host selection, and enterprise details stay in the
  user's normal GitHub CLI configuration.
* Read operations are bundled before comparison so one run can reuse the same
  evidence across many checks. Apply mode is intentionally narrow and only
  touches checks listed in the contract's `auto_apply_check_ids`.
* Subset, check-id, and fetch-bundle filters let explicit audits check only the
  relevant org surface without invoking one command per setting.
* Destructive, irreversible, paid, or identity-sensitive settings are never
  fixed automatically here; they are reported as drift that needs review.

Called by org health audits, organization setup checks, and standards-governance
reviews when the task needs current organization settings in one bundled run.
It is not called after every successful `gh api` setting command; command
success is already evidence for that exact mutation unless broader drift needs
an audit.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import struct
import subprocess
import sys
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Any


API_VERSION = "2026-03-10"
PARAM_RE = re.compile(r"\$\{([^}]+)\}")
FORK_PR_APPROVAL_RANK = {
    "first_time_contributors_new_to_github": 0,
    "first_time_contributors": 1,
    "all_external_contributors": 2,
}


@dataclass
class ApiResult:
    """Normalized wrapper for a GitHub API request.

    Keeping failures and successful JSON responses in one object makes the
    comparison layer deterministic: every check sees the status, parsed data,
    and raw command output instead of handling subprocess details itself.
    """

    ok: bool
    method: str
    endpoint: str
    data: Any = None
    status: int | None = None
    message: str | None = None
    raw_stdout: str = ""
    raw_stderr: str = ""


def load_json(path: str) -> Any:
    """Load an org contract, fetch bundle, or JSON API payload."""

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def default_contract_path(filename: str) -> str:
    """Find bundled org contracts in source and installed skill layouts."""

    script_dir = pathlib.Path(__file__).resolve().parent
    skill_dir = script_dir.parent
    repo_root = skill_dir.parent.parent if skill_dir.parent.name == "skills" else skill_dir
    candidates = [
        pathlib.Path.cwd() / filename,
        pathlib.Path.cwd() / "skills" / "ceratops-gh-repo-lifecycle" / "references" / filename,
        repo_root / "skills" / "ceratops-gh-repo-lifecycle" / "references" / filename,
        skill_dir / "references" / filename,
        script_dir / filename,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return filename


def all_check_ids(contract: dict[str, Any]) -> set[str]:
    """Return the deterministic check IDs declared by the org contract."""

    return {str(check.get("id")) for check in contract.get("checks", []) if check.get("id")}


def subset_check_ids(contract: dict[str, Any], subset: str) -> set[str] | None:
    """Map workflow subsets to org contract checks.

    `None` means every org check. Subsets are intentionally prefix-based so the
    JSON contract remains the policy source of truth and Python only narrows the
    selected evidence surface.
    """

    ids = all_check_ids(contract)
    if subset == "all":
        return None
    prefixes = {
        "settings": ("org.", "organization.", "custom_properties."),
        "actions": ("actions.",),
        "dependabot": ("dependabot.",),
        "security": ("code_security.", "dependabot.", "private_registries."),
    }[subset]
    return {check_id for check_id in ids if check_id.startswith(prefixes)}


def selected_contract_checks(contract: dict[str, Any], selected_ids: set[str] | None) -> list[dict[str, Any]]:
    """Return checks matching the current selection."""

    checks = contract.get("checks", [])
    if selected_ids is None:
        return checks
    return [check for check in checks if check.get("id") in selected_ids]


def selected_ids_for_report(contract: dict[str, Any], selected_ids: set[str] | None) -> set[str]:
    """Return concrete selected check IDs for structured output."""

    return all_check_ids(contract) if selected_ids is None else set(selected_ids)


def apply_explicit_check_ids(contract: dict[str, Any], requested: list[str] | None, selected_ids: set[str] | None) -> set[str] | None:
    """Restrict subset selection to explicit check IDs from `--check-id`."""

    if not requested:
        return selected_ids
    known = all_check_ids(contract)
    unknown = sorted(set(requested) - known)
    if unknown:
        raise SystemExit(f"Unknown check id(s): {', '.join(unknown)}")
    requested_set = set(requested)
    filtered = requested_set if selected_ids is None else requested_set & selected_ids
    excluded = requested_set - filtered
    if excluded:
        raise SystemExit(f"Check id(s) excluded by current --subset: {', '.join(sorted(excluded))}")
    return filtered


def canonical(value: Any) -> str:
    """Return stable JSON for equality checks and compact diagnostics."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def substitute(value: Any, params: dict[str, Any]) -> Any:
    """Replace `${param}` placeholders anywhere in a JSON-compatible value."""
    if isinstance(value, str):
        match = PARAM_RE.fullmatch(value)
        if match:
            return params.get(match.group(1), value)
        return PARAM_RE.sub(lambda m: str(params.get(m.group(1), m.group(0))), value)
    if isinstance(value, list):
        return [substitute(item, params) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, params) for key, item in value.items()}
    return value


def endpoint_for(endpoint: str, params: dict[str, Any]) -> str:
    """Resolve an endpoint template using the active org parameters."""

    return substitute(endpoint, params)


def parse_error(stdout: str, stderr: str) -> tuple[int | None, str]:
    """Extract the most useful HTTP status/message from a failed `gh api` run."""
    text = "\n".join(part for part in [stdout, stderr] if part)
    for candidate in [stdout, stderr, text]:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        status = obj.get("status")
        try:
            status_int = int(status) if status is not None else None
        except (TypeError, ValueError):
            status_int = None
        message_parts = [str(obj.get("message") or "")]
        if obj.get("errors"):
            message_parts.append(str(obj.get("errors")))
        return status_int, " ".join(part for part in message_parts if part) or candidate
    status_match = re.search(r"HTTP (\d{3})", text)
    status = int(status_match.group(1)) if status_match else None
    return status, text.strip()


def run_gh_api(
    method: str,
    endpoint: str,
    body: Any | None = None,
    paginate: bool = False,
) -> ApiResult:
    """Run `gh api` and parse the JSON response or structured API error.

    `--paginate --slurp` returns a list of pages for many endpoints. When every
    page is itself a list, the result is flattened because contract checks care
    about the complete collection, not page boundaries.
    """
    cmd = [
        "gh",
        "api",
        "-H",
        f"X-GitHub-Api-Version: {API_VERSION}",
    ]
    if method.upper() != "GET":
        cmd.extend(["-X", method.upper()])
    if paginate:
        cmd.extend(["--paginate", "--slurp"])
    if body is not None:
        cmd.extend(["--input", "-"])
    cmd.append(endpoint)
    proc = subprocess.run(
        cmd,
        input=json.dumps(body) if body is not None else None,
        text=True,
        capture_output=True,
    )
    if proc.returncode == 0:
        text = proc.stdout.strip()
        if not text:
            data = None
        else:
            data = json.loads(text)
            if paginate and isinstance(data, list):
                if all(isinstance(page, list) for page in data):
                    merged: list[Any] = []
                    for page in data:
                        merged.extend(page)
                    data = merged
        return ApiResult(True, method.upper(), endpoint, data=data, raw_stdout=proc.stdout, raw_stderr=proc.stderr)
    status, message = parse_error(proc.stdout, proc.stderr)
    return ApiResult(
        False,
        method.upper(),
        endpoint,
        status=status,
        message=message,
        raw_stdout=proc.stdout,
        raw_stderr=proc.stderr,
    )


def object_subset(actual: Any, expected: Any) -> Any:
    """Project an API response down to the fields named by the expected shape."""
    if isinstance(expected, dict):
        actual_dict = actual if isinstance(actual, dict) else {}
        return {key: object_subset(actual_dict.get(key), expected_value) for key, expected_value in expected.items()}
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return actual
        if not expected:
            return actual
        keys: set[str] = set()
        for item in expected:
            if isinstance(item, dict):
                keys.update(item.keys())
        if not keys:
            return actual
        return [{key: object_subset(item.get(key) if isinstance(item, dict) else None, _expected_for_key(expected, key)) for key in sorted(keys)} for item in actual]
    return actual


def _expected_for_key(expected_list: list[Any], key: str) -> Any:
    """Find the expected object from a contract list by stable key/name."""

    for item in expected_list:
        if isinstance(item, dict) and key in item:
            return item[key]
    return None


def normalize_for_compare(value: Any) -> Any:
    """Normalize nested JSON before comparing expected and actual values."""

    if isinstance(value, list):
        return sorted((normalize_for_compare(item) for item in value), key=canonical)
    if isinstance(value, dict):
        return {key: normalize_for_compare(value[key]) for key in sorted(value.keys())}
    return value


def diff_values(actual: Any, expected: Any, path: str = "$") -> list[dict[str, Any]]:
    """Return stable, path-addressed drift entries between two JSON values."""
    actual_n = normalize_for_compare(actual)
    expected_n = normalize_for_compare(expected)
    if actual_n == expected_n:
        return []
    if isinstance(actual_n, dict) and isinstance(expected_n, dict):
        diffs: list[dict[str, Any]] = []
        for key in sorted(set(actual_n.keys()) | set(expected_n.keys())):
            diffs.extend(diff_values(actual_n.get(key), expected_n.get(key), f"{path}.{key}"))
        return diffs
    return [{"path": path, "expected": expected_n, "actual": actual_n}]


def error_matches(result: ApiResult, expected: dict[str, Any]) -> bool:
    """Check whether a failed endpoint matches a contract-declared error."""

    expected_status = expected.get("status")
    if expected_status is not None and result.status != expected_status:
        return False
    needle = expected.get("message_contains")
    if needle and needle not in (result.message or ""):
        return False
    return True


def retention_days_drifts(check_id: str, data: Any, expected: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare Actions artifact/log retention against a contract max-days policy."""
    max_days = expected.get("max_days")
    days = data.get("days") if isinstance(data, dict) else None
    if isinstance(days, int) and isinstance(max_days, int) and days <= max_days:
        return []
    return [
        {
            "check_id": check_id,
            "path": "$.days",
            "expected": f"<= {max_days}",
            "actual": days,
            "message": "Actions artifact and log retention exceeds policy.",
        }
    ]


def fork_pr_approval_drifts(check_id: str, data: Any, expected: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare fork-PR approval policy by minimum strictness."""
    actual = data.get("approval_policy") if isinstance(data, dict) else None
    minimum = expected.get("minimum_approval_policy")
    allowed = set(expected.get("allowed_policies") or [])
    actual_rank = FORK_PR_APPROVAL_RANK.get(str(actual))
    minimum_rank = FORK_PR_APPROVAL_RANK.get(str(minimum))
    if actual in allowed or (
        actual_rank is not None and minimum_rank is not None and actual_rank >= minimum_rank
    ):
        return []
    return [
        {
            "check_id": check_id,
            "path": "$.approval_policy",
            "expected": minimum,
            "actual": actual,
            "message": "Fork PR contributor approval policy is weaker than required.",
        }
    ]


def png_unique_rgba_colors(data: bytes) -> int:
    """Count unique PNG colors without external imaging dependencies.

    GitHub generated avatars are simple identicons, while the required Ceratops
    logo is a custom upload. The contract can use this helper either as an exact
    hash check or as a fallback generated-avatar detector.
    """
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG")

    pos = 8
    width = height = bit_depth = color_type = interlace = None
    palette: list[tuple[int, int, int, int]] = []
    transparency: bytes | None = None
    idat = bytearray()

    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        chunk_type = data[pos + 4 : pos + 8]
        chunk_data = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", chunk_data)
        elif chunk_type == b"PLTE":
            palette = [(chunk_data[i], chunk_data[i + 1], chunk_data[i + 2], 255) for i in range(0, len(chunk_data), 3)]
        elif chunk_type == b"tRNS":
            transparency = chunk_data
        elif chunk_type == b"IDAT":
            idat.extend(chunk_data)
        elif chunk_type == b"IEND":
            break

    if width is None or height is None or bit_depth != 8 or interlace != 0:
        raise ValueError("unsupported PNG format")
    if color_type not in (0, 2, 3, 4, 6):
        raise ValueError("unsupported PNG color type")

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    bpp = channels
    row_len = width * channels
    raw = zlib.decompress(bytes(idat))
    prev = bytearray(row_len)
    offset = 0
    colors: set[tuple[int, int, int, int]] = set()

    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        row = bytearray(raw[offset : offset + row_len])
        offset += row_len
        for i in range(row_len):
            left = row[i - bpp] if i >= bpp else 0
            up = prev[i]
            up_left = prev[i - bpp] if i >= bpp else 0
            if filter_type == 1:
                row[i] = (row[i] + left) & 0xFF
            elif filter_type == 2:
                row[i] = (row[i] + up) & 0xFF
            elif filter_type == 3:
                row[i] = (row[i] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                row[i] = (row[i] + paeth(left, up, up_left)) & 0xFF
            elif filter_type != 0:
                raise ValueError("unsupported PNG filter")

        for x in range(width):
            idx = x * channels
            if color_type == 0:
                g = row[idx]
                rgba = (g, g, g, 255)
            elif color_type == 2:
                rgba = (row[idx], row[idx + 1], row[idx + 2], 255)
            elif color_type == 3:
                rgba = palette[row[idx]]
                if transparency and row[idx] < len(transparency):
                    rgba = (rgba[0], rgba[1], rgba[2], transparency[row[idx]])
            elif color_type == 4:
                g = row[idx]
                rgba = (g, g, g, row[idx + 1])
            else:
                rgba = (row[idx], row[idx + 1], row[idx + 2], row[idx + 3])
            colors.add(rgba)
        prev = row

    return len(colors)


def paeth(a: int, b: int, c: int) -> int:
    """Return the PNG Paeth predictor used while decoding logo pixels."""

    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def verify_logo(check: dict[str, Any], org_data: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Fetch the live org avatar and compare it to the contract verifier."""
    expected = check.get("expected", {})
    avatar_url = org_data.get("avatar_url")
    if not avatar_url:
        return False, {"reason": "missing avatar_url"}
    req = urllib.request.Request(avatar_url, headers={"User-Agent": "github-org-contract-checker"})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = response.read()
        content_type = response.headers.get("Content-Type")
    sha256 = hashlib.sha256(data).hexdigest().upper()
    evidence = {
        "avatar_url": avatar_url,
        "content_type": content_type,
        "bytes": len(data),
        "sha256": sha256,
    }
    if expected.get("sha256"):
        passed = True
        if expected.get("content_type") and content_type != expected["content_type"]:
            passed = False
        if expected.get("bytes") is not None and len(data) != expected["bytes"]:
            passed = False
        if sha256 != str(expected["sha256"]).upper():
            passed = False
        return passed, evidence

    detector = check.get("verifier", {}).get("image_detector", {})
    unique_colors = png_unique_rgba_colors(data)
    evidence["unique_rgba_colors"] = unique_colors
    evidence["max_bytes"] = detector.get("max_bytes")
    evidence["max_unique_rgba_colors"] = detector.get("max_unique_rgba_colors")
    passed = True
    if detector.get("content_type") and content_type != detector["content_type"]:
        passed = False
    if detector.get("max_bytes") is not None and len(data) > detector["max_bytes"]:
        passed = False
    if detector.get("max_unique_rgba_colors") is not None and unique_colors > detector["max_unique_rgba_colors"]:
        passed = False
    return passed, evidence


def check_matches_exclusion(rule: dict[str, Any], check_id: str, org: str) -> bool:
    """Return whether an approved drift rule applies to one org check."""

    ids = rule.get("check_id", rule.get("check_ids", "*"))
    if ids != "*" and check_id not in (ids if isinstance(ids, list) else [ids]):
        return False
    orgs = rule.get("orgs")
    if orgs and org not in (orgs if isinstance(orgs, list) else [orgs]):
        return False
    expires = rule.get("expires_on")
    if expires and dt.date.fromisoformat(expires) < dt.date.today():
        return False
    return True


def apply_approved_drift(
    drifts: list[dict[str, Any]],
    contract: dict[str, Any],
    org: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split raw drift into unapproved and contract-approved drift buckets."""
    policy = contract.get("approved_drift", {})
    allowances = policy.get("allowances", [])
    approved: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    for drift in drifts:
        matched = False
        for rule in allowances:
            if not check_matches_exclusion(rule, drift["check_id"], org):
                continue
            if rule.get("path") not in (None, "*", drift.get("path")):
                continue
            if "actual" in rule and normalize_for_compare(rule["actual"]) != normalize_for_compare(drift.get("actual")):
                continue
            if "value" in rule and normalize_for_compare(rule["value"]) != normalize_for_compare(drift.get("actual")):
                continue
            matched = True
            drift = dict(drift)
            drift["approved_by"] = rule.get("id", rule.get("reason", "approved_drift"))
            approved.append(drift)
            break
        if not matched:
            remaining.append(drift)
    return remaining, approved


def compare_check(
    check: dict[str, Any],
    result: ApiResult,
    params: dict[str, Any],
    fetched: dict[tuple[str, str], ApiResult],
) -> list[dict[str, Any]]:
    """Evaluate one contract check against its fetched evidence.

    Most checks are pure JSON comparisons. A few comparisons need custom logic
    because the API shape is an inventory rather than a setting: logo image
    verification, allowed uninitialized errors, and Dependabot queue posture.
    """
    check_id = check["id"]
    expected = substitute(check.get("expected"), params)
    comparison = check.get("comparison")

    if comparison == "custom_verifier":
        org_endpoint = endpoint_for("/orgs/${org_login}", params)
        org_result = fetched.get(("GET", org_endpoint))
        if not org_result or not org_result.ok:
            return [{"check_id": check_id, "path": "$", "expected": expected, "actual": "missing org data", "message": "cannot verify logo"}]
        try:
            ok, evidence = verify_logo(check, org_result.data)
        except Exception as exc:
            return [{"check_id": check_id, "path": "$", "expected": expected, "actual": str(exc), "message": "logo verifier failed"}]
        return [] if ok else [{"check_id": check_id, "path": "$", "expected": expected, "actual": evidence, "message": "logo mismatch"}]

    if comparison == "expected_error":
        if result.ok:
            return [{"check_id": check_id, "path": "$", "expected": expected, "actual": result.data, "message": "expected API error but request succeeded"}]
        if error_matches(result, expected):
            return []
        return [{"check_id": check_id, "path": "$", "expected": expected, "actual": {"status": result.status, "message": result.message}, "message": "API error did not match expected state"}]

    if comparison == "selected_fields_equal_or_expected_error_when_uninitialized":
        if not result.ok:
            allowed = check.get("allowed_uninitialized_error", {})
            org_endpoint = endpoint_for("/orgs/${org_login}", params)
            org_result = fetched.get(("GET", org_endpoint))
            public_repos = org_result.data.get("public_repos") if org_result and org_result.ok else None
            if allowed and error_matches(result, allowed) and public_repos == allowed.get("only_when_public_repos_count"):
                return []
            return [{"check_id": check_id, "path": "$", "expected": expected, "actual": {"status": result.status, "message": result.message}, "message": "API error did not match allowed uninitialized state"}]
        actual_subset = object_subset(result.data, expected)
        return [{"check_id": check_id, **drift} for drift in diff_values(actual_subset, expected)]

    if not result.ok:
        return [{"check_id": check_id, "path": "$", "expected": expected, "actual": {"status": result.status, "message": result.message}, "message": "request failed"}]

    if comparison == "dependabot_org_alert_queue_policy":
        alerts = result.data if isinstance(result.data, list) else []
        max_open = int(expected.get("max_open_alerts", 0)) if isinstance(expected, dict) else 0
        if len(alerts) > max_open:
            compact = [
                {
                    "repo": ((item.get("repository") or {}).get("full_name") if isinstance(item, dict) else None),
                    "number": item.get("number") if isinstance(item, dict) else None,
                    "severity": ((item.get("security_advisory") or {}).get("severity") if isinstance(item, dict) else None),
                    "url": item.get("html_url") if isinstance(item, dict) else None,
                }
                for item in alerts[:25]
            ]
            return [
                {
                    "check_id": check_id,
                    "path": "$.open_dependabot_alerts",
                    "expected": f"<= {max_open}",
                    "actual": {"count": len(alerts), "sample": compact},
                    "message": "open org Dependabot alert queue is not empty",
                }
            ]
        return []

    if comparison == "dependabot_org_pr_queue_policy":
        total = result.data.get("total_count") if isinstance(result.data, dict) else None
        items_obj = result.data.get("items") if isinstance(result.data, dict) else []
        items = items_obj if isinstance(items_obj, list) else []
        max_open = int(expected.get("max_open_dependabot_prs", 0)) if isinstance(expected, dict) else 0
        if isinstance(total, int) and total > max_open:
            compact = []
            for item in items[:25]:
                if not isinstance(item, dict):
                    compact.append({"repo": None, "number": None, "title": None, "url": None, "updated_at": None})
                    continue
                repository_url = item.get("repository_url", "")
                compact.append(
                    {
                        "repo": repository_url.rsplit("/repos/", 1)[-1] if isinstance(repository_url, str) else None,
                        "number": item.get("number"),
                        "title": item.get("title"),
                        "url": item.get("html_url"),
                        "updated_at": item.get("updated_at"),
                    }
                )
            return [
                {
                    "check_id": check_id,
                    "path": "$.open_dependabot_prs",
                    "expected": f"<= {max_open}",
                    "actual": {"count": total, "sample": compact},
                    "message": "open org Dependabot PR queue is not empty",
                }
            ]
        return []

    if comparison == "retention_days_policy":
        return retention_days_drifts(check_id, result.data, expected)
    if comparison == "fork_pr_contributor_approval_policy":
        return fork_pr_approval_drifts(check_id, result.data, expected)
    if comparison == "selected_fields_equal":
        actual_subset = object_subset(result.data, expected)
        return [{"check_id": check_id, **drift} for drift in diff_values(actual_subset, expected)]
    if comparison in ("object_equal", "array_equal"):
        return [{"check_id": check_id, **drift} for drift in diff_values(result.data, expected)]
    if comparison == "contains_matching_object":
        if not isinstance(result.data, list):
            return [{"check_id": check_id, "path": "$", "expected": expected, "actual": result.data, "message": "actual response is not a list"}]
        for item in result.data:
            if normalize_for_compare(object_subset(item, expected)) == normalize_for_compare(expected):
                return []
        return [{"check_id": check_id, "path": "$", "expected": expected, "actual": result.data, "message": "no matching object found"}]
    return [{"check_id": check_id, "path": "$", "expected": expected, "actual": None, "message": f"unsupported comparison {comparison}"}]


def request_covers_selected(
    bundle: dict[str, Any],
    req: dict[str, Any],
    selected_check_ids: set[str] | None,
    selected_bundle_ids: set[str] | None,
) -> bool:
    """Decide whether one fetch-bundle request is needed for this run."""

    if selected_bundle_ids is not None and bundle.get("id") not in selected_bundle_ids:
        return False
    if selected_check_ids is None:
        return True
    covers = set(req.get("covers_checks") or bundle.get("covers_checks") or [])
    return not covers or bool(covers & selected_check_ids)


def fetch_contract(
    contract: dict[str, Any],
    params: dict[str, Any],
    selected_check_ids: set[str] | None = None,
    selected_bundle_ids: set[str] | None = None,
) -> dict[tuple[str, str], ApiResult]:
    """Fetch selected API requests declared by contract fetch bundles once."""
    requests: dict[tuple[str, str], dict[str, Any]] = {}
    for bundle in contract.get("fetch_bundles", []):
        for req in bundle.get("requests", []):
            if not request_covers_selected(bundle, req, selected_check_ids, selected_bundle_ids):
                continue
            method = req.get("method", "GET").upper()
            endpoint = endpoint_for(req["endpoint"], params)
            requests[(method, endpoint)] = req
    fetched: dict[tuple[str, str], ApiResult] = {}
    for (method, endpoint), req in requests.items():
        fetched[(method, endpoint)] = run_gh_api(method, endpoint, paginate=bool(req.get("paginate")))
    return fetched


def compare_contract(
    contract: dict[str, Any],
    params: dict[str, Any],
    fetched: dict[tuple[str, str], ApiResult],
    selected_check_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Run selected checks, then apply contract-level exclusions and allowances."""
    org = str(params["org_login"])
    exclusions = contract.get("approved_drift", {}).get("exclusions", [])
    skipped: list[dict[str, Any]] = []
    drifts: list[dict[str, Any]] = []
    for check in selected_contract_checks(contract, selected_check_ids):
        if any(check_matches_exclusion(rule, check["id"], org) for rule in exclusions):
            skipped.append({"check_id": check["id"], "reason": "approved exclusion"})
            continue
        method = check.get("method", "GET").upper()
        endpoint = endpoint_for(check["endpoint"], params)
        result = fetched.get((method, endpoint))
        if result is None:
            result = run_gh_api(method, endpoint)
            fetched[(method, endpoint)] = result
        drifts.extend(compare_check(check, result, params, fetched))
    remaining, approved = apply_approved_drift(drifts, contract, org)
    return remaining, approved, skipped


def remediate(check_ids: set[str], contract: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply only the narrow reversible remediations declared by the contract."""
    applied: list[dict[str, Any]] = []
    checks = {check["id"]: check for check in contract.get("checks", [])}
    policy = contract.get("remediation_policy", {})
    auto_apply_ids = set(policy.get("auto_apply_check_ids", []))
    allowed_ids = set(auto_apply_ids)
    check_ids = check_ids & allowed_ids
    org_endpoint = endpoint_for("/orgs/${org_login}", params)

    if "org.settings" in check_ids:
        body = substitute(checks["org.settings"]["expected"], params)
        result = run_gh_api("PATCH", org_endpoint, body)
        applied.append({"check_id": "org.settings", "ok": result.ok, "status": result.status, "message": result.message})

    if "actions.permissions" in check_ids:
        check = checks["actions.permissions"]
        result = run_gh_api("PUT", endpoint_for(check["endpoint"], params), substitute(check["expected"], params))
        applied.append({"check_id": "actions.permissions", "ok": result.ok, "status": result.status, "message": result.message})

    if "actions.workflow_permissions" in check_ids:
        check = checks["actions.workflow_permissions"]
        result = run_gh_api("PUT", endpoint_for(check["endpoint"], params), substitute(check["expected"], params))
        applied.append({"check_id": "actions.workflow_permissions", "ok": result.ok, "status": result.status, "message": result.message})

    if "organization.immutable_releases" in check_ids:
        check = checks["organization.immutable_releases"]
        result = run_gh_api("PUT", endpoint_for(check["endpoint"], params), substitute(check["expected"], params))
        applied.append({"check_id": "organization.immutable_releases", "ok": result.ok, "status": result.status, "message": result.message})

    return applied


def remediation_summary(drifts: list[dict[str, Any]], contract: dict[str, Any]) -> dict[str, Any]:
    """Group remaining drift by whether `--apply` is allowed to touch it."""
    policy = contract.get("remediation_policy", {})
    auto_apply_ids = set(policy.get("auto_apply_check_ids", []))
    summary: dict[str, list[dict[str, str]]] = {
        "auto_apply": [],
        "needs_review_or_report_only": [],
    }
    seen: set[tuple[str, str]] = set()
    for drift in drifts:
        check_id = drift["check_id"]
        path = drift.get("path", "$")
        key = (check_id, path)
        if key in seen:
            continue
        seen.add(key)
        item = {"check_id": check_id, "path": path}
        if check_id in auto_apply_ids:
            summary["auto_apply"].append(item)
        else:
            summary["needs_review_or_report_only"].append(item)
    return summary


def build_params(args: argparse.Namespace, contract: dict[str, Any]) -> dict[str, Any]:
    """Merge CLI parameters with contract defaults and validate requirements."""
    params: dict[str, Any] = {}
    for key, spec in contract.get("parameters", {}).items():
        if "default" in spec:
            params[key] = spec["default"]
    params["org_login"] = args.org
    if args.billing_email:
        params["billing_email"] = args.billing_email
    if args.owner_login:
        params["owner_login"] = args.owner_login
    for item in args.param or []:
        if "=" not in item:
            raise SystemExit(f"--param must be KEY=VALUE, got {item!r}")
        key, raw = item.split("=", 1)
        try:
            params[key] = json.loads(raw)
        except json.JSONDecodeError:
            params[key] = raw
    missing = [key for key, spec in contract.get("parameters", {}).items() if spec.get("required") and key not in params]
    if missing:
        raise SystemExit(f"Missing required parameter(s): {', '.join(missing)}")
    return params


def main() -> int:
    """Parse CLI arguments, fetch org evidence, compare, and report drift."""

    parser = argparse.ArgumentParser(description="Check and optionally remediate a GitHub org contract.")
    parser.add_argument("--contract", default=default_contract_path("github-org-deterministic-contract.json"))
    parser.add_argument("--org", required=True)
    parser.add_argument("--billing-email")
    parser.add_argument("--owner-login")
    parser.add_argument("--param", action="append", help="Additional contract parameter as KEY=VALUE. VALUE may be JSON.")
    parser.add_argument("--subset", choices=["all", "settings", "actions", "dependabot", "security"], default="all", help="Run a workflow-oriented subset of org checks.")
    parser.add_argument("--check-id", action="append", help="Run one deterministic check ID. Can be repeated.")
    parser.add_argument("--bundle", action="append", help="Fetch only this contract fetch bundle ID. Can be repeated.")
    parser.add_argument("--apply", action="store_true", help="Apply contract-declared automatic remediations.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON report.")
    parser.add_argument("--no-fail", action="store_true", help="Exit 0 even when unapproved drift remains.")
    args = parser.parse_args()

    contract = load_json(args.contract)
    params = build_params(args, contract)
    selected_check_ids = apply_explicit_check_ids(contract, args.check_id, subset_check_ids(contract, args.subset))
    selected_bundle_ids = set(args.bundle) if args.bundle else None
    if selected_bundle_ids is not None:
        known_bundles = {str(bundle.get("id")) for bundle in contract.get("fetch_bundles", []) if bundle.get("id")}
        unknown_bundles = sorted(selected_bundle_ids - known_bundles)
        if unknown_bundles:
            raise SystemExit(f"Unknown fetch bundle id(s): {', '.join(unknown_bundles)}")

    fetched = fetch_contract(contract, params, selected_check_ids, selected_bundle_ids)
    drifts, approved, skipped = compare_contract(contract, params, fetched, selected_check_ids)
    applied: list[dict[str, Any]] = []

    if args.apply and drifts:
        applied = remediate({drift["check_id"] for drift in drifts}, contract, params)
        applied_success_ids = {str(item["check_id"]) for item in applied if item.get("ok")}
        # A successful mutation command is sufficient evidence for that exact
        # applied check. Leave unrelated drift in the report, and do not spend a
        # second API bundle just to read back fields that the command accepted.
        if applied_success_ids:
            drifts = [drift for drift in drifts if drift["check_id"] not in applied_success_ids]

    failed_fetches = [
        {"method": result.method, "endpoint": result.endpoint, "status": result.status, "message": result.message}
        for result in fetched.values()
        if not result.ok
    ]
    expected_error_checks = {
        endpoint_for(check["endpoint"], params)
        for check in contract.get("checks", [])
        if check.get("comparison") in ("expected_error", "selected_fields_equal_or_expected_error_when_uninitialized")
    }
    unexpected_fetch_failures = [item for item in failed_fetches if item["endpoint"] not in expected_error_checks]

    report = {
        "org": params["org_login"],
        "contract": os.path.abspath(args.contract),
        "subset": args.subset,
        "checks": len(selected_contract_checks(contract, selected_check_ids)),
        "total_checks": len(contract.get("checks", [])),
        "selected_check_ids": sorted(selected_ids_for_report(contract, selected_check_ids)),
        "selected_bundles": sorted(selected_bundle_ids) if selected_bundle_ids else None,
        "fetched_endpoints": len(fetched),
        "unapproved_drift_count": len(drifts),
        "approved_drift_count": len(approved),
        "skipped_count": len(skipped),
        "remediation": remediation_summary(drifts, contract),
        "applied": applied,
        "unapproved_drifts": drifts,
        "approved_drifts": approved,
        "skipped": skipped,
        "unexpected_fetch_failures": unexpected_fetch_failures,
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Org: {report['org']}")
        print(f"Subset: {report['subset']}")
        print(f"Checks: {report['checks']}; fetched endpoints: {report['fetched_endpoints']}")
        print(f"Unapproved drift: {report['unapproved_drift_count']}; approved drift: {report['approved_drift_count']}; skipped: {report['skipped_count']}")
        if applied:
            print("Applied:")
            for item in applied:
                status = "ok" if item.get("ok") else f"failed {item.get('status')}"
                print(f"  {item['check_id']}: {status}")
        if drifts:
            print("Unapproved drifts:")
            for drift in drifts:
                print(f"  {drift['check_id']} {drift.get('path', '$')}: {drift.get('message', 'drift')}")
            summary = report["remediation"]
            if summary["auto_apply"]:
                print("Auto-remediable with --apply:")
                for item in summary["auto_apply"]:
                    print(f"  {item['check_id']} {item['path']}")
            if summary["needs_review_or_report_only"]:
                print("Needs review or report-only drift:")
                for item in summary["needs_review_or_report_only"]:
                    print(f"  {item['check_id']} {item['path']}")
        if unexpected_fetch_failures:
            print("Unexpected fetch failures:")
            for item in unexpected_fetch_failures:
                print(f"  {item['method']} {item['endpoint']}: {item['status']} {item['message']}")

    if (drifts or unexpected_fetch_failures) and not args.no_fail:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
