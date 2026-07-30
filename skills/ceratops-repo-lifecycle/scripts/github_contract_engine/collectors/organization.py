"""Collect organization facts for contract evaluation."""

from __future__ import annotations

import hashlib
import urllib.request
from typing import Any

from ..github_api import ApiResult, substitute


def collect_organization(
    fetched: dict[tuple[str, str], ApiResult],
    parameters: dict[str, Any],
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    """Collect the organization avatar bytes once when selected assertions need them."""

    avatar_needed = any(
        str(assertion.get("path", "")).startswith("/organization/avatar/")
        for rule in rules
        for assertion in rule.get("assertions", [])
    )
    if not avatar_needed:
        return {"avatar": {"collected": False}}
    endpoint = str(substitute("/orgs/${org_login}", parameters))
    response = fetched.get(("GET", endpoint))
    org = (
        response.data
        if response and response.ok and isinstance(response.data, dict)
        else {}
    )
    avatar_url = org.get("avatar_url")
    if not avatar_url:
        return {
            "avatar": {
                "collected": False,
                "error": "organization response has no avatar_url",
            }
        }
    try:
        request = urllib.request.Request(
            str(avatar_url),
            headers={"User-Agent": "ceratops-github-contract-validator"},
        )
        with urllib.request.urlopen(request, timeout=30) as stream:
            content = stream.read()
            content_type = stream.headers.get("Content-Type")
        return {
            "avatar": {
                "collected": True,
                "url": avatar_url,
                "content_type": content_type,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest().upper(),
            }
        }
    except Exception as exc:
        return {"avatar": {"collected": False, "url": avatar_url, "error": str(exc)}}
