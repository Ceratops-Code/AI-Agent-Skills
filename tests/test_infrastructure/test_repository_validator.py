from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tomllib
import zoneinfo
from importlib.metadata import version
from typing import Any

import pytest
import yaml
from packaging.requirements import Requirement

ROOT = pathlib.Path(__file__).resolve().parents[2]
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
        "tools",
        "skills/ceratops-repo-lifecycle/references/templates/"
        "install-skills-bootstrap-template.py",
    )
    assert checks[3].command[-2:] == ("--platform", "linux")
    assert checks[4].command[-2:] == ("--platform", "win32")
    diagnostic = repo_root / "build" / "test-diagnostics" / "pytest-failure.json"
    assert checks[5].command == (
        "python executable",
        "scripts/run-tests.py",
        "--all",
        "--diagnostic-output",
        str(diagnostic),
    )
    assert len(
        VALIDATOR.build_checks(
            repo_root,
            python_executable="python executable",
            npm_executable="npm executable",
            include_tests=False,
        )
    ) == 5


def test_ci_runs_repository_validator_that_owns_both_mypy_platforms() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "validate.yml").read_text(
            encoding="utf-8"
        )
    )
    steps = workflow["jobs"]["validate-repository"]["steps"]
    python_step = next(step for step in steps if step.get("name") == "Select repository Python")
    assert python_step["uses"].startswith("actions/setup-python@")
    assert python_step["with"] == {"python-version-file": "pyproject.toml"}
    installation_step = next(step for step in steps if step.get("name") == "Install development validators")
    assert steps.index(python_step) < steps.index(installation_step)
    validation_step = next(
        step for step in steps if step.get("name") == "Validate repository"
    )
    assert " ".join(validation_step["run"].split()).startswith(
        "python scripts/validate-repository.py "
    )
    assert "--without-tests" in validation_step["run"].split()
    pull_request_step = next(
        step for step in steps if step.get("name") == "Run pull-request impact tests"
    )
    full_step = next(
        step for step in steps if step.get("name") == "Run full main-branch tests"
    )
    pull_request_command = " ".join(pull_request_step["run"].split())
    assert pull_request_command.startswith(
        "python scripts/run-tests.py --base "
    )
    assert " --head " in pull_request_command
    assert (
        "--diagnostic-output ${{ runner.temp }}/pytest-failure.json"
        in pull_request_command
    )
    assert " ".join(full_step["run"].split()) == (
        "python scripts/run-tests.py --all "
        "--diagnostic-output ${{ runner.temp }}/pytest-failure.json"
    )
    upload_step = next(
        step for step in steps if step.get("name") == "Upload validation evidence"
    )
    assert upload_step["with"]["path"].splitlines() == [
        "${{ runner.temp }}/repository-validation.log",
        "${{ runner.temp }}/pytest-failure.json",
    ]

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
    assert next(check for check in checks if check.name == "pytest").command == (
        "python",
        "scripts/run-tests.py",
        "--all",
        "--diagnostic-output",
        str(ROOT / "build" / "test-diagnostics" / "pytest-failure.json"),
    )


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


def test_pytest_failure_surfaces_bounded_actions_and_retains_complete_evidence(
    tmp_path: pathlib.Path, capsys: Any
) -> None:
    calls: list[tuple[str, ...]] = []
    child_payload: dict[str, Any] = {
        "status": "pytest-failed",
        "pytest": {
            "failure_count": 6,
            "omitted_failure_count": 4,
            "failures": [
                {
                    "test": "tests/test_alpha.py::test_contract",
                    "source_location": "tests/test_alpha.py:18",
                    "excerpt": "E       assert actual == expected",
                },
                {
                    "test": "tests/test_beta.py::test_configuration",
                    "source_location": "tests/test_beta.py:27",
                    "excerpt": "E       RuntimeError: invalid configuration",
                },
            ],
            "diagnostic": {
                "bytes": 4321,
                "path": "build/test-diagnostics/pytest-failure.json",
                "sha256": "a" * 64,
            },
            "context_excerpt": "full child context that is not forwarded",
        },
        "unrelated": "not part of the aggregate failure contract",
    }
    child_stdout = json.dumps(child_payload, separators=(",", ":"))

    def fake_runner(
        command: tuple[str, ...], cwd: pathlib.Path
    ) -> subprocess.CompletedProcess[str]:
        del cwd
        calls.append(command)
        if len(calls) == 6:
            return completed(
                command,
                returncode=1,
                stdout=child_stdout,
                stderr="complete pytest runner stderr",
            )
        return completed(command)

    evidence_file = tmp_path / "validator" / "failure.log"
    result = VALIDATOR.main(
        ["--evidence-file", str(evidence_file)],
        process_runner=fake_runner,
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 1
    assert len(calls) == 6
    assert payload == {
        "check": "pytest",
        "exit_code": 1,
        "evidence_file": str(evidence_file.resolve()),
        "failure_count": 6,
        "omitted_failure_count": 4,
        "failures": child_payload["pytest"]["failures"],
        "diagnostic": child_payload["pytest"]["diagnostic"],
    }
    assert "context_excerpt" not in captured.out
    assert "unrelated" not in captured.out
    evidence = evidence_file.read_text(encoding="utf-8")
    assert child_stdout in evidence
    assert "complete pytest runner stderr" in evidence


def test_omitted_evidence_flag_keeps_repository_default(
    tmp_path: pathlib.Path, monkeypatch: Any, capsys: Any
) -> None:
    repo_root = tmp_path / "repository"
    repo_root.mkdir()
    (repo_root / "pyproject.toml").write_text(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )
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


@pytest.mark.parametrize(
    ("requirement", "version", "accepted"),
    [
        (">=3.14,<3.15", "3.14.7", True),
        (">=3.14,<3.15", "3.13.12", False),
        (">=3.14,<3.15", "3.15.0", False),
        (">=3.14,<3.15", "3.15.0rc1", False),
        (">=3.15,<3.16", "3.15.1", True),
        (">=3.15,<3.16", "3.14.7", False),
    ],
)
def test_python_requirement_uses_declared_range_not_a_helper_pin(
    tmp_path: pathlib.Path, monkeypatch: Any, requirement: str, version: str, accepted: bool
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nrequires-python = "{requirement}"\n', encoding="utf-8"
    )
    monkeypatch.setattr(VALIDATOR.platform, "python_version", lambda: version)
    if accepted:
        VALIDATOR.require_repository_python(tmp_path)
    else:
        with pytest.raises(ValueError, match="does not satisfy"):
            VALIDATOR.require_repository_python(tmp_path)


@pytest.mark.parametrize("metadata", ["", "[project]\n", '[project]\nrequires-python = ""\n', '[project]\nrequires-python = "not-a-version"\n'])
def test_python_requirement_rejects_missing_or_invalid_metadata(
    tmp_path: pathlib.Path, metadata: str
) -> None:
    (tmp_path / "pyproject.toml").write_text(metadata, encoding="utf-8")
    with pytest.raises(ValueError):
        VALIDATOR.require_repository_python(tmp_path)


def test_wrong_python_stops_before_checks_and_succeeds_after_correction(
    tmp_path: pathlib.Path, monkeypatch: Any, capsys: Any
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.14,<3.15"\n', encoding="utf-8"
    )
    monkeypatch.setattr(VALIDATOR, "__file__", str(tmp_path / "scripts" / "validate-repository.py"))
    monkeypatch.setattr(VALIDATOR.platform, "python_version", lambda: "3.13.12")
    calls: list[Any] = []

    def runner(command: Any, cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
        calls.append((command, cwd))
        return completed(command)

    evidence = tmp_path / "diagnostics" / "python.log"
    result = VALIDATOR.main(["--evidence-file", str(evidence)], process_runner=runner)
    payload = json.loads(capsys.readouterr().out)
    assert result == 2
    assert calls == []
    assert payload["check"] == "python-requirement"
    assert "Python 3.13.12" in payload["reason"]
    assert "project.requires-python" in evidence.read_text(encoding="utf-8")
    monkeypatch.setattr(VALIDATOR.platform, "python_version", lambda: "3.14.7")
    assert VALIDATOR.main(["--evidence-file", str(evidence)], process_runner=runner) == 0
    assert capsys.readouterr().out == "OK\n"
    assert len(calls) == 6
    assert not evidence.exists()


def test_repository_setup_has_one_python_selection_and_no_interpreter_downloads() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["tool"]["uv"]["python-preference"] == "only-system"
    assert metadata["tool"]["uv"]["python-downloads"] == "never"
    assert metadata["tool"]["uv"]["package"] is False
    assert "python_version" not in metadata["tool"]["mypy"]
    assert "target-version" not in metadata["tool"].get("ruff", {})
    tool_metadata = tomllib.loads(
        (ROOT / "tools" / "ceratops-tool-manager" / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert metadata["project"]["requires-python"] == tool_metadata["project"]["requires-python"]


def test_runtime_dependencies_supply_timezones_without_an_os_database() -> None:
    requirements = [
        Requirement(line)
        for line in (ROOT / "requirements-runtime.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    timezone_requirement = next(item for item in requirements if item.name == "tzdata")
    assert version("tzdata") in timezone_requirement.specifier
    original_path = zoneinfo.TZPATH
    zoneinfo.reset_tzpath(())
    try:
        for key in ("UTC", "Asia/Jerusalem"):
            assert zoneinfo.ZoneInfo.no_cache(key).key == key
    finally:
        zoneinfo.reset_tzpath(original_path)
