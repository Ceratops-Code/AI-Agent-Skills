"""Collect one shared state document for non-deterministic contract review."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
from typing import Any

from . import (
    collect_observed_states,
    compose_desired_state,
)
from .format_report import write_json
from .github_api import default_contract_path, load_json


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent


def parse_param(item: str) -> tuple[str, Any]:
    name, separator, raw = item.partition("=")
    if not separator:
        raise ValueError(f"--param must be KEY=VALUE, got {item!r}")
    try:
        return name, json.loads(raw)
    except json.JSONDecodeError:
        return name, raw


def _defaults(contracts: list[dict[str, Any]]) -> dict[str, Any]:
    parameters: dict[str, Any] = {}
    for contract in contracts:
        for name, specification in contract.get("parameters", {}).items():
            if "default" in specification:
                parameters.setdefault(name, specification["default"])
    return parameters


def _overrides(args: argparse.Namespace, parameters: dict[str, Any]) -> dict[str, Any]:
    if args.local_repo_path:
        parameters["local_repo_path"] = args.local_repo_path
    for item in args.param or []:
        name, value = parse_param(item)
        parameters[name] = value
    return parameters


def _load_nd_contract(
    deterministic_path: str, deterministic_contract: dict[str, Any]
) -> tuple[str, dict[str, dict[str, list[str]]]]:
    """Load canonical AI-review checks linked by a deterministic contract."""

    filename = deterministic_contract.get("non_deterministic_review_file")
    if not isinstance(filename, str) or not filename:
        raise ValueError(
            f"{deterministic_path} does not declare non_deterministic_review_file"
        )
    review_path = pathlib.Path(deterministic_path).resolve().parent / filename
    review_contract = load_json(review_path)
    mappings: dict[str, dict[str, list[str]]] = {}
    for check in review_contract.get("checks", []):
        if not isinstance(check, dict):
            raise ValueError(f"{review_path} contains a non-object check")
        check_id = check.get("id")
        evidence_keys = check.get("evidence_keys")
        if (
            not isinstance(check_id, str)
            or not check_id.startswith("ND.")
            or not isinstance(evidence_keys, list)
            or not evidence_keys
            or not all(isinstance(key, str) and key for key in evidence_keys)
        ):
            raise ValueError(
                f"{review_path} contains an invalid AI-review check mapping"
            )
        mappings[check_id] = {"evidence_keys": evidence_keys}
    if not mappings:
        raise ValueError(f"{review_path} does not declare AI-review checks")
    return str(review_path), mappings


def org_evidence(args: argparse.Namespace) -> dict[str, Any]:
    if not args.org:
        raise ValueError("--org is required for --surface org")
    contract = load_json(args.org_contract)
    review_contract, nd_checks = _load_nd_contract(args.org_contract, contract)
    parameters = _overrides(args, {**_defaults([contract]), "org_login": args.org})
    desired_state = compose_desired_state(
        {"org": args.org_contract}, parameters, {"org": None}
    )
    observed_states = collect_observed_states(desired_state)
    return {
        "surface": "org",
        "org": args.org,
        "contract": os.path.abspath(args.org_contract),
        "review_contract": review_contract,
        "evidence_command": f"python -m github_contract_engine collect --surface org --org {args.org} --json",
        "observed_states": observed_states,
        "nd_checks": nd_checks,
    }


def _repo_parameters(
    args: argparse.Namespace, contracts: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    if not args.repo or "/" not in args.repo:
        raise ValueError("--repo must be OWNER/REPO")
    owner, repo = args.repo.split("/", 1)
    return _overrides(
        args,
        {
            **_defaults(list(contracts.values())),
            "owner": owner,
            "repo": repo,
            "audit_only": True,
        },
    )


def repo_or_artifact_evidence(args: argparse.Namespace, surface: str) -> dict[str, Any]:
    paths = {
        "repo": args.github_contract,
        "code": args.code_contract,
        "artifact": args.artifact_contract,
    }
    contracts = {name: load_json(path) for name, path in paths.items()}
    review_contract, nd_checks = _load_nd_contract(
        paths[surface], contracts[surface]
    )
    parameters = _repo_parameters(args, contracts)
    selected: dict[str, set[str] | None] = {
        name: (None if name == surface else set()) for name in paths
    }
    desired_state = compose_desired_state(paths, parameters, selected)
    observed_states = collect_observed_states(desired_state)
    return {
        "surface": surface,
        "repo": args.repo,
        "contract_paths": paths,
        "review_contract": review_contract,
        "evidence_command": f"python -m github_contract_engine collect --surface {surface} --repo {args.repo} --local-repo-path <PATH> --json",
        "observed_states": observed_states,
        "nd_checks": nd_checks,
    }


def pr_evidence(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_json(args.pr_contract)
    review_contract, nd_checks = _load_nd_contract(args.pr_contract, contract)
    command = [
        sys.executable,
        "-m",
        "github_pr_workflow",
        "validate",
        "--contract",
        args.pr_contract,
        "--json",
    ]
    if args.pr:
        command.extend(["--pr", args.pr])
    if args.local_repo_path:
        command.extend(["--cwd", args.local_repo_path])
    process = subprocess.run(
        command,
        cwd=SCRIPTS_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    try:
        validator_report = (
            json.loads(process.stdout) if process.stdout.strip() else None
        )
    except json.JSONDecodeError:
        validator_report = {"raw_stdout": process.stdout}
    return {
        "surface": "pr",
        "pr": args.pr,
        "contract": os.path.abspath(args.pr_contract),
        "review_contract": review_contract,
        "evidence_command": " ".join(command),
        "validator_exit_code": process.returncode,
        "validator_report": validator_report,
        "validator_stderr": process.stderr.strip(),
        "nd_checks": nd_checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m github_contract_engine collect",
        description="Collect a shared state document for ND GitHub contract review."
    )
    parser.add_argument(
        "--surface", choices=["org", "repo", "code", "artifact", "pr"], required=True
    )
    parser.add_argument("--org")
    parser.add_argument("--repo")
    parser.add_argument("--pr")
    parser.add_argument(
        "--org-contract",
        default=default_contract_path("github-org-deterministic-contract.json"),
    )
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
    parser.add_argument(
        "--pr-contract",
        default=default_contract_path(
            "github-pr-readiness-deterministic-contract.json"
        ),
    )
    parser.add_argument("--local-repo-path")
    parser.add_argument("--param", action="append")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.surface == "org":
            report = org_evidence(args)
        elif args.surface == "pr":
            report = pr_evidence(args)
        else:
            report = repo_or_artifact_evidence(args, args.surface)
    except ValueError as exc:
        parser.error(str(exc))
    if args.json:
        write_json(report)
    else:
        print(f"Surface: {report['surface']}")
        print(f"Evidence command: {report['evidence_command']}")
        print(f"ND checks: {len(report['nd_checks'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
