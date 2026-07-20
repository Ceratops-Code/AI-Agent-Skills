"""Shared severity vocabulary for GitHub lifecycle validators.

The helper keeps user-facing validator levels consistent across the shared
state engine and the separate PR-readiness validator.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


ERROR = "ERROR"
WARN = "WARN"
NEEDS_AI_AGENT_REVIEW = "NEEDS_AI_AGENT_REVIEW"
INFO = "INFO"
PASS = "PASS"
SKIP = "SKIP"

CANONICAL_LEVELS = (ERROR, WARN, NEEDS_AI_AGENT_REVIEW, INFO, PASS, SKIP)
DEFAULT_SUMMARY_LEVELS = (ERROR, WARN, NEEDS_AI_AGENT_REVIEW)
BLOCKING_LEVELS = frozenset((ERROR, WARN))
ACTIONABLE_LEVELS = frozenset((ERROR, WARN, NEEDS_AI_AGENT_REVIEW))


def item_level(item: Any) -> str:
    """Return a finding level from dict or dataclass-like finding records."""

    if isinstance(item, dict):
        return str(item.get("level", ""))
    return str(getattr(item, "level", ""))


def count_by_level(findings: Iterable[Any]) -> dict[str, int]:
    """Count findings by canonical level, preserving unexpected levels."""

    counts = {level: 0 for level in CANONICAL_LEVELS}
    for item in findings:
        level = item_level(item)
        counts[level] = counts.get(level, 0) + 1
    return counts


def parse_levels(raw: str | None) -> list[str]:
    """Parse comma-separated summary levels and reject legacy names."""

    if raw is None or raw.strip() == "":
        return list(DEFAULT_SUMMARY_LEVELS)
    levels = [part.strip().upper() for part in raw.split(",") if part.strip()]
    invalid = [level for level in levels if level not in CANONICAL_LEVELS]
    if invalid:
        expected = ", ".join(CANONICAL_LEVELS)
        raise ValueError(
            f"unknown level(s): {', '.join(invalid)}; expected one or more of {expected}"
        )
    return levels


def has_blocking_findings(findings: Iterable[Any]) -> bool:
    """Return whether any unapproved finding should produce a failing exit."""

    return any(item_level(item) in BLOCKING_LEVELS for item in findings)
