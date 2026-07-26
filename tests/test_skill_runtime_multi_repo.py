from __future__ import annotations

import base64
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
INSTALLER_TEMPLATE = LIFECYCLE_SOURCE / "scripts" / "templates" / "install-skills-template.py"
INSTALLER_SYNCHRONIZER = LIFECYCLE_SOURCE / "scripts" / "runtime" / "synchronize-installers.py"
RUNTIME_VALIDATOR = LIFECYCLE_SOURCE / "scripts" / "runtime" / "skills-consistency-runtime-validator.py"
PROMOTION_HELPER = (
    LIFECYCLE_SOURCE
    / "scripts"
    / "promote-skill-branches-to-release-and-install.ps1"
)
MANAGE_PENDING_RELEASE_WORK = (
    LIFECYCLE_SOURCE / "scripts" / "manage-pending-release-work.ps1"
)
MODEL_CALL_LEDGER = ROOT / "skills" / "ceratops-credit-savings-analysis" / "scripts" / "model-call-ledger.py"
RUNTIME_MANIFEST = ".runtime-manifest.json"
RUNTIME_MANIFEST_SCHEMA = "ceratops-runtime-skill.v3"
INSTALLER_VERSION = 3


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
            "payload": {"turn_id": "incomplete-turn"},
        },
        {
            "timestamp": "2026-07-25T00:00:06Z",
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
    assert summary["totals"]["runs"] == 1
    assert summary["totals"]["model_calls"] == 2
    assert [run["turn_id"] for run in summary["runs"]] == ["turn-1"]
    assert [call["index"] for call in summary["runs"][0]["calls"]] == [1, 2]
    assert "tokens" not in summary["runs"][0]["calls"][0]
    after = sorted(path.relative_to(codex_home) for path in codex_home.rglob("*"))
    assert after == before

    invalid_cases = [
        (["--last-runs", "1"], "--closure requires the full thread"),
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

    (repo / "templates" / "sections").mkdir(parents=True)
    (repo / "templates" / "sections" / "core.md").write_text(
        "## Shared Runtime Rules\n\nUse the source repository contract.\n",
        encoding="utf-8",
        newline="\n",
    )
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
        "sections": {"core": "templates/sections/core.md"},
        "skills": {name: ["core"] for name in skill_names},
    }
    (repo / "templates" / "skill-sections.json").write_text(
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


@pytest.mark.skipif(
    shutil.which("powershell") is None,
    reason="PowerShell lifecycle helper is unavailable",
)
def test_promotion_helper_owns_release_branch_preparation(
    tmp_path: pathlib.Path,
) -> None:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    repo = tmp_path / "AI-Agent-Skills"
    assert run_git(tmp_path, "init", "--bare", str(remote)).returncode == 0
    seed.mkdir()
    assert run_git(seed, "init").returncode == 0
    assert run_git(seed, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(seed, "config", "user.name", "Test Agent").returncode == 0
    (seed / "dummy.py").write_text("value: int = 1\n", encoding="utf-8", newline="\n")
    (seed / "mypy.ini").write_text(
        "[mypy]\nfiles = dummy.py\n",
        encoding="utf-8",
        newline="\n",
    )
    (seed / "README.md").write_text("base\n", encoding="utf-8", newline="\n")
    (seed / "scripts").mkdir()
    (seed / "scripts" / "install-skills.py").write_text(
        "import os, pathlib\n"
        "pathlib.Path(os.environ['PROMOTION_TEST_LOG']).write_text("
        "'installed\\n', encoding='utf-8')\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(seed, "add", ".").returncode == 0
    assert run_git(seed, "commit", "-m", "base").returncode == 0
    assert run_git(seed, "branch", "-M", "main").returncode == 0
    assert run_git(seed, "remote", "add", "origin", str(remote)).returncode == 0
    assert run_git(seed, "push", "-u", "origin", "main").returncode == 0
    assert (
        run_git(remote, "symbolic-ref", "HEAD", "refs/heads/main").returncode
        == 0
    )
    assert run_git(tmp_path, "clone", str(remote), str(repo)).returncode == 0
    assert run_git(repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(repo, "config", "user.name", "Test Agent").returncode == 0
    assert run_git(repo, "switch", "-c", "approved").returncode == 0
    (repo / "README.md").write_text(
        "base\napproved\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(repo, "add", "README.md").returncode == 0
    assert run_git(repo, "commit", "-m", "approved change").returncode == 0
    approved_head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    log = tmp_path / "promotion.log"
    environment = os.environ.copy()
    environment["PROMOTION_TEST_LOG"] = str(log)

    promoted = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROMOTION_HELPER),
            "-SkillsRepoRoot",
            str(repo),
            "-ApprovedBranch",
            "approved",
            "-MainBranch",
            "main",
            "-ReleaseBranch",
            "release/local",
            "-RemoteName",
            "origin",
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
    assert result["retained_approved_branches"] == ["approved"]
    assert pathlib.Path(result["promotion_record"]).is_file()
    assert log.read_text(encoding="utf-8") == "installed\n"
    assert run_git(repo, "branch", "--show-current").stdout.strip() == "release/local"
    assert run_git(repo, "status", "--porcelain").stdout == ""


@pytest.mark.skipif(
    shutil.which("powershell") is None,
    reason="PowerShell lifecycle helper is unavailable",
)
def test_promotion_records_are_collision_free_and_cleaned_terminally(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "AI-Agent-Skills"
    repo.mkdir()
    assert run_git(repo, "init").returncode == 0
    assert run_git(repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(repo, "config", "user.name", "Test Agent").returncode == 0
    (repo / "README.md").write_text("base\n", encoding="utf-8", newline="\n")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "install-skills.py").write_text(
        "import os, pathlib\n"
        "record = pathlib.Path(os.environ['EXPECTED_PROMOTION_RECORD'])\n"
        "worktree = pathlib.Path(os.environ['EXPECTED_APPROVED_WORKTREE'])\n"
        "if not record.is_file() or not worktree.is_dir():\n"
        "    raise SystemExit('cleanup ran before installation')\n"
        "with pathlib.Path(os.environ['FINALIZER_TEST_LOG']).open('a') as log:\n"
        "    log.write('install\\n')\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(repo, "add", ".").returncode == 0
    assert run_git(repo, "commit", "-m", "base").returncode == 0
    assert run_git(repo, "branch", "-M", "main").returncode == 0
    assert run_git(repo, "branch", "approved").returncode == 0
    assert run_git(repo, "branch", "unrelated").returncode == 0

    worktree_root = tmp_path / "worktrees" / repo.name
    approved_worktree = worktree_root / "approved"
    unrelated_worktree = worktree_root / "unrelated"
    worktree_root.mkdir(parents=True)
    assert (
        run_git(repo, "worktree", "add", str(approved_worktree), "approved").returncode
        == 0
    )
    assert (
        run_git(repo, "worktree", "add", str(unrelated_worktree), "unrelated").returncode
        == 0
    )
    (approved_worktree / "README.md").write_text(
        "base\napproved\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(approved_worktree, "add", "README.md").returncode == 0
    assert (
        run_git(approved_worktree, "commit", "-m", "approved change").returncode
        == 0
    )
    promotion_commit = run_git(
        approved_worktree, "rev-parse", "HEAD"
    ).stdout.strip()
    assert run_git(repo, "branch", "release/local", promotion_commit).returncode == 0

    approved_branch_data = base64.b64encode(b"approved").decode("ascii")
    record_command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(MANAGE_PENDING_RELEASE_WORK),
        "-SkillsRepoRoot",
        str(repo),
        "-ReleaseBranch",
        "release/local",
        "-PromotionCommit",
        promotion_commit,
        "-ApprovedBranchData",
        approved_branch_data,
        "-RecordPromotion",
    ]

    retained = subprocess.run(
        record_command,
        capture_output=True,
        text=True,
        check=False,
    )
    assert retained.returncode == 0, retained.stderr
    retained_payload = json.loads(retained.stdout)
    record = pathlib.Path(retained_payload["promotion_record"])
    assert approved_worktree.is_dir()
    assert unrelated_worktree.is_dir()
    assert record.is_file()
    assert retained_payload["approved_branches"] == ["approved"]

    (approved_worktree / "README.md").write_text(
        "base\napproved\nlater retained commit\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(approved_worktree, "add", "README.md").returncode == 0
    assert (
        run_git(approved_worktree, "commit", "-m", "later retained change").returncode
        == 0
    )
    (approved_worktree / "README.md").write_text(
        "base\napproved\nlater retained commit\nuncommitted retained work\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(repo, "branch", "approved-next", promotion_commit).returncode == 0
    next_record_command = record_command.copy()
    next_record_command[
        next_record_command.index(approved_branch_data)
    ] = base64.b64encode(b"approved-next").decode("ascii")
    next_retained = subprocess.run(
        next_record_command,
        capture_output=True,
        text=True,
        check=False,
    )
    assert next_retained.returncode == 0, next_retained.stderr
    next_payload = json.loads(next_retained.stdout)
    assert next_payload["approved_branches"] == ["approved", "approved-next"]
    assert pathlib.Path(next_payload["promotion_record"]) == record
    assert (
        run_git(approved_worktree, "reset", "--hard", promotion_commit).returncode
        == 0
    )

    collision_branch = "release__local"
    assert (
        run_git(repo, "branch", collision_branch, promotion_commit).returncode == 0
    )
    collision_record_command = record_command.copy()
    collision_record_command[
        collision_record_command.index("release/local")
    ] = collision_branch
    collision_retained = subprocess.run(
        collision_record_command,
        capture_output=True,
        text=True,
        check=False,
    )
    assert collision_retained.returncode == 0, collision_retained.stderr
    collision_record = pathlib.Path(
        json.loads(collision_retained.stdout)["promotion_record"]
    )
    assert collision_record != record
    assert collision_record.is_file()

    bundle_scripts = tmp_path / "bundle" / "scripts"
    (bundle_scripts / "runtime").mkdir(parents=True)
    finalizer_helper = bundle_scripts / MANAGE_PENDING_RELEASE_WORK.name
    shutil.copy2(MANAGE_PENDING_RELEASE_WORK, finalizer_helper)
    (bundle_scripts / "runtime" / "skills-consistency-runtime-validator.py").write_text(
        "import os, pathlib\n"
        "record = pathlib.Path(os.environ['EXPECTED_PROMOTION_RECORD'])\n"
        "worktree = pathlib.Path(os.environ['EXPECTED_APPROVED_WORKTREE'])\n"
        "if not record.is_file() or not worktree.is_dir():\n"
        "    raise SystemExit('cleanup ran before runtime validation')\n"
        "with pathlib.Path(os.environ['FINALIZER_TEST_LOG']).open('a') as log:\n"
        "    log.write('runtime\\n')\n"
        "if os.environ.get('FAIL_RUNTIME') == '1':\n"
        "    raise SystemExit('requested runtime failure')\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(repo, "reset", "--hard", promotion_commit).returncode == 0
    finalizer_log = tmp_path / "finalizer.log"
    finalizer_env = {
        **os.environ,
        "EXPECTED_APPROVED_WORKTREE": str(approved_worktree),
        "EXPECTED_PROMOTION_RECORD": str(record),
        "FINALIZER_TEST_LOG": str(finalizer_log),
    }
    cleanup_command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(finalizer_helper),
        "-SkillsRepoRoot",
        str(repo),
        "-ReleaseBranch",
        "release/local",
        "-PromotionCommit",
        promotion_commit,
        "-FinalizeShippedRelease",
    ]
    failed = subprocess.run(
        cleanup_command,
        capture_output=True,
        text=True,
        check=False,
        env={**finalizer_env, "FAIL_RUNTIME": "1"},
    )
    assert failed.returncode != 0
    assert approved_worktree.is_dir()
    assert run_git(repo, "show-ref", "--verify", "refs/heads/approved").returncode == 0
    assert record.is_file()
    assert finalizer_log.read_text(encoding="utf-8").splitlines() == [
        "install",
        "runtime",
    ]
    finalizer_log.unlink()

    cleaned = subprocess.run(
        cleanup_command,
        capture_output=True,
        text=True,
        check=False,
        env=finalizer_env,
    )
    assert cleaned.returncode == 0, cleaned.stderr
    cleaned_payload = json.loads(cleaned.stdout)
    assert cleaned_payload["install"] == "managed"
    assert cleaned_payload["runtime_validation"] == "full"
    assert finalizer_log.read_text(encoding="utf-8").splitlines() == [
        "install",
        "runtime",
    ]
    assert not approved_worktree.exists()
    assert run_git(repo, "show-ref", "--verify", "refs/heads/approved").returncode != 0
    assert unrelated_worktree.is_dir()
    assert run_git(repo, "show-ref", "--verify", "refs/heads/unrelated").returncode == 0
    assert not record.exists()
    assert collision_record.is_file()

    collision_cleanup = subprocess.run(
        [*collision_record_command[:-3], "-CleanMergedBranches"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert collision_cleanup.returncode == 0, collision_cleanup.stderr
    assert not collision_record.exists()


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


def test_multi_action_membership_is_owned_by_the_skill_index(
    tmp_path: pathlib.Path,
) -> None:
    skills_dir = tmp_path / "skills"
    write_multi_action_skill(
        skills_dir,
        "ceratops-gh-repo-lifecycle",
        ["references/merge-pr.md", "references/new-command.md"],
        {
            "references/merge-pr.md": "# Merge PR Action\n\nMerge the ready pull request.\n",
            "references/new-command.md": "# New Command Action\n\nRun the new command.\n",
        },
    )
    validator = load_source_validator(skills_dir)
    manifest = {
        "skills": {
            "ceratops-gh-repo-lifecycle": ["multi-action-skill"],
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
        / "ceratops-gh-repo-lifecycle"
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
        "ceratops-gh-repo-lifecycle: merge-pr action must not run repo/artifact "
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
        (ignored_dir / "generated.md").write_text(
            "C:\\Users\\roman\\generated\nUse $" + "unknown-skill.\n",
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
    runtime_input.write_text(
        "Generated from C:\\Users\\roman\\private-source.\n",
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

    manifest_path = repo / "templates" / "skill-sections.json"
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


def test_bootstrap_falls_back_to_checkout_for_first_install(tmp_path: pathlib.Path) -> None:
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
