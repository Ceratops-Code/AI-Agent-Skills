"""Validate the deterministic GitHub pull-request readiness contract.

This script is intentionally narrow. Repository health, repo contents, and
artifact posture are owned by the other contract validators; this validator
answers the merge-decision contract that needs fresh PR state close to the final
action.

Called by merge, ship, dependency-maintenance, and create/publish workflows when a PR
merge decision is in scope. It reads GitHub PR metadata, applicable branch
rules, and local branch state; it does not mutate the repository or GitHub.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Any

from github_contract_engine.github_api import run_gh_graphql
from github_contract_engine.levels import ERROR, count_by_level


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent
SKILL_DIR = SCRIPTS_DIR.parent
ROOT = SKILL_DIR.parent.parent if SKILL_DIR.parent.name == "skills" else SKILL_DIR

PULL_REQUEST_RULES_QUERY = """
query(
  $owner: String!
  $name: String!
  $qualifiedName: String!
  $cursor: String
) {
  repository(owner: $owner, name: $name) {
    ref(qualifiedName: $qualifiedName) {
      name
      branchProtectionRule {
        requiresApprovingReviews
        requiredApprovingReviewCount
        requiresConversationResolution
        requiresStatusChecks
        requiredStatusChecks {
          context
        }
      }
      rules(first: 100, after: $cursor) {
        nodes {
          type
          parameters {
            __typename
            ... on PullRequestParameters {
              requiredApprovingReviewCount
              requiredReviewThreadResolution
            }
            ... on RequiredStatusChecksParameters {
              requiredStatusChecks {
                context
              }
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}
"""

PASSING_CHECK_CONCLUSIONS = frozenset({"SUCCESS", "SKIPPED", "NEUTRAL"})
FAILING_CHECK_CONCLUSIONS = frozenset(
    {
        "FAILURE",
        "TIMED_OUT",
        "CANCELLED",
        "ACTION_REQUIRED",
        "STALE",
        "STARTUP_FAILURE",
    }
)
PENDING_CHECK_STATUSES = frozenset(
    {"IN_PROGRESS", "PENDING", "QUEUED", "REQUESTED", "WAITING"}
)
KNOWN_CHECK_STATUSES = PENDING_CHECK_STATUSES | {"COMPLETED"}
PENDING_CONTEXT_STATES = frozenset({"PENDING", "EXPECTED"})
FAILING_CONTEXT_STATES = frozenset({"FAILURE", "ERROR"})
KNOWN_CONTEXT_STATES = PENDING_CONTEXT_STATES | FAILING_CONTEXT_STATES | {"SUCCESS"}
NO_STATUS_CHECKS_MESSAGE = "No status checks are attached to this PR."
REQUIRED_STATUS_CHECKS_MISSING_MESSAGE = (
    "Required status checks are not attached to this PR."
)
UNKNOWN_STATUS_CHECK_MESSAGE = "Status-check entry has unknown state."
INCOMPLETE_STATUS_CHECK_MESSAGE = (
    "Status-check entry has no terminal or pending state."
)
SHORT_STATUS_CHECK_UNCERTAINTY_MESSAGES = frozenset(
    {
        REQUIRED_STATUS_CHECKS_MISSING_MESSAGE,
        UNKNOWN_STATUS_CHECK_MESSAGE,
        INCOMPLETE_STATUS_CHECK_MESSAGE,
    }
)


class CommandError(RuntimeError):
    """Raised when a required local command fails."""


@dataclass(frozen=True)
class Finding:
    """One machine-readable readiness finding."""

    level: str
    check: str
    message: str
    actual: object | None = None
    expected: object | None = None


def run_command(args: list[str], cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
    """Run a command without shell expansion and keep stdout/stderr separate."""

    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def require_command(args: list[str], cwd: pathlib.Path) -> str:
    """Run a command and return stdout, raising a compact error on failure."""

    completed = run_command(args, cwd)
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "command failed"
        raise CommandError(f"{' '.join(args)}: {stderr}")
    return completed.stdout.strip()


def current_branch(cwd: pathlib.Path) -> str | None:
    """Return the current git branch when the working directory is a checkout."""

    completed = run_command(["git", "branch", "--show-current"], cwd)
    if completed.returncode != 0:
        return None
    branch = completed.stdout.strip()
    return branch or None


def gh_pr_view(selector: str | None, cwd: pathlib.Path) -> dict[str, Any]:
    """Fetch the live PR fields used by the merge-readiness policy."""

    fields = [
        "number",
        "url",
        "state",
        "isDraft",
        "mergeable",
        "reviewDecision",
        "statusCheckRollup",
        "headRefName",
        "headRefOid",
        "baseRefName",
        "autoMergeRequest",
    ]
    args = ["gh", "pr", "view", "--json", ",".join(fields)]
    if selector:
        args.append(selector)
    return json.loads(require_command(args, cwd))


def current_repository(cwd: pathlib.Path) -> tuple[str, str]:
    """Return the current checkout repository as an owner/name pair."""

    try:
        payload = json.loads(
            require_command(["gh", "repo", "view", "--json", "nameWithOwner"], cwd)
        )
    except json.JSONDecodeError as exc:
        raise CommandError(
            "GitHub repository lookup returned invalid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise CommandError("GitHub repository lookup returned an invalid response")
    name_with_owner = payload.get("nameWithOwner")
    if not isinstance(name_with_owner, str):
        raise CommandError("GitHub repository lookup omitted nameWithOwner")
    owner, separator, name = name_with_owner.partition("/")
    if separator != "/" or not owner or not name or "/" in name:
        raise CommandError("GitHub repository identity must use owner/name")
    return owner, name


def gh_graphql(
    query: str,
    variables: dict[str, Any],
    cwd: pathlib.Path,
) -> dict[str, Any]:
    """Run one authenticated GraphQL read and fail closed on invalid output."""

    try:
        result = run_gh_graphql(
            query,
            variables,
            "pull-request-rules",
            cwd=cwd,
        )
    except (json.JSONDecodeError, OSError) as exc:
        raise CommandError(f"GitHub GraphQL request failed: {exc}") from exc
    if not result.ok:
        raise CommandError(result.message or "GitHub GraphQL request failed")
    if not isinstance(result.data, dict):
        raise CommandError("GitHub GraphQL returned an invalid response")
    return result.data


def normalized_pull_request_parameters(
    count: object,
    thread_resolution: object,
    *,
    source: str,
) -> dict[str, Any]:
    """Validate and normalize one pull-request rule parameter set."""

    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise CommandError(
            f"GitHub {source} has an invalid approving-review count"
        )
    if not isinstance(thread_resolution, bool):
        raise CommandError(
            f"GitHub {source} has an invalid thread-resolution requirement"
        )
    return {
        "required_approving_review_count": count,
        "required_review_thread_resolution": thread_resolution,
    }


def normalized_required_status_checks(
    raw_checks: object,
    *,
    source: str,
) -> list[str]:
    """Validate required-check contexts from one applicable branch rule."""

    if raw_checks is None:
        raw_checks = []
    if not isinstance(raw_checks, list):
        raise CommandError(f"GitHub {source} required checks are invalid")
    contexts: list[str] = []
    for index, raw_check in enumerate(raw_checks):
        if not isinstance(raw_check, dict):
            raise CommandError(
                f"GitHub {source} required check {index} is invalid"
            )
        context = raw_check.get("context")
        if not isinstance(context, str) or not context:
            raise CommandError(
                f"GitHub {source} required check {index} omitted its context"
            )
        contexts.append(context)
    return sorted(set(contexts))


def classic_rule_parameters(raw_rule: object) -> dict[str, Any] | None:
    """Normalize classic branch protection when the exact ref has one."""

    if raw_rule is None:
        return None
    if not isinstance(raw_rule, dict):
        raise CommandError("GitHub classic branch protection is invalid")
    requires_approvals = raw_rule.get("requiresApprovingReviews")
    if not isinstance(requires_approvals, bool):
        raise CommandError(
            "GitHub classic branch protection omitted approval policy"
        )
    count = raw_rule.get("requiredApprovingReviewCount")
    if count is None:
        count = 0
    if isinstance(count, int) and not isinstance(count, bool):
        count = max(count, int(requires_approvals))
    parameters = normalized_pull_request_parameters(
        count,
        raw_rule.get("requiresConversationResolution"),
        source="classic branch protection",
    )
    requires_checks = raw_rule.get("requiresStatusChecks")
    if not isinstance(requires_checks, bool):
        raise CommandError(
            "GitHub classic branch protection omitted status-check policy"
        )
    required_checks = normalized_required_status_checks(
        raw_rule.get("requiredStatusChecks"),
        source="classic branch protection",
    )
    if requires_checks and not required_checks:
        raise CommandError(
            "GitHub classic branch protection requires checks but names none"
        )
    parameters["required_status_checks"] = (
        required_checks if requires_checks else []
    )
    return parameters


def ruleset_rule_parameters(raw_rule: object) -> dict[str, Any] | None:
    """Normalize one applicable PR or required-status-check ruleset rule."""

    if not isinstance(raw_rule, dict):
        raise CommandError("GitHub applicable branch rule is invalid")
    rule_type = raw_rule.get("type")
    if not isinstance(rule_type, str):
        raise CommandError("GitHub applicable branch rule omitted its type")
    if rule_type not in {"PULL_REQUEST", "REQUIRED_STATUS_CHECKS"}:
        return None
    parameters = raw_rule.get("parameters")
    if not isinstance(parameters, dict):
        raise CommandError("GitHub applicable branch rule has invalid parameters")
    if rule_type == "PULL_REQUEST":
        if parameters.get("__typename") != "PullRequestParameters":
            raise CommandError("GitHub pull-request rule has invalid parameters")
        return normalized_pull_request_parameters(
            parameters.get("requiredApprovingReviewCount"),
            parameters.get("requiredReviewThreadResolution"),
            source="pull-request rule",
        )
    if parameters.get("__typename") != "RequiredStatusChecksParameters":
        raise CommandError("GitHub required-status-check rule has invalid parameters")
    required_checks = normalized_required_status_checks(
        parameters.get("requiredStatusChecks"),
        source="required-status-check rule",
    )
    if not required_checks:
        raise CommandError("GitHub required-status-check rule names no checks")
    return {"required_status_checks": required_checks}


def applicable_branch_rule_parameters(
    base_branch: str, cwd: pathlib.Path
) -> list[dict[str, Any]]:
    """Return active PR and status-check rules applied to the exact base ref."""

    if not base_branch:
        raise CommandError("GitHub base branch is empty")
    owner, name = current_repository(cwd)
    qualified_name = f"refs/heads/{base_branch}"
    parameters_list: list[dict[str, Any]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    classic_policy: object = None
    first_page = True
    while True:
        payload = gh_graphql(
            PULL_REQUEST_RULES_QUERY,
            {
                "owner": owner,
                "name": name,
                "qualifiedName": qualified_name,
                "cursor": cursor,
            },
            cwd,
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise CommandError("GitHub GraphQL response omitted data")
        repository = data.get("repository")
        if not isinstance(repository, dict):
            raise CommandError("GitHub GraphQL response omitted the repository")
        ref = repository.get("ref")
        if not isinstance(ref, dict) or ref.get("name") != base_branch:
            raise CommandError(
                f"GitHub GraphQL response omitted base ref {qualified_name}"
            )

        raw_classic_policy = ref.get("branchProtectionRule")
        if first_page:
            classic_policy = raw_classic_policy
            normalized_classic = classic_rule_parameters(raw_classic_policy)
            if normalized_classic is not None:
                parameters_list.append(normalized_classic)
            first_page = False
        elif raw_classic_policy != classic_policy:
            raise CommandError(
                "GitHub branch protection changed during paginated rule lookup"
            )

        rules = ref.get("rules")
        if not isinstance(rules, dict):
            raise CommandError("GitHub GraphQL response omitted applicable rules")
        nodes = rules.get("nodes")
        if not isinstance(nodes, list):
            raise CommandError("GitHub applicable rules response is not a list")
        for raw_rule in nodes:
            normalized_rule = ruleset_rule_parameters(raw_rule)
            if normalized_rule is not None:
                parameters_list.append(normalized_rule)

        page_info = rules.get("pageInfo")
        if not isinstance(page_info, dict):
            raise CommandError("GitHub applicable rules omitted pagination state")
        has_next_page = page_info.get("hasNextPage")
        if not isinstance(has_next_page, bool):
            raise CommandError("GitHub applicable rules have invalid pagination state")
        if not has_next_page:
            break
        next_cursor = page_info.get("endCursor")
        if (
            not isinstance(next_cursor, str)
            or not next_cursor
            or next_cursor in seen_cursors
        ):
            raise CommandError("GitHub applicable rules pagination did not advance")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    return parameters_list


def branch_rule_policy(base_branch: str, cwd: pathlib.Path) -> dict[str, Any]:
    """Aggregate the applied review and required-status-check policy."""

    required_count = 0
    thread_resolution = False
    required_checks: set[str] = set()
    for parameters in applicable_branch_rule_parameters(base_branch, cwd):
        count = parameters.get("required_approving_review_count")
        if count is not None:
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise CommandError(
                    "GitHub pull-request rule has an invalid review count"
                )
            required_count = max(required_count, count)
        thread_resolution = thread_resolution or (
            parameters.get("required_review_thread_resolution") is True
        )
        checks = parameters.get("required_status_checks")
        if checks is not None:
            if not isinstance(checks, list) or any(
                not isinstance(check, str) or not check for check in checks
            ):
                raise CommandError(
                    "GitHub branch rule has invalid required status checks"
                )
            required_checks.update(checks)
    return {
        "required_approving_review_count": required_count,
        "required_review_thread_resolution": thread_resolution,
        "required_status_checks": sorted(required_checks),
    }


def required_approving_review_count(base_branch: str, cwd: pathlib.Path) -> int:
    """Return the strongest pull-request approval rule applied to the branch."""

    return int(branch_rule_policy(base_branch, cwd)["required_approving_review_count"])


def review_thread_resolution_required(
    base_branch: str, cwd: pathlib.Path
) -> bool:
    """Return whether an applied branch rule requires every thread resolved."""

    return bool(
        branch_rule_policy(base_branch, cwd)["required_review_thread_resolution"]
    )


def default_contract_path() -> pathlib.Path:
    """Find the bundled PR readiness contract in source or installed copies."""

    candidates = [
        pathlib.Path.cwd() / "github-pr-readiness-deterministic-contract.json",
        pathlib.Path.cwd() / "skills" / "ceratops-repo-lifecycle" / "references" / "contracts" / "github-pr-readiness-deterministic-contract.json",
        ROOT / "skills" / "ceratops-repo-lifecycle" / "references" / "contracts" / "github-pr-readiness-deterministic-contract.json",
        SKILL_DIR / "references" / "contracts" / "github-pr-readiness-deterministic-contract.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return SKILL_DIR / "references" / "contracts" / "github-pr-readiness-deterministic-contract.json"


def load_contract(path: pathlib.Path) -> dict[str, Any]:
    """Load the PR readiness contract so finding IDs stay contract-backed."""

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def contract_check_ids(contract: dict[str, Any]) -> set[str]:
    """Return deterministic check IDs declared by the PR contract."""

    return {str(check.get("id")) for check in contract.get("checks", []) if check.get("id")}


def add(
    findings: list[Finding],
    level: str,
    check: str,
    message: str,
    *,
    actual: object | None = None,
    expected: object | None = None,
) -> None:
    """Append a finding with consistent field names."""

    findings.append(Finding(level=level, check=check, message=message, actual=actual, expected=expected))


def status_rollup_findings(
    pr_data: dict[str, Any],
    findings: list[Finding],
    *,
    required_checks: list[str] | None = None,
) -> None:
    """Classify the visible status checks attached to the PR."""

    raw_rollup = pr_data.get("statusCheckRollup")
    if not isinstance(raw_rollup, list):
        add(findings, "ERROR", "pr.status_checks", "Could not parse status-check rollup.", actual=type(raw_rollup).__name__)
        return
    if not raw_rollup:
        if required_checks:
            add(
                findings,
                "WARN",
                "pr.status_checks",
                REQUIRED_STATUS_CHECKS_MISSING_MESSAGE,
                actual=required_checks,
            )
        else:
            add(
                findings,
                "WARN",
                "pr.status_checks",
                NO_STATUS_CHECKS_MESSAGE,
            )
        return

    failed: list[str] = []
    pending: list[str] = []
    passed: list[str] = []
    for index, item in enumerate(raw_rollup):
        if not isinstance(item, dict):
            add(
                findings,
                "ERROR",
                "pr.status_checks",
                "Could not parse a status-check entry.",
                actual=f"item {index}: {type(item).__name__}",
            )
            return
        name = str(item.get("name") or item.get("context") or item.get("workflowName") or "unnamed-check")
        conclusion = item.get("conclusion")
        status = item.get("status")
        state = item.get("state")
        state_evidence = {
            "index": index,
            "name": name,
            "conclusion": conclusion,
            "status": status,
            "state": state,
        }
        fields = {
            "conclusion": conclusion,
            "status": status,
            "state": state,
        }
        if any(
            value is not None and not isinstance(value, str)
            for value in fields.values()
        ):
            add(
                findings,
                "ERROR",
                "pr.status_checks",
                "Status-check entry has invalid field types.",
                actual=name,
            )
            return
        if (
            conclusion not in (None, "")
            and conclusion
            not in PASSING_CHECK_CONCLUSIONS | FAILING_CHECK_CONCLUSIONS
        ) or (status is not None and status not in KNOWN_CHECK_STATUSES) or (
            state is not None and state not in KNOWN_CONTEXT_STATES
        ):
            add(
                findings,
                "ERROR",
                "pr.status_checks",
                UNKNOWN_STATUS_CHECK_MESSAGE,
                actual=state_evidence,
            )
            return
        # GitHub treats SUCCESS, SKIPPED, and NEUTRAL as successful required
        # checks. Keep completed failures distinct from incomplete checks.
        if conclusion in FAILING_CHECK_CONCLUSIONS or state in FAILING_CONTEXT_STATES:
            failed.append(name)
        elif status in PENDING_CHECK_STATUSES or state in PENDING_CONTEXT_STATES:
            pending.append(name)
        elif conclusion in PASSING_CHECK_CONCLUSIONS or state == "SUCCESS":
            passed.append(name)
        else:
            add(
                findings,
                "ERROR",
                "pr.status_checks",
                INCOMPLETE_STATUS_CHECK_MESSAGE,
                actual=state_evidence,
            )
            return

    visible = set(failed) | set(pending) | set(passed)
    missing_required = [
        check for check in (required_checks or []) if check not in visible
    ]
    if failed:
        add(findings, "ERROR", "pr.status_checks", "One or more status checks are failing.", actual=failed)
    elif missing_required:
        add(
            findings,
            "WARN",
            "pr.status_checks",
            REQUIRED_STATUS_CHECKS_MISSING_MESSAGE,
            actual=missing_required,
        )
    elif pending:
        add(findings, "WARN", "pr.status_checks", "Status checks are still pending.", actual=pending)
    else:
        add(findings, "PASS", "pr.status_checks", "All visible status checks are passing.", actual=passed)


def pr_readiness(selector: str | None, cwd: pathlib.Path, *, allow_admin_review_bypass: bool = False) -> tuple[dict[str, object], list[Finding]]:
    """Evaluate the live PR state needed before merge or auto-merge."""

    pr_data = gh_pr_view(selector, cwd)
    findings: list[Finding] = []

    if pr_data.get("state") == "OPEN":
        add(findings, "PASS", "pr.state_open", "PR is open.")
    else:
        add(findings, "ERROR", "pr.state_open", "PR is not open.", actual=pr_data.get("state"), expected="OPEN")

    if pr_data.get("isDraft") is True:
        add(findings, "ERROR", "pr.not_draft", "PR is still marked draft.", actual=True, expected=False)
    else:
        add(findings, "PASS", "pr.not_draft", "PR is ready for review.")

    mergeable = pr_data.get("mergeable")
    if mergeable == "CONFLICTING":
        add(findings, "ERROR", "pr.mergeable", "PR has merge conflicts.", actual=mergeable)
    elif mergeable == "MERGEABLE":
        add(findings, "PASS", "pr.mergeable", "PR is mergeable.", actual=mergeable)
    else:
        add(findings, "WARN", "pr.mergeable", "PR mergeability needs a live re-check.", actual=mergeable)

    review_decision = pr_data.get("reviewDecision")
    raw_rollup = pr_data.get("statusCheckRollup")
    needs_branch_policy = review_decision in {None, ""} or isinstance(
        raw_rollup, list
    )
    branch_policy: dict[str, Any] | None = None
    if needs_branch_policy:
        base_branch = pr_data.get("baseRefName")
        if not isinstance(base_branch, str) or not base_branch:
            raise CommandError("PR readiness did not return a base branch")
        branch_policy = branch_rule_policy(base_branch, cwd)
    if review_decision in {None, ""}:
        assert branch_policy is not None
        if branch_policy["required_approving_review_count"] > 0:
            review_decision = "REVIEW_REQUIRED"
    if review_decision in {"APPROVED", None, ""}:
        add(findings, "PASS", "pr.review_decision", "No blocking review decision is present.", actual=review_decision)
    elif review_decision == "REVIEW_REQUIRED" and allow_admin_review_bypass:
        add(findings, "WARN", "pr.review_decision", "Required review is bypassable by explicitly authorized admin direct merge.", actual=review_decision, expected="APPROVED or admin bypass")
    elif review_decision == "REVIEW_REQUIRED":
        add(findings, "ERROR", "pr.review_decision", "PR still requires review before merge.", actual=review_decision, expected="APPROVED")
    else:
        add(findings, "ERROR", "pr.review_decision", "PR has a blocking review decision.", actual=review_decision, expected="APPROVED")

    required_checks = None
    if isinstance(raw_rollup, list):
        assert branch_policy is not None
        policy_checks = branch_policy["required_status_checks"]
        assert isinstance(policy_checks, list)
        required_checks = policy_checks
    status_rollup_findings(
        pr_data,
        findings,
        required_checks=required_checks,
    )

    if pr_data.get("autoMergeRequest"):
        add(findings, "PASS", "pr.auto_merge_request", "Auto-merge is already configured.", actual=True)
    else:
        add(findings, "WARN", "pr.auto_merge_request", "Auto-merge is not configured.", actual=False)

    summary = {
        "number": pr_data.get("number"),
        "url": pr_data.get("url"),
        "base": pr_data.get("baseRefName"),
        "head": pr_data.get("headRefName"),
        "head_oid": pr_data.get("headRefOid"),
    }
    return summary, findings


def emit(summary: dict[str, object], findings: list[Finding], *, as_json: bool, contract_path: pathlib.Path) -> int:
    """Print JSON or compact text and return an error status only on ERROR."""

    counts = count_by_level(findings)

    payload = {
        "contract": str(contract_path),
        "summary": summary,
        "counts": counts,
        "findings": [asdict(finding) for finding in findings],
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"summary: {json.dumps(summary, sort_keys=True)}")
        print(f"counts: {json.dumps(counts, sort_keys=True)}")
        for finding in findings:
            print(f"[{finding.level}] {finding.check}: {finding.message}")
            if finding.actual is not None:
                print(f"  actual: {json.dumps(finding.actual, sort_keys=True)}")
            if finding.expected is not None:
                print(f"  expected: {json.dumps(finding.expected, sort_keys=True)}")
    return 1 if counts.get(ERROR, 0) else 0


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""

    parser = argparse.ArgumentParser(
        prog="python -m github_pr_workflow validate",
        description="Validate the live GitHub PR readiness contract before merge.",
    )
    parser.add_argument("--contract", type=pathlib.Path, default=default_contract_path(), help="PR readiness deterministic contract JSON.")
    parser.add_argument("--cwd", type=pathlib.Path, default=pathlib.Path.cwd(), help="Repo working directory used for git and gh context.")
    parser.add_argument("--pr", help="PR number, URL, or branch. Defaults to the PR attached to the current branch.")
    parser.add_argument("--allow-admin-review-bypass", action="store_true", help="Warn instead of error when REVIEW_REQUIRED is the only review blocker for an explicitly authorized admin direct merge.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def validate_readiness(
    selector: str | None,
    cwd: pathlib.Path,
    contract_path: pathlib.Path,
    *,
    allow_admin_review_bypass: bool = False,
) -> tuple[dict[str, object], list[Finding]]:
    """Evaluate readiness and enforce that every emitted check is contract-backed."""

    contract = load_contract(contract_path)
    summary, findings = pr_readiness(
        selector,
        cwd,
        allow_admin_review_bypass=allow_admin_review_bypass,
    )
    unknown = sorted(
        {finding.check for finding in findings} - contract_check_ids(contract)
    )
    if unknown:
        add(
            findings,
            "ERROR",
            "contract.unknown_check_ids",
            "Validator emitted checks missing from the PR readiness contract.",
            actual=unknown,
        )
    return summary, findings


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments, evaluate the live PR, and emit the report."""

    parser = build_parser()
    args = parser.parse_args(argv)
    cwd = args.cwd.resolve()
    try:
        contract_path = args.contract.resolve()
        selector = args.pr
        if selector is None:
            selector = current_branch(cwd)
        summary, findings = validate_readiness(
            selector,
            cwd,
            contract_path,
            allow_admin_review_bypass=args.allow_admin_review_bypass,
        )
        return emit(summary, findings, as_json=args.json, contract_path=contract_path)
    except CommandError as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, sort_keys=True))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
