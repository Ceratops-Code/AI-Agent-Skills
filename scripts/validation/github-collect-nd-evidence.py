#!/usr/bin/env python3
"""Collect bundled evidence for non-deterministic health checks.

The Markdown ND contracts ask a reviewer to make judgment calls. This helper
keeps that review cheap and repeatable by collecting one evidence bundle per
surface (org, live GitHub repo state, repo code, or artifact) and mapping each ND
check ID to the evidence keys it should inspect. It does not decide
intent-quality checks by itself.

Called by health audits and standards reviews when deterministic contract output
leaves intent, prose quality, paid/free fit, or browser-visible behavior for a
human reviewer. It collects evidence once per surface instead of asking the
reviewer to run many separate commands.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
from typing import Any


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
CORE_PATH = SCRIPT_DIR / "github-validate-repo-artifact-contract.py"
CORE_SPEC = importlib.util.spec_from_file_location("github_validate_repo_artifact_contract", CORE_PATH)
if CORE_SPEC is None or CORE_SPEC.loader is None:
    raise RuntimeError(f"Unable to load repo/artifact validator from {CORE_PATH}")
core = importlib.util.module_from_spec(CORE_SPEC)
sys.modules[CORE_SPEC.name] = core
CORE_SPEC.loader.exec_module(core)


def compact_api(result: core.ApiResult) -> dict[str, Any]:
    """Drop raw stdout/stderr so evidence JSON stays compact and readable."""
    return {
        "ok": result.ok,
        "method": result.method,
        "endpoint": result.endpoint,
        "status": result.status,
        "message": result.message,
        "data": result.data,
    }


def build_org_params(args: argparse.Namespace, contract: dict[str, Any]) -> dict[str, Any]:
    """Build org parameters from contract defaults plus CLI overrides."""
    if not args.org:
        raise SystemExit("--org is required for --surface org")
    params: dict[str, Any] = {"org_login": args.org}
    for key, spec in contract.get("parameters", {}).items():
        if "default" in spec and key not in params:
            params[key] = spec["default"]
    for item in args.param or []:
        key, value = parse_param(item)
        params[key] = value
    return params


def parse_param(item: str) -> tuple[str, Any]:
    """Parse `--param KEY=VALUE`, accepting JSON values where possible."""
    if "=" not in item:
        raise SystemExit(f"--param must be KEY=VALUE, got {item!r}")
    key, raw = item.split("=", 1)
    try:
        return key, json.loads(raw)
    except json.JSONDecodeError:
        return key, raw


def org_evidence(args: argparse.Namespace) -> dict[str, Any]:
    """Fetch org contract endpoints and group them by ND org check ID."""
    contract = core.load_json(args.org_contract)
    params = build_org_params(args, contract)
    fetched = core.fetch_contract_requests(contract, params)
    endpoints = {result.endpoint: compact_api(result) for result in fetched.values()}
    nd_checks = {
        "ND.org.identity-screen-parity": [
            f"/orgs/{params['org_login']}"
        ],
        "ND.org.logo-visual-confirmation": [
            f"/orgs/{params['org_login']}"
        ],
        "ND.org.member-role-intent": [
            f"/orgs/{params['org_login']}/members",
            f"/orgs/{params['org_login']}/outside_collaborators",
            f"/orgs/{params['org_login']}/invitations",
            f"/orgs/{params['org_login']}/failed_invitations",
            f"/orgs/{params['org_login']}/organization-roles",
            f"/orgs/{params['org_login']}/custom-repository-roles",
            f"/orgs/{params['org_login']}/security-managers",
        ],
        "ND.org.team-purpose-and-permission-fit": [
            f"/orgs/{params['org_login']}/teams"
        ],
        "ND.org.webhook-and-integration-intent": [
            f"/orgs/{params['org_login']}/hooks",
            f"/orgs/{params['org_login']}/actions/secrets",
            f"/orgs/{params['org_login']}/actions/variables",
            f"/orgs/{params['org_login']}/dependabot/secrets",
            f"/orgs/{params['org_login']}/private-registries",
        ],
        "ND.org.actions-policy-fit": [
            f"/orgs/{params['org_login']}/actions/permissions",
            f"/orgs/{params['org_login']}/actions/permissions/workflow",
            f"/orgs/{params['org_login']}/actions/permissions/artifact-and-log-retention",
            f"/orgs/{params['org_login']}/actions/permissions/fork-pr-contributor-approval",
            f"/orgs/{params['org_login']}/actions/runner-groups",
            f"/orgs/{params['org_login']}/actions/runners",
            f"/orgs/{params['org_login']}/actions/oidc/customization/sub",
        ],
        "ND.org.security-configuration-intent": [
            f"/orgs/{params['org_login']}/code-security/configurations",
            f"/orgs/{params['org_login']}/code-security/configurations/defaults",
            f"/orgs/{params['org_login']}/security-managers",
        ],
        "ND.org.dependabot-private-registry-fit": [
            f"/orgs/{params['org_login']}/dependabot/repository-access",
            f"/orgs/{params['org_login']}/dependabot/secrets",
            f"/orgs/{params['org_login']}/private-registries",
        ],
        "ND.org.dependabot-queue-fit": [
            f"/orgs/{params['org_login']}/dependabot/alerts?state=open&per_page=100",
            f"/search/issues?q=org:{params['org_login']}+is:pr+is:open+author:app/dependabot&per_page=100",
        ],
        "ND.org.custom-property-schema-fit": [
            f"/orgs/{params['org_login']}/properties/schema"
        ],
        "ND.org.moderation-and-community-fit": [
            f"/orgs/{params['org_login']}/blocks",
            f"/orgs/{params['org_login']}/interaction-limits",
            f"/orgs/{params['org_login']}/issue-types",
            f"/orgs/{params['org_login']}/issue-fields",
            f"/orgs/{params['org_login']}/announcement",
        ],
        "ND.org.ruleset-and-token-request-fit": [
            f"/orgs/{params['org_login']}/rulesets",
            f"/orgs/{params['org_login']}/personal-access-token-requests",
        ],
        "ND.org.paid-feature-classification": [
            "*failed_or_plan_limited_endpoints"
        ],
        "ND.org.source-doc-recheck": [
            "source-docs.json"
        ],
    }
    return {
        "surface": "org",
        "org": params["org_login"],
        "contract": os.path.abspath(args.org_contract),
        "evidence_command": f"python scripts/validation/github-collect-nd-evidence.py --surface org --org {params['org_login']} --json",
        "fetched_endpoints": endpoints,
        "failed_or_plan_limited_endpoints": [item for item in endpoints.values() if not item["ok"]],
        "nd_checks": {check_id: {"evidence_keys": keys, "evidence": [endpoints.get(key) for key in keys if key in endpoints]} for check_id, keys in nd_checks.items()},
    }


def repo_or_artifact_evidence(args: argparse.Namespace, surface: str) -> dict[str, Any]:
    """Build one repo, code, or artifact evidence bundle.

    `repo` intentionally means live GitHub repository state only. Code evidence
    is a separate surface so broad workflows must opt into two explicit bundles
    instead of receiving hidden local-content review data.
    """

    github_contract = core.load_json(args.github_contract)
    code_contract = core.load_json(args.code_contract)
    artifact_contract = core.load_json(args.artifact_contract)
    params = core.build_params(args, github_contract, code_contract, artifact_contract)
    local = core.scan_local(params.get("local_repo_path"))
    github_findings: list[dict[str, Any]] = []
    code_findings: list[dict[str, Any]] = []
    repo_context: dict[str, Any]
    if surface == "repo":
        github_findings, repo_context = core.compare_repo_contract(github_contract, params, local)
    elif surface == "artifact":
        github_findings, repo_context = core.compare_repo_contract(github_contract, params, local, set())
    else:
        code_findings, repo_context = core.compare_repo_contract(code_contract, params, local)
    if surface == "artifact":
        core.fetch_artifact_contract_requests(artifact_contract, params, None, None, repo_context["fetched"], repo_context["repo"])
    registries = core.registry_metadata(params, artifact_contract, local) if surface == "artifact" else {}
    endpoints = {result.endpoint: compact_api(result) for result in repo_context["fetched"].values()}
    common = {
        "repo": f"{params['owner']}/{params['repo']}",
        "github_contract": os.path.abspath(args.github_contract),
        "code_contract": os.path.abspath(args.code_contract),
        "artifact_contract": os.path.abspath(args.artifact_contract),
        "types": repo_context["types"],
        "local_scan": {
            "available": local.get("available"),
            "root": local.get("root"),
            "files": local.get("files", [])[:500],
            "file_count": len(local.get("files", [])),
            "errors": local.get("errors", []),
        },
        "fetched_endpoints": endpoints,
        "registry_metadata": registries,
        "github_findings_summary": core.summarize(github_findings),
        "code_findings_summary": core.summarize(code_findings),
    }
    github_nd_checks = {
        "ND.github.repo-public-contract-accuracy": ["repo", "topics", "community_profile"],
        "ND.github.release-posture-fit": ["releases", "tags"],
        "ND.github.merge-branch-policy-fit": ["branch_protection", "rulesets", "expected_required_checks"],
        "ND.github.actions-policy-fit": ["actions_permissions", "workflow_permissions", "artifact_log_retention", "fork_pr_contributor_approval", "default_branch_runs"],
        "ND.github.security-reporting-and-paid-surface-fit": ["security_and_analysis", "alerts", "private_vulnerability_reporting", "code_security_configuration"],
        "ND.github.dependabot-queue-fit": ["dependabot_alerts", "dependabot_pr_queue"],
        "ND.github.stale-state-intent-classification": ["pulls", "branches", "tags", "releases"],
        "ND.github.sources-current-doc-recheck": ["source-docs.json"],
        "ND.reference-repo.comparator-only": ["reference_repository_question"],
    }
    code_nd_checks = {
        "ND.code.public-content-quality": ["README", "LICENSE", "SECURITY.md", "CONTRIBUTING", "CODE_OF_CONDUCT", "issue_templates", "pull_request_template"],
        "ND.code.support-routing-quality": ["homepage", "SUPPORT.md", "issue_templates", "SECURITY.md"],
        "ND.code.workflow-intent-and-pin-verification": ["workflow_files", "workflow_sha_pinning_findings"],
        "ND.code.dependabot-policy-fit": ["dependabot.yml", "manifests", "lockfiles", "dependency_ecosystems"],
        "ND.code.local-state-classification": ["local_scan", "git_state"],
        "ND.code.secret-pattern-intent": ["local_scan", "secret_pattern_findings"],
        "ND.code.comment-sufficiency": ["contracts/code/code-comment-nondeterministic-contract.md", "scripts", "README"],
        "ND.code.sources-current-doc-recheck": ["source-docs.json"],
    }
    if surface == "repo":
        nd_checks = github_nd_checks
        evidence_command = f"python scripts/validation/github-collect-nd-evidence.py --surface repo --repo {params['owner']}/{params['repo']} --local-repo-path <PATH> --json"
    elif surface == "code":
        nd_checks = code_nd_checks
        evidence_command = f"python scripts/validation/github-collect-nd-evidence.py --surface code --repo {params['owner']}/{params['repo']} --local-repo-path <PATH> --json"
    else:
        nd_checks = {
            "ND.artifact.scope-fit": ["types", "artifact_contracts", "task_flags"],
            "ND.artifact.real-deliverable-intent": ["types", "manifests", "workflows", "releases", "registry_metadata"],
            "ND.artifact.identity-contract-fit": ["artifact_contracts", "manifests", "registry_metadata"],
            "ND.artifact.audit-boundary": ["audit_only", "remediation_policy"],
            "ND.artifact.local-smoke-sufficiency": ["post_publish_consumer_bundle", "local_scan"],
            "ND.artifact.publish-necessity": ["merged_change_requires_release", "release_policy", "tags"],
            "ND.artifact.version-policy-fit": ["manifests", "tags", "releases", "registry_metadata"],
            "ND.artifact.live-endpoint-sufficiency": ["registry_metadata", "releases"],
            "ND.artifact.identity-path-fit": ["workflow_files", "trusted_publishing_sources"],
            "ND.artifact.provenance-fit": ["workflow_files", "registry_metadata", "attestation_permissions"],
            "ND.pypi.package-contract-quality": ["pyproject.toml", "workflow_files", "registry_metadata.pypi", "trusted_publisher_configuration"],
            "ND.npm.package-contract-quality": ["package.json", "workflow_files", "registry_metadata.npm", "trusted_publisher_configuration"],
            "ND.docker.image-contract-quality": ["Dockerfile", ".dockerignore", "registry_metadata.dockerhub"],
            "ND.maven.package-contract-quality": ["pom.xml", "build.gradle"],
            "ND.nuget.package-contract-quality": ["*.csproj", "*.nuspec"],
            "ND.crates.package-contract-quality": ["Cargo.toml"],
            "ND.rubygems.package-contract-quality": ["*.gemspec"],
            "ND.powershell.package-contract-quality": ["*.psd1"],
            "ND.github-packages.contract-quality": ["github_packages_bundle"],
            "ND.release-assets.contract-quality": ["releases", "release_assets"],
            "ND.docs-site.contract-quality": ["pages", "docs_site"],
            "ND.iac-module.contract-quality": ["*.tf", "Chart.yaml"],
            "ND.sources.current-doc-recheck": ["source-docs.json"],
        }
        evidence_command = f"python scripts/validation/github-collect-nd-evidence.py --surface artifact --repo {params['owner']}/{params['repo']} --local-repo-path <PATH> --json"
    common.update(
        {
            "surface": surface,
            "evidence_command": evidence_command,
            "nd_checks": {check_id: {"evidence_keys": keys} for check_id, keys in nd_checks.items()},
        }
    )
    return common


def pr_evidence(args: argparse.Namespace) -> dict[str, Any]:
    """Collect one PR-readiness evidence bundle for ND merge decisions."""

    validator = SCRIPT_DIR / "github-validate-pr-readiness-contract.py"
    command = [sys.executable, str(validator), "--contract", args.pr_contract, "--json"]
    if args.pr:
        command.extend(["--pr", args.pr])
    if args.local_repo_path:
        command.extend(["--cwd", args.local_repo_path])
    proc = subprocess.run(command, text=True, capture_output=True)
    try:
        validator_report = json.loads(proc.stdout) if proc.stdout.strip() else None
    except json.JSONDecodeError:
        validator_report = {"raw_stdout": proc.stdout}
    nd_checks = {
        "ND.pr.merge-method-fit": ["validator_report.summary", "validator_report.findings", "merge_method_policy"],
        "ND.pr.auto-merge-vs-direct-fit": ["validator_report.findings.pr.status_checks", "validator_report.findings.pr.auto_merge_request"],
        "ND.pr.queue-or-admin-bypass-fit": ["validator_report.findings", "branch_protection_or_queue_context"],
        "ND.pr.self-merge-fit": ["validator_report.findings.pr.review_decision", "actor_and_review_policy"],
        "ND.pr.workflow-change-risk": ["changed_files", "workflow_files", "actions_permissions"],
        "ND.pr.flaky-or-unrelated-check-classification": ["validator_report.findings.pr.status_checks", "ci_logs_or_reruns"],
        "ND.pr.release-or-artifact-followup-fit": ["changed_files", "release_policy", "artifact_contract"],
        "ND.pr.branch-cleanup-fit": ["validator_report.summary", "branch_cleanup_policy", "local_git_state"],
    }
    return {
        "surface": "pr",
        "pr": args.pr,
        "contract": os.path.abspath(args.pr_contract),
        "evidence_command": " ".join(command),
        "validator_exit_code": proc.returncode,
        "validator_report": validator_report,
        "validator_stderr": proc.stderr.strip(),
        "nd_checks": {check_id: {"evidence_keys": keys} for check_id, keys in nd_checks.items()},
    }


def main() -> int:
    """CLI entrypoint for org, repo, code, or artifact evidence collection."""
    parser = argparse.ArgumentParser(
        description="Collect one bundled evidence report for ND GitHub, code, or artifact health checks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Surfaces mirror deterministic contract surfaces:\n"
            "  org            GitHub organization evidence\n"
            "  repo           live GitHub repository state evidence\n"
            "  code           repository-content evidence\n"
            "  artifact       external artifact and registry evidence\n"
            "  pr             pull-request readiness evidence\n"
        ),
    )
    parser.add_argument("--surface", choices=["org", "repo", "code", "artifact", "pr"], required=True)
    parser.add_argument("--org")
    parser.add_argument("--repo")
    parser.add_argument("--org-contract", default=core.default_contract_path("github-org-deterministic-contract.json"))
    parser.add_argument("--github-contract", "--repo-contract", dest="github_contract", default=core.default_contract_path("github-repo-deterministic-contract.json"))
    parser.add_argument("--code-contract", default=core.default_contract_path("code-repo-deterministic-contract.json"))
    parser.add_argument("--artifact-contract", default=core.default_contract_path("artifact-deterministic-contract.json"))
    parser.add_argument("--pr-contract", default=core.default_contract_path("github-pr-readiness-deterministic-contract.json"))
    parser.add_argument("--local-repo-path")
    parser.add_argument("--param", action="append", help="Additional parameter as KEY=VALUE. VALUE may be JSON.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.surface == "org":
        report = org_evidence(args)
    elif args.surface == "pr":
        report = pr_evidence(args)
    else:
        if not args.repo:
            raise SystemExit("--repo is required for repo, code, and artifact surfaces")
        report = repo_or_artifact_evidence(args, args.surface)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Surface: {report['surface']}")
        print(f"Evidence command: {report['evidence_command']}")
        print(f"ND checks: {len(report['nd_checks'])}")
        if "fetched_endpoints" in report:
            print(f"Fetched endpoints: {len(report['fetched_endpoints'])}")
        if report.get("registry_metadata"):
            print("Registry metadata keys:", ", ".join(k for k, v in report["registry_metadata"].items() if v))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
