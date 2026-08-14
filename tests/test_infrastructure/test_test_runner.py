from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from typing import Any

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = "1" * 40
HEAD = "2" * 40


class DeterministicExecution:
    """Provide Git evidence and collect real tests while stubbing final execution."""

    def __init__(self, runner: Any, diff: bytes, *, untracked: bytes = b"") -> None:
        self.runner = runner
        self.diff = diff
        self.untracked = untracked
        self.commands: list[tuple[str, ...]] = []
        self.final_pytest: list[tuple[str, ...]] = []

    def text(
        self, command: Any, cwd: pathlib.Path
    ) -> subprocess.CompletedProcess[str]:
        argv = tuple(command)
        self.commands.append(argv)
        if argv[:3] == ("git", "rev-parse", "--verify"):
            revision = argv[3].split("^", 1)[0]
            if revision == "HEAD":
                revision = BASE
            return subprocess.CompletedProcess(command, 0, revision + "\n", "")
        assert argv[:3] == (sys.executable, "-m", "pytest")
        if "--collect-only" in argv:
            return self.runner.run_text(command, cwd)
        self.final_pytest.append(argv)
        return subprocess.CompletedProcess(command, 0, "all selected tests passed\n", "")

    def bytes(
        self, command: Any, cwd: pathlib.Path
    ) -> subprocess.CompletedProcess[bytes]:
        argv = tuple(command)
        self.commands.append(argv)
        if argv == ("git", "ls-files", "-z"):
            return self.runner.run_bytes(command, cwd)
        if argv == ("git", "ls-files", "--others", "--exclude-standard", "-z"):
            return subprocess.CompletedProcess(command, 0, self.untracked, b"")
        assert argv[:5] == (
            "git",
            "diff",
            "--name-status",
            "-z",
            "--find-renames",
        )
        return subprocess.CompletedProcess(command, 0, self.diff, b"")


def payload(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    return json.loads(capsys.readouterr().out)


def test_committed_diff_mode_collects_and_invokes_only_selected_suite(
    test_runner_module: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = test_runner_module
    execution = DeterministicExecution(
        runner,
        b"M\0skills/ceratops-credit-savings-analysis/scripts/credit_analysis/holistic.py\0",
    )

    exit_code = runner.execute(
        ["--base", BASE, "--head", HEAD],
        repo_root=ROOT,
        text_runner=execution.text,
        bytes_runner=execution.bytes,
    )
    result = payload(capsys)

    assert exit_code == 0
    assert result["status"] == "passed"
    assert result["base"] == BASE
    assert result["head"] == HEAD
    assert result["selected_suites"] == ["credit-analysis"]
    assert result["pytest_targets"] == ["tests/credit_analysis"]
    assert result["changed"] == [
        {
            "paths": [
                "skills/ceratops-credit-savings-analysis/scripts/credit_analysis/holistic.py"
            ],
            "status": "M",
        }
    ]
    assert execution.final_pytest == [
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/credit_analysis",
        )
    ]
    assert all(
        command[0] == "git"
        or command[:3] == (sys.executable, "-m", "pytest")
        for command in execution.commands
    )


def test_mapping_gap_runs_full_suite_and_returns_distinct_status(
    test_runner_module: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = test_runner_module
    execution = DeterministicExecution(runner, b"A\0src/unmapped.py\0")

    exit_code = runner.execute(
        ["--base", BASE, "--head", HEAD],
        repo_root=ROOT,
        text_runner=execution.text,
        bytes_runner=execution.bytes,
    )
    result = payload(capsys)

    assert exit_code == runner.MAPPING_GAP_EXIT_CODE
    assert result["status"] == "mapping-gap"
    assert result["pytest"]["outcome"] == "passed"
    assert result["full_suite_fallback"] is True
    assert result["mapping_gaps"] == [
        {"path": "src/unmapped.py", "reason": "unmapped repository path"}
    ]
    assert result["selected_suites"] == sorted(
        runner.load_manifest(ROOT / "tests" / "test-impact.json").suites
    )
    assert len(execution.final_pytest) == 1


def test_full_mode_uses_sorted_manifest_targets_without_ambient_inference(
    test_runner_module: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = test_runner_module
    execution = DeterministicExecution(runner, b"")

    exit_code = runner.execute(
        ["--all"],
        repo_root=ROOT,
        text_runner=execution.text,
        bytes_runner=execution.bytes,
    )
    result = payload(capsys)

    assert exit_code == 0
    assert result["mode"] == "all"
    assert result["full_suite"] is True
    assert result["full_suite_fallback"] is False
    final = execution.final_pytest[0]
    assert final[:4] == (sys.executable, "-m", "pytest", "-q")
    assert list(final[4:]) == sorted(final[4:])


def test_explicit_worktree_mode_selects_tracked_and_untracked_changes(
    test_runner_module: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = test_runner_module
    execution = DeterministicExecution(
        runner,
        b"M\0skills/ceratops-credit-savings-analysis/SKILL.md\0",
        untracked=b"skills/ceratops-governance-lifecycle/new.py\0",
    )

    exit_code = runner.execute(
        ["--worktree"],
        repo_root=ROOT,
        text_runner=execution.text,
        bytes_runner=execution.bytes,
    )
    result = payload(capsys)

    assert exit_code == 0
    assert result["mode"] == "worktree"
    assert result["base"] == BASE
    assert result["head"] == "WORKTREE"
    assert result["selected_suites"] == ["credit-analysis", "governance-lifecycle"]
    assert result["changed"] == [
        {
            "paths": ["skills/ceratops-credit-savings-analysis/SKILL.md"],
            "status": "M",
        },
        {
            "paths": ["skills/ceratops-governance-lifecycle/new.py"],
            "status": "A",
        },
    ]
    assert len(execution.final_pytest) == 1


def test_revision_mode_requires_two_full_commit_shas(
    test_runner_module: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = test_runner_module

    missing_head = runner.execute(["--base", BASE], repo_root=ROOT)
    first = payload(capsys)
    short_sha = runner.execute(
        ["--base", "1234", "--head", HEAD], repo_root=ROOT
    )
    second = payload(capsys)

    assert missing_head == runner.CONFIGURATION_EXIT_CODE
    assert first["status"] == "configuration-error"
    assert short_sha == runner.CONFIGURATION_EXIT_CODE
    assert second["status"] == "configuration-error"
    assert "full 40-character SHA" in second["manifest_errors"][0]


def test_manifest_validation_mode_collects_every_declared_target(
    test_runner_module: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = test_runner_module

    exit_code = runner.execute(["--validate-manifest"], repo_root=ROOT)
    result = payload(capsys)

    assert exit_code == 0
    assert result["status"] == "manifest-valid"
    assert result["pytest"]["outcome"] == "not-run"
