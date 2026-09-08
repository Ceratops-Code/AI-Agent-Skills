from __future__ import annotations

import argparse
import json
import pathlib
import runpy
import sys
from typing import Any

import pytest

from tests.repository_lifecycle.support import (
    OPERATION_RUNNER,
    SHIP_REPOSITORY,
    load_pr_workflow_module,
)
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


@pytest.mark.parametrize(
    "metadata",
    [
        [],
        ["--title", "Complete Dev Tools catalog"],
        ["--body", "Collection policy.\n\nDeploy configuration.\n"],
        ["--title", "Caller title", "--body", "Exact description"],
        ["--body", ""],
    ],
)
def test_repository_ship_metadata_reaches_shared_pr_producer(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, metadata: list[str],
) -> None:
    loaded = runpy.run_path(str(SHIP_REPOSITORY))
    ship = load_pr_workflow_module(monkeypatch, "ship")
    args = loaded["build_parser"]().parse_args(
        ["--repo-root", str(tmp_path), "--head-branch", "release/local", *metadata]
    )
    command = loaded["_ship_command"](args, tmp_path, None, "a" * 40)
    parsed = ship.build_parser().parse_args(command[4:])
    events: list[str] = []
    monkeypatch.setattr(ship.merge, "restore_unfinished_checkpoints", lambda root: None)
    monkeypatch.setattr(ship, "_repository_name", lambda *args: "example/repository")
    monkeypatch.setattr(ship, "_resolve_commit", lambda *args: "a" * 40)
    monkeypatch.setattr(ship, "_load_pending_work_scope", lambda *args: (None, None))
    monkeypatch.setattr(
        ship, "_load_or_create_checkpoint",
        lambda *args: (tmp_path / "checkpoint.json", {"phase": "prepared"}),
    )
    monkeypatch.setattr(ship, "_enforce_actions_availability", lambda *args: events.append("availability"))

    class ProducerReached(Exception):
        pass

    def ensure(arguments: argparse.Namespace) -> None:
        assert events == ["availability"]
        assert arguments.title == args.title
        assert arguments.body == args.body
        assert arguments.head_branch == "release/local"
        assert arguments.base_branch == "main"
        assert arguments.remote_name == "origin"
        events.append("producer")
        raise ProducerReached

    monkeypatch.setattr(ship.ensure_pr, "ensure_pr", ensure)
    with pytest.raises(ProducerReached):
        ship.ship(parsed)
    assert events == ["availability", "producer"]


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


def _publish_pr_setup(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    """Exercise real Git preparation/push, replacing only remote GitHub responses."""

    module = load_pr_workflow_module(monkeypatch, "ensure_pr")
    repo, remote = tmp_path / "repo", tmp_path / "remote.git"
    repo.mkdir()
    remote.mkdir()
    assert run_git(repo, "init", "-b", "main").returncode == 0
    assert run_git(remote, "init", "--bare", "-b", "main").returncode == 0
    for key, value in (("user.name", "Tests"), ("user.email", "tests@example.invalid"), ("core.autocrlf", "false")):
        assert run_git(repo, "config", key, value).returncode == 0
    (repo / "code.txt").write_text("before\n", encoding="utf-8")
    (repo / "removed.txt").write_text("old\n", encoding="utf-8")
    _commit(repo)
    assert run_git(repo, "remote", "add", "origin", str(remote)).returncode == 0
    assert run_git(repo, "push", "origin", "main").returncode == 0
    args = module.build_parser().parse_args([
        "--repo-root", str(repo), "--head-branch", "codex/publish", "--prepare",
        "--path", "code.txt", "--commit-message", "Publish selected change", "--draft",
    ])
    state: dict[str, Any] = {
        "commands": [], "api": [], "pr": None, "creates": 0, "fail": None,
        "urls": {}, "repo": "example/repository", "push_repo": "example/repository",
        "extra_records": [],
    }
    original = module.require_output

    def pr_record() -> dict[str, Any]:
        assert state["pr"] is not None
        head = run_git(remote, "rev-parse", f"refs/heads/{args.head_branch}")
        assert head.returncode == 0
        return {
            "number": 24, "url": "https://github.com/example/repository/pull/24",
            "headRefOid": state.get("head_override", head.stdout.strip()),
            "changedFiles": 1, "state": state.get("pr_state", "OPEN"),
            "isDraft": state["pr"]["draft"], "statusCheckRollup": [],
        }

    def create(metadata: dict[str, Any]) -> None:
        if state["fail"] == "create":
            raise module.EnsurePrError("simulated PR creation failure")
        state["pr"] = metadata
        state["creates"] += 1
        if state["fail"] == "create-after-write":
            raise module.EnsurePrError("simulated lost response after PR creation")

    def output(command: list[str], *, cwd: pathlib.Path) -> str:
        state["commands"].append(command)
        if command[0] == "git":
            git_args = command[3:]
            if git_args[:2] == ["remote", "get-url"] and state["urls"]:
                return state["urls"][git_args[-1]]
            if git_args[0] in {"commit", "push"} and state["fail"] == git_args[0]:
                raise module.CommandError("simulated " + git_args[0] + " failure")
        if command[:3] == ["gh", "auth", "status"]:
            if state["fail"] == "auth":
                raise module.CommandError("simulated authentication failure")
            return ""
        if command[:3] == ["gh", "pr", "list"]:
            return json.dumps([pr_record()] if state["pr"] else [])
        if command[:3] == ["gh", "pr", "view"]:
            return json.dumps(pr_record())
        if command[:3] in (["gh", "pr", "create"], ["gh", "pr", "edit"]):
            metadata = {}
            if "--title" in command:
                metadata["title"] = command[command.index("--title") + 1]
            if "--body-file" in command:
                metadata["body"] = pathlib.Path(command[command.index("--body-file") + 1]).read_text(encoding="utf-8")
            if command[2] == "create":
                create({**metadata, "draft": "--draft" in command})
            else:
                state["pr"].update(metadata)
            return ""
        assert command[0] != "gh", command
        return original(command, cwd=cwd)

    def api(method: str, endpoint: str, body: Any = None, **kwargs: Any) -> argparse.Namespace:
        state["api"].append((method, endpoint, body))
        if method == "POST":
            create(body)
            data: Any = {"number": 24}
        elif "/pulls?" in endpoint:
            data = list(state["extra_records"])
            if state["pr"]:
                data.append({
                    "number": 24,
                    "head": {"ref": args.head_branch, "repo": {"full_name": state["push_repo"]}},
                    "base": {"ref": args.base_branch, "repo": {"full_name": state["repo"]}},
                })
        else:
            data = {"full_name": state["repo"]}
        return argparse.Namespace(ok=True, data=data, message=None)

    monkeypatch.setattr(module, "require_output", output)
    monkeypatch.setattr(module, "require_success", lambda command, **kwargs: output(command, **kwargs))
    monkeypatch.setattr(module, "run_gh_api", api)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    return module, args, repo, remote, state


def test_publish_pr_prepares_literal_files_validates_and_reuses_draft(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, args, repo, remote, state = _publish_pr_setup(tmp_path, monkeypatch)
    (repo / "code.txt").write_text("after\n", encoding="utf-8")
    (repo / "removed.txt").rename(repo / " [new].txt")
    args.path += ["removed.txt", " [new].txt"]
    args.title, args.body = "Selected change", "Why it matters.\n\nChecked locally.\n"
    args.check_command = [[sys.executable, "-c", "from pathlib import Path; assert Path('code.txt').read_text() == 'after\\n'"]]
    result = module.ensure_pr(args)
    head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    assert result["status"] == "pr_ready" and result["head"] == head and result["draft"] is True
    assert run_git(remote, "rev-parse", args.head_branch).stdout.strip() == head
    assert run_git(repo, "status", "--porcelain").stdout == ""
    assert run_git(repo, "rev-list", "--count", "main..HEAD").stdout.strip() == "1"
    assert state["pr"] == {"title": args.title, "body": args.body, "draft": True}
    check = next(i for i, command in enumerate(state["commands"]) if command == args.check_command[0])
    push = next(i for i, command in enumerate(state["commands"]) if command[3:4] == ["push"])
    assert check < push
    args.title = args.body = None
    # Retrying with the original deleted filename must not create another commit.
    assert module.ensure_pr(args)["head"] == head
    assert state["creates"] == 1
    assert run_git(repo, "rev-list", "--count", "main..HEAD").stdout.strip() == "1"


@pytest.mark.parametrize("kind", ["dirty", "staged", "unknown", "directory", "escape", "ignored", "message", "base", "detached", "operation", "existing", "auth"])
def test_publish_pr_rejects_unsafe_preparation_before_local_writes(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    module, args, repo, remote, state = _publish_pr_setup(tmp_path, monkeypatch)
    (repo / "code.txt").write_text("after\n", encoding="utf-8")
    if kind in {"dirty", "staged"}:
        (repo / "unrelated.txt").write_text("keep", encoding="utf-8")
        if kind == "staged":
            assert run_git(repo, "add", "unrelated.txt").returncode == 0
    elif kind == "unknown":
        args.path.append("missing.txt")
    elif kind == "directory":
        args.path = ["."]
    elif kind == "escape":
        args.path.append("../outside.txt")
    elif kind == "ignored":
        (repo / ".git" / "info" / "exclude").write_text("ignored.txt\n", encoding="utf-8")
        (repo / "ignored.txt").write_text("keep", encoding="utf-8")
        args.path.append("ignored.txt")
    elif kind == "message":
        args.commit_message = " "
    elif kind == "base":
        args.head_branch = "main"
    elif kind == "detached":
        assert run_git(repo, "checkout", "--detach").returncode == 0
    elif kind == "operation":
        (repo / ".git" / "CHERRY_PICK_HEAD").write_text(run_git(repo, "rev-parse", "HEAD").stdout, encoding="utf-8")
    elif kind == "existing":
        assert run_git(repo, "branch", args.head_branch).returncode == 0
    elif kind == "auth":
        state["fail"] = "auth"
    before = [run_git(repo, *command).stdout for command in (
        ("rev-parse", "HEAD"), ("branch", "--show-current"), ("status", "--porcelain"), ("diff", "--cached"),
    )]
    with pytest.raises((module.EnsurePrError, module.CommandError)):
        module.ensure_pr(args)
    after = [run_git(repo, *command).stdout for command in (
        ("rev-parse", "HEAD"), ("branch", "--show-current"), ("status", "--porcelain"), ("diff", "--cached"),
    )]
    assert before == after
    assert run_git(remote, "show-ref", "--verify", f"refs/heads/{args.head_branch}").returncode != 0 or kind == "base"
    assert not any(command[3:4] in (["switch"], ["commit"], ["push"]) for command in state["commands"])
    assert state["creates"] == 0


@pytest.mark.parametrize("failure,phase", [("commit", "preparation_pending"), ("validation", "prepared"), ("push", "validated"), ("create", "pushed"), ("create-after-write", "pushed")])
def test_publish_pr_failure_retains_work_and_retry_does_not_duplicate(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, failure: str, phase: str,
) -> None:
    module, args, repo, remote, state = _publish_pr_setup(tmp_path, monkeypatch)
    (repo / "code.txt").write_text("after\n", encoding="utf-8")
    state["fail"] = failure
    if failure == "validation":
        args.check_command = [[sys.executable, "-c", "raise SystemExit(7)"]]
    with pytest.raises((module.EnsurePrError, module.CommandError)):
        module.ensure_pr(args)
    assert args.publication_phase == phase
    assert (repo / "code.txt").read_text() == "after\n"
    assert run_git(repo, "branch", "--show-current").stdout.strip() == args.head_branch
    if failure == "commit":
        assert run_git(repo, "diff", "--cached", "--name-only").stdout.strip() == "code.txt"
        assert run_git(repo, "rev-list", "--count", "main..HEAD").stdout.strip() == "0"
    else:
        assert run_git(repo, "rev-list", "--count", "main..HEAD").stdout.strip() == "1"
    if failure in {"commit", "validation", "push"}:
        assert run_git(remote, "show-ref", "--verify", f"refs/heads/{args.head_branch}").returncode != 0
    state["fail"] = None
    args.check_command = []
    assert module.ensure_pr(args)["status"] == "pr_ready"
    assert run_git(repo, "rev-list", "--count", "main..HEAD").stdout.strip() == "1"
    assert state["creates"] == 1


@pytest.mark.parametrize("mutation", ["worktree", "head", "branch"])
def test_publish_pr_validation_drift_blocks_push(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    module, args, repo, remote, _ = _publish_pr_setup(tmp_path, monkeypatch)
    (repo / "code.txt").write_text("after\n", encoding="utf-8")
    args.check_command = {
        "worktree": [[sys.executable, "-c", "from pathlib import Path; Path('code.txt').write_text('drift')"]],
        "head": [["git", "commit", "--allow-empty", "-m", "Drift"]],
        "branch": [["git", "switch", "-c", "other"]],
    }[mutation]
    with pytest.raises(module.EnsurePrError, match="Validation changed"):
        module.ensure_pr(args)
    assert run_git(remote, "show-ref", "--verify", f"refs/heads/{args.head_branch}").returncode != 0


@pytest.mark.parametrize("fork", [False, True])
def test_publish_pr_explicit_target_and_organization_fork_identity(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, fork: bool,
) -> None:
    module, args, repo, remote, state = _publish_pr_setup(tmp_path, monkeypatch)
    (repo / "code.txt").write_text("after\n", encoding="utf-8")
    args.repo = state["repo"]
    state["urls"] = {"origin": "git@github.com:example/repository.git"}
    if fork:
        assert run_git(repo, "remote", "add", "upstream", str(remote)).returncode == 0
        args.base_remote = "upstream"
        state["push_repo"] = "example/fork"
        state["urls"] = {"origin": "https://github.com/example/fork.git", "upstream": "git@github.com:example/repository.git"}
        state["extra_records"] = [{
            "number": 19,
            "head": {"ref": args.head_branch, "repo": {"full_name": "example/other-fork"}},
            "base": {"ref": args.base_branch, "repo": {"full_name": args.repo}},
        }]
    result = module.ensure_pr(args)
    assert result["status"] == "pr_ready"
    post = next(call for call in state["api"] if call[0] == "POST")
    assert post[1] == "/repos/example/repository/pulls"
    assert post[2]["head"] == "example:codex/publish" and post[2]["draft"] is True
    assert post[2].get("head_repo") == ("fork" if fork else None)
    assert module.ensure_pr(args)["head"] == result["head"]
    assert state["creates"] == 1
    assert all("--repo" in command for command in state["commands"] if command[:3] == ["gh", "pr", "view"])


def test_publish_pr_target_mismatch_blocks_before_preparation(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, args, repo, _, state = _publish_pr_setup(tmp_path, monkeypatch)
    (repo / "code.txt").write_text("after\n", encoding="utf-8")
    args.repo = "expected/repository"
    state["urls"] = {"origin": "https://github.com/wrong/repository.git"}
    with pytest.raises(module.EnsurePrError, match="base remote does not match"):
        module.ensure_pr(args)
    assert run_git(repo, "branch", "--show-current").stdout.strip() == "main"
    assert state["api"] == [] and state["creates"] == 0


def test_publish_pr_existing_ready_pr_is_not_downgraded_or_rewritten(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, args, repo, _, state = _publish_pr_setup(tmp_path, monkeypatch)
    (repo / "code.txt").write_text("after\n", encoding="utf-8")
    state["pr"] = {"draft": False, "title": "Keep title", "body": "Keep body"}
    result = module.ensure_pr(args)
    assert result["draft"] is False and state["creates"] == 0
    assert state["pr"] == {"draft": False, "title": "Keep title", "body": "Keep body"}


def test_publish_pr_head_readback_failure_reports_retained_push(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    module, args, repo, remote, state = _publish_pr_setup(tmp_path, monkeypatch)
    (repo / "code.txt").write_text("after\n", encoding="utf-8")
    state["head_override"] = "0" * 40
    assert module.main([
        "--repo-root", str(repo), "--head-branch", args.head_branch,
        "--prepare", "--path", "code.txt", "--commit-message", "Change", "--draft",
    ]) == 1
    result = json.loads(capsys.readouterr().err)
    assert result["status"] == "error" and result["phase"] == "pushed"
    assert result["head"] == run_git(remote, "rev-parse", args.head_branch).stdout.strip()
    assert state["creates"] == 1


@pytest.mark.parametrize("value", ["not-json", "[]", '[""]', '["git", 2]', '{}'])
def test_publish_pr_validation_requires_shell_free_argv(
    monkeypatch: pytest.MonkeyPatch, value: str,
) -> None:
    module = load_pr_workflow_module(monkeypatch, "ensure_pr")
    with pytest.raises(argparse.ArgumentTypeError):
        module._check_argv(value)
    assert module._check_argv('["python", "check.py", "two words"]') == ["python", "check.py", "two words"]


def test_publish_pr_preparation_flags_are_opt_in(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, args, repo, _, state = _publish_pr_setup(tmp_path, monkeypatch)
    args.prepare = False
    with pytest.raises(module.EnsurePrError, match="require --prepare"):
        module.ensure_pr(args)
    assert run_git(repo, "branch", "--show-current").stdout.strip() == "main"
    assert state["creates"] == 0
