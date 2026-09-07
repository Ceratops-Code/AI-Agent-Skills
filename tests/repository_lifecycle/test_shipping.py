from __future__ import annotations

import argparse
import json
import pathlib
import runpy
import sys
from typing import Any

import pytest

from tests.repository_lifecycle.support import OPERATION_RUNNER, SHIP_REPOSITORY
from tests.support.repositories import run_git, write_sdlc_contract

LOCAL = "deliverables.tools.deploy-local.standalone"
PUBLIC = "deliverables.tools.publish.public"


def _commit(repo: pathlib.Path) -> str:
    assert run_git(repo, "add", ".").returncode == 0
    assert run_git(repo, "commit", "--allow-empty", "-m", "test state").returncode == 0
    return run_git(repo, "rev-parse", "HEAD").stdout.strip()


def _setup(tmp_path: pathlib.Path, *, contract: bool = True) -> tuple[Any, ...]:
    """Use real SDLC execution and Git identity, simulating only GitHub and cleanup."""

    repo = tmp_path / "repo"
    repo.mkdir()
    log = tmp_path / "order.txt"
    external_failure = tmp_path / "publication-unavailable"
    assert run_git(repo, "init", "-b", "release/local").returncode == 0
    assert run_git(repo, "config", "user.name", "Tests").returncode == 0
    assert (
        run_git(repo, "config", "user.email", "tests@example.invalid").returncode == 0
    )
    (repo / "code.txt").write_text("good", encoding="utf-8")
    for script, label in (
        ("quality-check.py", "check"),
        ("publish-package.py", "publish"),
        ("install-local.py", "deploy"),
    ):
        (repo / script).write_text(
            "import pathlib, sys\n"
            f"label = {label!r}\n"
            f"log = pathlib.Path({str(log)!r})\n"
            "with log.open('a') as out: out.write(label + '\\n')\n"
            "if label == 'check' and pathlib.Path('code.txt').read_text() != 'good':\n"
            "    print('ordinary check failure', file=sys.stderr)\n"
            "    raise SystemExit(7)\n"
            f"if label == 'publish' and pathlib.Path({str(external_failure)!r}).exists():\n"
            "    print('publication unavailable', file=sys.stderr)\n"
            "    raise SystemExit(8)\n",
            encoding="utf-8",
        )
    if contract:
        write_sdlc_contract(
            repo,
            repository={
                "validate": {
                    "repository": {
                        "steps": [{"run": [sys.executable, "quality-check.py"]}]
                    },
                }
            },
            deliverables={
                "tools": {
                    "publish": {
                        "public": {
                            "steps": [{"run": [sys.executable, "publish-package.py"]}]
                        }
                    },
                    "deploy-local": {
                        "standalone": {
                            "steps": [{"run": [sys.executable, "install-local.py"]}]
                        }
                    },
                }
            },
        )
    _commit(repo)
    loaded = runpy.run_path(str(SHIP_REPOSITORY))
    original = loaded["_run_json"]
    commands: list[list[str]] = []
    scope = tmp_path / "scope.json"
    state: dict[str, Any] = {
        "scope": False,
        "late_block": None,
        "remote_error": None,
        "calls": 0,
        "break_after_remote": False,
        "external_failure": external_failure,
    }

    def run_json(command: list[str], **kwargs: Any) -> tuple[int, dict[str, Any]]:
        commands.append(command)
        if len(command) > 1 and pathlib.Path(command[1]) == OPERATION_RUNNER:
            return original(command, **kwargs)
        head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
        prepared = {
            "status": "ready",
            "source_branches": ["selected"] if state["scope"] else [],
            "pending_work_scope": str(scope) if state["scope"] else "",
            "target_commit": head,
        }
        if "github_pr_workflow" in command:
            if state["remote_error"]:
                return 1, state["remote_error"]
            assert not log.exists() or log.read_text().splitlines()[-1] == "check"
            with log.open("a") as out:
                out.write("remote\n")
            state["calls"] += 1
            if state["break_after_remote"]:
                (repo / "code.txt").write_text("broken", encoding="utf-8")
                if state["break_after_remote"] != "dirty":
                    head = _commit(repo)
            return 0, {
                "status": "shipped" if state["calls"] == 1 else "already_shipped",
                "repository": "example/repository",
                "commit": head,
                "synchronized_head": head,
                "merge_commit": head,
                "pr": 24,
                "url": "https://example.invalid/pull/24",
            }
        if "prepare" in command:
            return 0, prepared
        if "check" in command:
            if state["late_block"] == "post_sync":
                return 2, {"status": "pending_work", "findings": ["advanced source"]}
            return 0, prepared
        if "finalize" in command:
            if state["late_block"] == "post_finalize":
                return 2, {"status": "pending_work", "findings": ["advanced source"]}
            with log.open("a") as out:
                out.write("finalize\n")
            return 0, {"status": "finalized"}
        raise AssertionError(command)

    loaded["ship_repository"].__globals__["_run_json"] = run_json
    loaded["ship_repository"].__globals__["_branch_worktree"] = lambda *args: None
    # Cleanup path eligibility itself has separate real-path coverage below.
    loaded["ship_repository"].__globals__["_require_cleanup_safe_caller"] = (
        lambda *args: None
    )
    args = loaded["build_parser"]().parse_args(
        [
            "--repo-root",
            str(repo),
            "--head-branch",
            "release/local",
            "--reusable-head",
            *(
                ["--publish-operation", PUBLIC, "--deploy-operation", LOCAL]
                if contract
                else []
            ),
        ]
    )
    return repo, loaded, args, log, state, commands


@pytest.mark.parametrize("scope_present", [False, True])
def test_repository_ship_absent_default_contract_is_no_op_and_finalizes(
    tmp_path: pathlib.Path,
    scope_present: bool,
) -> None:
    repo, loaded, args, log, state, commands = _setup(tmp_path, contract=False)
    state["scope"] = scope_present
    result = loaded["ship_repository"](args)
    assert result["status"] == "shipped"
    for phase in ("release_publication", "deployment"):
        assert result[phase] == {
            "status": "completed",
            "completed_operations": [],
            "pending_operations": [],
            "results": [],
        }
    assert result["finalization"] == (
        {"status": "finalized"} if scope_present else None
    )
    assert log.read_text().splitlines() == (
        ["remote", "finalize"] if scope_present else ["remote"]
    )
    remote = next(command for command in commands if "github_pr_workflow" in command)
    assert ("--pending-work-check" in remote) is scope_present
    assert ("--no-pending-work-check" in remote) is not scope_present
    args.review_replies_request = tmp_path / "review-replies.json"
    forwarded = loaded["_ship_command"](args, repo, None, None)
    assert forwarded[forwarded.index("--review-replies-request") + 1] == str(
        args.review_replies_request
    )


def test_repository_ship_missing_custom_contract_blocks_before_remote_mutation(
    tmp_path: pathlib.Path,
) -> None:
    _, loaded, args, log, state, _ = _setup(tmp_path)
    args.sdlc_contract = pathlib.Path("sdlc/missing.yml")
    with pytest.raises(loaded["RepositoryShipError"], match="repository file"):
        loaded["ship_repository"](args)
    assert state["calls"] == 0 and not log.exists()


def test_repository_ship_prevalidates_and_executes_ordered_phase_selections(
    tmp_path: pathlib.Path,
) -> None:
    _, loaded, args, log, _, commands = _setup(tmp_path)
    args.publish_operation = [PUBLIC, PUBLIC]
    result = loaded["ship_repository"](args)
    assert log.read_text().splitlines() == [
        "check",
        "remote",
        "check",
        "publish",
        "publish",
        "check",
        "deploy",
    ]
    assert result["release_publication"]["completed_operations"] == [PUBLIC, PUBLIC]
    assert result["deployment"]["completed_operations"] == [LOCAL]
    assert "--prepare-only" in commands[0]
    assert "--validate" in next(
        command for command in commands if "--validate" in command
    )


def test_failed_checks_prevent_remote_work_and_succeed_after_committed_repair(
    tmp_path: pathlib.Path,
) -> None:
    repo, loaded, args, log, state, _ = _setup(tmp_path)
    (repo / "code.txt").write_text("broken", encoding="utf-8")
    broken = _commit(repo)
    with pytest.raises(loaded["RepositoryShipError"]) as failure:
        loaded["ship_repository"](args)
    assert failure.value.payload["status"] == "validation_failed"
    assert failure.value.payload["phase"] == "before_remote"
    assert failure.value.payload["commit"] == broken
    assert failure.value.payload["diagnostic"]["stderr_tail"] == [
        "ordinary check failure"
    ]
    assert failure.value.payload["remote_mutation"] is False
    assert state["calls"] == 0 and log.read_text().splitlines() == ["check"]
    (repo / "code.txt").write_text("good", encoding="utf-8")
    repaired = _commit(repo)
    result = loaded["ship_repository"](args)
    assert result["commit"] == repaired != broken
    assert result["status"] == "shipped"
    assert log.read_text().splitlines()[-1] == "deploy"


def test_repository_ship_release_failure_blocks_deployment_and_cleanup(
    tmp_path: pathlib.Path,
) -> None:
    repo, loaded, args, log, state, _ = _setup(tmp_path)
    state["scope"] = True
    state["external_failure"].touch()
    with pytest.raises(loaded["RepositoryShipError"]) as failure:
        loaded["ship_repository"](args)
    payload = failure.value.payload
    assert payload["phase"] == "release_publication"
    assert payload["diagnostic"]["stderr_tail"] == ["publication unavailable"]
    assert payload["remote_mutation"] is True
    assert "deploy" not in log.read_text() and "finalize" not in log.read_text()
    assert pathlib.Path(payload["resume_action"]["cwd"]) == repo
    assert "--review-replies-request" not in payload["resume_action"]["argv"]
    state["external_failure"].unlink()
    result = loaded["ship_repository"](args)
    assert result["status"] == "already_shipped"
    assert log.read_text().splitlines()[-2:] == ["deploy", "finalize"]


def test_synchronized_source_is_checked_before_publication_or_deployment(
    tmp_path: pathlib.Path,
) -> None:
    repo, loaded, args, log, state, _ = _setup(tmp_path)
    state["break_after_remote"] = True
    with pytest.raises(loaded["RepositoryShipError"]) as failure:
        loaded["ship_repository"](args)
    payload = failure.value.payload
    assert payload["status"] == "validation_failed"
    assert payload["phase"] == "release_publication"
    assert payload["remote_mutation"] is True
    assert payload["commit"] == run_git(repo, "rev-parse", "HEAD").stdout.strip()
    assert log.read_text().splitlines() == ["check", "remote", "check"]
    state["break_after_remote"] = False
    (repo / "code.txt").write_text("good", encoding="utf-8")
    _commit(repo)
    result = loaded["ship_repository"](args)
    assert result["status"] == "already_shipped"
    assert log.read_text().splitlines()[-1] == "deploy"


def test_synchronized_dirty_state_preserves_remote_recovery(
    tmp_path: pathlib.Path,
) -> None:
    repo, loaded, args, log, state, _ = _setup(tmp_path)
    state["break_after_remote"] = "dirty"
    with pytest.raises(loaded["RepositoryShipError"]) as failure:
        loaded["ship_repository"](args)
    payload = failure.value.payload
    assert payload["status"] == "state_changed"
    assert payload["remote_mutation"] is True
    assert payload["phase"] == "release_publication"
    assert pathlib.Path(payload["resume_action"]["cwd"]) == repo
    assert log.read_text().splitlines() == ["check", "remote"]


@pytest.mark.parametrize("late_phase", ["post_sync", "post_finalize"])
def test_repository_ship_late_pending_work_reports_remote_mutation(
    tmp_path: pathlib.Path,
    late_phase: str,
) -> None:
    repo, loaded, args, log, state, _ = _setup(tmp_path)
    state["scope"] = True
    state["late_block"] = late_phase
    result = loaded["ship_repository"](args)
    assert result["status"] == "pending_work"
    assert result["remote_mutation"] is True
    assert result["remaining"] == (
        "selected_work_recheck" if late_phase == "post_sync" else "finalization"
    )
    assert result["resume_action"]["argv"][:2] == [sys.executable, str(SHIP_REPOSITORY)]
    if late_phase == "post_sync":
        assert "publish" not in log.read_text()
    else:
        assert log.read_text().splitlines().count("publish") == 1
        assert loaded["_operation_checkpoint_directory"](repo).is_dir()
    state["late_block"] = None
    resumed = loaded["ship_repository"](args)
    assert resumed["status"] == "already_shipped"
    assert log.read_text().splitlines().count("publish") == 1
    assert log.read_text().splitlines().count("deploy") == 1
    assert not list(loaded["_operation_checkpoint_directory"](repo).glob("*.json"))


def test_repository_ship_checkpoints_each_operation_before_the_next(
    tmp_path: pathlib.Path,
) -> None:
    repo, loaded, args, log, state, _ = _setup(tmp_path)
    args.publish_operation = [PUBLIC, PUBLIC]
    original = loaded["execute_prepared_operation"]
    count = 0

    def execute(prepared: Any) -> dict[str, Any]:
        nonlocal count
        if prepared.category == "publish":
            count += 1
            if count == 2:
                files = list(
                    loaded["_operation_checkpoint_directory"](repo).glob("*.json")
                )
                assert len(files) == 1
                assert json.loads(files[0].read_text())["position"] == 1
                raise RuntimeError("interrupted between operations")
        return original(prepared)

    loaded["_checkpointed_operation_batch"].__globals__[
        "execute_prepared_operation"
    ] = execute
    with pytest.raises(RuntimeError, match="interrupted"):
        loaded["ship_repository"](args)
    assert log.read_text().splitlines().count("publish") == 1
    loaded["_checkpointed_operation_batch"].__globals__[
        "execute_prepared_operation"
    ] = original
    resumed = loaded["ship_repository"](args)
    assert resumed["status"] == "already_shipped"
    assert log.read_text().splitlines().count("publish") == 2
    assert log.read_text().splitlines().count("deploy") == 1


def test_repository_ship_rejects_malformed_deployment_checkpoint(
    tmp_path: pathlib.Path,
) -> None:
    _, loaded, _, _, _, _ = _setup(tmp_path)
    path = tmp_path / "checkpoint.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(loaded["RepositoryShipError"], match="invalid structure"):
        loaded["_read_operation_checkpoint"](
            path, {"version": 2, "phase": "deployment"}
        )


def test_repository_ship_rejects_noncanonical_release_branch_before_remote_process(
    tmp_path: pathlib.Path,
) -> None:
    _, loaded, args, log, state, _ = _setup(tmp_path)
    args.head_branch = "release/task"
    with pytest.raises(
        loaded["RepositoryShipError"], match="Head branch must be release/local"
    ):
        loaded["ship_repository"](args)
    assert state["calls"] == 0 and not log.exists()


def test_remote_gate_failure_remains_a_terminal_external_blocker(
    tmp_path: pathlib.Path,
) -> None:
    _, loaded, args, log, state, _ = _setup(tmp_path)
    blocker = {
        "status": "blocked",
        "message": "Code review needs authorization",
        "phase": "gates",
    }
    state["remote_error"] = blocker
    with pytest.raises(loaded["RepositoryShipError"]) as failure:
        loaded["ship_repository"](args)
    assert failure.value.payload == blocker
    assert log.read_text().splitlines() == ["check"]


def test_repository_ship_finalization_runs_outside_selected_worktree(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = runpy.run_path(str(SHIP_REPOSITORY))
    repo = tmp_path / "repo"
    repo.mkdir()
    command = ["python", "manage-pending-work.py", "finalize"]
    events: list[tuple[str, object]] = []
    original_directory = pathlib.Path.cwd().resolve()

    def change_directory(path: pathlib.Path) -> None:
        events.append(("chdir", path))

    def run_json(
        child_command: list[str], *, cwd: pathlib.Path
    ) -> tuple[int, dict[str, Any]]:
        events.append(("run", (child_command, cwd)))
        return 0, {"status": "finalized"}

    monkeypatch.setattr(loaded["os"], "chdir", change_directory)
    loaded["_run_finalization"].__globals__["_run_json"] = run_json

    result = loaded["_run_finalization"](command, repo_root=repo)

    assert result == (0, {"status": "finalized"})
    assert events == [
        ("chdir", repo),
        ("run", (command, repo)),
        ("chdir", original_directory),
    ]


def test_repository_ship_blocks_selected_worktree_caller_before_remote_process(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = runpy.run_path(str(SHIP_REPOSITORY))
    repo = tmp_path / "repo"
    selected = tmp_path / "worktrees" / "repo" / "thread"
    selected.mkdir(parents=True)
    repo.mkdir()
    scope = tmp_path / "scope.json"
    scope.write_text(
        json.dumps(
            {
                "version": 2,
                "target_branch": "release/local",
                "target_commit": "a" * 40,
                "sources": [
                    {
                        "branch": "selected",
                        "commit": "a" * 40,
                        "state": "retained",
                    }
                ],
            }
        ),
        encoding="utf-8",
        newline="\n",
    )
    child_calls: list[list[str]] = []
    selected_path = {"value": selected}

    def branch_worktree(repo_root: pathlib.Path, branch: str) -> pathlib.Path:
        assert repo_root == repo
        assert branch == "selected"
        return selected_path["value"]

    def run_json(command: list[str]) -> tuple[int, dict[str, Any]]:
        child_calls.append(command)
        return 0, {
            "status": "ready",
            "source_branches": ["selected"],
            "pending_work_scope": str(scope),
        }

    ship_repository = loaded["ship_repository"]
    ship_repository.__globals__["_branch_worktree"] = branch_worktree
    ship_repository.__globals__["_run_json"] = run_json
    ship_repository.__globals__["_prepare_operation_batch"] = lambda *args, **kwargs: (
        None
    )
    monkeypatch.chdir(selected)

    with pytest.raises(
        loaded["RepositoryShipError"],
        match="outside selected worktree",
    ):
        ship_repository(
            argparse.Namespace(
                repo_root=repo,
                repo="example/repository",
                head_branch="release/local",
                base_branch="main",
                remote_name="origin",
                commit="a" * 40,
                title=None,
                body=None,
                merge_method="merge",
                delete_branch=False,
                reusable_head=True,
                sdlc_contract=pathlib.Path("sdlc/sdlc.yml"),
                validation_operation=None,
                publish_operation=None,
                deploy_operation=None,
                ci_wait_seconds=1,
                review_wait_seconds=1,
                interval_seconds=1,
            )
        )

    assert len(child_calls) == 1
    assert "prepare" in child_calls[0]

    preserved = tmp_path / "custom" / "repo" / "thread"
    preserved.mkdir(parents=True)
    selected_path["value"] = preserved
    monkeypatch.chdir(preserved)
    loaded["_require_cleanup_safe_caller"](
        repo,
        scope,
        [
            {
                "branch": "selected",
                "path": str(preserved.resolve()),
                "reason": "resolved parent chain has no 'worktrees' directory",
            }
        ],
    )
