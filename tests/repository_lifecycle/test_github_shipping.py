from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
from typing import Any

import pytest

from tests.repository_lifecycle.support import (
    load_pr_workflow_module,
)


def test_integrated_ship_delegates_admin_semantics_to_merge_owner(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ship = load_pr_workflow_module(monkeypatch, "ship")
    repo = tmp_path / "repo"
    repo.mkdir()
    head = "a" * 40
    checkpoint = tmp_path / "ship-checkpoint.json"
    events: list[str] = []
    state = {
        "phase": "gates_passed",
        "pr": 24,
        "url": "https://example.invalid/pull/24",
        "commit": head,
        "gate_disposition": "admin_authorized",
    }
    ci = {
        "base": "main",
        "head_oid": head,
        "review_required": True,
    }

    monkeypatch.setattr(
        ship.merge,
        "restore_unfinished_checkpoints",
        lambda root: events.append("recover"),
    )
    monkeypatch.setattr(ship, "_repository_name", lambda *args: "example/repository")
    monkeypatch.setattr(ship, "_resolve_commit", lambda *args: head)
    monkeypatch.setattr(ship, "_load_pending_work_scope", lambda *args: (None, None))
    monkeypatch.setattr(
        ship,
        "_load_or_create_checkpoint",
        lambda *args: (checkpoint, state),
    )
    monkeypatch.setattr(
        ship,
        "_live_pr",
        lambda *args: {"state": "OPEN", "headRefOid": head},
    )
    monkeypatch.setattr(
        ship,
        "run_parallel_gates",
        lambda *args, **kwargs: {
            "disposition": "admin_authorized",
            "ci": ci,
            "codex": {"active_threads": 0, "unresolved_threads": 0},
        },
    )
    monkeypatch.setattr(ship, "_write_checkpoint", lambda *args: None)
    monkeypatch.setattr(ship.sync, "sync_main", lambda args: {"head": "b" * 40})
    monkeypatch.setattr(ship, "_remove_completed_pr_checkpoints", lambda *args: [])

    def delegated(
        args: argparse.Namespace,
        *,
        expected_head: str,
        readiness_summary: dict[str, object],
        recover_checkpoints: bool,
    ) -> dict[str, Any]:
        events.append("merge")
        assert args.admin is True
        assert args.auto is False
        assert expected_head == head
        assert readiness_summary is ci
        assert recover_checkpoints is False
        return {
            "status": "merged",
            "merged_at": "2026-08-01T00:00:00Z",
            "merge_commit": "c" * 40,
        }

    monkeypatch.setattr(ship.merge, "merge_verified_pr", delegated)
    result = ship.ship(
        argparse.Namespace(
            repo_root=repo,
            repo="example/repository",
            commit=head,
            head_branch="release/local",
            base_branch="main",
            remote_name="origin",
            title=None,
            body=None,
            merge_method="merge",
            delete_branch=False,
            reusable_head=False,
            pending_work_check=False,
            pending_work_scope=None,
            ci_wait_seconds=0,
            review_wait_seconds=0,
            interval_seconds=0,
        )
    )

    assert result["status"] == "shipped"
    assert events == ["recover", "merge"]

    review_task_root = tmp_path / "tmp" / repo.name / "review-fix"
    review_task_root.mkdir(parents=True)
    review_request = review_task_root / "replies.json"
    review_request.write_text("{}\n", encoding="utf-8", newline="\n")
    review_state: dict[str, Any] = {
        "phase": "pr_ready",
        "pr": 24,
        "url": "https://example.invalid/pull/24",
        "commit": head,
    }
    address_calls: list[pathlib.Path] = []

    def address_request(
        request_path: pathlib.Path,
        *,
        cwd: pathlib.Path | None = None,
    ) -> dict[str, Any]:
        address_calls.append(request_path)
        assert cwd == repo
        return {
            "status": "addressed",
            "repo": "example/repository",
            "pr": 24,
            "head_oid": head,
            "reply_count": 1,
            "posted": 1,
            "resolved": 1,
            "already_addressed": 0,
        }

    monkeypatch.setattr(ship.codex_review, "address_request", address_request)
    review_args = argparse.Namespace(review_replies_request=review_request)
    addressed = ship._address_review_replies(
        review_args,
        state=review_state,
        checkpoint_path=checkpoint,
        repo_root=repo,
        repository="example/repository",
        pr="24",
        commit=head,
    )
    assert addressed == {
        "status": "addressed",
        "reply_count": 1,
        "posted": 1,
        "resolved": 1,
        "already_addressed": 0,
        "cleanup": "removed",
    }
    assert not review_request.exists() and not review_task_root.exists()
    assert review_state["review_replies"]["cleanup"] == "removed"
    assert ship._address_review_replies(
        review_args,
        state=review_state,
        checkpoint_path=checkpoint,
        repo_root=repo,
        repository="example/repository",
        pr="24",
        commit=head,
    ) == addressed
    assert address_calls == [review_request.resolve()]

    review_result = {
        "repo": "example/repository",
        "pr": 24,
        "url": "https://example.invalid/pull/24",
        "head_oid": head,
        "active_codex_thread_count": 1,
        "active_codex_threads": [
            {
                "id": "PRRT_1",
                "thread_id": "PRRT_1",
                "path": "skills/example/SKILL.md",
                "line": 17,
                "body": "Preserve the exact contract.",
                "top_comment_database_id": 91,
                "comment_url": "https://example.invalid/comment/91",
            }
        ],
        "unresolved_review_thread_count": 1,
    }
    with pytest.raises(ship.ShipBlocked) as review_blocked:
        ship._enforce_review_thread_gate(
            argparse.Namespace(repo_root=repo, base_branch="main"),
            review_result,
            head,
            base_branch="main",
        )
    review_payload = review_blocked.value.payload["blocker"]
    assert review_payload["kind"] == "review_threads"
    assert review_payload["threads"][0] == {
        "thread_id": "PRRT_1",
        "path": "skills/example/SKILL.md",
        "line": 17,
        "is_outdated": False,
        "body": "Preserve the exact contract.",
        "top_comment_database_id": 91,
        "comment_url": "https://example.invalid/comment/91",
    }

    failing = ship.readiness.Finding(
        level="ERROR",
        check="pr.status_checks",
        message="One or more status checks are failing.",
        actual=["validate"],
    )
    monkeypatch.setattr(
        ship.readiness,
        "validate_readiness",
        lambda *args, **kwargs: (
            {
                "number": 24,
                "url": "https://example.invalid/pull/24",
                "head_oid": head,
            },
            [failing],
        ),
    )
    monkeypatch.setattr(
        ship,
        "run_json_command",
        lambda *args, **kwargs: argparse.Namespace(
            ok=True,
            data=[
                {
                    "name": "validate",
                    "state": "FAILURE",
                    "bucket": "fail",
                    "workflow": "CI",
                    "link": (
                        "https://github.com/example/repository/"
                        "actions/runs/42/job/84"
                    ),
                }
            ],
            message=None,
        ),
    )
    monkeypatch.setattr(
        ship,
        "run_command",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            stdout=(
                "setup\nFAILED tests/test_example.py::test_contract\n"
                "assert False\n"
            ),
            stderr="",
        ),
    )
    with pytest.raises(ship.ShipBlocked) as ci_blocked:
        ship.wait_for_ci_gate(
            "24",
            repo,
            head,
            repository="example/repository",
            wait_seconds=0,
            interval_seconds=0,
        )
    ci_payload = ci_blocked.value.payload["blocker"]
    assert ci_payload["kind"] == "ci"
    assert ci_payload["head_oid"] == head
    assert ci_payload["check"] == {
        "name": "validate",
        "state": "FAILURE",
        "workflow": "CI",
        "url": "https://github.com/example/repository/actions/runs/42/job/84",
        "run_id": "42",
        "job_id": "84",
        "failed_log_excerpt": (
            "setup\nFAILED tests/test_example.py::test_contract\nassert False"
        ),
        "failing_names": ["validate"],
        "diagnostic": None,
    }

    clock = {"now": 0.0}
    validation_times: list[float] = []
    ambiguous = ship.readiness.Finding(
        level="ERROR",
        check="pr.status_checks",
        message=ship.readiness.UNKNOWN_STATUS_CHECK_MESSAGE,
        actual={
            "index": 0,
            "name": "validate",
            "conclusion": None,
            "status": "FUTURE_STATE",
            "state": None,
        },
    )

    def ambiguous_readiness(
        *args: Any, **kwargs: Any
    ) -> tuple[dict[str, Any], list[Any]]:
        validation_times.append(clock["now"])
        return (
            {
                "number": 24,
                "url": "https://example.invalid/pull/24",
                "head_oid": head,
            },
            [ambiguous],
        )

    def uncertainty_json(
        command: list[str],
        *args: Any,
        **kwargs: Any,
    ) -> argparse.Namespace:
        if command[1:3] == ["pr", "checks"]:
            return argparse.Namespace(
                ok=True,
                data=[
                    {
                        "name": "validate",
                        "state": "FUTURE_STATE",
                        "bucket": "pending",
                        "workflow": "CI",
                        "link": (
                            "https://github.com/example/repository/"
                            "actions/runs/42/job/84"
                        ),
                    }
                ],
                message=None,
            )
        if command[1:3] == ["run", "view"]:
            assert command[-2:] == [
                "--json",
                "status,conclusion,headSha,url,name,workflowName,jobs",
            ]
            assert "--jq" not in command
            return argparse.Namespace(
                ok=True,
                data={
                    "status": "in_progress",
                    "conclusion": None,
                    "headSha": head,
                    "url": (
                        "https://github.com/example/repository/actions/runs/42"
                    ),
                    "name": "CI",
                    "workflowName": "CI",
                    "jobs": [
                        {
                            "databaseId": 84,
                            "name": "validate",
                            "conclusion": None,
                            "url": (
                                "https://github.com/example/repository/"
                                "actions/runs/42/job/84"
                            ),
                        },
                        {
                            "databaseId": 85,
                            "name": "other",
                            "conclusion": "success",
                            "url": (
                                "https://github.com/example/repository/"
                                "actions/runs/42/job/85"
                            ),
                        },
                    ],
                },
                message=None,
            )
        raise AssertionError(command)

    monkeypatch.setattr(ship.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        ship.time,
        "sleep",
        lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
    )
    monkeypatch.setattr(ship.readiness, "validate_readiness", ambiguous_readiness)
    monkeypatch.setattr(ship, "run_json_command", uncertainty_json)
    with pytest.raises(ship.ShipBlocked) as ambiguous_blocked:
        ship.wait_for_ci_gate(
            "24",
            repo,
            head,
            repository="example/repository",
            wait_seconds=900,
            interval_seconds=10,
        )
    ambiguous_payload = ambiguous_blocked.value.payload["blocker"]
    assert ambiguous_payload["kind"] == "ci_ambiguous"
    assert ambiguous_payload["head_oid"] == head
    assert ambiguous_payload["grace_seconds"] == 60
    assert ambiguous_payload["diagnostic"]["finding"]["actual"] == ambiguous.actual
    assert ambiguous_payload["diagnostic"]["normalized_checks"][0]["bucket"] == (
        "pending"
    )
    assert ambiguous_payload["diagnostic"]["action_run"]["head_matches"] is True
    assert ambiguous_payload["diagnostic"]["action_run"]["matching_jobs"] == [
        {
            "database_id": 84,
            "name": "validate",
            "conclusion": None,
            "url": (
                "https://github.com/example/repository/actions/runs/42/job/84"
            ),
        }
    ]
    assert validation_times[:2] == [0.0, 0.0]
    assert validation_times[-1] == 60.0

    clock["now"] = 0.0
    pending_times: list[float] = []
    explicit_pending = ship.readiness.Finding(
        level="WARN",
        check="pr.status_checks",
        message="Status checks are still pending.",
        actual=["validate"],
    )

    def pending_then_pass(*args: Any, **kwargs: Any) -> tuple[dict[str, Any], list[Any]]:
        pending_times.append(clock["now"])
        findings = [explicit_pending] if clock["now"] < 70 else []
        return (
            {
                "number": 24,
                "url": "https://example.invalid/pull/24",
                "head_oid": head,
            },
            findings,
        )

    monkeypatch.setattr(ship.readiness, "validate_readiness", pending_then_pass)
    monkeypatch.setattr(
        ship,
        "run_json_command",
        lambda *args, **kwargs: pytest.fail(
            "explicit pending checks must not use uncertainty diagnostics"
        ),
    )
    completed = ship.wait_for_ci_gate(
        "24",
        repo,
        head,
        repository="example/repository",
        wait_seconds=900,
        interval_seconds=10,
    )
    assert completed["pending"] == 0
    assert 60.0 in pending_times
    assert pending_times[-1] == 70.0

    clock["now"] = 0.0
    missing = ship.readiness.Finding(
        level="WARN",
        check="pr.status_checks",
        message=ship.readiness.REQUIRED_STATUS_CHECKS_MISSING_MESSAGE,
        actual=["validate"],
    )
    monkeypatch.setattr(
        ship.readiness,
        "validate_readiness",
        lambda *args, **kwargs: (
            {
                "number": 24,
                "url": "https://example.invalid/pull/24",
                "head_oid": head,
            },
            [missing],
        ),
    )
    monkeypatch.setattr(
        ship,
        "run_json_command",
        lambda *args, **kwargs: argparse.Namespace(
            ok=False,
            data=None,
            message="no checks reported on the release/local branch",
        ),
    )
    with pytest.raises(ship.ShipBlocked) as missing_blocked:
        ship.wait_for_ci_gate(
            "24",
            repo,
            head,
            repository="example/repository",
            wait_seconds=900,
            interval_seconds=10,
        )
    missing_payload = missing_blocked.value.payload["blocker"]
    assert missing_payload["kind"] == "checks_missing"
    assert missing_payload["grace_seconds"] == 60
    assert missing_payload["diagnostic"]["checks_diagnostic"].startswith(
        "no checks reported"
    )


def test_dependency_finalization_delegates_admin_to_shared_merge(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependency = load_pr_workflow_module(monkeypatch, "dependency_finalization")
    commands: list[list[str]] = []

    def run_command(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "merged", "head": "a" * 40}),
            stderr="",
        )

    monkeypatch.setattr(dependency, "run_command", run_command)
    monkeypatch.setattr(dependency, "merge_helper_directory", lambda: tmp_path)
    result, error = dependency.merge_pr(
        "example/repository",
        24,
        tmp_path,
        "merge",
        expected_head="a" * 40,
        admin=True,
        wait_seconds=0,
        interval_seconds=0,
    )

    assert error is None
    assert result == {"status": "merged", "head": "a" * 40}
    command = commands[0]
    assert command[1:4] == ["-m", "github_pr_workflow", "merge"]
    assert "--admin" in command
    assert command[command.index("--expected-head") + 1] == "a" * 40
    assert "enforce_admins" not in " ".join(command)
