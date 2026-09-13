from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest

from tests.support.repositories import ROOT, run_git

CLOSURE_SNAPSHOT = ROOT / "skills" / "ceratops-task-lifecycle" / "scripts" / "closure_snapshot.py"
CREDIT_SKILL = ROOT / "skills" / "ceratops-credit-savings-analysis" / "SKILL.md"
CREDIT_CONTRACT = (
    ROOT
    / "skills"
    / "ceratops-credit-savings-analysis"
    / "scripts"
    / "credit-analysis-contract.json"
)
CREDIT_FULL_REFERENCE = (
    ROOT
    / "skills"
    / "ceratops-credit-savings-analysis"
    / "references"
    / "full-analysis.md"
)


def test_closure_snapshot_composes_only_named_local_state(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    task_worktree = tmp_path / "task-worktree"
    temp_root = tmp_path / "retained-temp"
    repo.mkdir()
    temp_root.mkdir()
    (temp_root / "one.txt").write_text("one\n", encoding="utf-8", newline="\n")
    (temp_root / "two.txt").write_text("two\n", encoding="utf-8", newline="\n")

    spec = importlib.util.spec_from_file_location("closure_snapshot", CLOSURE_SNAPSHOT)
    assert spec is not None and spec.loader is not None
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)

    def unexpected_traversal(*args: object, **kwargs: object) -> object:
        raise AssertionError("Default closure must not enumerate the temp tree")

    with monkeypatch.context() as scoped:
        scoped.setattr(pathlib.Path, "rglob", unexpected_traversal)
        scoped.setattr(pathlib.Path, "iterdir", unexpected_traversal)
        assert helper.temp_snapshot(temp_root)["files"] is None
        assert helper.temp_snapshot(temp_root / "absent")["files"] == 0
    nested = temp_root / "nested"
    nested.mkdir()
    (nested / "three.txt").write_text("three\n", encoding="utf-8")
    assert helper.temp_snapshot(temp_root, count_files=True)["files"] == 3
    with pytest.raises(helper.SnapshotError, match="not a directory"):
        helper.temp_snapshot(temp_root / "one.txt")

    assert run_git(tmp_path, "init", "--bare", str(remote)).returncode == 0
    assert run_git(repo, "init", "-b", "main").returncode == 0
    assert run_git(repo, "config", "user.name", "Closure Test").returncode == 0
    assert (
        run_git(repo, "config", "user.email", "closure@example.invalid").returncode
        == 0
    )
    (repo / "README.md").write_text("base\n", encoding="utf-8", newline="\n")
    assert run_git(repo, "add", "README.md").returncode == 0
    assert run_git(repo, "commit", "-m", "base").returncode == 0
    assert run_git(repo, "remote", "add", "origin", str(remote)).returncode == 0
    assert run_git(repo, "push", "-u", "origin", "main").returncode == 0
    assert run_git(repo, "branch", "release/local").returncode == 0
    assert run_git(repo, "push", "origin", "release/local").returncode == 0
    (repo / "local.txt").write_text("local\n", encoding="utf-8", newline="\n")
    assert run_git(repo, "add", "local.txt").returncode == 0
    assert run_git(repo, "commit", "-m", "local").returncode == 0
    assert (
        run_git(
            repo,
            "worktree",
            "add",
            "-b",
            "codex/closure-test",
            str(task_worktree),
            "release/local",
        ).returncode
        == 0
    )
    (task_worktree / "task.txt").write_text(
        "task\n", encoding="utf-8", newline="\n"
    )
    assert run_git(task_worktree, "add", "task.txt").returncode == 0
    assert run_git(task_worktree, "commit", "-m", "task").returncode == 0
    assert (
        run_git(repo, "branch", "-f", "release/local", "codex/closure-test").returncode
        == 0
    )

    snapshot = subprocess.run(
        [
            sys.executable,
            str(CLOSURE_SNAPSHOT),
            "--repo",
            str(repo),
            "--fetch-remote",
            "origin",
            "--release-branch",
            "release/local",
            "--release-upstream",
            "origin/release/local",
            "--task-worktree",
            str(task_worktree),
            "--task-branch",
            "codex/closure-test",
            "--temp-root",
            str(temp_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert snapshot.returncode == 0, snapshot.stderr
    result = json.loads(snapshot.stdout)
    assert result["schema"] == "ceratops-closure-snapshot.v1"
    assert result["repo"]["branch"] == "main"
    assert result["repo"]["clean"] is True
    assert result["repo"]["tracking"] == {
        "status": "tracked",
        "ref": "origin/main",
        "ahead": 1,
        "behind": 0,
    }
    assert result["release"]["ahead"] == 1
    assert result["release"]["behind"] == 0
    assert result["task"]["branch"] == "codex/closure-test"
    assert result["task"]["clean"] is True
    assert result["task"]["staged_in_release"] is True
    assert result["temp"]["files"] is None

    counted = subprocess.run(
        [sys.executable, str(CLOSURE_SNAPSHOT), "--repo", str(repo),
         "--temp-root", str(temp_root), "--count-temp-files"],
        capture_output=True, text=True, check=False,
    )
    assert counted.returncode == 0, counted.stderr
    assert json.loads(counted.stdout)["temp"]["files"] == 3
    missing_root = subprocess.run(
        [sys.executable, str(CLOSURE_SNAPSHOT), "--repo", str(repo), "--count-temp-files"],
        capture_output=True, text=True, check=False,
    )
    assert missing_root.returncode == 2
    assert "--count-temp-files requires --temp-root" in missing_root.stderr

    invalid = subprocess.run(
        [
            sys.executable,
            str(CLOSURE_SNAPSHOT),
            "--repo",
            str(repo),
            "--release-branch",
            "release/local",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalid.returncode == 2
    assert "must be provided together" in invalid.stderr


def test_explicit_credit_analysis_defaults_to_full_analysis() -> None:
    skill = CREDIT_SKILL.read_text(encoding="utf-8")
    full = CREDIT_FULL_REFERENCE.read_text(encoding="utf-8")
    contract = json.loads(CREDIT_CONTRACT.read_text(encoding="utf-8"))
    actions = {row["id"]: row for row in contract["public_actions"]}

    assert "`full-analysis` for a generic single-thread or closure request" in skill
    assert actions["full-analysis"] == {
        "id": "full-analysis",
        "reference": "references/full-analysis.md",
        "mode": "full-analysis",
    }
    assert list(actions) == [
        "full-analysis",
        "helper-contracts",
        "context-evidence",
        "rework-validation",
        "tool-flow",
        "instruction-reasoning",
    ]
    assert full.startswith("# Full Analysis Action\n")
    assert "every completed run as one semantic unit" in full
    assert "assign the admitted tasks among `A = min(6," in full
    assert "Plan at most eight" in full
    assert "Sol calls, excluding retries and corrective attempts" in full
    assert "allow at most sixteen" in full
    assert "actual Sol invocations including initial calls, retries" in full
    assert contract["end_to_end_controller_commands"] == [
        "run",
        "plan",
        "execute",
    ]
