from __future__ import annotations

import argparse
import json
import os
import pathlib
import runpy
import shutil
import subprocess
import sys
from typing import Any

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "skills-consistency-source-validator.py"
BUILDER = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "runtime" / "managed_runtime_builder.py"
BOOTSTRAP = ROOT / "scripts" / "install-skills.py"
LIFECYCLE_SOURCE = ROOT / "skills" / "ceratops-skill-lifecycle"
REPOSITORY_LIFECYCLE_SOURCE = ROOT / "skills" / "ceratops-repo-lifecycle"
LIVE_SECTION_MANIFEST = ROOT / "skills" / "skill-sections.json"
SECTION_MANIFEST_TEMPLATE = ROOT / "templates" / "skill-sections-template.json"
DEPLOY_CONTRACT_TEMPLATE = ROOT / "templates" / "deploy-template.yml"
INSTALLER_TEMPLATE = LIFECYCLE_SOURCE / "scripts" / "templates" / "install-skills-template.py"
INSTALLER_SYNCHRONIZER = LIFECYCLE_SOURCE / "scripts" / "runtime" / "synchronize-installers.py"
RUNTIME_VALIDATOR = LIFECYCLE_SOURCE / "scripts" / "runtime" / "skills-consistency-runtime-validator.py"
DEPLOY_OPERATION = REPOSITORY_LIFECYCLE_SOURCE / "scripts" / "run-deploy-operation.py"
PROMOTE_REPOSITORY = REPOSITORY_LIFECYCLE_SOURCE / "scripts" / "promote-repository.py"
MANAGE_PENDING_WORK = REPOSITORY_LIFECYCLE_SOURCE / "scripts" / "manage-pending-work.py"
SHIP_REPOSITORY = REPOSITORY_LIFECYCLE_SOURCE / "scripts" / "ship-repository.py"
MODEL_CALL_LEDGER = ROOT / "skills" / "ceratops-credit-savings-analysis" / "scripts" / "model-call-ledger.py"
CLOSURE_SNAPSHOT = ROOT / "skills" / "ceratops-task-lifecycle" / "scripts" / "closure_snapshot.py"
RUNTIME_MANIFEST = ".runtime-manifest.json"
RUNTIME_MANIFEST_SCHEMA = "ceratops-runtime-skill.v3"
INSTALLER_VERSION = 6


def test_model_call_ledger_keeps_full_evidence_out_of_stdout(
    tmp_path: pathlib.Path,
) -> None:
    session = tmp_path / "session.jsonl"
    evidence = tmp_path / "ledger.json"
    rows = [
        {
            "timestamp": "2026-07-25T00:00:00Z",
            "type": "turn_context",
            "payload": {"turn_id": "turn-1"},
        },
        {
            "timestamp": "2026-07-25T00:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "shell_command",
                "arguments": '{"credential":"sentinel-secret"}',
            },
        },
        {
            "timestamp": "2026-07-25T00:00:02Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 10,
                        "output_tokens": 1,
                        "total_tokens": 11,
                    }
                },
            },
        },
        {
            "timestamp": "2026-07-25T00:00:03Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
            },
        },
        {
            "timestamp": "2026-07-25T00:00:04Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 20,
                        "output_tokens": 2,
                        "total_tokens": 22,
                    }
                },
            },
        },
    ]
    session.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )

    compact = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--session",
            str(session),
            "--evidence-output",
            str(evidence),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert compact.returncode == 0, compact.stderr
    summary = json.loads(compact.stdout)
    assert summary["schema"] == "ceratops-model-call-ledger-summary.v1"
    assert summary["totals"]["model_calls"] == 2
    assert summary["runs"][0]["turn_id"] == "turn-1"
    assert summary["selected_runs"] == []
    assert "calls" not in summary["runs"][0]
    ledger = json.loads(evidence.read_text(encoding="utf-8"))
    assert len(ledger["runs"][0]["calls"]) == 2
    assert "sentinel-secret" not in evidence.read_text(encoding="utf-8")

    selected = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--session",
            str(session),
            "--evidence-output",
            str(evidence),
            "--include-run",
            "turn-1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert selected.returncode == 0, selected.stderr
    assert len(json.loads(selected.stdout)["selected_runs"][0]["calls"]) == 2


def test_model_call_ledger_closure_mode_is_artifact_free(
    tmp_path: pathlib.Path,
) -> None:
    thread_id = "019f9b47-678b-7e93-9fb7-acefa2453eeb"
    codex_home = tmp_path / "codex-home"
    session = (
        codex_home
        / "sessions"
        / "2026"
        / "07"
        / "26"
        / f"rollout-2026-07-26T00-56-15-{thread_id}.jsonl"
    )
    session.parent.mkdir(parents=True)
    rows = [
        {
            "timestamp": "2026-07-25T00:00:00Z",
            "type": "turn_context",
            "payload": {"turn_id": "turn-1"},
        },
        {
            "timestamp": "2026-07-25T00:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "shell_command",
                "arguments": '{"credential":"sentinel-secret"}',
            },
        },
        {
            "timestamp": "2026-07-25T00:00:02Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 10,
                        "output_tokens": 1,
                        "total_tokens": 11,
                    }
                },
            },
        },
        {
            "timestamp": "2026-07-25T00:00:03Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
            },
        },
        {
            "timestamp": "2026-07-25T00:00:04Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 20,
                        "output_tokens": 2,
                        "total_tokens": 22,
                    }
                },
            },
        },
        {
            "timestamp": "2026-07-25T00:00:05Z",
            "type": "turn_context",
            "payload": {"turn_id": "turn-2"},
        },
        {
            "timestamp": "2026-07-25T00:00:06Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
            },
        },
        {
            "timestamp": "2026-07-25T00:00:07Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 25,
                        "output_tokens": 2,
                        "total_tokens": 27,
                    }
                },
            },
        },
        {
            "timestamp": "2026-07-25T00:00:08Z",
            "type": "turn_context",
            "payload": {"turn_id": "incomplete-turn"},
        },
        {
            "timestamp": "2026-07-25T00:00:09Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 30,
                        "output_tokens": 3,
                        "total_tokens": 33,
                    }
                },
            },
        },
    ]
    session.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )
    before = sorted(path.relative_to(codex_home) for path in codex_home.rglob("*"))
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)

    closure = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--closure",
            "--thread-id",
            thread_id,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert closure.returncode == 0, closure.stderr
    assert "sentinel-secret" not in closure.stdout
    summary = json.loads(closure.stdout)
    assert summary["schema"] == "ceratops-model-call-ledger-closure.v1"
    assert summary["totals"]["runs"] == 2
    assert summary["totals"]["model_calls"] == 3
    assert [run["turn_id"] for run in summary["runs"]] == ["turn-1", "turn-2"]
    assert [call["index"] for call in summary["runs"][0]["calls"]] == [1, 2]
    assert "tokens" not in summary["runs"][0]["calls"][0]

    bounded = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--closure",
            "--session",
            str(session),
            "--last-runs",
            "1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert bounded.returncode == 0, bounded.stderr
    bounded_summary = json.loads(bounded.stdout)
    assert bounded_summary["window"] == {
        "mode": "last_runs",
        "requested_runs": 1,
        "completed_runs": 1,
    }
    assert bounded_summary["totals"]["model_calls"] == 1
    assert [run["turn_id"] for run in bounded_summary["runs"]] == ["turn-2"]

    after = sorted(path.relative_to(codex_home) for path in codex_home.rglob("*"))
    assert after == before

    invalid_cases = [
        (["--include-run", "turn-1"], "--closure includes every completed run"),
        (
            ["--evidence-output", str(tmp_path / "unexpected.json")],
            "--closure does not accept --evidence-output",
        ),
    ]
    for extra_arguments, expected_error in invalid_cases:
        invalid = subprocess.run(
            [
                sys.executable,
                str(MODEL_CALL_LEDGER),
                "--closure",
                "--session",
                str(session),
                *extra_arguments,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert invalid.returncode == 2
        assert expected_error in invalid.stderr
    assert not (tmp_path / "unexpected.json").exists()

    archived_session = (
        codex_home
        / "archived_sessions"
        / f"rollout-2026-07-26T00-56-15-{thread_id}.jsonl"
    )
    archived_session.parent.mkdir()
    shutil.copy2(session, archived_session)
    ambiguous = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--closure",
            "--thread-id",
            thread_id,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert ambiguous.returncode == 2
    assert "multiple sessions found for thread ID" in ambiguous.stderr


def run_git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one isolated test-repository Git command."""

    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def write_deploy_contract(
    repo: pathlib.Path,
    operations: dict[str, object],
) -> pathlib.Path:
    """Write one JSON-compatible YAML deployment contract."""

    contract = repo / "deploy" / "deploy.yml"
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text(
        json.dumps({"version": 1, "operations": operations}, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return contract


def run_deploy_operation(
    repo: pathlib.Path,
    operation: str,
    *,
    contract: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one isolated deployment operation."""

    command = [
        sys.executable,
        str(DEPLOY_OPERATION),
        "--repo-root",
        str(repo),
        "--operation",
        operation,
    ]
    if contract is not None:
        command.extend(("--contract", str(contract)))
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )


def test_deploy_template_is_a_schema_valid_empty_skeleton(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy2(DEPLOY_CONTRACT_TEMPLATE, write_deploy_contract(repo, {}))

    result = run_deploy_operation(repo, "missing")

    assert result.returncode == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert payload["message"] == "Deployment operation is not declared: missing"


def test_deploy_operation_preserves_argv_without_a_shell(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    probe = repo / "argv-probe.py"
    output = repo / "argv.json"
    injected = repo / "injected.txt"
    literal = f"literal; echo injected > {injected}"
    probe.write_text(
        "import json, pathlib, sys\n"
        "pathlib.Path(sys.argv[1]).write_text("
        "json.dumps(sys.argv[2:]), encoding='utf-8')\n",
        encoding="utf-8",
        newline="\n",
    )
    write_deploy_contract(
        repo,
        {
            "verify": {
                "steps": [
                    {
                        "id": "argv",
                        "run": [
                            sys.executable,
                            "argv-probe.py",
                            str(output),
                            "value with spaces",
                            literal,
                        ],
                    }
                ]
            }
        },
    )

    result = run_deploy_operation(repo, "verify")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "status": "deployed",
        "operation": "verify",
        "steps": ["argv"],
    }
    assert json.loads(output.read_text(encoding="utf-8")) == [
        "value with spaces",
        literal,
    ]
    assert not injected.exists()


def test_deploy_operation_rejects_invalid_schema(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    contract = write_deploy_contract(
        repo,
        {"invalid": {"steps": [{"id": "invalid", "run": "python -V"}]}},
    )

    result = run_deploy_operation(repo, "invalid", contract=contract)

    assert result.returncode == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert payload["message"].startswith("Invalid deployment contract:")


def test_deploy_operation_enforces_repository_path_boundaries(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    write_deploy_contract(
        repo,
        {
            "escape": {
                "steps": [
                    {
                        "id": "escape",
                        "cwd": "../outside",
                        "run": [sys.executable, "-c", "raise SystemExit(0)"],
                    }
                ]
            }
        },
    )

    escaped_cwd = run_deploy_operation(repo, "escape")

    assert escaped_cwd.returncode == 1
    assert json.loads(escaped_cwd.stderr)["message"] == (
        "Deployment step cwd must be a directory inside the repository."
    )

    outside_contract = outside / "deploy.yml"
    outside_contract.write_text(
        json.dumps({"version": 1, "operations": {}}),
        encoding="utf-8",
        newline="\n",
    )
    escaped_contract = run_deploy_operation(
        repo,
        "escape",
        contract=outside_contract,
    )
    assert escaped_contract.returncode == 1
    assert json.loads(escaped_contract.stderr)["message"] == (
        "Deployment contract must be a file inside the repository."
    )


def test_deploy_operation_reports_a_bounded_failure_tail(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    failure = repo / "fail.py"
    failure.write_text(
        "import sys\n"
        "for index in range(12):\n"
        "    print(f'line-{index}', file=sys.stderr)\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
        newline="\n",
    )
    write_deploy_contract(
        repo,
        {
            "fail": {
                "steps": [
                    {
                        "id": "expected-failure",
                        "run": [sys.executable, "fail.py"],
                    }
                ]
            }
        },
    )

    result = run_deploy_operation(repo, "fail")

    assert result.returncode == 1
    message = json.loads(result.stderr)["message"]
    assert message.startswith("Deployment step failed: expected-failure\nline-4")
    assert "line-11" in message
    assert "line-3" not in message


def test_closure_snapshot_composes_only_named_local_state(
    tmp_path: pathlib.Path,
) -> None:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    task_worktree = tmp_path / "task-worktree"
    temp_root = tmp_path / "retained-temp"
    repo.mkdir()
    temp_root.mkdir()
    (temp_root / "one.txt").write_text("one\n", encoding="utf-8", newline="\n")
    (temp_root / "two.txt").write_text("two\n", encoding="utf-8", newline="\n")

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
    assert result["temp"]["files"] == 2

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


def load_source_validator(skills_dir: pathlib.Path) -> dict[str, Any]:
    """Load the source validator with an isolated skill tree for contract tests."""

    validator = runpy.run_path(str(VALIDATOR))
    check_contract = validator["check_multi_action_skill_contract"]
    check_contract.__globals__["SKILLS_DIR"] = skills_dir
    return validator


def write_multi_action_skill(
    skills_dir: pathlib.Path,
    name: str,
    action_references: list[str],
    action_files: dict[str, str],
) -> None:
    """Write one minimal multi-action index and its declared reference files."""

    skill_dir = skills_dir / name
    references_dir = skill_dir / "references"
    references_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "### Action References\n\n"
        + "\n".join(f"- `{action_reference}`" for action_reference in action_references)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for action_reference, content in action_files.items():
        action_path = skill_dir / pathlib.PurePosixPath(action_reference)
        action_path.write_text(content, encoding="utf-8", newline="\n")


def add_skill(repo: pathlib.Path, name: str) -> None:
    """Add one minimal source skill that satisfies the compatible profile."""

    skill_dir = repo / "skills" / name
    (skill_dir / "agents").mkdir(parents=True)
    (skill_dir / "assets").mkdir()
    (skill_dir / "assets" / "icon.png").write_bytes(b"test-icon")
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: Manage {name.replace('-', ' ')} workflows safely across compatible repositories.",
                "---",
                "",
                f"# {name.replace('-', ' ').title()}",
                "",
                "## Workflow",
                "",
                "### Boundaries",
                "",
                "Stay within the selected repository.",
                "",
                "### Output Contract",
                "",
                "Report the validated result.",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    (skill_dir / "agents" / "openai.yaml").write_text(
        "\n".join(
            [
                "interface:",
                f'  display_name: "{name.replace("-", " ").title()}"',
                f'  short_description: "Manage {name.replace("-", " ")} workflows"',
                '  icon_small: "./assets/icon.png"',
                '  icon_large: "./assets/icon.png"',
                f'  default_prompt: "Use ${name} for this workflow."',
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )


def create_compatible_repo(repo: pathlib.Path, source_id: str, skill_names: list[str]) -> None:
    """Create the smallest complete Ceratops-compatible source repository."""

    (repo / "skills" / "sections").mkdir(parents=True)
    (repo / "skills" / "sections" / "core.md").write_text(
        "## Shared Runtime Rules\n\nUse the source repository contract.\n",
        encoding="utf-8",
        newline="\n",
    )
    (repo / "deploy").mkdir()
    shutil.copy2(DEPLOY_CONTRACT_TEMPLATE, repo / "deploy" / "deploy.yml")
    (repo / "scripts").mkdir()
    shutil.copy2(INSTALLER_TEMPLATE, repo / "scripts" / "install-skills.py")
    for skill_name in skill_names:
        add_skill(repo, skill_name)
    write_manifest(repo, source_id)
    rows = "\n".join(f"| `{name}` | Test skill. |" for name in sorted(skill_names))
    (repo / "README.md").write_text(
        "# Compatible Skills\n\n"
        "| org | repo |\n| --- | --- |\n| `unrelated-row` | value |\n\n"
        "## Skills\n\n| Skill | Purpose |\n| --- | --- |\n"
        f"{rows}\n\n## Notes\n",
        encoding="utf-8",
        newline="\n",
    )


def write_manifest(repo: pathlib.Path, source_id: str) -> None:
    """Rewrite assignments after a test adds or removes source skills."""

    skill_names = sorted(path.parent.name for path in (repo / "skills").glob("*/SKILL.md"))
    manifest = {
        "runtime_source_id": source_id,
        "validation_profile": "ceratops-compatible",
        "sections": {"core": "skills/sections/core.md"},
        "skills": {name: ["core"] for name in skill_names},
    }
    (repo / "skills" / "skill-sections.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def run_builder(
    repo: pathlib.Path,
    install_root: pathlib.Path,
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    """Run the managed runtime builder against one isolated install root."""

    return subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--repo-root",
            str(repo),
            "--install-root",
            str(install_root),
            "--installer-version",
            str(INSTALLER_VERSION),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def runtime_owner(install_root: pathlib.Path, skill_name: str) -> str:
    data = json.loads((install_root / skill_name / RUNTIME_MANIFEST).read_text(encoding="utf-8"))
    return str(data["runtime_source_id"])


def prepare_repository_lifecycle_repo(
    tmp_path: pathlib.Path,
) -> tuple[pathlib.Path, str, pathlib.Path, dict[str, str]]:
    """Create one isolated repository with a promotable source branch."""

    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    log = tmp_path / "deploy.log"
    assert run_git(tmp_path, "init", "--bare", str(remote)).returncode == 0
    repo.mkdir()
    assert run_git(repo, "init", "-b", "main").returncode == 0
    assert run_git(repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(repo, "config", "user.name", "Test Agent").returncode == 0
    (repo / "README.md").write_text("base\n", encoding="utf-8", newline="\n")
    (repo / "deploy-probe.py").write_text(
        "import os, pathlib\n"
        "pathlib.Path(os.environ['DEPLOY_TEST_LOG']).write_text("
        "'after_promote\\n', encoding='utf-8')\n",
        encoding="utf-8",
        newline="\n",
    )
    write_deploy_contract(
        repo,
        {
            "after_promote": {
                "steps": [
                    {
                        "id": "record",
                        "run": [sys.executable, "deploy-probe.py"],
                    }
                ]
            }
        },
    )
    assert run_git(repo, "add", ".").returncode == 0
    assert run_git(repo, "commit", "-m", "base").returncode == 0
    assert run_git(repo, "remote", "add", "origin", str(remote)).returncode == 0
    assert run_git(repo, "push", "-u", "origin", "main").returncode == 0
    assert run_git(repo, "switch", "-c", "approved").returncode == 0
    (repo / "README.md").write_text(
        "base\napproved\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(repo, "add", "README.md").returncode == 0
    assert run_git(repo, "commit", "-m", "approved change").returncode == 0
    approved_head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    environment = {**os.environ, "DEPLOY_TEST_LOG": str(log)}
    return repo, approved_head, log, environment


@pytest.mark.parametrize(
    ("operation_arguments", "expected_operation", "expected_log"),
    [
        (["--no-run-operation"], None, None),
        (
            ["--run-operation", "after_promote"],
            {
                "status": "deployed",
                "operation": "after_promote",
                "steps": ["record"],
            },
            "after_promote\n",
        ),
    ],
)
def test_promote_repository_requires_an_explicit_deployment_choice(
    tmp_path: pathlib.Path,
    operation_arguments: list[str],
    expected_operation: dict[str, object] | None,
    expected_log: str | None,
) -> None:
    repo, approved_head, log, environment = prepare_repository_lifecycle_repo(
        tmp_path
    )

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
    assert result["operation"] == expected_operation
    scope_path = pathlib.Path(result["pending_work_scope"])
    assert json.loads(scope_path.read_text(encoding="utf-8")) == {
        "source_branches": ["approved"],
        "target_branch": "release/local",
        "target_commit": approved_head,
        "version": 1,
    }
    assert run_git(repo, "branch", "--show-current").stdout.strip() == "release/local"
    assert run_git(repo, "status", "--porcelain").stdout == ""
    if expected_log is None:
        assert not log.exists()
    else:
        assert log.read_text(encoding="utf-8") == expected_log


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
            "after_promote",
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


@pytest.mark.parametrize("late_phase", ["post_sync", "post_finalize"])
def test_repository_ship_late_pending_work_reports_remote_mutation(
    tmp_path: pathlib.Path,
    late_phase: str,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    scope = tmp_path / "scope.json"
    shipped = {
        "status": "shipped",
        "repository": "example/repository",
        "commit": "a" * 40,
        "pr": 17,
        "url": "https://example.invalid/pull/17",
        "merge_commit": "c" * 40,
        "synchronized_head": "b" * 40,
    }
    pending = {
        "status": "pending_work",
        "remote_mutation": False,
        "findings": [
            {
                "kind": "dirty_worktree",
                "subject": "selected",
                "detail": "1 status entry",
            }
        ],
    }
    deployed = {
        "status": "deployed",
        "operation": "after_ship",
        "steps": ["install"],
    }
    responses: list[tuple[int, dict[str, Any]]] = (
        [(0, shipped), (2, pending)]
        if late_phase == "post_sync"
        else [
            (0, shipped),
            (0, {"status": "ready"}),
            (0, deployed),
            (2, pending),
        ]
    )
    commands: list[list[str]] = []

    def run_json(command: list[str]) -> tuple[int, dict[str, Any]]:
        commands.append(command)
        return responses[len(commands) - 1]

    loaded = runpy.run_path(str(SHIP_REPOSITORY))
    ship_repository = loaded["ship_repository"]
    ship_repository.__globals__["_run_json"] = run_json
    args = argparse.Namespace(
        repo_root=repo,
        repo="example/repository",
        head_branch="release/local",
        base_branch="main",
        remote_name="origin",
        commit="a" * 40,
        title=None,
        body=None,
        merge_method="merge",
        pending_work_scope=scope,
        no_pending_work_check=False,
        delete_branch=False,
        reusable_head=True,
        deploy_contract=pathlib.Path("deploy/deploy.yml"),
        deploy_operation="after_ship",
        ci_wait_seconds=1,
        review_wait_seconds=1,
        interval_seconds=1,
    )

    result = ship_repository(args)

    assert result["status"] == "pending_work"
    assert result["remote_mutation"] is True
    assert result["repository"] == "example/repository"
    assert result["commit"] == "a" * 40
    assert "check" in commands[1]
    if late_phase == "post_sync":
        assert len(commands) == 2
        assert "deployment" not in result
    else:
        assert len(commands) == 4
        assert "finalize" in commands[3]
        assert result["deployment"] == deployed


def run_pending_work(
    repo: pathlib.Path,
    command: str,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    """Run one generic pending-work operation."""

    return subprocess.run(
        [
            sys.executable,
            str(MANAGE_PENDING_WORK),
            "--repo-root",
            str(repo),
            command,
            *arguments,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_pending_work_scope_is_selected_generic_and_finalized_late(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "Repository"
    repo.mkdir()
    assert run_git(repo, "init", "-b", "main").returncode == 0
    assert run_git(repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(repo, "config", "user.name", "Test Agent").returncode == 0
    (repo / "README.md").write_text("base\n", encoding="utf-8", newline="\n")
    assert run_git(repo, "add", "README.md").returncode == 0
    assert run_git(repo, "commit", "-m", "base").returncode == 0
    assert run_git(repo, "branch", "selected").returncode == 0
    assert run_git(repo, "branch", "unrelated").returncode == 0

    worktree_root = tmp_path / "worktrees" / repo.name
    selected_worktree = worktree_root / "selected"
    unrelated_worktree = worktree_root / "unrelated"
    worktree_root.mkdir(parents=True)
    assert (
        run_git(repo, "worktree", "add", str(selected_worktree), "selected").returncode
        == 0
    )
    assert (
        run_git(repo, "worktree", "add", str(unrelated_worktree), "unrelated").returncode
        == 0
    )
    (selected_worktree / "README.md").write_text(
        "base\nselected\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(selected_worktree, "add", "README.md").returncode == 0
    assert run_git(selected_worktree, "commit", "-m", "selected").returncode == 0
    target_commit = run_git(selected_worktree, "rev-parse", "HEAD").stdout.strip()
    assert run_git(repo, "branch", "release/local", target_commit).returncode == 0

    recorded = run_pending_work(
        repo,
        "record",
        "--target-branch",
        "release/local",
        "--target-commit",
        target_commit,
        "--source-branch",
        "selected",
    )

    assert recorded.returncode == 0, recorded.stderr
    recorded_payload = json.loads(recorded.stdout)
    assert recorded_payload["status"] == "ready"
    scope_path = pathlib.Path(recorded_payload["pending_work_scope"])
    assert json.loads(scope_path.read_text(encoding="utf-8")) == {
        "source_branches": ["selected"],
        "target_branch": "release/local",
        "target_commit": target_commit,
        "version": 1,
    }

    (selected_worktree / "README.md").write_text(
        "base\nselected\nlater commit\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(selected_worktree, "add", "README.md").returncode == 0
    assert run_git(selected_worktree, "commit", "-m", "later selected").returncode == 0
    (selected_worktree / "README.md").write_text(
        "base\nselected\nlater commit\ndirty\n",
        encoding="utf-8",
        newline="\n",
    )
    (unrelated_worktree / "README.md").write_text(
        "base\nunrelated commit\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(unrelated_worktree, "add", "README.md").returncode == 0
    assert run_git(unrelated_worktree, "commit", "-m", "unrelated").returncode == 0
    (unrelated_worktree / "README.md").write_text(
        "base\nunrelated commit\ndirty\n",
        encoding="utf-8",
        newline="\n",
    )

    checked = run_pending_work(
        repo,
        "check",
        "--scope",
        str(scope_path),
        "--target-branch",
        "release/local",
        "--target-commit",
        target_commit,
    )

    assert checked.returncode == 2, checked.stderr
    checked_payload = json.loads(checked.stdout)
    assert checked_payload["status"] == "pending_work"
    assert checked_payload["remote_mutation"] is False
    assert [(item["kind"], item["subject"]) for item in checked_payload["findings"]] == [
        ("dirty_worktree", "selected"),
        ("unmerged_branch_commits", "selected"),
    ]
    assert all(
        item["subject"] != "unrelated" for item in checked_payload["findings"]
    )

    assert run_git(selected_worktree, "reset", "--hard", target_commit).returncode == 0
    assert run_git(repo, "merge", "--ff-only", "release/local").returncode == 0
    current_commit = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    finalized = run_pending_work(
        repo,
        "finalize",
        "--scope",
        str(scope_path),
        "--target-branch",
        "release/local",
        "--target-commit",
        target_commit,
        "--current-branch",
        "main",
        "--current-commit",
        current_commit,
    )

    assert finalized.returncode == 0, finalized.stderr
    assert json.loads(finalized.stdout) == {
        "status": "finalized",
        "removed": ["selected"],
        "pending_work_scope": "",
    }
    assert not selected_worktree.exists()
    assert run_git(repo, "show-ref", "--verify", "refs/heads/selected").returncode != 0
    assert unrelated_worktree.is_dir()
    assert run_git(repo, "show-ref", "--verify", "refs/heads/unrelated").returncode == 0
    assert not scope_path.exists()


def install_bundle_manifest(
    bundle_root: pathlib.Path,
    installer_version: int = INSTALLER_VERSION,
) -> None:
    """Mark one copied lifecycle source folder as a supported installed bundle."""

    (bundle_root / RUNTIME_MANIFEST).write_text(
        json.dumps(
            {
                "schema": RUNTIME_MANIFEST_SCHEMA,
                "skill": "ceratops-skill-lifecycle",
                "validation_profile": "ceratops",
                "installer_version": installer_version,
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def test_compatible_full_validation_accepts_arbitrary_skill_names(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok: 1"


def test_source_validator_ignores_shared_sections_directory(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "sections"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok: sections 1"


def test_skill_sections_template_contains_no_live_repository_inventory() -> None:
    template = json.loads(SECTION_MANIFEST_TEMPLATE.read_text(encoding="utf-8"))
    live = json.loads(LIVE_SECTION_MANIFEST.read_text(encoding="utf-8"))

    assert template == {
        "runtime_source_id": "",
        "validation_profile": "ceratops-compatible",
        "sections": {"core": "skills/sections/core.md"},
        "maintenance_workflows": {},
        "runtime_payloads": {},
        "skills": {},
    }
    assert live["runtime_source_id"]
    assert live["skills"]


def test_source_validator_rejects_consecutive_name_hyphens(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha--tool"])

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "alpha--tool: invalid directory name" in result.stderr


@pytest.mark.parametrize(
    ("length", "expected_error"),
    [
        (39, "description is too short"),
        (40, None),
        (1024, None),
        (1025, "description exceeds 1024 characters"),
    ],
)
def test_source_validator_enforces_description_boundaries(
    tmp_path: pathlib.Path,
    length: int,
    expected_error: str | None,
) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    skill_md = repo / "skills" / "alpha-tool" / "SKILL.md"
    lines = skill_md.read_text(encoding="utf-8").splitlines()
    seed = "Manage alpha tool workflows safely across compatible repositories. "
    lines[2] = f"description: {(seed * (length // len(seed) + 1))[:length]}"
    skill_md.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )

    if expected_error is None:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode == 1
        assert expected_error in result.stderr


def test_multi_action_membership_is_owned_by_the_skill_index(
    tmp_path: pathlib.Path,
) -> None:
    skills_dir = tmp_path / "skills"
    write_multi_action_skill(
        skills_dir,
        "ceratops-repo-lifecycle",
        ["references/merge-pr.md", "references/new-command.md"],
        {
            "references/merge-pr.md": "# Merge PR Action\n\nMerge the ready pull request.\n",
            "references/new-command.md": "# New Command Action\n\nRun the new command.\n",
        },
    )
    validator = load_source_validator(skills_dir)
    manifest = {
        "skills": {
            "ceratops-repo-lifecycle": ["multi-action-skill"],
        }
    }

    assert validator["check_multi_action_skill_contract"](manifest) == []
    assert validator["check_skill_scope_validator"]() == []


def test_multi_action_contract_rejects_structural_drift(
    tmp_path: pathlib.Path,
) -> None:
    skills_dir = tmp_path / "skills"
    write_multi_action_skill(
        skills_dir,
        "example-lifecycle",
        [
            "references/first.md",
            "references/first.md",
            "references/missing.md",
        ],
        {
            "references/first.md": "---\n# First Action\n",
            "references/orphan.md": "# Orphan Action\n",
        },
    )
    validator = load_source_validator(skills_dir)
    manifest = {"skills": {"example-lifecycle": ["multi-action-skill"]}}

    errors = validator["check_multi_action_skill_contract"](manifest)

    assert "example-lifecycle: duplicate action reference references/first.md" in errors
    assert "example-lifecycle: missing action reference references/missing.md" in errors
    assert (
        "example-lifecycle: references/first.md still looks like a standalone skill"
        in errors
    )
    assert "example-lifecycle: unlisted action reference references/orphan.md" in errors


def test_skill_scope_validator_retains_semantic_boundaries(
    tmp_path: pathlib.Path,
) -> None:
    merge_path = (
        tmp_path
        / "skills"
        / "ceratops-repo-lifecycle"
        / "references"
        / "merge-pr.md"
    )
    merge_path.parent.mkdir(parents=True)
    merge_path.write_text(
        "# Merge PR Action\n\npython -m github_contract_engine validate repo\n",
        encoding="utf-8",
        newline="\n",
    )
    validator = load_source_validator(tmp_path / "skills")

    assert validator["check_skill_scope_validator"]() == [
        "ceratops-repo-lifecycle: merge-pr action must not run repo/artifact "
        "contract validation"
    ]


def test_full_validation_excludes_git_ignored_files(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    subprocess.run(
        ["git", "init", "--quiet", str(repo)],
        capture_output=True,
        text=True,
        check=True,
    )
    (repo / ".gitignore").write_text(
        ".venv/\nignored-output/\n",
        encoding="utf-8",
        newline="\n",
    )
    for ignored_dir in (repo / ".venv", repo / "ignored-output"):
        ignored_dir.mkdir()
        private_path = chr(92).join(("C:", "Users", "fixture", "generated"))
        (ignored_dir / "generated.md").write_text(
            f"{private_path}\nUse $" + "unknown-skill.\n",
            encoding="utf-8",
            newline="\n",
        )

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok: 1"


def test_full_validation_scans_manifest_runtime_inputs_only(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    runtime_input = repo / "runtime-note.md"
    private_path = chr(92).join(("C:", "Users", "fixture", "private-source"))
    runtime_input.write_text(
        f"Generated from {private_path}.\n",
        encoding="utf-8",
        newline="\n",
    )

    unlisted = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert unlisted.returncode == 0, unlisted.stderr

    manifest_path = repo / "skills" / "skill-sections.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtime_payloads"] = {"alpha-tool": ["runtime-note.md"]}
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    listed = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert listed.returncode == 1
    assert "runtime-note.md: high-confidence secret or private path pattern" in listed.stderr


def test_full_install_removes_only_same_source_stale_skills(tmp_path: pathlib.Path) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo_a, "example/source-a", ["alpha-tool", "retired-tool"])
    create_compatible_repo(repo_b, "example/source-b", ["beta-tool"])

    assert run_builder(repo_a, install_root, "--remove-stale").returncode == 0
    assert run_builder(repo_b, install_root, "--remove-stale").returncode == 0
    shutil.rmtree(repo_a / "skills" / "retired-tool")
    write_manifest(repo_a, "example/source-a")

    result = run_builder(repo_a, install_root, "--remove-stale")

    assert result.returncode == 0, result.stderr
    assert not (install_root / "retired-tool").exists()
    assert runtime_owner(install_root, "alpha-tool") == "example/source-a"
    assert runtime_owner(install_root, "beta-tool") == "example/source-b"


def test_targeted_install_keeps_stale_and_rejects_other_source_collision(tmp_path: pathlib.Path) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo_a, "example/source-a", ["alpha-tool", "retired-tool"])
    create_compatible_repo(repo_b, "example/source-b", ["beta-tool"])
    assert run_builder(repo_a, install_root, "--remove-stale").returncode == 0
    assert run_builder(repo_b, install_root, "--remove-stale").returncode == 0

    shutil.rmtree(repo_a / "skills" / "retired-tool")
    write_manifest(repo_a, "example/source-a")
    targeted = run_builder(repo_a, install_root, "--skill", "alpha-tool")
    assert targeted.returncode == 0, targeted.stderr
    assert (install_root / "retired-tool").is_dir()

    add_skill(repo_b, "alpha-tool")
    write_manifest(repo_b, "example/source-b")
    collision = run_builder(repo_b, install_root, "--skill", "alpha-tool")
    assert collision.returncode == 1
    assert "owned by 'example/source-a'" in collision.stderr
    assert runtime_owner(install_root, "alpha-tool") == "example/source-a"

    unmanaged = install_root / "unmanaged-tool"
    unmanaged.mkdir()
    (unmanaged / "sentinel.txt").write_text("keep\n", encoding="utf-8")
    add_skill(repo_b, "unmanaged-tool")
    write_manifest(repo_b, "example/source-b")
    unmanaged_collision = run_builder(repo_b, install_root, "--skill", "unmanaged-tool")
    assert unmanaged_collision.returncode == 1
    assert "unmanaged runtime skill folder" in unmanaged_collision.stderr
    assert (unmanaged / "sentinel.txt").is_file()

    legacy = install_root / "legacy-tool"
    legacy.mkdir()
    (legacy / RUNTIME_MANIFEST).write_text(
        json.dumps({"schema": "ceratops-runtime-skill.v2", "skill": "legacy-tool"}) + "\n",
        encoding="utf-8",
    )
    add_skill(repo_b, "legacy-tool")
    write_manifest(repo_b, "example/source-b")
    legacy_collision = run_builder(repo_b, install_root, "--skill", "legacy-tool")
    assert legacy_collision.returncode == 1
    assert "unsupported ownership manifest" in legacy_collision.stderr


def test_bootstrap_prefers_installed_bundle_for_external_repo(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    codex_home = tmp_path / "codex-home"
    install_root = tmp_path / "installed"
    installed_bundle = codex_home / "skills" / "ceratops-skill-lifecycle"
    create_compatible_repo(repo, "example/external", ["alpha-tool"])
    shutil.copytree(LIFECYCLE_SOURCE, installed_bundle)
    shutil.copytree(
        REPOSITORY_LIFECYCLE_SOURCE,
        codex_home / "skills" / "ceratops-repo-lifecycle",
    )
    install_bundle_manifest(installed_bundle)
    env = {**os.environ, "CODEX_HOME": str(codex_home)}

    result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "install-skills.py"),
            "--repo-root",
            str(repo),
            "--install-root",
            str(install_root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert runtime_owner(install_root, "alpha-tool") == "example/external"


def test_bootstrap_prefers_ceratops_checkout_over_same_version_installed_bundle(
    tmp_path: pathlib.Path,
) -> None:
    codex_home = tmp_path / "codex-home"
    install_root = tmp_path / "installed"
    installed_bundle = codex_home / "skills" / "ceratops-skill-lifecycle"
    shutil.copytree(LIFECYCLE_SOURCE, installed_bundle)
    shutil.copytree(
        REPOSITORY_LIFECYCLE_SOURCE,
        codex_home / "skills" / "ceratops-repo-lifecycle",
    )
    install_bundle_manifest(installed_bundle)
    installed_validator = (
        installed_bundle / "scripts" / "skills-consistency-source-validator.py"
    )
    installed_validator.write_text(
        "raise SystemExit('retired references/skill-source-docs.json was requested')\n",
        encoding="utf-8",
        newline="\n",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP),
            "--repo-root",
            str(ROOT),
            "--install-root",
            str(install_root),
            "--skill",
            "ceratops-skill-lifecycle",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )

    assert result.returncode == 0, result.stderr
    assert runtime_owner(install_root, "ceratops-skill-lifecycle") == (
        "Ceratops-Code/AI-Agent-Skills"
    )


def test_bootstrap_uses_checkout_for_first_install(tmp_path: pathlib.Path) -> None:
    codex_home = tmp_path / "empty-codex-home"
    install_root = tmp_path / "installed"
    env = {**os.environ, "CODEX_HOME": str(codex_home)}

    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP),
            "--repo-root",
            str(ROOT),
            "--install-root",
            str(install_root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert runtime_owner(install_root, "ceratops-skill-lifecycle") == "Ceratops-Code/AI-Agent-Skills"


def test_bootstrap_uses_checkout_resolver_for_outdated_installed_bundle(
    tmp_path: pathlib.Path,
) -> None:
    codex_home = tmp_path / "codex-home"
    install_root = tmp_path / "installed"
    installed_bundle = codex_home / "skills" / "ceratops-skill-lifecycle"
    shutil.copytree(LIFECYCLE_SOURCE, installed_bundle)
    shutil.copytree(
        REPOSITORY_LIFECYCLE_SOURCE,
        codex_home / "skills" / "ceratops-repo-lifecycle",
    )
    install_bundle_manifest(installed_bundle, installer_version=1)
    installed_resolver = installed_bundle / "scripts" / "runtime" / "resolve-lifecycle-bundle.py"
    installed_resolver.write_text(
        "raise SystemExit('outdated resolver was selected')\n",
        encoding="utf-8",
        newline="\n",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP),
            "--repo-root",
            str(ROOT),
            "--install-root",
            str(install_root),
            "--skill",
            "ceratops-skill-lifecycle",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )

    assert result.returncode == 0, result.stderr
    assert runtime_owner(install_root, "ceratops-skill-lifecycle") == "Ceratops-Code/AI-Agent-Skills"


def test_runtime_manifest_records_source_profile_and_installer_version(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])

    result = run_builder(repo, install_root, "--skill", "alpha-tool")

    assert result.returncode == 0, result.stderr
    manifest = json.loads((install_root / "alpha-tool" / RUNTIME_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["schema"] == RUNTIME_MANIFEST_SCHEMA
    assert manifest["skill"] == "alpha-tool"
    assert manifest["runtime_source_id"] == "example/compatible"
    assert manifest["source_path"] == "skills/alpha-tool"
    assert manifest["source_repository_root"] == str(repo.resolve())
    assert manifest["validation_profile"] == "ceratops-compatible"
    assert manifest["installer_version"] == INSTALLER_VERSION


def test_full_install_runs_full_source_validation(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    codex_home = tmp_path / "codex-home"
    install_root = tmp_path / "installed"
    installed_bundle = codex_home / "skills" / "ceratops-skill-lifecycle"
    create_compatible_repo(repo, "example/external", ["alpha-tool"])
    shutil.copytree(LIFECYCLE_SOURCE, installed_bundle)
    shutil.copytree(
        REPOSITORY_LIFECYCLE_SOURCE,
        codex_home / "skills" / "ceratops-repo-lifecycle",
    )
    install_bundle_manifest(installed_bundle)
    (repo / "README.md").write_text("# Invalid\n", encoding="utf-8", newline="\n")

    result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "install-skills.py"),
            "--repo-root",
            str(repo),
            "--install-root",
            str(install_root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )

    assert result.returncode == 1
    assert "Full source-repository validation failed" in result.stderr
    assert not (install_root / "alpha-tool").exists()


def test_targeted_install_validates_only_selected_skill(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    codex_home = tmp_path / "codex-home"
    install_root = tmp_path / "installed"
    installed_bundle = codex_home / "skills" / "ceratops-skill-lifecycle"
    create_compatible_repo(repo, "example/external", ["alpha-tool", "broken-tool"])
    shutil.copytree(LIFECYCLE_SOURCE, installed_bundle)
    shutil.copytree(
        REPOSITORY_LIFECYCLE_SOURCE,
        codex_home / "skills" / "ceratops-repo-lifecycle",
    )
    install_bundle_manifest(installed_bundle)
    (repo / "skills" / "broken-tool" / "SKILL.md").write_text("invalid\n", encoding="utf-8", newline="\n")

    result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "install-skills.py"),
            "--repo-root",
            str(repo),
            "--install-root",
            str(install_root),
            "--skill",
            "alpha-tool",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )

    assert result.returncode == 0, result.stderr
    assert (install_root / "alpha-tool" / "SKILL.md").is_file()
    assert not (install_root / "broken-tool").exists()

    (repo / "skills" / "alpha-tool" / "SKILL.md").write_text("invalid\n", encoding="utf-8", newline="\n")
    invalid_selected = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "install-skills.py"),
            "--repo-root",
            str(repo),
            "--install-root",
            str(install_root),
            "--skill",
            "alpha-tool",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )

    assert invalid_selected.returncode == 1
    assert "Targeted skill validation failed" in invalid_selected.stderr


def test_installer_synchronization_compares_only_version(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    (repo / ".git").write_text("gitdir: test\n", encoding="utf-8", newline="\n")
    target = repo / "scripts" / "install-skills.py"
    custom = target.read_text(encoding="utf-8") + "\n# same-version local difference\n"
    target.write_text(custom, encoding="utf-8", newline="\n")

    retained = subprocess.run(
        [sys.executable, str(INSTALLER_SYNCHRONIZER), "--target-repo-root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert retained.returncode == 0, retained.stderr
    assert json.loads(retained.stdout)["status"] == "retained"
    assert target.read_text(encoding="utf-8") == custom

    target.write_text(
        custom.replace(
            f"INSTALLER_VERSION = {INSTALLER_VERSION}", "INSTALLER_VERSION = 0"
        ),
        encoding="utf-8",
        newline="\n",
    )
    updated = subprocess.run(
        [sys.executable, str(INSTALLER_SYNCHRONIZER), "--target-repo-root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert updated.returncode == 0, updated.stderr
    assert json.loads(updated.stdout)["status"] == "updated"
    assert target.read_bytes() == INSTALLER_TEMPLATE.read_bytes()


def test_installer_behavior_fingerprint_is_python_version_stable() -> None:
    validator = runpy.run_path(str(VALIDATOR))
    fingerprint = validator["installer_behavior_fingerprint"]

    assert fingerprint(INSTALLER_TEMPLATE) == (
        "8086819d9e08d9e638ecad0b0a781132aa2b6c15c4e088ea8d950704f3e5d018"
    )


def test_installer_version_producer_assigns_versions_without_model_repair(
    tmp_path: pathlib.Path,
) -> None:
    validator = runpy.run_path(str(VALIDATOR))
    fingerprint = validator["installer_behavior_fingerprint"]
    check_history = validator["check_installer_version_history"]
    synchronize = validator["synchronize_authoritative_installer_version"]
    template = tmp_path / "install-skills-template.py"
    bootstrap = tmp_path / "install-skills.py"
    history = tmp_path / "installer-version-history.json"
    template.write_text(
        '"""Bootstrap documentation."""\n'
        "INSTALLER_VERSION = 4\n"
        "def main():\n"
        '    """Run the bootstrap."""\n'
        '    print("first")\n',
        encoding="utf-8",
        newline="\n",
    )
    bootstrap.write_text("stale\n", encoding="utf-8", newline="\n")
    baseline = fingerprint(template)
    assert isinstance(baseline, str)
    history.write_text(
        json.dumps(
            {
                "schema": "ceratops-installer-version-history.v1",
                "versions": [{"version": 4, "behavior_sha256": baseline}],
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    synchronize.__globals__["INSTALLER_TEMPLATE"] = template
    synchronize.__globals__["INSTALLER_VERSION_HISTORY"] = history
    synchronize.__globals__["BOOTSTRAP_INSTALLER"] = bootstrap

    synchronize()
    assert check_history() == []
    assert bootstrap.read_bytes() == template.read_bytes()

    template.write_text(
        template.read_text(encoding="utf-8").replace(
            "INSTALLER_VERSION = 4", "INSTALLER_VERSION = 9"
        ),
        encoding="utf-8",
        newline="\n",
    )
    synchronize()
    assert "INSTALLER_VERSION = 4" in template.read_text(encoding="utf-8")
    assert len(json.loads(history.read_text(encoding="utf-8"))["versions"]) == 1
    assert fingerprint(template) == baseline
    assert check_history() == []

    template.write_text(
        template.read_text(encoding="utf-8").replace('print("first")', 'print("changed")'),
        encoding="utf-8",
        newline="\n",
    )
    changed = fingerprint(template)
    assert isinstance(changed, str)
    assert changed != baseline
    synchronize()
    assert "INSTALLER_VERSION = 5" in template.read_text(encoding="utf-8")
    assert [entry["version"] for entry in json.loads(history.read_text(encoding="utf-8"))["versions"]] == [4, 5]
    assert bootstrap.read_bytes() == template.read_bytes()
    assert check_history() == []

    before = (template.read_bytes(), history.read_bytes(), bootstrap.read_bytes())
    synchronize()
    assert (template.read_bytes(), history.read_bytes(), bootstrap.read_bytes()) == before

    template.write_text(
        template.read_text(encoding="utf-8")
        .replace("Bootstrap documentation.", "Updated bootstrap documentation.")
        .replace("Run the bootstrap.", "Run the documented bootstrap."),
        encoding="utf-8",
        newline="\n",
    )
    synchronize()
    assert "INSTALLER_VERSION = 5" in template.read_text(encoding="utf-8")
    assert len(json.loads(history.read_text(encoding="utf-8"))["versions"]) == 2
    assert check_history() == []

    template.write_text(
        template.read_text(encoding="utf-8")
        .replace("INSTALLER_VERSION = 5", "INSTALLER_VERSION = 2")
        .replace('print("changed")', 'print("first")'),
        encoding="utf-8",
        newline="\n",
    )
    synchronize()
    history_entries = json.loads(history.read_text(encoding="utf-8"))["versions"]
    assert [entry["version"] for entry in history_entries] == [4, 5, 6]
    assert history_entries[-1]["behavior_sha256"] == baseline
    assert "INSTALLER_VERSION = 6" in template.read_text(encoding="utf-8")
    assert check_history() == []


def test_repository_review_uses_only_attributable_direct_manifest_folders(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    other_repo = tmp_path / "other-compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    create_compatible_repo(other_repo, "example/other-compatible", ["beta-tool"])
    assert run_builder(repo, install_root, "--skill", "alpha-tool").returncode == 0
    assert run_builder(other_repo, install_root, "--skill", "beta-tool").returncode == 0
    (install_root / "unmanaged-tool").mkdir()
    nested = install_root / "unmanaged-tool" / "nested-managed"
    nested.mkdir()
    (nested / RUNTIME_MANIFEST).write_text("{}\n", encoding="utf-8", newline="\n")

    result = subprocess.run(
        [
            sys.executable,
            str(RUNTIME_VALIDATOR),
            "--repo-root",
            str(repo),
            "--runtime-root",
            str(install_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "managed": 1,
        "runtime_source_id": "example/compatible",
        "status": "valid",
    }

    installed_metadata = install_root / "alpha-tool" / "agents" / "openai.yaml"
    installed_metadata.write_text("stale: true\n", encoding="utf-8", newline="\n")
    stale_metadata = subprocess.run(
        [
            sys.executable,
            str(RUNTIME_VALIDATOR),
            "--repo-root",
            str(repo),
            "--runtime-root",
            str(install_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert stale_metadata.returncode == 1
    assert "managed file content differs: agents/openai.yaml" in stale_metadata.stderr
    assert run_builder(repo, install_root, "--skill", "alpha-tool").returncode == 0

    installed_skill = install_root / "alpha-tool" / "SKILL.md"
    installed_skill.write_text(
        installed_skill.read_text(encoding="utf-8").replace(
            "Use the source repository contract.",
            "Stale generated section.",
        ),
        encoding="utf-8",
        newline="\n",
    )
    stale = subprocess.run(
        [
            sys.executable,
            str(RUNTIME_VALIDATOR),
            "--repo-root",
            str(repo),
            "--runtime-root",
            str(install_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert stale.returncode == 1
    assert "managed file content differs: SKILL.md" in stale.stderr


def test_selected_skill_review_does_not_audit_sibling_skills(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool", "beta-tool"])
    assert run_builder(repo, install_root, "--remove-stale").returncode == 0
    (install_root / "beta-tool" / "SKILL.md").write_text(
        "stale\n",
        encoding="utf-8",
        newline="\n",
    )

    selected = subprocess.run(
        [
            sys.executable,
            str(RUNTIME_VALIDATOR),
            "--runtime-root",
            str(install_root),
            "--skill",
            "alpha-tool",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert selected.returncode == 0, selected.stderr
    assert json.loads(selected.stdout) == {
        "managed": 1,
        "runtime_source_id": "example/compatible",
        "status": "valid",
    }


def test_runtime_inventory_lists_direct_manifests_and_malformed_blockers(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool", "beta-tool"])
    assert run_builder(repo, install_root, "--remove-stale").returncode == 0
    malformed = install_root / "broken-tool"
    malformed.mkdir()
    (malformed / RUNTIME_MANIFEST).write_text("{\n", encoding="utf-8", newline="\n")
    nested = install_root / "unmanaged-tool" / "nested-managed"
    nested.mkdir(parents=True)
    (nested / RUNTIME_MANIFEST).write_text("{}\n", encoding="utf-8", newline="\n")

    result = subprocess.run(
        [
            sys.executable,
            str(RUNTIME_VALIDATOR),
            "--runtime-root",
            str(install_root),
            "--inventory",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    inventory = json.loads(result.stdout)
    assert inventory["status"] == "inventory"
    assert inventory["managed"] == 2
    assert inventory["blocked"] == 1
    assert [item["skill"] for item in inventory["skills"]] == ["alpha-tool", "beta-tool"]
    assert inventory["blockers"][0]["directory"] == "broken-tool"
    assert "unreadable runtime manifest" in inventory["blockers"][0]["errors"][0]
