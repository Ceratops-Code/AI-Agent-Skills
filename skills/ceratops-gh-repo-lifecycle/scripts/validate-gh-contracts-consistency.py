#!/usr/bin/env python3
"""Validate deterministic contract schema, implementation coverage, and ND mappings."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import pathlib
import re
from typing import Any

from github_contract.collect_observed_states import PRODUCER_REGISTRY, state_producer
from github_contract.collectors.local_repository import (
    ARTIFACT_DETECTOR_KEYS,
    ARTIFACT_DETECTOR_WHEN,
    COLLECTION_KEYS as LOCAL_COLLECTION_KEYS,
)
from github_contract.collectors.repository import (
    COLLECTION_KEYS as REPO_COLLECTION_KEYS,
)
from github_contract.collectors.registries import FETCHERS
from github_contract.compare_states import (
    OPERATORS,
    condition_syntax_valid,
    pointer_get,
)
from github_contract.compose_desired_state import org_subset_ids, repo_subset_ids
from github_contract.remediations import HANDLERS


SKILL_DIR = pathlib.Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_DIR.parents[1]
REFERENCES = SKILL_DIR / "references"
SCRIPTS = SKILL_DIR / "scripts"
SOURCE_DOCS = REFERENCES / "contract-source-docs.json"
STATE_CONTRACT_PATHS = {
    "org": REFERENCES / "github-org-deterministic-contract.json",
    "repo": REFERENCES / "github-repo-deterministic-contract.json",
    "code": REFERENCES / "code-repo-deterministic-contract.json",
    "artifact": REFERENCES / "artifact-deterministic-contract.json",
}
PR_CONTRACT = REFERENCES / "github-pr-readiness-deterministic-contract.json"
ND_CONTRACTS = [
    REFERENCES / "github-org-nondeterministic-contract.md",
    REFERENCES / "github-repo-nondeterministic-contract.md",
    REFERENCES / "github-pr-readiness-nondeterministic-contract.md",
    REFERENCES / "code-repo-nondeterministic-contract.md",
    REFERENCES / "artifact-nondeterministic-contract.md",
]
REQUIRED_FILES = [
    SOURCE_DOCS,
    *STATE_CONTRACT_PATHS.values(),
    PR_CONTRACT,
    *ND_CONTRACTS,
    REFERENCES / "code-comment-nondeterministic-contract.md",
    SCRIPTS / "github-collect-nd-evidence.py",
    SCRIPTS / "github-validate-org-contract.py",
    SCRIPTS / "github-validate-repo-artifact-contract.py",
    SCRIPTS / "github_contract" / "compose_desired_state.py",
    SCRIPTS / "github_contract" / "collect_observed_states.py",
    SCRIPTS / "github_contract" / "compare_states.py",
    SCRIPTS / "github_contract" / "format_report.py",
]
ND_ID_RE = re.compile(r"`(ND\.[^`]+)`")


def rel(path: pathlib.Path) -> str:
    return path.relative_to(SKILL_DIR).as_posix()


def load_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def check_ids(contract: dict[str, Any]) -> list[str]:
    return [
        str(check.get("id"))
        for check in contract.get("checks", [])
        if isinstance(check, dict) and check.get("id")
    ]


def _evidence_keys(node: ast.AST) -> list[str] | None:
    if not isinstance(node, ast.List):
        return None
    values: list[str] = []
    for item in node.elts:
        if (
            isinstance(item, ast.Constant)
            and isinstance(item.value, str)
            and item.value
        ):
            values.append(item.value)
        elif isinstance(item, ast.JoinedStr):
            values.append(ast.unparse(item))
        else:
            return None
    return values


def nd_evidence_mappings(path: pathlib.Path) -> dict[str, list[str]]:
    """Read literal ND mapping dictionaries without importing the networked collector."""

    mappings: dict[str, list[str]] = {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and key.value.startswith("ND.")
            ):
                mappings[key.value] = _evidence_keys(value) or []
    return mappings


def _validate_fetch_bundles(
    path: pathlib.Path, contract: dict[str, Any], known: set[str]
) -> list[str]:
    errors: list[str] = []
    bundles = contract.get("fetch_bundles", [])
    if isinstance(bundles, list):
        bundle_ids = [
            str(bundle.get("id")) for bundle in bundles if isinstance(bundle, dict)
        ]
        duplicates = {item for item in bundle_ids if bundle_ids.count(item) > 1}
        errors.extend(
            f"{rel(path)}: duplicate fetch bundle ID {item}"
            for item in sorted(duplicates)
        )
        for bundle in bundles:
            for request in bundle.get("requests", []):
                if not request.get("endpoint") or str(
                    request.get("method", "GET")
                ).upper() not in {"GET", "HEAD"}:
                    errors.append(
                        f"{rel(path)}: invalid read request in fetch bundle {bundle.get('id')}"
                    )
                unknown = set(request.get("covers_checks", [])) - known
                errors.extend(
                    f"{rel(path)}: fetch request covers unknown check {item}"
                    for item in sorted(unknown)
                )
    elif isinstance(bundles, dict):
        for bundle_id, bundle in bundles.items():
            feeds = bundle.get("feeds_checks", [])
            for pattern in feeds:
                if not any(fnmatch.fnmatch(check_id, pattern) for check_id in known):
                    errors.append(
                        f"{rel(path)}: fetch bundle {bundle_id} pattern matches no check: {pattern}"
                    )
            for request in bundle.get("endpoints", []):
                if not isinstance(request, dict):
                    continue
                if (
                    str(request.get("method", "GET")).upper() not in {"GET", "HEAD"}
                    or not str(request.get("endpoint", "")).startswith("/")
                    or not isinstance(request.get("paginate", False), bool)
                ):
                    errors.append(
                        f"{rel(path)}: invalid read request in fetch bundle {bundle_id}"
                    )
    else:
        errors.append(f"{rel(path)}: fetch_bundles must be an array or object")
    return errors


def _validate_artifact_detectors(
    path: pathlib.Path, contract: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    type_system = contract.get("artifact_type_system")
    if type_system is None:
        return errors
    detectors = type_system.get("detectors") if isinstance(type_system, dict) else None
    if not isinstance(detectors, list):
        return [f"{rel(path)}: artifact detectors must be an array"]
    predicate_keys = ARTIFACT_DETECTOR_KEYS - {"artifact_type", "confidence"}
    for detector in detectors:
        if not isinstance(detector, dict):
            errors.append(f"{rel(path)}: artifact detector must be an object")
            continue
        artifact_type = detector.get("artifact_type")
        unknown = set(detector) - ARTIFACT_DETECTOR_KEYS
        errors.extend(
            f"{rel(path)}: {artifact_type} uses unsupported detector key {key}"
            for key in sorted(unknown)
        )
        if not isinstance(artifact_type, str) or not artifact_type:
            errors.append(f"{rel(path)}: artifact detector has no artifact_type")
        if not set(detector) & predicate_keys:
            errors.append(f"{rel(path)}: {artifact_type} detector has no predicate")
        condition = detector.get("when")
        if condition is not None and condition not in ARTIFACT_DETECTOR_WHEN:
            errors.append(
                f"{rel(path)}: {artifact_type} uses unsupported detector condition {condition!r}"
            )
    registry_types = set(
        contract.get("fetch_bundles", {})
        .get("registry_metadata_bundle", {})
        .get("endpoints_by_type", {})
    )
    implemented_registry_types = set(FETCHERS)
    detector_types = {
        str(detector.get("artifact_type"))
        for detector in detectors
        if isinstance(detector, dict) and detector.get("artifact_type")
    }
    errors.extend(
        f"{rel(path)}: registry type has no collector implementation: {item}"
        for item in sorted(registry_types - implemented_registry_types)
    )
    errors.extend(
        f"{rel(path)}: registry collector is absent from contract metadata: {item}"
        for item in sorted(implemented_registry_types - registry_types)
    )
    errors.extend(
        f"{rel(path)}: registry collector type has no artifact detector: {item}"
        for item in sorted(implemented_registry_types - detector_types)
    )
    return errors


def _validate_source_lines(path: pathlib.Path, check: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for reference in check.get("source_lines", []):
        source_name, separator, anchor = str(reference).partition(":")
        if source_name.startswith("$"):
            continue
        source = (
            path.parent / source_name
            if "/" not in source_name and "\\" not in source_name
            else REPO_ROOT / source_name
        )
        if not source.is_file():
            errors.append(
                f"{rel(path)}: {check.get('id')} references missing source {source_name}"
            )
            continue
        if separator and anchor and not re.fullmatch(r"\d+(?:-\d+)?", anchor):
            if source.suffix == ".json":
                document = load_json(source)

                def contains_id(value: Any) -> bool:
                    if isinstance(value, dict):
                        return value.get("id") == anchor or any(
                            contains_id(item) for item in value.values()
                        )
                    if isinstance(value, list):
                        return any(contains_id(item) for item in value)
                    return False

                if not contains_id(document):
                    errors.append(
                        f"{rel(path)}: {check.get('id')} references missing source ID {reference}"
                    )
                continue
            text = source.read_text(encoding="utf-8")
            if re.search(rf"(?m)^(?:def|class)\s+{re.escape(anchor)}\b", text) is None:
                errors.append(
                    f"{rel(path)}: {check.get('id')} references missing source symbol {reference}"
                )
    return errors


def _validate_state_contract(path: pathlib.Path, contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if "type_system" in contract:
        errors.append(
            f"{rel(path)}: unconsumed type_system duplicates collector-derived facts"
        )
    if contract.get("contract_format_version") != 2:
        errors.append(f"{rel(path)}: state contract format must be 2")
    if contract.get("source_docs_ref") != "contract-source-docs.json":
        errors.append(f"{rel(path)}: source_docs_ref must be contract-source-docs.json")
    ids = check_ids(contract)
    for duplicate in sorted({check_id for check_id in ids if ids.count(check_id) > 1}):
        errors.append(f"{rel(path)}: duplicate deterministic check ID {duplicate}")
    known = set(ids)
    errors.extend(_validate_fetch_bundles(path, contract, known))
    errors.extend(_validate_artifact_detectors(path, contract))
    declared_collection_keys = {
        key
        for check in contract.get("checks", [])
        for key in check.get("collection", {})
    }
    implemented_collection_keys = LOCAL_COLLECTION_KEYS | REPO_COLLECTION_KEYS
    errors.extend(
        f"{rel(path)}: unsupported collection key {key}"
        for key in sorted(declared_collection_keys - implemented_collection_keys)
    )

    auto_apply = set(
        contract.get("remediation_policy", {}).get("auto_apply_check_ids", [])
    )
    unknown_auto = auto_apply - known
    errors.extend(
        f"{rel(path)}: remediation policy references unknown check {item}"
        for item in sorted(unknown_auto)
    )
    for allowance in contract.get("approved_drift", {}).get("allowances", []):
        ids = allowance.get(
            "check_ids", allowance.get("allowed_checks", allowance.get("check_id", "*"))
        )
        candidates = ids if isinstance(ids, list) else [ids]
        errors.extend(
            f"{rel(path)}: approved drift references unknown check {item}"
            for item in sorted(set(candidates) - known - {"*"})
        )
        if not condition_syntax_valid(allowance.get("when")):
            errors.append(
                f"{rel(path)}: approved drift {allowance.get('id')} has unsupported when syntax"
            )
    declared_actions: set[str] = set()
    for check in contract.get("checks", []):
        check_id = str(check.get("id"))
        errors.extend(_validate_source_lines(path, check))
        assertions = check.get("assertions")
        if not isinstance(assertions, list) or not assertions:
            errors.append(
                f"{rel(path)}: {check_id} has no deterministic state assertions"
            )
            continue
        if check.get("applies_when") is not None and not isinstance(
            check.get("applies_when"), str
        ):
            errors.append(f"{rel(path)}: {check_id} applies_when must be a string")
        elif not condition_syntax_valid(check.get("applies_when")):
            errors.append(
                f"{rel(path)}: {check_id} has unsupported applies_when syntax"
            )
        for assertion in assertions:
            state_path = assertion.get("path")
            if not isinstance(state_path, str) or state_producer(state_path) is None:
                errors.append(
                    f"{rel(path)}: {check_id} assertion has no registered state producer: {state_path!r}"
                )
            operator = assertion.get("operator")
            if operator not in OPERATORS:
                errors.append(
                    f"{rel(path)}: {check_id} assertion uses unsupported operator {operator!r}"
                )
            desired_path = assertion.get("desired_path")
            if desired_path and pointer_get(check, str(desired_path), None) is None:
                errors.append(
                    f"{rel(path)}: {check_id} assertion references missing desired path {desired_path}"
                )
            if not condition_syntax_valid(assertion.get("when")):
                errors.append(
                    f"{rel(path)}: {check_id} assertion has unsupported when syntax"
                )
        referenced_desired = [
            str(assertion["desired_path"])
            for assertion in assertions
            if str(assertion.get("desired_path", "")).startswith("/desired")
        ]
        desired = check.get("desired")
        if desired is not None:
            leaves: list[str] = []

            def visit(value: Any, pointer: str) -> None:
                if isinstance(value, dict) and value:
                    for key, child in value.items():
                        visit(
                            child,
                            f"{pointer}/{str(key).replace('~', '~0').replace('/', '~1')}",
                        )
                else:
                    leaves.append(pointer)

            visit(desired, "/desired")
            for leaf in leaves:
                if not any(
                    leaf == reference or leaf.startswith(reference + "/")
                    for reference in referenced_desired
                ):
                    errors.append(
                        f"{rel(path)}: {check_id} desired field is not consumed by an assertion: {leaf}"
                    )
        action = check.get("remediation_action")
        if action:
            declared_actions.add(str(action))
            if check_id not in auto_apply:
                errors.append(
                    f"{rel(path)}: {check_id} has a remediation action but is not auto-apply"
                )
            if action not in HANDLERS:
                errors.append(
                    f"{rel(path)}: {check_id} remediation action has no handler: {action}"
                )
        elif check_id in auto_apply:
            errors.append(
                f"{rel(path)}: auto-apply check has no remediation action: {check_id}"
            )
    unused_handlers = set(HANDLERS) - declared_actions
    # Handlers are shared across contracts, so global unused-handler validation is done later.
    _ = unused_handlers
    return errors


def _validate_subsets(contracts: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    repo_contracts = {
        surface: contracts[surface] for surface in ("repo", "code", "artifact")
    }
    for subset in (
        "all",
        "health",
        "create",
        "settings",
        "dependency",
        "artifact",
        "content",
    ):
        selected = repo_subset_ids(repo_contracts, subset)
        for surface, ids in selected.items():
            if ids is not None and not ids.issubset(
                set(check_ids(repo_contracts[surface]))
            ):
                errors.append(
                    f"repository subset {subset} selects unknown {surface} checks"
                )
    for subset in ("all", "settings", "actions", "dependabot", "security"):
        ids = org_subset_ids(contracts["org"], subset)
        if ids is not None and not ids.issubset(set(check_ids(contracts["org"]))):
            errors.append(f"organization subset {subset} selects unknown checks")
    return errors


def _validate_nd_coverage() -> list[str]:
    required = {
        check_id
        for path in ND_CONTRACTS
        for check_id in ND_ID_RE.findall(path.read_text(encoding="utf-8"))
    }
    mappings = nd_evidence_mappings(SCRIPTS / "github-collect-nd-evidence.py")
    errors = [
        f"{check_id}: no ND evidence mapping"
        for check_id in sorted(required - set(mappings))
    ]
    errors.extend(
        f"scripts/github-collect-nd-evidence.py: obsolete ND evidence mapping {check_id}"
        for check_id in sorted(set(mappings) - required)
    )
    errors.extend(
        f"{check_id}: ND evidence mapping must list evidence keys"
        for check_id in sorted(required)
        if not mappings.get(check_id)
    )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate GH lifecycle contract and state-engine consistency."
    )
    parser.parse_args()
    errors = [
        f"missing required GH contract file: {rel(path)}"
        for path in REQUIRED_FILES
        if not path.is_file()
    ]
    contracts: dict[str, dict[str, Any]] = {}
    for surface, path in STATE_CONTRACT_PATHS.items():
        if not path.is_file():
            continue
        try:
            contracts[surface] = load_json(path)
        except json.JSONDecodeError as exc:
            errors.append(f"{rel(path)}: invalid JSON: {exc}")
            continue
        errors.extend(_validate_state_contract(path, contracts[surface]))
    if all(surface in contracts for surface in STATE_CONTRACT_PATHS):
        errors.extend(_validate_subsets(contracts))
        declared_collection_keys = {
            key
            for contract in contracts.values()
            for check in contract.get("checks", [])
            for key in check.get("collection", {})
        }
        errors.extend(
            f"implemented collection key is unused: {key}"
            for key in sorted(
                (LOCAL_COLLECTION_KEYS | REPO_COLLECTION_KEYS)
                - declared_collection_keys
            )
        )
        used_producers = {
            state_producer(str(assertion["path"]))
            for contract in contracts.values()
            for check in contract.get("checks", [])
            for assertion in check.get("assertions", [])
        }
        errors.extend(
            f"registered state producer is unused: {producer}"
            for producer in sorted(set(PRODUCER_REGISTRY) - used_producers)
        )
        used_actions = {
            str(check["remediation_action"])
            for contract in contracts.values()
            for check in contract.get("checks", [])
            if check.get("remediation_action")
        }
        errors.extend(
            f"unused remediation handler: {action}"
            for action in sorted(set(HANDLERS) - used_actions)
        )
    if PR_CONTRACT.is_file():
        try:
            pr = load_json(PR_CONTRACT)
            ids = check_ids(pr)
            errors.extend(
                f"{rel(PR_CONTRACT)}: duplicate deterministic check ID {item}"
                for item in sorted({item for item in ids if ids.count(item) > 1})
            )
        except json.JSONDecodeError as exc:
            errors.append(f"{rel(PR_CONTRACT)}: invalid JSON: {exc}")
    if (
        all(path.is_file() for path in ND_CONTRACTS)
        and (SCRIPTS / "github-collect-nd-evidence.py").is_file()
    ):
        errors.extend(_validate_nd_coverage())
    if errors:
        print(f"errors: {len(errors)}")
        for error in errors:
            print(error)
        return 1
    print("ok: gh-contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
