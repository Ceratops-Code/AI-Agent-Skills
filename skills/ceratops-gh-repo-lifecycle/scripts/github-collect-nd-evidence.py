#!/usr/bin/env python3
"""Collect one shared state document for non-deterministic contract review."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
from typing import Any

from github_contract import (
    collect_observed_states,
    compare_states,
    compose_desired_state,
)
from github_contract.github_api import default_contract_path, load_json
from validator_levels import count_by_level


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent


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


def org_evidence(args: argparse.Namespace) -> dict[str, Any]:
    if not args.org:
        raise ValueError("--org is required for --surface org")
    contract = load_json(args.org_contract)
    parameters = _overrides(args, {**_defaults([contract]), "org_login": args.org})
    desired_state = compose_desired_state(
        {"org": args.org_contract}, parameters, {"org": None}
    )
    observed_states = collect_observed_states(desired_state)
    comparison = compare_states(observed_states, desired_state)
    nd_checks = {
        "ND.org.identity-screen-parity": ["api.org.settings", "api.org.plan"],
        "ND.org.logo-visual-confirmation": ["organization.avatar"],
        "ND.org.member-role-intent": [
            "api.organization.members",
            "api.organization.outside_collaborators",
            "api.organization.roles",
        ],
        "ND.org.team-purpose-and-permission-fit": ["api.organization.teams"],
        "ND.org.webhook-and-integration-intent": [
            "api.organization.webhooks",
            "api.actions.secrets",
            "api.actions.variables",
        ],
        "ND.org.actions-policy-fit": [
            "api.actions.permissions",
            "api.actions.workflow_permissions",
            "api.actions.artifact_log_retention",
        ],
        "ND.org.security-configuration-intent": [
            "api.code_security.configurations",
            "api.code_security.configuration_defaults",
        ],
        "ND.org.dependabot-private-registry-fit": [
            "api.dependabot.repository_access",
            "api.dependabot.secrets",
            "api.private_registries.configurations",
        ],
        "ND.org.dependabot-queue-fit": [
            "api.dependabot.open_alert_queue",
            "api.dependabot.open_pr_queue",
        ],
        "ND.org.custom-property-schema-fit": ["api.custom_properties.schema"],
        "ND.org.moderation-and-community-fit": [
            "api.organization.blocked_users",
            "api.organization.interaction_limits",
            "api.organization.issue_types",
        ],
        "ND.org.ruleset-and-token-request-fit": [
            "api.organization.rulesets",
            "api.organization.personal_access_token_requests",
        ],
        "ND.org.paid-feature-classification": ["api"],
        "ND.org.source-doc-recheck": ["contract-source-docs.json"],
    }
    return {
        "surface": "org",
        "org": args.org,
        "contract": os.path.abspath(args.org_contract),
        "evidence_command": f"python skills/ceratops-gh-repo-lifecycle/scripts/github-collect-nd-evidence.py --surface org --org {args.org} --json",
        "observed_states": observed_states,
        "deterministic_counts": count_by_level(
            comparison["findings"] + comparison["approved_drift"]
        ),
        "nd_checks": {
            check_id: {"evidence_keys": keys} for check_id, keys in nd_checks.items()
        },
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
    parameters = _repo_parameters(args, contracts)
    selected: dict[str, set[str] | None] = {
        name: (None if name == surface else set()) for name in paths
    }
    desired_state = compose_desired_state(paths, parameters, selected)
    observed_states = collect_observed_states(desired_state)
    comparison = compare_states(observed_states, desired_state)
    github_nd_checks = {
        "ND.github.repo-public-contract-accuracy": [
            "repository.repo",
            "repository.topics",
            "repository.content.community_profile",
        ],
        "ND.github.release-posture-fit": [
            "repository.stale.releases",
            "repository.stale.tags",
        ],
        "ND.github.merge-branch-policy-fit": [
            "repository.protection",
            "repository.rulesets",
        ],
        "ND.github.actions-policy-fit": ["repository.actions", "local.workflows"],
        "ND.github.security-reporting-and-paid-surface-fit": ["repository.security"],
        "ND.github.dependabot-queue-fit": [
            "repository.security.dependabot_alerts",
            "repository.security.dependabot_prs",
        ],
        "ND.github.stale-state-intent-classification": ["repository.stale"],
        "ND.github.sources-current-doc-recheck": ["contract-source-docs.json"],
        "ND.reference-repo.comparator-only": ["reference_repository_question"],
    }
    code_nd_checks = {
        "ND.code.public-content-quality": ["local.files", "local.texts"],
        "ND.code.support-routing-quality": ["repository.repo.homepage", "local.files"],
        "ND.code.workflow-intent-and-pin-verification": ["local.workflows"],
        "ND.code.dependabot-policy-fit": [
            "local.dependabot",
            "repository.content.dependabot",
        ],
        "ND.code.local-state-classification": ["local", "local.git"],
        "ND.code.secret-pattern-intent": [
            "local.scans.content.local_secret_pattern_scan"
        ],
        "ND.code.comment-sufficiency": [
            "skills/ceratops-gh-repo-lifecycle/references/code-comment-nondeterministic-contract.md",
            "local.files",
        ],
        "ND.code.sources-current-doc-recheck": ["contract-source-docs.json"],
    }
    artifact_nd_checks = {
        "ND.artifact.scope-fit": [
            "artifact.types",
            "parameters.current_change_affects_artifact",
            "parameters.final_answer_makes_artifact_claim",
        ],
        "ND.artifact.real-deliverable-intent": [
            "artifact.types",
            "local.manifests",
            "local.workflows",
            "repository.stale.releases",
            "registries",
        ],
        "ND.artifact.identity-contract-fit": [
            "artifact.contracts",
            "local.manifests",
            "registries",
        ],
        "ND.artifact.audit-boundary": [
            "artifact.audit_only",
            "artifact.publish_requested",
        ],
        "ND.artifact.local-smoke-sufficiency": ["artifact.recorded_checks", "local"],
        "ND.artifact.publish-necessity": [
            "parameters.merged_change_requires_release",
            "artifact.contracts",
            "repository.stale.tags",
        ],
        "ND.artifact.version-policy-fit": [
            "artifact.contracts",
            "repository.stale.tags",
            "repository.stale.releases",
            "registries",
        ],
        "ND.artifact.live-endpoint-sufficiency": [
            "registries",
            "repository.stale.releases",
        ],
        "ND.artifact.identity-path-fit": ["local.workflows", "artifact.contracts"],
        "ND.artifact.provenance-fit": ["local.workflows", "registries"],
        "ND.pypi.package-contract-quality": [
            "local.manifests.pypi",
            "local.workflows",
            "registries.pypi",
        ],
        "ND.npm.package-contract-quality": [
            "local.manifests.npm",
            "local.workflows",
            "registries.npm",
        ],
        "ND.docker.image-contract-quality": [
            "local.manifests.docker",
            "registries.dockerhub",
        ],
        "ND.maven.package-contract-quality": [
            "local.manifests.maven",
            "registries.maven",
        ],
        "ND.nuget.package-contract-quality": [
            "local.manifests.nuget",
            "registries.nuget",
        ],
        "ND.crates.package-contract-quality": [
            "local.manifests.crates",
            "registries.crates",
        ],
        "ND.rubygems.package-contract-quality": [
            "local.manifests.rubygems",
            "registries.rubygems",
        ],
        "ND.powershell.package-contract-quality": [
            "local.manifests.powershell_gallery",
            "registries.powershell_gallery",
        ],
        "ND.github-packages.contract-quality": ["artifact.contracts", "api"],
        "ND.release-assets.contract-quality": [
            "artifact.release_assets",
            "repository.stale.releases",
        ],
        "ND.docs-site.contract-quality": ["artifact.types", "local.workflows"],
        "ND.iac-module.contract-quality": ["local.manifests.iac", "artifact.contracts"],
        "ND.sources.current-doc-recheck": ["contract-source-docs.json"],
    }
    nd_checks = {
        "repo": github_nd_checks,
        "code": code_nd_checks,
        "artifact": artifact_nd_checks,
    }[surface]
    return {
        "surface": surface,
        "repo": args.repo,
        "contract_paths": paths,
        "evidence_command": f"python skills/ceratops-gh-repo-lifecycle/scripts/github-collect-nd-evidence.py --surface {surface} --repo {args.repo} --local-repo-path <PATH> --json",
        "observed_states": observed_states,
        "deterministic_counts": count_by_level(
            comparison["findings"] + comparison["approved_drift"]
        ),
        "nd_checks": {
            check_id: {"evidence_keys": keys} for check_id, keys in nd_checks.items()
        },
    }


def pr_evidence(args: argparse.Namespace) -> dict[str, Any]:
    validator = SCRIPT_DIR / "github-validate-pr-readiness-contract.py"
    command = [sys.executable, str(validator), "--contract", args.pr_contract, "--json"]
    if args.pr:
        command.extend(["--pr", args.pr])
    if args.local_repo_path:
        command.extend(["--cwd", args.local_repo_path])
    process = subprocess.run(
        command, text=True, encoding="utf-8", errors="replace", capture_output=True
    )
    try:
        validator_report = (
            json.loads(process.stdout) if process.stdout.strip() else None
        )
    except json.JSONDecodeError:
        validator_report = {"raw_stdout": process.stdout}
    nd_checks = {
        "ND.pr.merge-method-fit": [
            "validator_report.summary",
            "validator_report.findings",
            "merge_method_policy",
        ],
        "ND.pr.auto-merge-vs-direct-fit": [
            "validator_report.findings.pr.status_checks",
            "validator_report.findings.pr.auto_merge_request",
        ],
        "ND.pr.queue-or-admin-bypass-fit": [
            "validator_report.findings",
            "branch_protection_or_queue_context",
        ],
        "ND.pr.self-merge-fit": [
            "validator_report.findings.pr.review_decision",
            "actor_and_review_policy",
        ],
        "ND.pr.workflow-change-risk": [
            "changed_files",
            "workflow_files",
            "actions_permissions",
        ],
        "ND.pr.flaky-or-unrelated-check-classification": [
            "validator_report.findings.pr.status_checks",
            "ci_logs_or_reruns",
        ],
        "ND.pr.release-or-artifact-followup-fit": [
            "changed_files",
            "release_policy",
            "artifact_contract",
        ],
        "ND.pr.branch-cleanup-fit": [
            "validator_report.summary",
            "branch_cleanup_policy",
            "local_git_state",
        ],
    }
    return {
        "surface": "pr",
        "pr": args.pr,
        "contract": os.path.abspath(args.pr_contract),
        "evidence_command": " ".join(command),
        "validator_exit_code": process.returncode,
        "validator_report": validator_report,
        "validator_stderr": process.stderr.strip(),
        "nd_checks": {
            check_id: {"evidence_keys": keys} for check_id, keys in nd_checks.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
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
    args = parser.parse_args()
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
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Surface: {report['surface']}")
        print(f"Evidence command: {report['evidence_command']}")
        print(f"ND checks: {len(report['nd_checks'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
