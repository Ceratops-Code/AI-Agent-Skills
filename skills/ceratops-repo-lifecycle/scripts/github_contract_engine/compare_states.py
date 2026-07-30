"""Compare observed JSON state to contract-engine assertions."""

from __future__ import annotations

import datetime as dt
import fnmatch
import json
import re
from typing import Any, Callable

from .github_api import substitute


MISSING = object()


def canonical(value: Any) -> str:
    """Return stable JSON for set-like nested comparisons."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def normalize(value: Any) -> Any:
    """Normalize object order and treat arrays as unordered contract sets."""

    if isinstance(value, list):
        return sorted((normalize(item) for item in value), key=canonical)
    if isinstance(value, dict):
        return {key: normalize(value[key]) for key in sorted(value)}
    return value


def pointer_get(document: Any, pointer: str, default: Any = MISSING) -> Any:
    """Resolve an RFC 6901 JSON pointer."""

    if pointer in ("", "/"):
        return document
    if not pointer.startswith("/"):
        raise ValueError(f"state path must be a JSON pointer: {pointer}")
    value = document
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and token.isdigit() and int(token) < len(value):
            value = value[int(token)]
        else:
            return default
    return value


def object_subset(actual: Any, expected: Any) -> Any:
    """Project an observed object to the desired object's shape."""

    if isinstance(expected, dict):
        source = actual if isinstance(actual, dict) else {}
        return {
            key: object_subset(source.get(key), item) for key, item in expected.items()
        }
    if isinstance(expected, list) and expected and isinstance(actual, list):
        keys = {key for item in expected if isinstance(item, dict) for key in item}
        if keys:
            prototypes = {
                key: next(
                    (
                        item[key]
                        for item in expected
                        if isinstance(item, dict) and key in item
                    ),
                    None,
                )
                for key in keys
            }
            return [
                {
                    key: object_subset(
                        item.get(key) if isinstance(item, dict) else None,
                        prototypes[key],
                    )
                    for key in keys
                }
                for item in actual
            ]
    return actual


def _equal(actual: Any, expected: Any) -> bool:
    return normalize(actual) == normalize(expected)


def _equal_ci(actual: Any, expected: Any) -> bool:
    return str(actual).casefold() == str(expected).casefold()


def _subset_equal(actual: Any, expected: Any) -> bool:
    return _equal(object_subset(actual, expected), expected)


def _contains_subset(actual: Any, expected: Any) -> bool:
    return isinstance(actual, list) and any(
        _subset_equal(item, expected) for item in actual
    )


def _empty(actual: Any, _expected: Any) -> bool:
    return actual in (None, "", [], {})


def _not_empty(actual: Any, _expected: Any) -> bool:
    return not _empty(actual, None)


def _matches(actual: Any, expected: Any) -> bool:
    return isinstance(actual, str) and re.search(str(expected), actual) is not None


def _contains(actual: Any, expected: Any) -> bool:
    return (
        expected in actual
        if isinstance(actual, (str, list, tuple, set, dict))
        else False
    )


def _contains_all(actual: Any, expected: Any) -> bool:
    return isinstance(actual, (list, tuple, set, dict)) and all(
        item in actual for item in expected
    )


def _any_true(actual: Any, _expected: Any) -> bool:
    return isinstance(actual, (list, tuple, set, dict)) and any(
        actual.values() if isinstance(actual, dict) else actual
    )


def _all_true(actual: Any, _expected: Any) -> bool:
    return isinstance(actual, (list, tuple, set, dict)) and all(
        actual.values() if isinstance(actual, dict) else actual
    )


def _all_objects_have(actual: Any, expected: Any) -> bool:
    return (
        bool(actual)
        and isinstance(actual, list)
        and all(
            isinstance(item, dict)
            and all(item.get(field) not in (None, "", [], {}) for field in expected)
            for item in actual
        )
    )


def _version_tuple(value: Any) -> tuple[int, ...] | None:
    match = re.fullmatch(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(value))
    return (
        tuple(int(part or 0) for part in match.groups(default="0")) if match else None
    )


def _all_versions_gte(actual: Any, expected: Any) -> bool:
    minimum = _version_tuple(expected)
    versions = (
        [_version_tuple(item) for item in actual] if isinstance(actual, list) else []
    )
    if minimum is None:
        return False
    return bool(versions) and all(
        version is not None and version >= minimum for version in versions
    )


OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "equal": _equal,
    "equal_ci": _equal_ci,
    "subset_equal": _subset_equal,
    "contains_subset": _contains_subset,
    "empty": _empty,
    "not_empty": _not_empty,
    "truthy": lambda actual, _expected: bool(actual),
    "falsy": lambda actual, _expected: not bool(actual),
    "in": lambda actual, expected: actual in expected,
    "not_in": lambda actual, expected: actual not in expected,
    "lte": lambda actual, expected: (
        isinstance(actual, (int, float)) and actual <= expected
    ),
    "lt": lambda actual, expected: (
        isinstance(actual, (int, float)) and actual < expected
    ),
    "gte": lambda actual, expected: (
        isinstance(actual, (int, float)) and actual >= expected
    ),
    "gt": lambda actual, expected: (
        isinstance(actual, (int, float)) and actual > expected
    ),
    "matches": _matches,
    "not_matches": lambda actual, expected: not _matches(actual, expected),
    "contains": _contains,
    "not_contains": lambda actual, expected: not _contains(actual, expected),
    "contains_all": _contains_all,
    "any_true": _any_true,
    "all_true": _all_true,
    "all_objects_have": _all_objects_have,
    "all_versions_gte": _all_versions_gte,
    "max_items": lambda actual, expected: (
        isinstance(actual, (list, tuple, set, dict)) and len(actual) <= expected
    ),
    "min_items": lambda actual, expected: (
        isinstance(actual, (list, tuple, set, dict)) and len(actual) >= expected
    ),
    "glob_present": lambda actual, expected: (
        isinstance(actual, list)
        and any(fnmatch.fnmatch(str(item), str(expected)) for item in actual)
    ),
    "glob_absent": lambda actual, expected: (
        isinstance(actual, list)
        and not any(fnmatch.fnmatch(str(item), str(expected)) for item in actual)
    ),
}


def _split(expression: str, operator: str) -> list[str]:
    """Split a boolean expression outside brackets and parentheses."""

    parts: list[str] = []
    start = depth = 0
    quote: str | None = None
    index = 0
    while index < len(expression):
        char = expression[index]
        if quote:
            if char == quote and (index == 0 or expression[index - 1] != "\\"):
                quote = None
        elif char in "'\"":
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif depth == 0 and expression.startswith(operator, index):
            parts.append(expression[start:index].strip())
            index += len(operator)
            start = index
            continue
        index += 1
    parts.append(expression[start:].strip())
    return parts


def _condition_value(raw: str) -> Any:
    raw = raw.strip()
    if raw in {"true", "false", "null"}:
        return {"true": True, "false": False, "null": None}[raw]
    if raw.startswith("[") and raw.endswith("]"):
        return [_condition_value(item) for item in _split(raw[1:-1], ",") if item]
    if (raw.startswith('"') and raw.endswith('"')) or (
        raw.startswith("'") and raw.endswith("'")
    ):
        return raw[1:-1]
    try:
        return int(raw)
    except ValueError:
        return raw


def _state_value(states: dict[str, Any], name: str) -> Any:
    """Resolve dotted applicability names without conflating dotted JSON keys."""

    if name in states:
        return states[name]
    value: Any = states
    for part in name.split("."):
        if not isinstance(value, dict) or part not in value:
            return MISSING
        value = value[part]
    return value


def condition_syntax_valid(expression: str | None) -> bool:
    """Return whether an applicability expression uses the supported grammar."""

    if not expression or expression == "always":
        return True
    expression = expression.strip()
    if expression.startswith("(") and expression.endswith(")"):
        expression = expression[1:-1].strip()
    for operator in ("||", "&&"):
        groups = _split(expression, operator)
        if len(groups) > 1:
            return all(condition_syntax_valid(group) for group in groups)
    if expression.startswith("!"):
        return condition_syntax_valid(expression[1:].strip())
    patterns = (
        r"[A-Za-z_][A-Za-z0-9_.-]*\s+is\s+(?:not\s+)?(?:empty|provided)",
        r"[A-Za-z_][A-Za-z0-9_.-]*\s+(?:contains|includes|has|intersects)\s+.+",
        r"[A-Za-z_][A-Za-z0-9_.-]*\s+(?:==|!=|>=|<=|>|<|in)\s+.+",
        r"[A-Za-z_][A-Za-z0-9_.-]*",
    )
    return any(re.fullmatch(pattern, expression) for pattern in patterns)


def condition_matches(expression: str | None, observed_states: dict[str, Any]) -> bool:
    """Evaluate the small declarative applicability language used by contracts."""

    if not condition_syntax_valid(expression):
        raise ValueError(f"unsupported applicability expression: {expression}")
    if not expression or expression == "always":
        return True
    expression = expression.strip()
    if expression.startswith("(") and expression.endswith(")"):
        expression = expression[1:-1].strip()
    groups = _split(expression, "||")
    if len(groups) > 1:
        return any(condition_matches(group, observed_states) for group in groups)
    groups = _split(expression, "&&")
    if len(groups) > 1:
        return all(condition_matches(group, observed_states) for group in groups)
    if expression.startswith("!"):
        return not condition_matches(expression[1:].strip(), observed_states)

    match = re.fullmatch(r"(.+?)\s+is\s+(not\s+)?(empty|provided)", expression)
    if match:
        value = _state_value(observed_states, match.group(1).strip())
        present = value is not MISSING and value not in (None, "", [], {})
        expected_present = match.group(3) == "provided"
        if match.group(2):
            expected_present = not expected_present
        return present is expected_present
    match = re.fullmatch(r"(.+?)\s+(contains|includes|has)\s+(.+)", expression)
    if match:
        value = _state_value(observed_states, match.group(1).strip())
        expected = _condition_value(match.group(3))
        if match.group(2) == "has" and isinstance(value, dict):
            return bool(value.get(expected))
        return _contains(value, expected)
    match = re.fullmatch(r"(.+?)\s+intersects\s+(.+)", expression)
    if match:
        value = _state_value(observed_states, match.group(1).strip())
        expected = _condition_value(match.group(2))
        expected_values = (
            expected
            if isinstance(expected, list)
            else [item.strip() for item in str(expected).split(",")]
        )
        return bool(
            set(value if isinstance(value, (list, set, tuple)) else [])
            & set(expected_values)
        )
    match = re.fullmatch(r"(.+?)\s+(==|!=|>=|<=|>|<|in)\s+(.+)", expression)
    if match:
        actual = _state_value(observed_states, match.group(1).strip())
        expected = _condition_value(match.group(3))
        operator = match.group(2)
        if actual is MISSING:
            return False
        return {
            "==": lambda: actual == expected,
            "!=": lambda: actual != expected,
            ">=": lambda: actual >= expected,
            "<=": lambda: actual <= expected,
            ">": lambda: actual > expected,
            "<": lambda: actual < expected,
            "in": lambda: actual in expected,
        }[operator]()
    value = _state_value(observed_states, expression)
    return value is not MISSING and bool(value)


def evaluate_assertion(
    assertion: dict[str, Any], rule: dict[str, Any], observed_states: dict[str, Any]
) -> tuple[bool, Any, Any]:
    """Evaluate one assertion; unsupported operators are contract errors."""

    operator = str(assertion["operator"])
    if operator not in OPERATORS:
        raise ValueError(f"unsupported comparison operator: {operator}")
    actual = pointer_get(observed_states, str(assertion["path"]))
    expected = (
        pointer_get(rule, str(assertion["desired_path"]))
        if assertion.get("desired_path")
        else assertion.get("expected")
    )
    if expected is MISSING:
        raise ValueError(
            f"desired path does not exist in {rule['id']}: {assertion['desired_path']}"
        )
    if actual is MISSING:
        return False, MISSING, expected
    return OPERATORS[operator](actual, expected), actual, expected


def _finding(
    rule: dict[str, Any],
    assertion: dict[str, Any],
    actual: Any,
    expected: Any,
    *,
    collection_error: bool = False,
    source_error: Any = None,
) -> dict[str, Any]:
    path = str(assertion["path"])
    return {
        "level": "ERROR"
        if collection_error
        else assertion.get("level", rule.get("level", "ERROR")),
        "check_id": rule["id"],
        "path": path,
        "message": (
            f"Required observed state was not collected: {path}."
            if collection_error
            else assertion.get(
                "message", f"Observed state does not satisfy {assertion['operator']}."
            )
        ),
        "actual": None if actual is MISSING else actual,
        "expected": expected,
        **({"kind": "collection_error"} if collection_error else {}),
        **({"source_error": source_error} if source_error is not None else {}),
    }


def _source_collection_error(
    rule: dict[str, Any], assertion: dict[str, Any], observed_states: dict[str, Any]
) -> Any:
    """Return unavailable source evidence that invalidates a normalized fact."""

    path = str(assertion["path"])
    api_state = observed_states.get("api", {}).get(str(rule["id"]))
    if (
        rule.get("endpoint")
        and not path.startswith("/api/")
        and isinstance(api_state, dict)
        and api_state.get("ok") is False
        and api_state.get("status") != 404
    ):
        return {
            "endpoint": api_state.get("endpoint"),
            "status": api_state.get("status"),
            "message": api_state.get("message"),
        }
    local = observed_states.get("local", {})
    if path.startswith("/local/") and local.get("available") is False:
        return {"errors": local.get("errors", ["local repository was not collected"])}
    if path == "/artifact/live_metadata/all_resolved":
        failures = [
            {
                "registry": registry,
                "identity": identity,
                "status": metadata.get("status"),
                "error": metadata.get("error") or metadata.get("message"),
            }
            for registry, state in observed_states.get("registries", {}).items()
            for identity, metadata in state.get("packages", {}).items()
            if isinstance(metadata, dict)
            and metadata.get("ok") is False
            and metadata.get("status") != 404
            and (
                metadata.get("error")
                or metadata.get("message")
                or metadata.get("status") in {401, 403, 429}
                or (
                    isinstance(metadata.get("status"), int)
                    and metadata["status"] >= 500
                )
            )
        ]
        if failures:
            return failures
    return None


def _allowance_matches(
    rule: dict[str, Any], finding: dict[str, Any], observed_states: dict[str, Any]
) -> bool:
    ids = rule.get("check_ids", rule.get("allowed_checks", rule.get("check_id", "*")))
    candidates = ids if isinstance(ids, list) else [ids]
    if "*" not in candidates and finding["check_id"] not in candidates:
        return False
    if rule.get("path") not in (None, "*", finding.get("path")):
        return False
    if rule.get("when") and not condition_matches(str(rule["when"]), observed_states):
        return False
    expires = rule.get("expires_on")
    return not expires or dt.date.fromisoformat(expires) >= dt.date.today()


def compare_states(
    observed_states: dict[str, Any], desired_state: dict[str, Any]
) -> dict[str, Any]:
    """Compare all selected rules once against one collected state document."""

    findings: list[dict[str, Any]] = []
    for original_rule in desired_state["rules"]:
        rule = substitute(original_rule, desired_state.get("parameters", {}))
        if not condition_matches(rule.get("applies_when"), observed_states):
            findings.append(
                {
                    "level": "SKIP",
                    "check_id": rule["id"],
                    "path": "/",
                    "message": "Check does not apply to the observed state.",
                }
            )
            continue
        failures: list[dict[str, Any]] = []
        for assertion in rule["assertions"]:
            if assertion.get("when") and not condition_matches(
                str(assertion["when"]), observed_states
            ):
                continue
            passed, actual, expected = evaluate_assertion(
                assertion, rule, observed_states
            )
            source_error = _source_collection_error(rule, assertion, observed_states)
            if source_error is not None:
                failures.append(
                    _finding(
                        rule,
                        assertion,
                        MISSING,
                        expected,
                        collection_error=True,
                        source_error=source_error,
                    )
                )
                continue
            if not passed:
                failures.append(
                    _finding(
                        rule,
                        assertion,
                        actual,
                        expected,
                        collection_error=actual is MISSING,
                    )
                )
        findings.extend(
            failures
            or [
                {
                    "level": "PASS",
                    "check_id": rule["id"],
                    "path": "/",
                    "message": "Observed state matches desired state.",
                }
            ]
        )

    allowances = [
        item
        for contract in desired_state["contracts"]
        for item in contract.get("approved_drift", {}).get("allowances", [])
    ]
    approved: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    for finding in findings:
        if finding["level"] in {"PASS", "SKIP", "INFO"}:
            remaining.append(finding)
            continue
        matched = next(
            (
                rule
                for rule in allowances
                if _allowance_matches(rule, finding, observed_states)
            ),
            None,
        )
        if matched:
            approved.append(
                {
                    **finding,
                    "approved_by": matched.get(
                        "id", matched.get("reason", "approved_drift")
                    ),
                }
            )
        else:
            remaining.append(finding)
    return {"findings": remaining, "approved_drift": approved}
