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


class CollectionExecution:
    """Return one declared pytest collection without running any test."""

    def __init__(self, runner: Any, nodes: tuple[str, ...]) -> None:
        self.runner = runner
        self.nodes = nodes
        self.commands: list[tuple[str, ...]] = []

    def text(
        self, command: Any, cwd: pathlib.Path
    ) -> subprocess.CompletedProcess[str]:
        argv = tuple(command)
        self.commands.append(argv)
        assert argv[:5] == (
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
        )
        return subprocess.CompletedProcess(command, 0, "\n".join(self.nodes) + "\n", "")

    def bytes(
        self, command: Any, cwd: pathlib.Path
    ) -> subprocess.CompletedProcess[bytes]:
        argv = tuple(command)
        self.commands.append(argv)
        assert argv == ("git", "ls-files", "-z")
        return self.runner.run_bytes(command, cwd)


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


def test_collection_snapshot_reconciles_moved_parameterized_nodes(
    test_runner_module: Any,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = test_runner_module
    baseline_path = tmp_path / "collection.json"
    old_nodes = (
        "tests/legacy/test_flow.py::test_case[first]",
        "tests/legacy/test_flow.py::test_case[second]",
    )
    writer = CollectionExecution(runner, old_nodes)

    write_exit = runner.execute(
        ["--write-collection", str(baseline_path)],
        repo_root=ROOT,
        text_runner=writer.text,
        bytes_runner=writer.bytes,
    )
    written = payload(capsys)

    assert write_exit == 0
    assert written["status"] == "collection-snapshot-written"
    assert written["collection"]["count"] == 2
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert baseline["schema"] == runner.COLLECTION_SCHEMA
    assert baseline["nodes"] == list(old_nodes)

    current_nodes = (
        "tests/domain/test_flow.py::test_case[first]",
        "tests/domain/test_flow.py::test_case[second]",
        "tests/domain/test_flow.py::test_new_case",
    )
    reconciler = CollectionExecution(runner, current_nodes)
    reconcile_exit = runner.execute(
        ["--reconcile-collection", str(baseline_path)],
        repo_root=ROOT,
        text_runner=reconciler.text,
        bytes_runner=reconciler.bytes,
    )
    reconciled = payload(capsys)

    assert reconcile_exit == 0
    assert reconciled["status"] == "collection-reconciled"
    assert reconciled["collection"]["preserved_count"] == 2
    assert reconciled["collection"]["moved_count"] == 2
    assert reconciled["collection"]["added"] == [
        "tests/domain/test_flow.py::test_new_case"
    ]
    assert {
        (item["old"], item["new"], item["method"])
        for item in reconciled["collection"]["moved"]
    } == {
        (old_nodes[0], current_nodes[0], "identity"),
        (old_nodes[1], current_nodes[1], "identity"),
    }


def test_collection_node_map_resolves_ambiguous_identity(
    test_runner_module: Any,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = test_runner_module
    baseline_path = tmp_path / "collection.json"
    old = "tests/legacy/test_flow.py::test_case[value]"
    writer = CollectionExecution(runner, (old,))
    assert runner.execute(
        ["--write-collection", str(baseline_path)],
        repo_root=ROOT,
        text_runner=writer.text,
        bytes_runner=writer.bytes,
    ) == 0
    payload(capsys)

    candidates = (
        "tests/alpha/test_flow.py::test_case[value]",
        "tests/beta/test_flow.py::test_case[value]",
    )
    ambiguous = CollectionExecution(runner, candidates)
    mismatch_exit = runner.execute(
        ["--reconcile-collection", str(baseline_path)],
        repo_root=ROOT,
        text_runner=ambiguous.text,
        bytes_runner=ambiguous.bytes,
    )
    mismatch = payload(capsys)

    assert mismatch_exit == runner.COLLECTION_MISMATCH_EXIT_CODE
    assert mismatch["status"] == "collection-mismatch"
    assert mismatch["collection"]["ambiguous"] == [
        {"old": old, "candidates": list(candidates)}
    ]
    missing = runner.reconcile_collections((old,), (), {})
    assert missing["ok"] is False
    assert missing["missing"] == [old]

    node_map = tmp_path / "node-map.json"
    node_map.write_text(
        json.dumps(
            {
                "schema": runner.NODE_MAP_SCHEMA,
                "mappings": {old: candidates[1]},
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    resolved = CollectionExecution(runner, candidates)
    resolved_exit = runner.execute(
        [
            "--reconcile-collection",
            str(baseline_path),
            "--node-map",
            str(node_map),
        ],
        repo_root=ROOT,
        text_runner=resolved.text,
        bytes_runner=resolved.bytes,
    )
    result = payload(capsys)

    assert resolved_exit == 0
    assert result["status"] == "collection-reconciled"
    assert result["collection"]["moved"] == [
        {"method": "explicit", "new": candidates[1], "old": old}
    ]
    assert result["collection"]["added"] == [candidates[0]]
    changed_identity = runner.reconcile_collections(
        (old,),
        ("tests/beta/test_flow.py::test_case[changed]",),
        {old: "tests/beta/test_flow.py::test_case[changed]"},
    )
    assert changed_identity["ok"] is False
    assert changed_identity["mapping_errors"] == [
        "node map changes pytest identity: "
        f"{old} -> tests/beta/test_flow.py::test_case[changed]"
    ]
