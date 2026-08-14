from __future__ import annotations

import argparse
import json
import pathlib
import runpy
import subprocess
import sys
from typing import Any

import pytest

from tests.repository_lifecycle.support import (
    MANAGE_PENDING_WORK,
    PROMOTE_REPOSITORY,
    SHIP_REPOSITORY,
    prepare_divergent_promotion_repo,
    prepare_repository_lifecycle_repo,
)
from tests.support.repositories import (
    run_git,
)


@pytest.mark.parametrize(
    (
        "operation_arguments",
        "declares_base_revision",
        "managed_skills",
        "declared_handoff",
        "expected_operation",
        "expected_managed_skills",
        "expected_handoff",
        "expects_base_revision",
    ),
    [
        (["--no-run-operation"], False, False, None, None, None, None, None),
        (
            ["--run-operation", "deploy"],
            False,
            False,
            None,
            {
                "status": "deployed",
                "operation": "deploy",
                "steps": ["record"],
            },
            False,
            None,
            False,
        ),
        (
            ["--run-operation", "deploy"],
            False,
            True,
            None,
            {
                "status": "deployed",
                "operation": "deploy",
                "steps": ["record"],
            },
            True,
            None,
            False,
        ),
        (
            ["--run-operation", "deploy"],
            False,
            True,
            "ceratops-skill-lifecycle/deploy",
            {
                "status": "deployed",
                "operation": "deploy",
                "steps": ["record"],
                "handoff": "ceratops-skill-lifecycle/deploy",
            },
            True,
            "ceratops-skill-lifecycle/deploy",
            False,
        ),
    ],
)
def test_promote_repository_requires_an_explicit_deployment_choice(
    tmp_path: pathlib.Path,
    operation_arguments: list[str],
    declares_base_revision: bool,
    managed_skills: bool,
    declared_handoff: str | None,
    expected_operation: dict[str, object] | None,
    expected_managed_skills: bool | None,
    expected_handoff: str | None,
    expects_base_revision: bool | None,
) -> None:
    repo, approved_head, log, environment = prepare_repository_lifecycle_repo(
        tmp_path,
        declares_base_revision=declares_base_revision,
        managed_skills=managed_skills,
        handoff=declared_handoff,
    )
    release_start = run_git(repo, "rev-parse", "main").stdout.strip()

    promoted = subprocess.run(
        [
            sys.executable,
            str(PROMOTE_REPOSITORY),
            "--repo-root",
            str(repo),
            "--source-branch",
            "approved",
            *operation_arguments,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert promoted.returncode == 0, promoted.stderr
    result = json.loads(promoted.stdout)
    assert result["status"] == "ready"
    assert result["release_branch"] == "release/local"
    assert result["merged_branches"] == ["approved"]
    assert result["head"] == approved_head
    assert result["release_start"] == release_start
    assert result["operation"] == expected_operation
    if expected_managed_skills is None:
        assert "managed_skills" not in result
        assert "handoff" not in result
    else:
        assert result["managed_skills"] is expected_managed_skills
        assert result["handoff"] == expected_handoff
    scope_path = pathlib.Path(result["pending_work_scope"])
    assert json.loads(scope_path.read_text(encoding="utf-8")) == {
        "sources": [
            {
                "branch": "approved",
                "commit": approved_head,
                "state": "retained",
            }
        ],
        "target_branch": "release/local",
        "target_commit": approved_head,
        "version": 2,
    }
    assert run_git(repo, "branch", "--show-current").stdout.strip() == "release/local"
    assert run_git(repo, "status", "--porcelain").stdout == ""
    if expects_base_revision is None:
        assert not log.exists()
    elif expects_base_revision:
        assert log.read_text(encoding="utf-8") == f"{release_start}\n"
    else:
        assert log.read_text(encoding="utf-8") == "no-base\n"


def test_promote_repository_ship_after_promotion_composes_terminal_workflow(
    tmp_path: pathlib.Path,
) -> None:
    repo, approved_head, log, _ = prepare_repository_lifecycle_repo(tmp_path)
    loaded = runpy.run_path(str(PROMOTE_REPOSITORY))
    parser = loaded["build_parser"]()
    arguments = [
        "--repo-root",
        str(repo),
        "--source-branch",
        "approved",
        "--main-branch",
        "main",
        "--release-branch",
        "release/local",
        "--remote-name",
        "origin",
        "--ship-after-promotion",
    ]
    parsed = parser.parse_args(arguments)
    assert parsed.ship_after_promotion is True
    assert parsed.run_operation is None
    assert parsed.no_run_operation is False
    for conflicting in (
        ["--run-operation", "deploy"],
        ["--no-run-operation"],
    ):
        with pytest.raises(SystemExit):
            parser.parse_args([*arguments, *conflicting])

    shipped = {
        "status": "shipped",
        "repository": "example/repository",
        "commit": approved_head,
        "pr": 31,
        "url": "https://example.invalid/pull/31",
        "merge_commit": "c" * 40,
        "synchronized_head": "b" * 40,
        "release_publication": {
            "status": "published",
            "operation": "publish",
            "steps": ["publish"],
        },
        "deployment": {
            "status": "deployed",
            "operation": "deploy",
            "steps": ["install"],
        },
        "finalization": {"status": "finalized"},
    }
    original_run_json = loaded["_run_json"]
    original_ship_after_promotion = loaded["_ship_after_promotion"]
    commands: list[list[str]] = []
    recorded: dict[str, object] = {}
    captured_handoff: dict[str, object] = {}

    def run_json(
        command: list[str], cwd: pathlib.Path
    ) -> tuple[int, dict[str, Any]]:
        commands.append(command)
        if pathlib.Path(command[1]) == MANAGE_PENDING_WORK:
            code, result = original_run_json(command, cwd)
            recorded.update(result)
            return code, result
        assert pathlib.Path(command[1]) == SHIP_REPOSITORY
        assert recorded["target_commit"] == approved_head
        assert pathlib.Path(str(recorded["pending_work_scope"])).is_file()
        assert run_git(repo, "rev-parse", "release/local").stdout.strip() == (
            approved_head
        )
        return 0, shipped

    def ship_after_promotion(
        args: argparse.Namespace,
        repo_root: pathlib.Path,
        *,
        target_commit: str,
        pending_work_scope: object,
    ) -> dict[str, object]:
        captured_handoff.update(
            {
                "target_commit": target_commit,
                "pending_work_scope": pending_work_scope,
            }
        )
        return original_ship_after_promotion(
            args,
            repo_root,
            target_commit=target_commit,
            pending_work_scope=pending_work_scope,
        )

    promote = loaded["promote"]
    promote.__globals__["_run_json"] = run_json
    promote.__globals__["_ship_after_promotion"] = ship_after_promotion
    result = promote(parsed)

    assert result == shipped
    assert len(commands) == 2
    assert pathlib.Path(commands[0][1]) == MANAGE_PENDING_WORK
    ship_command = commands[1]
    assert pathlib.Path(ship_command[1]) == SHIP_REPOSITORY
    assert ship_command[ship_command.index("--repo-root") + 1] == str(repo.resolve())
    assert ship_command[ship_command.index("--head-branch") + 1] == "release/local"
    assert ship_command[ship_command.index("--base-branch") + 1] == "main"
    assert ship_command[ship_command.index("--remote-name") + 1] == "origin"
    assert ship_command[ship_command.index("--commit") + 1] == approved_head
    assert pathlib.Path(
        ship_command[ship_command.index("--release-contract") + 1]
    ) == pathlib.Path("release/release.yml")
    assert ship_command[
        ship_command.index("--release-preflight-operation") + 1
    ] == "preflight"
    assert ship_command[ship_command.index("--release-operation") + 1] == "publish"
    assert ship_command[ship_command.index("--deploy-operation") + 1] == "deploy"
    assert "--reusable-head" in ship_command
    assert str(PROMOTE_REPOSITORY.parent / "run-deploy-operation.py") not in (
        command[1] for command in commands
    )
    assert captured_handoff == {
        "target_commit": approved_head,
        "pending_work_scope": recorded["pending_work_scope"],
    }
    assert not log.exists()


def test_promote_repository_ship_after_promotion_preserves_blocked_state(
    tmp_path: pathlib.Path,
) -> None:
    (
        repo,
        source_worktree,
        _,
        release_head,
        _,
    ) = prepare_divergent_promotion_repo(tmp_path / "shipping-blocker")
    loaded = runpy.run_path(str(PROMOTE_REPOSITORY))
    original_run_json = loaded["_run_json"]
    commands: list[list[str]] = []
    retained: dict[str, pathlib.Path] = {}
    blocker = {
        "status": "blocked",
        "message": "Codex review gate found one active thread.",
        "phase": "gates",
        "blocker": {
            "kind": "review_threads",
            "head_oid": "a" * 40,
            "threads": [{"thread_id": "PRRT_1", "body": "Fix this."}],
        },
    }

    def run_json(
        command: list[str], cwd: pathlib.Path
    ) -> tuple[int, dict[str, Any]]:
        commands.append(command)
        if pathlib.Path(command[1]) == MANAGE_PENDING_WORK:
            code, result = original_run_json(command, cwd)
            scope = pathlib.Path(str(result["pending_work_scope"]))
            checkpoint = scope.with_suffix(".release-publication.json")
            retained.update({"scope": scope, "checkpoint": checkpoint})
            return code, result
        assert pathlib.Path(command[1]) == SHIP_REPOSITORY
        retained["checkpoint"].write_text(
            "{}\n",
            encoding="utf-8",
            newline="\n",
        )
        return 1, blocker

    promote = loaded["promote"]
    promote.__globals__["_run_json"] = run_json
    args = loaded["build_parser"]().parse_args(
        [
            "--repo-root",
            str(repo),
            "--source-branch",
            "approved",
            "--ship-after-promotion",
        ]
    )
    with pytest.raises(loaded["PromotionError"]) as captured:
        promote(args)

    assert captured.value.payload == blocker
    assert len(commands) == 2
    assert retained["scope"].is_file()
    assert retained["checkpoint"].is_file()
    assert source_worktree.is_dir()
    assert run_git(source_worktree, "status", "--porcelain").stdout == ""
    assert run_git(repo, "show-ref", "--verify", "refs/heads/approved").returncode == 0
    assert run_git(repo, "status", "--porcelain").stdout == ""

    original_ship_after_promotion = loaded["_ship_after_promotion"]
    original_ship_after_promotion.__globals__["_run_json"] = (
        lambda command, cwd: (0, {"status": "ready"})
    )
    with pytest.raises(
        loaded["PromotionError"],
        match="incomplete terminal result",
    ):
        original_ship_after_promotion(
            args,
            repo.resolve(),
            target_commit=run_git(repo, "rev-parse", "release/local").stdout.strip(),
            pending_work_scope=str(retained["scope"]),
        )

    conflict_root = tmp_path / "promotion-blocker"
    (
        conflict_repo,
        _,
        _,
        conflict_release_head,
        _,
    ) = prepare_divergent_promotion_repo(conflict_root, conflict=True)
    conflict_loaded = runpy.run_path(str(PROMOTE_REPOSITORY))
    conflict_promote = conflict_loaded["promote"]

    def unexpected_run_json(
        command: list[str], cwd: pathlib.Path
    ) -> tuple[int, dict[str, Any]]:
        pytest.fail(f"promotion blocker invoked lifecycle child: {command}")

    conflict_promote.__globals__["_run_json"] = unexpected_run_json
    conflict_args = conflict_loaded["build_parser"]().parse_args(
        [
            "--repo-root",
            str(conflict_repo),
            "--source-branch",
            "approved",
            "--ship-after-promotion",
        ]
    )
    with pytest.raises(conflict_loaded["PromotionError"]):
        conflict_promote(conflict_args)
    assert run_git(conflict_repo, "rev-parse", "release/local").stdout.strip() == (
        conflict_release_head
    )


def test_promote_repository_prepare_only_mode_remains_unchanged(
    tmp_path: pathlib.Path,
) -> None:
    repo, _, log, _ = prepare_repository_lifecycle_repo(tmp_path)
    assert run_git(repo, "switch", "main").returncode == 0
    main_head = run_git(repo, "rev-parse", "main").stdout.strip()
    loaded = runpy.run_path(str(PROMOTE_REPOSITORY))
    promote = loaded["promote"]

    def unexpected_run_json(
        command: list[str], cwd: pathlib.Path
    ) -> tuple[int, dict[str, Any]]:
        pytest.fail(f"prepare-only invoked lifecycle child: {command}")

    promote.__globals__["_run_json"] = unexpected_run_json
    result = promote(
        loaded["build_parser"]().parse_args(
            [
                "--repo-root",
                str(repo),
                "--prepare-release-only",
            ]
        )
    )

    assert result == {
        "status": "prepared",
        "release_branch": "release/local",
        "head": main_head,
    }
    assert run_git(repo, "branch", "--show-current").stdout.strip() == "release/local"
    assert run_git(repo, "status", "--porcelain").stdout == ""
    assert not log.exists()


def test_promote_and_deploy_does_not_inject_base_revision(
    tmp_path: pathlib.Path,
) -> None:
    repo, approved_head, log, environment = prepare_repository_lifecycle_repo(
        tmp_path,
        managed_skills=True,
        handoff="ceratops-skill-lifecycle/deploy",
    )
    first = subprocess.run(
        [
            sys.executable,
            str(PROMOTE_REPOSITORY),
            "--repo-root",
            str(repo),
            "--source-branch",
            "approved",
            "--no-run-operation",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert first.returncode == 0, first.stderr
    assert not log.exists()

    retained_worktree = tmp_path / "approved-retained"
    assert (
        run_git(repo, "worktree", "add", str(retained_worktree), "approved").returncode
        == 0
    )
    retained_file = retained_worktree / "uncommitted.txt"
    retained_file.write_text("preserve me\n", encoding="utf-8", newline="\n")

    assert run_git(repo, "switch", "-c", "approved-second", "release/local").returncode == 0
    (repo / "README.md").write_text(
        "base\napproved\napproved second\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(repo, "add", "README.md").returncode == 0
    assert run_git(repo, "commit", "-m", "approved second change").returncode == 0
    second = subprocess.run(
        [
            sys.executable,
            str(PROMOTE_REPOSITORY),
            "--repo-root",
            str(repo),
            "--source-branch",
            "approved-second",
            "--run-operation",
            "deploy",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert second.returncode == 0, second.stderr
    second_result = json.loads(second.stdout)
    assert second_result["release_start"] == approved_head
    assert second_result["handoff"] == "ceratops-skill-lifecycle/deploy"
    assert second_result["preserved_sources"] == [
        {
            "branch": "approved",
            "findings": [
                {
                    "kind": "dirty_worktree",
                    "subject": "approved",
                    "detail": "1 status entry",
                }
            ],
        }
    ]
    second_head = run_git(repo, "rev-parse", "release/local").stdout.strip()
    assert json.loads(
        pathlib.Path(second_result["pending_work_scope"]).read_text(encoding="utf-8")
    ) == {
        "sources": [
            {
                "branch": "approved",
                "commit": approved_head,
                "state": "preserved",
            },
            {
                "branch": "approved-second",
                "commit": second_head,
                "state": "retained",
            },
        ],
        "target_branch": "release/local",
        "target_commit": second_head,
        "version": 2,
    }
    assert retained_file.read_text(encoding="utf-8") == "preserve me\n"
    assert log.read_text(encoding="utf-8") == "no-base\n"

    divergent = tmp_path / "automatic-rebase-success"
    (
        rebase_repo,
        source_worktree,
        source_head,
        release_head,
        rebase_environment,
    ) = prepare_divergent_promotion_repo(divergent)
    rebased = subprocess.run(
        [
            sys.executable,
            str(PROMOTE_REPOSITORY),
            "--repo-root",
            str(rebase_repo),
            "--source-branch",
            "approved",
            "--no-run-operation",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=rebase_environment,
    )

    assert rebased.returncode == 0, rebased.stderr
    rebase_result = json.loads(rebased.stdout)
    new_source_head = run_git(source_worktree, "rev-parse", "HEAD").stdout.strip()
    assert new_source_head != source_head
    assert rebase_result["head"] == new_source_head
    assert rebase_result["rebased_branches"] == [
        {
            "branch": "approved",
            "old_head": source_head,
            "new_head": new_source_head,
            "onto": release_head,
        }
    ]
    assert (
        run_git(
            rebase_repo,
            "merge-base",
            "--is-ancestor",
            release_head,
            "approved",
        ).returncode
        == 0
    )
    assert run_git(source_worktree, "status", "--porcelain").stdout == ""
    assert (source_worktree / "release.txt").read_text(encoding="utf-8") == (
        "release\n"
    )
    assert "approved" in (source_worktree / "README.md").read_text(
        encoding="utf-8"
    )


def test_promote_repository_rejects_noncanonical_release_branch_before_mutation(
    tmp_path: pathlib.Path,
) -> None:
    repo, _, _, environment = prepare_repository_lifecycle_repo(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(PROMOTE_REPOSITORY),
            "--repo-root",
            str(repo),
            "--source-branch",
            "approved",
            "--release-branch",
            "release/task",
            "--no-run-operation",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert result.returncode == 1
    assert json.loads(result.stderr)["message"] == (
        "release_branch must be release/local."
    )
    assert run_git(repo, "branch", "--show-current").stdout.strip() == "approved"
    assert run_git(repo, "branch", "--list", "release/task").stdout == ""

    conflict_root = tmp_path / "automatic-rebase-conflict"
    (
        conflict_repo,
        conflict_worktree,
        conflict_source_head,
        conflict_release_head,
        conflict_environment,
    ) = prepare_divergent_promotion_repo(conflict_root, conflict=True)
    conflicted = subprocess.run(
        [
            sys.executable,
            str(PROMOTE_REPOSITORY),
            "--repo-root",
            str(conflict_repo),
            "--source-branch",
            "approved",
            "--no-run-operation",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=conflict_environment,
    )

    assert conflicted.returncode == 1
    conflict_message = json.loads(conflicted.stderr)["message"]
    assert "original head" in conflict_message
    assert "conflicting paths: README.md" in conflict_message
    assert run_git(conflict_worktree, "rev-parse", "HEAD").stdout.strip() == (
        conflict_source_head
    )
    assert run_git(conflict_worktree, "status", "--porcelain").stdout == ""
    assert run_git(conflict_repo, "rev-parse", "release/local").stdout.strip() == (
        conflict_release_head
    )

    published_root = tmp_path / "automatic-rebase-published"
    (
        published_repo,
        published_worktree,
        published_source_head,
        _,
        published_environment,
    ) = prepare_divergent_promotion_repo(published_root, published=True)
    published = subprocess.run(
        [
            sys.executable,
            str(PROMOTE_REPOSITORY),
            "--repo-root",
            str(published_repo),
            "--source-branch",
            "approved",
            "--no-run-operation",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=published_environment,
    )

    assert published.returncode == 1
    assert json.loads(published.stderr)["message"] == (
        "Automatic rebase refuses published branch: approved"
    )
    assert run_git(published_worktree, "rev-parse", "HEAD").stdout.strip() == (
        published_source_head
    )
    assert run_git(published_worktree, "status", "--porcelain").stdout == ""

    nonlinear_root = tmp_path / "automatic-rebase-nonlinear"
    (
        nonlinear_repo,
        nonlinear_worktree,
        nonlinear_source_head,
        _,
        nonlinear_environment,
    ) = prepare_divergent_promotion_repo(nonlinear_root, nonlinear=True)
    nonlinear = subprocess.run(
        [
            sys.executable,
            str(PROMOTE_REPOSITORY),
            "--repo-root",
            str(nonlinear_repo),
            "--source-branch",
            "approved",
            "--no-run-operation",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=nonlinear_environment,
    )

    assert nonlinear.returncode == 1
    assert json.loads(nonlinear.stderr)["message"] == (
        "Automatic rebase requires linear source history: approved"
    )
    assert run_git(nonlinear_worktree, "rev-parse", "HEAD").stdout.strip() == (
        nonlinear_source_head
    )
    assert run_git(nonlinear_worktree, "status", "--porcelain").stdout == ""


def test_promote_and_deploy_rejects_operation_created_repository_work(
    tmp_path: pathlib.Path,
) -> None:
    repo, _, _, environment = prepare_repository_lifecycle_repo(tmp_path)
    probe = repo / "deploy-probe.py"
    probe.write_text(
        "import pathlib\n"
        "pathlib.Path('generated-by-deploy.txt').write_text("
        "'untracked\\n', encoding='utf-8')\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(repo, "add", "deploy-probe.py").returncode == 0
    assert run_git(repo, "commit", "-m", "create deploy output").returncode == 0

    promoted = subprocess.run(
        [
            sys.executable,
            str(PROMOTE_REPOSITORY),
            "--repo-root",
            str(repo),
            "--source-branch",
            "approved",
            "--run-operation",
            "deploy",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert promoted.returncode == 1
    result = json.loads(promoted.stderr)
    assert result["status"] == "error"
    assert "dirty" in result["message"].lower()
    assert "ready" in result["message"].lower()
    assert (repo / "generated-by-deploy.txt").is_file()
