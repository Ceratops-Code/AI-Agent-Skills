"""Validate one GitHub organization against its deterministic desired-state contract."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
from typing import Any

from . import (
    collect_observed_states,
    compare_states,
    compose_desired_state,
)
from .compose_desired_state import org_subset_ids
from .format_report import build_report, write_json
from .github_api import default_contract_path, load_json
from .levels import has_blocking_findings
from .remediations import apply_remediations


LOCAL_PARAM_FILE_ENV = "CERATOPS_GH_CONTRACT_PARAMS"
ENV_PARAM_NAMES = {
    "billing_email": "CERATOPS_GH_CONTRACT_BILLING_EMAIL",
    "owner_login": "CERATOPS_GH_CONTRACT_OWNER_LOGIN",
}


def local_param_path() -> pathlib.Path:
    configured = os.environ.get(LOCAL_PARAM_FILE_ENV)
    root = pathlib.Path(os.environ.get("CODEX_HOME", pathlib.Path.home() / ".codex"))
    return (
        pathlib.Path(configured).expanduser()
        if configured
        else root / "gh-contract-params.json"
    )


def _local_parameters(org: str) -> dict[str, Any]:
    path = local_param_path()
    if not path.exists():
        return {}
    payload = load_json(path)
    organizations = payload.get("orgs", payload) if isinstance(payload, dict) else None
    if not isinstance(organizations, dict) or not isinstance(
        organizations.get(org, {}), dict
    ):
        raise ValueError(f"invalid local organization parameter file: {path}")
    return organizations.get(org, {})


def _parameters(args: argparse.Namespace, contract: dict[str, Any]) -> dict[str, Any]:
    parameters = {
        name: specification["default"]
        for name, specification in contract.get("parameters", {}).items()
        if "default" in specification
    }
    parameters["org_login"] = args.org
    parameters.update(_local_parameters(args.org))
    parameters.update(
        {
            name: value
            for name, environment in ENV_PARAM_NAMES.items()
            if (value := os.environ.get(environment))
        }
    )
    if args.billing_email:
        parameters["billing_email"] = args.billing_email
    if args.owner_login:
        parameters["owner_login"] = args.owner_login
    for item in args.param or []:
        name, separator, raw = item.partition("=")
        if not separator:
            raise ValueError(f"--param must be KEY=VALUE, got {item!r}")
        try:
            parameters[name] = json.loads(raw)
        except json.JSONDecodeError:
            parameters[name] = raw
    missing = [
        name
        for name, specification in contract.get("parameters", {}).items()
        if specification.get("required") and name not in parameters
    ]
    if missing:
        raise ValueError(f"missing required parameter(s): {', '.join(missing)}")
    return parameters


def main(argv: list[str] | None = None) -> int:
    """Collect organization state once, compare, optionally remediate, and report."""

    parser = argparse.ArgumentParser(
        prog="python -m github_contract_engine validate org",
        description="Compare a GitHub organization observed state to its deterministic contract."
    )
    parser.add_argument(
        "--contract",
        default=default_contract_path("github-org-deterministic-contract.json"),
    )
    parser.add_argument("--org", required=True)
    parser.add_argument("--billing-email")
    parser.add_argument("--owner-login")
    parser.add_argument(
        "--param",
        action="append",
        help="Additional parameter as KEY=VALUE; VALUE may be JSON.",
    )
    parser.add_argument(
        "--subset",
        choices=["all", "settings", "actions", "dependabot", "security"],
        default="all",
    )
    parser.add_argument("--check-id", action="append")
    parser.add_argument("--bundle", action="append")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply only contract-declared reversible organization remediations.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-fail", action="store_true")
    args = parser.parse_args(argv)
    try:
        contract = load_json(args.contract)
        parameters = _parameters(args, contract)
        selected = org_subset_ids(contract, args.subset)
        desired_state = compose_desired_state(
            {"org": args.contract},
            parameters,
            {"org": selected},
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
        selection={"subset": args.subset},
    )
    if args.json:
        write_json(report)
    else:
        print(f"Organization: {report['target']}")
        print(
            f"Selected checks: {sum(report['selected_counts'].values())}; result counts: {report['result_counts']}"
        )
        for item in report["findings"]:
            if item["level"] in {"ERROR", "WARN", "NEEDS_AI_AGENT_REVIEW"}:
                print(
                    f"  {item['level']} {item['check_id']} {item.get('path', '/')}: {item['message']}"
                )
    return (
        2 if has_blocking_findings(comparison["findings"]) and not args.no_fail else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
