from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from typing import Any

import pytest

from tests.repository_lifecycle.support import (
    PR_WORKFLOW_ENTRYPOINT,
    PR_WORKFLOW_SCRIPTS,
    load_pr_workflow_module,
    merge_args,
    merged_pr_state,
)
from tests.support.repositories import (
    run_git,
)


@pytest.mark.parametrize("enabled", [True, False])
def test_read_admin_enforcement_preserves_boolean_state(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    monkeypatch.setattr(
        merge,
        "require_output",
        lambda command, *, cwd: json.dumps({"enabled": enabled}),
    )

    assert merge._read_admin_enforcement("endpoint", cwd=tmp_path) is enabled


def test_private_free_plan_limit_skips_admin_protection_mutation(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    repo = tmp_path / "repo"
    repo.mkdir()
    head = "a" * 40
    commands: list[tuple[str, ...]] = []

    def require_output(command: list[str], *, cwd: pathlib.Path) -> str:
        commands.append(tuple(command))
        if command[:2] == ["gh", "api"]:
            raise merge.CommandError(
                "gh api failed\n"
                "Upgrade to GitHub Pro or make this repository public "
                "to enable this feature. (HTTP 403)"
            )
        if command[:3] == ["gh", "pr", "view"]:
            return merged_pr_state(head)
        raise AssertionError(command)

    def require_success(command: list[str], *, cwd: pathlib.Path) -> None:
        commands.append(tuple(command))
        if command[:3] != ["gh", "pr", "merge"]:
            raise AssertionError(command)

    monkeypatch.setattr(merge, "require_output", require_output)
    monkeypatch.setattr(merge, "require_success", require_success)

    result = merge.merge_verified_pr(
        merge_args(repo, admin=True),
        expected_head=head,
        readiness_summary={
            "base": "main",
            "head_oid": head,
            "review_required": True,
        },
        recover_checkpoints=False,
    )

    assert result["status"] == "merged"
    assert not any(
        command[:2] == ("gh", "api") and "--method" in command
        for command in commands
    )


def test_read_admin_enforcement_rejects_unrelated_forbidden_error(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")

    def require_output(command: list[str], *, cwd: pathlib.Path) -> str:
        raise merge.CommandError("Resource not accessible by integration (HTTP 403)")

    monkeypatch.setattr(merge, "require_output", require_output)

    with pytest.raises(merge.CommandError, match="Resource not accessible"):
        merge._read_admin_enforcement("endpoint", cwd=tmp_path)


@pytest.mark.parametrize("initial", [True, False])
@pytest.mark.parametrize("merge_fails", [False, True])
def test_admin_enforcement_restores_exact_state_on_every_exit(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    initial: bool,
    merge_fails: bool,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    repo = tmp_path / "repo"
    repo.mkdir()
    checkpoints = tmp_path / "checkpoints"
    head = "a" * 40
    state = {"enabled": initial}
    commands: list[tuple[str, ...]] = []

    def require_output(command: list[str], *, cwd: pathlib.Path) -> str:
        commands.append(tuple(command))
        if command[:2] == ["gh", "api"]:
            return json.dumps({"url": "https://api.invalid", **state})
        if command[:3] == ["gh", "pr", "view"]:
            return merged_pr_state(head)
        raise AssertionError(command)

    def require_success(command: list[str], *, cwd: pathlib.Path) -> None:
        commands.append(tuple(command))
        if command[:4] == ["gh", "api", "--method", "DELETE"]:
            state["enabled"] = False
            return
        if command[:4] == ["gh", "api", "--method", "POST"]:
            state["enabled"] = True
            return
        if command[:3] == ["gh", "pr", "merge"]:
            if merge_fails:
                raise merge.CommandError("merge failed")
            return
        raise AssertionError(command)

    monkeypatch.setattr(merge, "require_output", require_output)
    monkeypatch.setattr(merge, "require_success", require_success)
    monkeypatch.setattr(merge, "_checkpoint_directory", lambda _: checkpoints)
    summary = {
        "base": "main",
        "head_oid": head,
        "review_required": True,
    }

    if merge_fails:
        with pytest.raises(merge.CommandError, match="merge failed"):
            merge.merge_verified_pr(
                merge_args(repo, admin=True),
                expected_head=head,
                readiness_summary=summary,
                recover_checkpoints=False,
            )
    else:
        result = merge.merge_verified_pr(
            merge_args(repo, admin=True),
            expected_head=head,
            readiness_summary=summary,
            recover_checkpoints=False,
        )
        assert result["status"] == "merged"

    labels = []
    for command in commands:
        if command[:2] == ("gh", "api") and "--method" not in command:
            labels.append("read")
        elif command[:4] == ("gh", "api", "--method", "DELETE"):
            labels.append("disable")
        elif command[:4] == ("gh", "api", "--method", "POST"):
            labels.append("restore")
        elif command[:3] == ("gh", "pr", "merge"):
            labels.append("merge")
        elif command[:3] == ("gh", "pr", "view"):
            labels.append("view")
    expected = ["read"]
    if initial:
        expected.append("disable")
    expected.append("merge")
    if not merge_fails:
        expected.append("view")
    if initial:
        expected.append("restore")
    expected.append("read")
    assert labels == expected
    assert state["enabled"] is initial
    assert not list(checkpoints.glob("*.json"))
    protection_calls = [command for command in commands if command[:2] == ("gh", "api")]
    assert protection_calls
    assert all(command[-1].endswith("/protection/enforce_admins") for command in protection_calls)


@pytest.mark.parametrize(
    ("admin", "auto", "review_required"),
    [(False, False, False), (True, True, True)],
)
def test_non_admin_and_auto_merge_never_toggle_protection(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    admin: bool,
    auto: bool,
    review_required: bool,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    repo = tmp_path / "repo"
    repo.mkdir()
    head = "a" * 40
    commands: list[tuple[str, ...]] = []

    def require_success(command: list[str], *, cwd: pathlib.Path) -> None:
        commands.append(tuple(command))

    def require_output(command: list[str], *, cwd: pathlib.Path) -> str:
        commands.append(tuple(command))
        return merged_pr_state(head)

    monkeypatch.setattr(merge, "require_success", require_success)
    monkeypatch.setattr(merge, "require_output", require_output)
    merge.merge_verified_pr(
        merge_args(repo, admin=admin, auto=auto),
        expected_head=head,
        readiness_summary={
            "base": "main",
            "head_oid": head,
            "review_required": review_required,
        },
        recover_checkpoints=False,
    )

    assert not any(command[:2] == ("gh", "api") for command in commands)
    assert [command[:3] for command in commands] == [
        ("gh", "pr", "merge"),
        ("gh", "pr", "view"),
    ]


def test_disable_failure_prevents_merge_and_still_verifies_restore(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    repo = tmp_path / "repo"
    repo.mkdir()
    checkpoints = tmp_path / "checkpoints"
    head = "a" * 40
    state = {"enabled": True}
    commands: list[tuple[str, ...]] = []

    def require_output(command: list[str], *, cwd: pathlib.Path) -> str:
        commands.append(tuple(command))
        return json.dumps(state)

    def require_success(command: list[str], *, cwd: pathlib.Path) -> None:
        commands.append(tuple(command))
        if command[:4] == ["gh", "api", "--method", "DELETE"]:
            state["enabled"] = False
            raise merge.CommandError("disable failed")
        if command[:4] == ["gh", "api", "--method", "POST"]:
            state["enabled"] = True
            return
        raise AssertionError("merge must not be attempted after disable failure")

    monkeypatch.setattr(merge, "require_output", require_output)
    monkeypatch.setattr(merge, "require_success", require_success)
    monkeypatch.setattr(merge, "_checkpoint_directory", lambda _: checkpoints)

    with pytest.raises(merge.CommandError, match="disable failed"):
        merge.merge_verified_pr(
            merge_args(repo, admin=True),
            expected_head=head,
            readiness_summary={
                "base": "main",
                "head_oid": head,
                "review_required": True,
            },
            recover_checkpoints=False,
        )

    assert not any(command[:3] == ("gh", "pr", "merge") for command in commands)
    assert state["enabled"] is True
    assert not list(checkpoints.glob("*.json"))


def test_restore_failure_is_critical_and_retains_checkpoint(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    repo = tmp_path / "repo"
    repo.mkdir()
    checkpoints = tmp_path / "checkpoints"
    head = "a" * 40
    state = {"enabled": True}

    def require_output(command: list[str], *, cwd: pathlib.Path) -> str:
        if command[:2] == ["gh", "api"]:
            return json.dumps(state)
        return merged_pr_state(head)

    def require_success(command: list[str], *, cwd: pathlib.Path) -> None:
        if command[:4] == ["gh", "api", "--method", "DELETE"]:
            state["enabled"] = False
            return
        if command[:4] == ["gh", "api", "--method", "POST"]:
            raise merge.CommandError("restore failed")
        if command[:3] == ["gh", "pr", "merge"]:
            return
        raise AssertionError(command)

    monkeypatch.setattr(merge, "require_output", require_output)
    monkeypatch.setattr(merge, "require_success", require_success)
    monkeypatch.setattr(merge, "_checkpoint_directory", lambda _: checkpoints)

    with pytest.raises(merge.CriticalRestoreError) as raised:
        merge.merge_verified_pr(
            merge_args(repo, admin=True),
            expected_head=head,
            readiness_summary={
                "base": "main",
                "head_oid": head,
                "review_required": True,
            },
            recover_checkpoints=False,
        )

    payload = raised.value.payload
    assert payload["status"] == "critical"
    assert payload["repository"] == "example/repository"
    assert payload["base_branch"] == "main"
    assert payload["pr"] == "24"
    assert payload["head"] == head
    assert payload["merge_state"] == "MERGED"
    assert "--method POST" in payload["recovery"]
    retained = list(checkpoints.glob("*.json"))
    assert len(retained) == 1
    assert set(json.loads(retained[0].read_text(encoding="utf-8"))) == {
        "version",
        "repository",
        "base_branch",
        "pr",
        "expected_head",
        "enforce_admins",
    }


def test_interrupted_checkpoint_recovers_before_later_merge(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    repo = tmp_path / "repo"
    repo.mkdir()
    checkpoints = tmp_path / "checkpoints"
    head = "a" * 40
    checkpoint = merge._checkpoint_document(
        "example/repository", "release/main", "24", head
    )
    monkeypatch.setattr(merge, "_checkpoint_directory", lambda _: checkpoints)
    path = merge._checkpoint_path(repo, "example/repository", "release/main")
    merge._write_restore_checkpoint(path, checkpoint)
    state = {"enabled": False}
    commands: list[tuple[str, ...]] = []

    def require_output(command: list[str], *, cwd: pathlib.Path) -> str:
        commands.append(tuple(command))
        if command[:2] == ["gh", "api"]:
            return json.dumps(state)
        return merged_pr_state(head)

    def require_success(command: list[str], *, cwd: pathlib.Path) -> None:
        commands.append(tuple(command))
        if command[:4] == ["gh", "api", "--method", "POST"]:
            state["enabled"] = True

    monkeypatch.setattr(merge, "require_output", require_output)
    monkeypatch.setattr(merge, "require_success", require_success)

    merge.merge_verified_pr(
        merge_args(repo, admin=False),
        expected_head=head,
    )

    labels = [
        "api" if command[:2] == ("gh", "api") else command[2]
        for command in commands
    ]
    assert labels == ["api", "api", "api", "merge", "view"]
    assert "%2F" in commands[0][-1]
    assert state["enabled"] is True
    assert not path.exists()


def test_admin_restore_checkpoint_is_shared_across_worktrees(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    repo = tmp_path / "repo"
    linked = tmp_path / "linked"
    repo.mkdir()
    assert run_git(repo, "init", "-b", "main").returncode == 0
    assert run_git(repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(repo, "config", "user.name", "Test Agent").returncode == 0
    (repo / "README.md").write_text("base\n", encoding="utf-8", newline="\n")
    assert run_git(repo, "add", "README.md").returncode == 0
    assert run_git(repo, "commit", "-m", "base").returncode == 0
    assert run_git(repo, "branch", "linked").returncode == 0
    assert run_git(repo, "worktree", "add", str(linked), "linked").returncode == 0

    assert merge._checkpoint_directory(repo) == merge._checkpoint_directory(linked)


def test_admin_bypass_accepts_only_review_required_readiness(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    readiness = load_pr_workflow_module(monkeypatch, "readiness")
    head = "a" * 40
    summary = {"base": "main", "head_oid": head}
    review = readiness.Finding(
        "WARN",
        "pr.review_decision",
        "Required review.",
        actual="REVIEW_REQUIRED",
    )
    pending = readiness.Finding(
        "WARN",
        "pr.status_checks",
        "Pending checks.",
        actual=["CI"],
    )
    requested = readiness.Finding(
        "ERROR",
        "pr.review_decision",
        "Changes requested.",
        actual="CHANGES_REQUESTED",
    )

    monkeypatch.setattr(
        merge.readiness,
        "validate_readiness",
        lambda *args, **kwargs: (summary, [review]),
    )
    accepted = merge._validate_readiness(
        "24", tmp_path, allow_admin_review_bypass=True
    )
    assert accepted["review_required"] is True

    for blocker in (pending, requested):
        monkeypatch.setattr(
            merge.readiness,
            "validate_readiness",
            lambda *args, blocker=blocker, **kwargs: (
                summary,
                [review, blocker],
            ),
        )
        with pytest.raises(merge.WorkflowError, match="PR readiness failed"):
            merge._validate_readiness(
                "24", tmp_path, allow_admin_review_bypass=True
            )

    queries: list[str] = []

    def branch_rules(
        query: str,
        variables: dict[str, Any],
        cwd: pathlib.Path,
    ) -> dict[str, Any]:
        queries.append(query)
        assert variables["qualifiedName"] == "refs/heads/main"
        assert cwd == tmp_path
        return {
            "data": {
                "repository": {
                    "ref": {
                        "name": "main",
                        "branchProtectionRule": {
                            "requiresApprovingReviews": False,
                            "requiredApprovingReviewCount": 0,
                            "requiresConversationResolution": False,
                            "requiresStatusChecks": True,
                            "requiredStatusChecks": [{"context": "classic-ci"}],
                        },
                        "rules": {
                            "nodes": [
                                {
                                    "type": "REQUIRED_STATUS_CHECKS",
                                    "parameters": {
                                        "__typename": (
                                            "RequiredStatusChecksParameters"
                                        ),
                                        "requiredStatusChecks": [
                                            {"context": "ruleset-ci"}
                                        ],
                                    },
                                }
                            ],
                            "pageInfo": {
                                "hasNextPage": False,
                                "endCursor": None,
                            },
                        },
                    }
                }
            }
        }

    monkeypatch.setattr(readiness, "current_repository", lambda cwd: ("acme", "repo"))
    monkeypatch.setattr(readiness, "gh_graphql", branch_rules)
    policy = readiness.branch_rule_policy("main", tmp_path)
    assert policy == {
        "required_approving_review_count": 0,
        "required_review_thread_resolution": False,
        "required_status_checks": ["classic-ci", "ruleset-ci"],
    }
    assert "RequiredStatusChecksParameters" in queries[0]
    assert "requiredStatusChecks" in queries[0]

    pr_data = {
        "number": 24,
        "url": "https://example.invalid/pull/24",
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "reviewDecision": "APPROVED",
        "statusCheckRollup": [],
        "headRefName": "release/local",
        "headRefOid": head,
        "baseRefName": "main",
        "autoMergeRequest": None,
    }
    monkeypatch.setattr(readiness, "gh_pr_view", lambda *args: pr_data)
    monkeypatch.setattr(readiness, "branch_rule_policy", lambda *args: policy)
    _, findings = readiness.pr_readiness("24", tmp_path)
    status_finding = next(
        finding for finding in findings if finding.check == "pr.status_checks"
    )
    assert status_finding.message == readiness.REQUIRED_STATUS_CHECKS_MISSING_MESSAGE
    assert status_finding.actual == ["classic-ci", "ruleset-ci"]

    pr_data["statusCheckRollup"] = [
        {
            "name": "classic-ci",
            "status": "COMPLETED",
            "conclusion": "SUCCESS",
        }
    ]
    _, findings = readiness.pr_readiness("24", tmp_path)
    status_finding = next(
        finding for finding in findings if finding.check == "pr.status_checks"
    )
    assert status_finding.message == readiness.REQUIRED_STATUS_CHECKS_MISSING_MESSAGE
    assert status_finding.actual == ["ruleset-ci"]

    no_ci_policy = {**policy, "required_status_checks": []}
    pr_data["statusCheckRollup"] = []
    monkeypatch.setattr(
        readiness,
        "branch_rule_policy",
        lambda *args: no_ci_policy,
    )
    _, findings = readiness.pr_readiness("24", tmp_path)
    status_finding = next(
        finding for finding in findings if finding.check == "pr.status_checks"
    )
    assert status_finding.message == readiness.NO_STATUS_CHECKS_MESSAGE
    assert status_finding.actual is None

    findings = []
    readiness.status_rollup_findings(
        {
            "statusCheckRollup": [
                {"name": "future-ci", "status": "FUTURE_STATE"}
            ]
        },
        findings,
    )
    assert findings[0].message == readiness.UNKNOWN_STATUS_CHECK_MESSAGE
    assert findings[0].actual == {
        "index": 0,
        "name": "future-ci",
        "conclusion": None,
        "status": "FUTURE_STATE",
        "state": None,
    }


def test_merge_pr_runs_all_gates_before_shared_merge(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    repo = tmp_path / "repo"
    repo.mkdir()
    head = "a" * 40
    events: list[str] = []

    monkeypatch.setattr(
        merge,
        "restore_unfinished_checkpoints",
        lambda root: events.append("recover"),
    )

    def validate(*args: Any, **kwargs: Any) -> dict[str, object]:
        events.append("readiness")
        return {
            "base": "main",
            "head_oid": head,
            "review_required": True,
        }

    monkeypatch.setattr(merge, "_validate_readiness", validate)
    def codex_gate(*args: Any, **kwargs: Any) -> dict[str, object]:
        events.append("codex")
        return {
            "head_oid": head,
            "active_codex_thread_count": 0,
            "unresolved_review_thread_count": 0,
        }

    monkeypatch.setattr(
        merge.codex_review,
        "wait_for_codex_threads",
        codex_gate,
    )

    def delegated(*args: Any, **kwargs: Any) -> dict[str, Any]:
        events.append("merge")
        assert kwargs["readiness_summary"]["review_required"] is True
        assert kwargs["recover_checkpoints"] is False
        return {"status": "merged"}

    monkeypatch.setattr(merge, "merge_verified_pr", delegated)
    result = merge.merge_pr(
        argparse.Namespace(
            **vars(merge_args(repo, admin=True)),
            expected_head=head,
            wait_seconds=0,
            interval_seconds=0,
        )
    )

    assert result["status"] == "merged"
    assert events == ["recover", "readiness", "codex", "readiness", "merge"]


def test_unresolved_required_conversation_blocks_before_shared_merge(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    repo = tmp_path / "repo"
    repo.mkdir()
    head = "a" * 40
    monkeypatch.setattr(merge, "restore_unfinished_checkpoints", lambda root: None)
    monkeypatch.setattr(
        merge,
        "_validate_readiness",
        lambda *args, **kwargs: {
            "base": "main",
            "head_oid": head,
            "review_required": True,
        },
    )
    monkeypatch.setattr(
        merge.codex_review,
        "wait_for_codex_threads",
        lambda *args, **kwargs: {
            "head_oid": head,
            "active_codex_thread_count": 0,
            "unresolved_review_thread_count": 1,
        },
    )
    monkeypatch.setattr(
        merge.readiness,
        "review_thread_resolution_required",
        lambda *args: True,
    )
    monkeypatch.setattr(
        merge,
        "merge_verified_pr",
        lambda *args, **kwargs: pytest.fail("merge must remain gated"),
    )

    with pytest.raises(merge.WorkflowError, match="require resolution"):
        merge.merge_pr(
            argparse.Namespace(
                **vars(merge_args(repo, admin=True)),
                expected_head=head,
                wait_seconds=0,
                interval_seconds=0,
            )
        )


def test_merge_cli_emits_compact_critical_json(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    critical = merge.CriticalRestoreError(
        repository="example/repository",
        base_branch="main",
        pr="24",
        head="a" * 40,
        merge_state="MERGED",
        recovery="gh api --method POST endpoint",
    )

    def fail(args: argparse.Namespace) -> dict[str, Any]:
        raise critical

    monkeypatch.setattr(merge, "merge_pr", fail)
    assert merge.main(["--pr", "24"]) == 1
    output = capsys.readouterr().err.strip()
    assert json.loads(output)["status"] == "critical"
    assert '": "' not in output
    assert '", "' not in output

    direct = subprocess.run(
        [sys.executable, str(PR_WORKFLOW_ENTRYPOINT), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert direct.returncode == 0, direct.stderr
    assert "GitHub PR workflows" in direct.stdout

    module = subprocess.run(
        [sys.executable, "-m", "github_pr_workflow", "--help"],
        cwd=PR_WORKFLOW_SCRIPTS,
        capture_output=True,
        text=True,
        check=False,
    )
    assert module.returncode == 0, module.stderr
    assert "GitHub PR workflows" in module.stdout
