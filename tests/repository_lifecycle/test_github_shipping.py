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
from tests.support.repositories import run_git


@pytest.fixture
def metadata_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """Use real commits while tests intercept every GitHub side effect."""

    repo = tmp_path / "repo"
    repo.mkdir()
    remote = tmp_path / "remote.git"
    assert run_git(tmp_path, "init", "--bare", str(remote)).returncode == 0
    for arguments in (
        ("init", "-b", "main"),
        ("config", "user.email", "test@example.invalid"),
        ("config", "user.name", "Test Agent"),
        ("commit", "--allow-empty", "-m", "Already released baseline"),
        ("remote", "add", "origin", str(remote)),
        ("push", "-u", "origin", "main"),
        ("switch", "-c", "release/local"),
    ):
        result = run_git(repo, *arguments)
        assert result.returncode == 0, result.stderr
    return repo


@pytest.mark.parametrize("multiple", [False, True])
def test_ensure_pr_metadata_describes_only_selected_change_commits(
    metadata_repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch, multiple: bool,
) -> None:
    ensure_pr = load_pr_workflow_module(monkeypatch, "ensure_pr")
    repo = metadata_repo
    assert run_git(
        repo, "commit", "--allow-empty", "-m", "Complete Dev Tools catalog",
        "-m", "Collect registered tools and their configuration.",
    ).returncode == 0
    if multiple:
        assert run_git(repo, "switch", "-c", "collection-policy").returncode == 0
        assert run_git(
            repo, "commit", "--allow-empty", "-m", "Use explicit exclusions",
            "-m", "Preserve configured deployment behavior.",
        ).returncode == 0
        assert run_git(repo, "switch", "release/local").returncode == 0
        assert run_git(
            repo, "merge", "--no-ff", "collection-policy", "-m", "Merge collection-policy",
        ).returncode == 0
    head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    title, body = ensure_pr._default_metadata(repo, "main", head)
    expected_title = "Complete Dev Tools catalog"
    if multiple:
        expected_title += "; Use explicit exclusions"
        assert "Preserve configured deployment behavior." in body
    assert title == expected_title
    assert "Collect registered tools and their configuration." in body
    assert "Already released baseline" not in body
    assert "Merge collection-policy" not in body
    # A later local commit must not leak into metadata for the pinned head.
    assert run_git(repo, "commit", "--allow-empty", "-m", "Later work").returncode == 0
    assert ensure_pr._default_metadata(repo, "main", head) == (title, body)


def test_ensure_pr_metadata_bounds_title_without_dropping_description(
    metadata_repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_pr = load_pr_workflow_module(monkeypatch, "ensure_pr")
    subject = "Complete catalog coverage for " + "collection policy " * 12
    assert run_git(
        metadata_repo, "commit", "--allow-empty", "-m", subject,
        "-m", "Retain the complete explanation in the PR body.",
    ).returncode == 0
    title, body = ensure_pr._default_metadata(metadata_repo, "main", "HEAD")
    assert len(title) <= 120
    assert title.endswith("...")
    assert subject.strip() in body
    assert "Retain the complete explanation in the PR body." in body
    with pytest.raises(ensure_pr.EnsurePrError, match="supply --title and --body"):
        ensure_pr._default_metadata(metadata_repo, "HEAD", "HEAD")


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize(
    ("title", "body"),
    [
        (None, None),
        ("Caller title", None),
        (None, "# Caller body\r\n\r\nKeep `code`, $(literal), café.\r\n"),
        ("Caller title", "Caller body\n\nWith details.\n"),
        (None, ""),
    ],
)
def test_ensure_pr_metadata_preserves_overrides_and_existing_fields(
    metadata_repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
    existing: bool, title: str | None, body: str | None,
) -> None:
    ensure_pr = load_pr_workflow_module(monkeypatch, "ensure_pr")
    repo = metadata_repo
    local_base = run_git(repo, "rev-parse", "main").stdout.strip()
    assert run_git(repo, "commit", "--allow-empty", "-m", "Already merged remote change").returncode == 0
    remote_base = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    assert run_git(repo, "push", "origin", "HEAD:main").returncode == 0
    # Keep both local main and its cached remote ref behind the actual remote.
    assert run_git(repo, "update-ref", "refs/remotes/origin/main", local_base).returncode == 0
    assert run_git(
        repo, "commit", "--allow-empty", "-m", "Complete Dev Tools catalog",
        "-m", "Use explicit collection exclusions.",
    ).returncode == 0
    head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    pr = {"number": 66, "headRefOid": head, "state": "OPEN"}
    responses = iter([pr if existing else None, pr])
    monkeypatch.setattr(ensure_pr, "_open_pr", lambda args: next(responses))
    original_output = ensure_pr.require_output
    original_success = ensure_pr.require_success
    git_reads: list[list[str]] = []
    published: list[tuple[list[str], bytes | None]] = []
    body_files: list[pathlib.Path] = []
    pushes: list[list[str]] = []

    def output(command: list[str], *, cwd: pathlib.Path) -> str:
        git_reads.append(command)
        return original_output(command, cwd=cwd)

    def publish(command: list[str], *, cwd: pathlib.Path) -> None:
        assert cwd == repo
        if command[0] == "git":
            if command[3] == "fetch":
                original_success(command, cwd=cwd)
                return
            assert command[3:] == ["push", "-u", "origin", "release/local:release/local"]
            pushes.append(command)
            return
        captured_body = None
        if "--body-file" in command:
            path = pathlib.Path(command[command.index("--body-file") + 1])
            captured_body = path.read_bytes()
            body_files.append(path)
        published.append((command, captured_body))

    monkeypatch.setattr(ensure_pr, "require_output", output)
    monkeypatch.setattr(ensure_pr, "require_success", publish)
    arguments = ensure_pr.build_parser().parse_args(
        ["--repo-root", str(repo), "--head-branch", "release/local"]
    )
    arguments.title, arguments.body = title, body
    assert ensure_pr.ensure_pr(arguments)["status"] == "pr_ready"
    assert run_git(repo, "rev-parse", "main").stdout.strip() == local_base
    assert run_git(repo, "rev-parse", "origin/main").stdout.strip() == remote_base
    assert len(pushes) == 1
    needs_defaults = not existing and (title is None or body is None)
    assert any("log" in command for command in git_reads) == needs_defaults
    if existing and title is None and body is None:
        assert published == []
        return
    assert len(published) == 1
    command, captured_body = published[0]
    assert command[:3] == ["gh", "pr", "edit" if existing else "create"]
    expected_title = title if existing or title is not None else "Complete Dev Tools catalog"
    if expected_title is None:
        assert "--title" not in command
    else:
        assert command[command.index("--title") + 1] == expected_title
    expected_body = body
    if not existing and body is None:
        expected_body = "- Complete Dev Tools catalog\n  \n  Use explicit collection exclusions."
    assert captured_body == (expected_body.encode("utf-8") if expected_body is not None else None)
    assert all(not path.parent.exists() for path in body_files)


def test_ensure_pr_metadata_body_file_is_removed_after_publish_failure(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_pr = load_pr_workflow_module(monkeypatch, "ensure_pr")
    body_files: list[pathlib.Path] = []

    def fail(command: list[str], *, cwd: pathlib.Path) -> None:
        path = pathlib.Path(command[command.index("--body-file") + 1])
        assert path.read_text(encoding="utf-8") == "Exact body\n"
        body_files.append(path)
        raise ensure_pr.CommandError("GitHub unavailable")

    monkeypatch.setattr(ensure_pr, "require_success", fail)
    with pytest.raises(ensure_pr.CommandError, match="GitHub unavailable"):
        ensure_pr._publish_metadata(
            ["gh", "pr", "create"], repo_root=tmp_path,
            title="Caller title", body="Exact body\n",
        )
    assert len(body_files) == 1
    assert not body_files[0].parent.exists()


def test_failed_log_excerpt_retains_decisive_lines_before_long_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ship = load_pr_workflow_module(monkeypatch, "ship")
    log = (
        "FAILED tests/test_contract.py::test_state - AssertionError: wrong state\n"
        "E       assert actual == expected\n"
        + "\n".join(f"cleanup-{index}-" + "x" * 180 for index in range(40))
        + "\nlast cleanup line\n"
    )

    excerpt = ship._compact_failed_log(log)

    assert excerpt is not None
    assert "FAILED tests/test_contract.py::test_state" in excerpt
    assert "E       assert actual == expected" in excerpt
    assert "last cleanup line" in excerpt
    assert len(excerpt.encode("utf-8")) <= 2_000


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
    monkeypatch.setattr(
        ship.actions_availability,
        "confirmed_actions_outage",
        lambda: None,
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


def test_actions_availability_classifies_only_confirmed_outages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    availability = load_pr_workflow_module(monkeypatch, "actions_availability")

    class Response:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.raw = json.dumps(payload).encode("utf-8")

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, limit: int) -> bytes:
            assert limit == availability.MAX_STATUS_BYTES + 1
            return self.raw

    def payload(status: str) -> dict[str, Any]:
        return {
            "page": {"updated_at": "2026-08-26T18:01:30Z"},
            "components": [
                {
                    "id": availability.ACTIONS_COMPONENT_ID,
                    "name": "Actions",
                    "status": status,
                    "updated_at": "2026-08-26T17:54:33Z",
                }
            ],
            "incidents": [
                {
                    "id": "incident-1",
                    "name": "Incident with Actions",
                    "status": "investigating",
                    "impact": "critical",
                    "shortlink": "https://status.example/incident-1",
                    "updated_at": "2026-08-26T17:55:00Z",
                    "components": [
                        {
                            "id": availability.ACTIONS_COMPONENT_ID,
                            "name": "Actions",
                        }
                    ],
                }
            ],
        }

    calls: list[tuple[str, float]] = []

    def probe(value: dict[str, Any]) -> dict[str, Any] | None:
        def opener(request: Any, *, timeout: float) -> Response:
            calls.append((request.full_url, timeout))
            return Response(value)

        return availability.confirmed_actions_outage(opener=opener)

    assert probe(payload("operational")) is None
    assert probe(payload("degraded_performance")) is None
    outage = probe(payload("major_outage"))
    assert outage == {
        "source": availability.STATUS_SUMMARY_URL,
        "page_updated_at": "2026-08-26T18:01:30Z",
        "component": {
            "id": availability.ACTIONS_COMPONENT_ID,
            "name": "Actions",
            "status": "major_outage",
            "updated_at": "2026-08-26T17:54:33Z",
        },
        "incident": {
            "id": "incident-1",
            "name": "Incident with Actions",
            "status": "investigating",
            "impact": "critical",
            "url": "https://status.example/incident-1",
            "updated_at": "2026-08-26T17:55:00Z",
        },
    }
    assert availability.confirmed_actions_outage(
        opener=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline"))
    ) is None
    assert calls == [
        (availability.STATUS_SUMMARY_URL, availability.DEFAULT_TIMEOUT_SECONDS),
        (availability.STATUS_SUMMARY_URL, availability.DEFAULT_TIMEOUT_SECONDS),
        (availability.STATUS_SUMMARY_URL, availability.DEFAULT_TIMEOUT_SECONDS),
    ]


def test_ship_stops_before_remote_mutation_on_confirmed_actions_outage(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ship = load_pr_workflow_module(monkeypatch, "ship")
    repo = tmp_path / "repo"
    repo.mkdir()
    head = "a" * 40
    checkpoint = tmp_path / "ship-checkpoint.json"
    state = {"phase": "prepared", "commit": head}
    evidence: dict[str, object] = {
        "source": "https://www.githubstatus.com/api/v2/summary.json",
        "component": {"name": "Actions", "status": "major_outage"},
        "incident": None,
    }
    events: list[str] = []

    def confirmed_actions_outage() -> dict[str, object]:
        events.append("probe")
        return evidence

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
        ship.actions_availability,
        "confirmed_actions_outage",
        confirmed_actions_outage,
    )
    monkeypatch.setattr(
        ship.ensure_pr,
        "ensure_pr",
        lambda *args, **kwargs: pytest.fail("outage must stop before PR mutation"),
    )
    with pytest.raises(ship.ShipBlocked) as blocked:
        ship.ship(
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
                ci_wait_seconds=900,
                review_wait_seconds=260,
                interval_seconds=10,
                review_replies_request=None,
            )
        )
    assert events == ["recover", "probe"]
    assert blocked.value.payload == {
        "status": "blocked",
        "message": "GitHub Actions has a confirmed outage; shipping stopped.",
        "phase": "gates",
        "remote_mutation": False,
        "blocker": {
            "kind": "external_service_outage",
            "service": "github_actions",
            "repository": "example/repository",
            "head_oid": head,
            "evidence": evidence,
        },
    }


def test_ship_reconciles_merged_pr_before_actions_outage(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ship = load_pr_workflow_module(monkeypatch, "ship")
    repo = tmp_path / "repo"
    repo.mkdir()
    head = "a" * 40
    checkpoint = tmp_path / "ship-checkpoint.json"
    state = {
        "phase": "pr_ready",
        "pr": 24,
        "url": "https://example.invalid/pull/24",
        "commit": head,
    }
    events: list[str] = []

    monkeypatch.setattr(
        ship.merge,
        "restore_unfinished_checkpoints",
        lambda root: events.append("recover"),
    )
    monkeypatch.setattr(
        ship.actions_availability,
        "confirmed_actions_outage",
        lambda: pytest.fail("merged PR reconciliation must bypass outage probing"),
    )
    monkeypatch.setattr(ship, "_repository_name", lambda *args: "example/repository")
    monkeypatch.setattr(ship, "_resolve_commit", lambda *args: head)
    monkeypatch.setattr(ship, "_load_pending_work_scope", lambda *args: (None, None))
    monkeypatch.setattr(
        ship,
        "_load_or_create_checkpoint",
        lambda *args: (checkpoint, state),
    )

    def live_pr(*args: object) -> dict[str, object]:
        events.append("live")
        return {
            "state": "MERGED",
            "headRefOid": head,
            "mergedAt": "2026-08-27T00:00:00Z",
            "mergeCommit": {"oid": "b" * 40},
        }

    monkeypatch.setattr(ship, "_live_pr", live_pr)
    monkeypatch.setattr(ship, "_write_checkpoint", lambda *args: None)

    def synchronize(args: argparse.Namespace) -> dict[str, object]:
        events.append("sync")
        return {"head": "b" * 40}

    monkeypatch.setattr(ship.sync, "sync_main", synchronize)
    monkeypatch.setattr(ship, "_remove_completed_pr_checkpoints", lambda *args: [])

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
            review_replies_request=None,
        )
    )

    assert result["status"] == "shipped"
    assert result["changes"] == ["merged_reconciled", "synchronized"]
    assert events == ["recover", "live", "sync"]


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


def test_dependabot_requirement_range_title_projects_concrete_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependency = load_pr_workflow_module(monkeypatch, "dependency_evidence")

    update = dependency.parse_update(
        "Update pypdf requirement from <7,>=6.14.2 to >=6.16.1,<7",
        [{"path": "requirements-dev.txt"}],
        [],
    )

    assert update == {
        "package": "pypdf",
        "current_version": "6.14.2",
        "target_version": "6.16.1",
        "path_hint": None,
        "ecosystem": "pip",
        "update_type": "minor",
    }


def test_dependabot_requirement_range_title_rejects_ambiguous_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependency = load_pr_workflow_module(monkeypatch, "dependency_evidence")

    update = dependency.parse_update(
        "Update pypdf requirement from >=6.14.2,<7 to >=6.16.1,>=6.17.0,<7",
        [{"path": "requirements-dev.txt"}],
        [],
    )

    assert update["package"] == "pypdf"
    assert update["current_version"] == "6.14.2"
    assert update["target_version"] is None
    assert update["update_type"] == "unknown"
