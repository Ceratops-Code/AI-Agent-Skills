#!/usr/bin/env python3
"""Validate GH lifecycle contract/checker ownership from skill-local files.

This helper owns deterministic consistency checks for the GitHub, repo-code,
artifact, org, and PR contract surfaces bundled with ceratops-gh-repo-lifecycle.
It intentionally does not inspect skill structure; that belongs to the skill
lifecycle validator.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re


SKILL_DIR = pathlib.Path(__file__).resolve().parent.parent
REFERENCES = SKILL_DIR / "references"
SCRIPTS = SKILL_DIR / "scripts"
SOURCE_DOCS = REFERENCES / "contract-source-docs.json"
REQUIRED_FILES = [
    SOURCE_DOCS,
    REFERENCES / "github-org-deterministic-contract.json",
    REFERENCES / "github-org-nondeterministic-contract.md",
    REFERENCES / "github-repo-deterministic-contract.json",
    REFERENCES / "github-repo-nondeterministic-contract.md",
    REFERENCES / "github-pr-readiness-deterministic-contract.json",
    REFERENCES / "github-pr-readiness-nondeterministic-contract.md",
    REFERENCES / "code-repo-deterministic-contract.json",
    REFERENCES / "code-repo-nondeterministic-contract.md",
    REFERENCES / "code-comment-nondeterministic-contract.md",
    REFERENCES / "artifact-deterministic-contract.json",
    REFERENCES / "artifact-nondeterministic-contract.md",
]
DETERMINISTIC_CONTRACTS = [
    REFERENCES / "github-org-deterministic-contract.json",
    REFERENCES / "github-repo-deterministic-contract.json",
    REFERENCES / "github-pr-readiness-deterministic-contract.json",
    REFERENCES / "code-repo-deterministic-contract.json",
    REFERENCES / "artifact-deterministic-contract.json",
]
REPO_ARTIFACT_CONTRACTS = [
    REFERENCES / "github-repo-deterministic-contract.json",
    REFERENCES / "code-repo-deterministic-contract.json",
    REFERENCES / "artifact-deterministic-contract.json",
]
ND_CONTRACTS = [
    REFERENCES / "github-org-nondeterministic-contract.md",
    REFERENCES / "github-repo-nondeterministic-contract.md",
    REFERENCES / "github-pr-readiness-nondeterministic-contract.md",
    REFERENCES / "code-repo-nondeterministic-contract.md",
    REFERENCES / "artifact-nondeterministic-contract.md",
]
REPO_ARTIFACT_VALIDATOR = SCRIPTS / "github-validate-repo-artifact-contract.py"
ND_EVIDENCE_HELPER = SCRIPTS / "github-collect-nd-evidence.py"

CONTRACT_ID_RE = re.compile(
    r"\b(?:org|organization|custom_properties|dependabot|code_security|private_registries|hosted_compute|type|repo|process|actions|security|content|local|stale_state|common|pypi|npm|docker|maven|nuget|crates|rubygems|powershell|github-packages|release-assets|docs-site|iac|pr)\.[A-Za-z0-9_.-]+\b"
)
ND_ID_RE = re.compile(r"`(ND\.[^`]+)`")


def rel(path: pathlib.Path) -> str:
    """Return a stable skill-relative display path."""

    return path.relative_to(SKILL_DIR).as_posix()


def load_json(path: pathlib.Path) -> dict[str, object]:
    """Load one deterministic contract JSON file."""

    return json.loads(path.read_text(encoding="utf-8"))


def contract_check_id_list(path: pathlib.Path) -> list[str]:
    """Return deterministic check IDs declared by one contract."""

    data = load_json(path)
    checks = data.get("checks", [])
    if not isinstance(checks, list):
        return []
    return [str(check.get("id")) for check in checks if isinstance(check, dict) and check.get("id")]


def contract_check_ids(path: pathlib.Path) -> set[str]:
    """Return unique deterministic check IDs declared by one contract."""

    return set(contract_check_id_list(path))


def checker_contract_id_literals(path: pathlib.Path) -> set[str]:
    """Return contract IDs used in `check_id` comparisons inside a script."""

    ids: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        sides = [node.left, *node.comparators]
        if not any(isinstance(side, ast.Name) and side.id == "check_id" for side in sides):
            continue
        for side in sides:
            candidates = side.elts if isinstance(side, (ast.Set, ast.List, ast.Tuple)) else [side]
            for candidate in candidates:
                if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str) and CONTRACT_ID_RE.fullmatch(candidate.value):
                    ids.add(candidate.value)
    return ids


def evidence_key_list(node: ast.AST) -> list[str] | None:
    """Return literal or dynamic evidence keys from a list AST node."""

    if not isinstance(node, ast.List):
        return None
    keys: list[str] = []
    for item in node.elts:
        if isinstance(item, ast.Constant) and isinstance(item.value, str) and item.value:
            keys.append(item.value)
        elif isinstance(item, ast.JoinedStr):
            keys.append(ast.unparse(item))
        else:
            return None
    return keys


def parse_nd_evidence_mappings(path: pathlib.Path) -> dict[str, list[str]]:
    """Extract ND evidence mappings from literal dictionaries in the helper."""

    mappings: dict[str, list[str]] = {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key_node, value_node in zip(node.keys, node.values):
            if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                continue
            if not key_node.value.startswith("ND."):
                continue
            value = evidence_key_list(value_node)
            mappings[key_node.value] = value or []
    return mappings


def check_required_files() -> list[str]:
    """Ensure every GH lifecycle contract file is present."""

    return [f"missing required GH contract file: {rel(path)}" for path in REQUIRED_FILES if not path.is_file()]


def check_json_contracts() -> list[str]:
    """Ensure deterministic contract JSON files parse and point at local source docs."""

    errors: list[str] = []
    for path in DETERMINISTIC_CONTRACTS:
        if not path.is_file():
            continue
        try:
            data = load_json(path)
        except json.JSONDecodeError as exc:
            errors.append(f"{rel(path)}: invalid JSON: {exc}")
            continue
        source_ref = data.get("source_docs_ref")
        if source_ref and source_ref != "contract-source-docs.json":
            errors.append(f"{rel(path)}: source_docs_ref must be contract-source-docs.json")
    return errors


def check_contract_ownership() -> list[str]:
    """Detect deterministic contract/checker drift from local files."""

    errors: list[str] = []
    for path in DETERMINISTIC_CONTRACTS:
        if not path.is_file():
            continue
        seen: set[str] = set()
        for check_id in contract_check_id_list(path):
            if check_id in seen:
                errors.append(f"{rel(path)}: duplicate deterministic check ID {check_id}")
            seen.add(check_id)

    known_repo_artifact_ids: set[str] = set()
    for path in REPO_ARTIFACT_CONTRACTS:
        if path.is_file():
            known_repo_artifact_ids.update(contract_check_ids(path))
    if REPO_ARTIFACT_VALIDATOR.is_file():
        for check_id in sorted(checker_contract_id_literals(REPO_ARTIFACT_VALIDATOR)):
            if check_id not in known_repo_artifact_ids:
                errors.append(f"{rel(REPO_ARTIFACT_VALIDATOR)}: checker references unknown repo/code/artifact contract ID {check_id}")
    return errors


def check_nd_evidence_coverage() -> list[str]:
    """Ensure ND contract IDs are mapped to evidence keys in the collector."""

    errors: list[str] = []
    required_ids: set[str] = set()
    for path in ND_CONTRACTS:
        if not path.is_file():
            continue
        required_ids.update(ND_ID_RE.findall(path.read_text(encoding="utf-8")))
    mappings = parse_nd_evidence_mappings(ND_EVIDENCE_HELPER) if ND_EVIDENCE_HELPER.is_file() else {}
    mapped_ids = set(mappings)
    for check_id in sorted(required_ids - mapped_ids):
        errors.append(f"{check_id}: no ND evidence mapping")
    for check_id in sorted(mapped_ids - required_ids):
        errors.append(f"{rel(ND_EVIDENCE_HELPER)}: obsolete ND evidence mapping {check_id}")
    for check_id, keys in sorted(mappings.items()):
        if check_id in required_ids and not keys:
            errors.append(f"{check_id}: ND evidence mapping must list evidence keys")
    return errors


def main() -> int:
    """Run the GH lifecycle contract consistency checks."""

    parser = argparse.ArgumentParser(description="Validate GH lifecycle contract/checker consistency.")
    parser.parse_args()
    errors: list[str] = []
    errors.extend(check_required_files())
    errors.extend(check_json_contracts())
    errors.extend(check_contract_ownership())
    errors.extend(check_nd_evidence_coverage())
    if errors:
        print(f"errors: {len(errors)}")
        for error in errors:
            print(error)
        return 1
    print("ok: gh-contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
