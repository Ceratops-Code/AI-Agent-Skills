#!/usr/bin/env python3
"""Validate repository, local-code, and artifact desired-state contracts.

The command is intentionally only orchestration. Contract JSON declares the
desired state, collectors compose one observed-states document, and the shared
comparator reports mismatches. `--apply` invokes only contract-declared,
reversible GitHub repository remediation actions; it never publishes artifacts
or mutates external registries.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from github_contract_engine import (
    collect_observed_states,
    compare_states,
    compose_desired_state,
)
from github_contract_engine.compose_desired_state import (
    REPO_SURFACES,
    check_ids,
    repo_subset_ids,
)
from github_contract_engine.format_report import (
    build_report,
    build_summary_report,
    print_human,
    write_json,
)
from github_contract_engine.github_api import default_contract_path, load_json
from github_contract_engine.remediations import apply_remediations
from validator_levels import has_blocking_findings, parse_levels


SURFACE_CHOICES = ("all", *REPO_SURFACES)
SUBSET_CHOICES = (
    "all",
    "health",
    "create",
    "settings",
    "dependency",
    "artifact",
    "content",
)


def split_repo(value: str) -> tuple[str, str]:
    """Validate and split an OWNER/REPO argument."""

    owner, separator, repo = value.partition("/")
    if not separator or not owner or not repo:
        raise ValueError("--repo must be OWNER/REPO")
    return owner, repo


def _parameters(
    args: argparse.Namespace, contracts: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    owner, repo = split_repo(args.repo)
    parameters: dict[str, Any] = {"owner": owner, "repo": repo, "audit_only": True}
    for contract in contracts.values():
        for name, specification in contract.get("parameters", {}).items():
            if "default" in specification:
                parameters.setdefault(name, specification["default"])
    if args.local_repo_path:
        parameters["local_repo_path"] = args.local_repo_path
    for item in args.param or []:
        name, separator, raw = item.partition("=")
        if not separator:
            raise ValueError(f"--param must be KEY=VALUE, got {item!r}")
        try:
            parameters[name] = json.loads(raw)
        except json.JSONDecodeError:
            parameters[name] = raw
    return parameters


def _merge_selection(
    target: dict[str, set[str]],
    source: dict[str, set[str] | None],
    contracts: dict[str, dict[str, Any]],
    surface: str,
) -> None:
    surfaces = REPO_SURFACES if surface == "all" else (surface,)
    for selected_surface in surfaces:
        ids = source[selected_surface]
        target[selected_surface].update(
            check_ids(contracts[selected_surface]) if ids is None else ids
        )


def _selection(
    args: argparse.Namespace, contracts: dict[str, dict[str, Any]]
) -> tuple[dict[str, set[str]], list[dict[str, str]]]:
    selected: dict[str, set[str]] = {surface: set() for surface in REPO_SURFACES}
    descriptors: list[dict[str, str]] = []
    if args.select:
        if args.surface != "all" or args.subset != "all":
            raise ValueError(
                "--select cannot be combined with non-default --surface or --subset"
            )
        for raw in args.select:
            surface, separator, subset = raw.partition(":")
            if (
                not separator
                or surface not in REPO_SURFACES
                or subset not in SUBSET_CHOICES
            ):
                raise ValueError(f"--select must be SURFACE:SUBSET, got {raw!r}")
            _merge_selection(
                selected, repo_subset_ids(contracts, subset), contracts, surface
            )
            descriptors.append({"surface": surface, "subset": subset})
    else:
        _merge_selection(
            selected, repo_subset_ids(contracts, args.subset), contracts, args.surface
        )
        descriptors.append({"surface": args.surface, "subset": args.subset})
    requested = set(args.check_id or [])
    if requested:
        selected_union = set().union(*selected.values())
        excluded = requested - selected_union
        if excluded:
            raise ValueError(
                f"check id(s) excluded by current selection: {', '.join(sorted(excluded))}"
            )
        selected = {
            surface: ids.intersection(requested) for surface, ids in selected.items()
        }
    return selected, descriptors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare GitHub repository, local-code, and artifact observed states to deterministic contracts."
    )
    parser.add_argument("--repo", required=True, help="OWNER/REPO")
    parser.add_argument(
        "--github-contract",
        "--repo-contract",
        dest="github_contract",
        default=default_contract_path("github-repo-deterministic-contract.json"),
    )
    parser.add_argument(
        "--code-contract",
        default=default_contract_path("code-repo-deterministic-contract.json"),
    )
    parser.add_argument(
        "--artifact-contract",
        default=default_contract_path("artifact-deterministic-contract.json"),
    )
    parser.add_argument("--local-repo-path")
    parser.add_argument(
        "--param",
        action="append",
        help="Additional parameter as KEY=VALUE; VALUE may be JSON.",
    )
    parser.add_argument("--surface", choices=SURFACE_CHOICES, default="all")
    parser.add_argument("--subset", choices=SUBSET_CHOICES, default="all")
    parser.add_argument(
        "--select",
        action="append",
        metavar="SURFACE:SUBSET",
        help="Repeat to combine selected surface/subset pairs.",
    )
    parser.add_argument(
        "--check-id",
        action="append",
        help="Run one deterministic check ID; repeat as needed.",
    )
    parser.add_argument(
        "--bundle",
        action="append",
        help="Restrict collection to a declared fetch bundle ID.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply only contract-declared reversible repository remediations.",
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--json", action="store_true", help="Print the complete JSON report."
    )
    output.add_argument(
        "--summary-json", action="store_true", help="Print a compact JSON report."
    )
    parser.add_argument(
        "--levels",
        help="Comma-separated levels for text or summary output; defaults to ERROR,WARN,NEEDS_AI_AGENT_REVIEW.",
    )
    parser.add_argument(
        "--no-fail", action="store_true", help="Exit zero despite blocking mismatches."
    )
    return parser


def main() -> int:
    """Parse arguments, run the state engine, optionally remediate, and report."""

    parser = _parser()
    args = parser.parse_args()
    if args.json and args.levels:
        parser.error("--levels applies to text or --summary-json, not full --json")
    try:
        levels = parse_levels(args.levels)
        contract_paths = {
            "repo": args.github_contract,
            "code": args.code_contract,
            "artifact": args.artifact_contract,
        }
        contracts = {
            surface: load_json(path) for surface, path in contract_paths.items()
        }
        parameters = _parameters(args, contracts)
        selected_ids, selections = _selection(args, contracts)
        desired_state = compose_desired_state(
            contract_paths,
            parameters,
            selected_ids,
            explicit_check_ids=args.check_id,
            bundle_ids=args.bundle,
        )
    except ValueError as exc:
        parser.error(str(exc))
    observed_states = collect_observed_states(desired_state)
    comparison = compare_states(observed_states, desired_state)
    applied = (
        apply_remediations(desired_state, comparison["findings"]) if args.apply else []
    )
    if applied:
        observed_states = collect_observed_states(desired_state)
        comparison = compare_states(observed_states, desired_state)
    report = build_report(
        desired_state,
        observed_states,
        comparison,
        applied=applied,
        selection={"pairs": selections},
    )
    if args.json:
        write_json(report)
    elif args.summary_json:
        write_json(build_summary_report(report, levels))
    else:
        print_human(report, levels)
    return (
        2 if has_blocking_findings(comparison["findings"]) and not args.no_fail else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
