from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "scripts" / "validate-repository.py"
SPEC = importlib.util.spec_from_file_location(
    "validate_repository_under_test", VALIDATOR_PATH
)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


def completed(
    command: Any, returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def test_build_checks_owns_order_both_platforms_and_space_safe_paths(
    tmp_path: pathlib.Path,
) -> None:
    repo_root = tmp_path / "repository with spaces"

    checks = VALIDATOR.build_checks(
        repo_root,
        python_executable="python executable",
        npm_executable="npm executable",
    )

    assert [(check.name, check.platform) for check in checks] == [
        ("markdown-lint", None),
        ("yaml-lint", None),
        ("ruff", None),
        ("mypy", "linux"),
        ("mypy", "win32"),
        ("pytest", None),
    ]
    assert checks[2].command == (
        "python executable",
        "-m",
        "ruff",
        "check",
        "scripts",
        "skills/ceratops-repo-lifecycle/references/templates/"
        "install-skills-bootstrap-template.py",
    )
    assert checks[3].command[-2:] == ("--platform", "linux")
    assert checks[4].command[-2:] == ("--platform", "win32")


def test_ci_runs_repository_validator_that_owns_both_mypy_platforms() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "validate.yml").read_text(
            encoding="utf-8"
        )
    )
    steps = workflow["jobs"]["validate-repository"]["steps"]
    validation_step = next(
        step for step in steps if step.get("name") == "Validate repository"
    )
    assert " ".join(validation_step["run"].split()).startswith(
        "python scripts/validate-repository.py "
    )

    checks = VALIDATOR.build_checks(
        ROOT,
        python_executable="python",
        npm_executable="npm",
    )
    assert [
        check.command[-1]
        for check in checks
        if check.name == "mypy"
    ] == ["linux", "win32"]


def test_run_process_captures_output_without_a_shell(
    tmp_path: pathlib.Path, monkeypatch: Any
) -> None:
    observed: dict[str, Any] = {}

    def fake_subprocess_run(command: list[str], **kwargs: Any) -> Any:
        observed["command"] = command
        observed.update(kwargs)
        return completed(command)

    monkeypatch.setattr(VALIDATOR.subprocess, "run", fake_subprocess_run)

    VALIDATOR.run_process(("tool", "argument with spaces"), tmp_path)

    assert observed["command"] == ["tool", "argument with spaces"]
    assert observed["cwd"] == tmp_path
    assert observed["capture_output"] is True
    assert observed["text"] is True
    assert observed["check"] is False
    assert "shell" not in observed


def test_success_prints_exactly_ok_and_suppresses_child_output(
    tmp_path: pathlib.Path, capsys: Any
) -> None:
    calls: list[tuple[tuple[str, ...], pathlib.Path]] = []

    def fake_runner(
        command: tuple[str, ...], cwd: pathlib.Path
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, cwd))
        return completed(command, stdout="noisy stdout", stderr="noisy stderr")

    evidence_file = tmp_path / "evidence file.log"
    evidence_file.write_text("stale failure evidence\n", encoding="utf-8")
    temporary = evidence_file.with_name(f".{evidence_file.name}.tmp")
    temporary.write_text("stale partial evidence\n", encoding="utf-8")
    result = VALIDATOR.main(
        ["--evidence-file", str(evidence_file)],
        process_runner=fake_runner,
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == "OK\n"
    assert captured.err == ""
    assert len(calls) == 6
    assert not evidence_file.exists()
    assert not temporary.exists()


def test_failure_is_fail_fast_compact_and_writes_complete_evidence(
    tmp_path: pathlib.Path, capsys: Any
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_runner(
        command: tuple[str, ...], cwd: pathlib.Path
    ) -> subprocess.CompletedProcess[str]:
        del cwd
        calls.append(command)
        if len(calls) == 5:
            return completed(
                command,
                returncode=7,
                stdout="complete stdout diagnostics",
                stderr="complete stderr diagnostics",
            )
        return completed(command)

    evidence_file = tmp_path / "evidence directory" / "failure evidence.log"
    result = VALIDATOR.main(
        ["--evidence-file", str(evidence_file)],
        process_runner=fake_runner,
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 7
    assert len(calls) == 5
    assert payload == {
        "check": "mypy",
        "platform": "win32",
        "exit_code": 7,
        "evidence_file": str(evidence_file.resolve()),
    }
    assert captured.out == json.dumps(payload, separators=(",", ":")) + "\n"
    assert captured.err == ""
    evidence = evidence_file.read_text(encoding="utf-8")
    assert "platform: win32" in evidence
    assert "complete stdout diagnostics" in evidence
    assert "complete stderr diagnostics" in evidence
    assert "complete stdout diagnostics" not in captured.out
    assert "complete stderr diagnostics" not in captured.out


def test_omitted_evidence_flag_keeps_repository_default(
    tmp_path: pathlib.Path, monkeypatch: Any, capsys: Any
) -> None:
    repo_root = tmp_path / "repository"
    validator_path = repo_root / "scripts" / "validate-repository.py"
    monkeypatch.setattr(VALIDATOR, "__file__", str(validator_path))

    def failing_runner(
        command: tuple[str, ...], cwd: pathlib.Path
    ) -> subprocess.CompletedProcess[str]:
        del cwd
        return completed(command, returncode=3, stderr="failure")

    result = VALIDATOR.main([], process_runner=failing_runner)

    payload = json.loads(capsys.readouterr().out)
    expected = repo_root / "build" / "deploy-validation" / "repository-validation.log"
    assert result == 3
    assert payload["evidence_file"] == str(expected)
    assert expected.is_file()

    def passing_runner(
        command: tuple[str, ...], cwd: pathlib.Path
    ) -> subprocess.CompletedProcess[str]:
        del cwd
        return completed(command)

    success = VALIDATOR.main([], process_runner=passing_runner)

    assert success == 0
    assert capsys.readouterr().out == "OK\n"
    assert not expected.exists()
    assert not expected.parent.exists()
