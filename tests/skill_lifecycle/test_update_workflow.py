from __future__ import annotations

import json
import pathlib
import sys

from tests.skill_lifecycle.support import (
    prepare_skill_update_workflow_worktree,
    run_skill_update_workflow,
)
from tests.support.repositories import (
    run_git,
)


def test_skill_update_workflow_accepts_new_shared_section_source(
    tmp_path: pathlib.Path,
) -> None:
    worktree, _scope, task_temp_root = prepare_skill_update_workflow_worktree(
        tmp_path
    )
    shared_source = (
        worktree / "skills" / "sections" / "scripts" / "shared-helper.py"
    )
    shared_source.parent.mkdir(parents=True)
    request_path = task_temp_root / "request.json"
    state_path = task_temp_root / "state.json"
    evidence_path = task_temp_root / "evidence.json"
    request = {
        "schema": "ceratops-skill-update-request.v2",
        "repo_root": str(worktree),
        "task_temp_root": str(task_temp_root),
        "evidence_output": str(evidence_path),
        "disposable_artifacts": ["request", "state", "evidence"],
        "selected_skills": ["alpha-tool"],
        "allowed_paths": [
            "skills/alpha-tool/scripts/tool.py",
            "skills/sections/scripts/shared-helper.py",
        ],
        "change_groups": [
            {
                "name": "shared-helper",
                "paths": [
                    "skills/alpha-tool/scripts/tool.py",
                    "skills/sections/scripts/shared-helper.py",
                ],
            }
        ],
        "checks": [
            {
                "kind": "search",
                "pattern": "SHARED_PAYLOAD",
                "paths": ["skills/sections/scripts/shared-helper.py"],
                "expected_matches": 1,
            }
        ],
    }
    request_path.write_text(
        json.dumps(request) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    prepared = run_skill_update_workflow(
        "prepare",
        "--request",
        str(request_path),
        "--state",
        str(state_path),
    )
    assert prepared.returncode == 0, prepared.stderr
    shared_source.write_text(
        "SHARED_PAYLOAD = True\n",
        encoding="utf-8",
        newline="\n",
    )
    verified = run_skill_update_workflow(
        "verify",
        "--state",
        str(state_path),
        "--evidence-output",
        str(evidence_path),
    )
    assert verified.returncode == 0, verified.stderr
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["changed_paths"] == [
        "skills/sections/scripts/shared-helper.py"
    ]
    finalized = run_skill_update_workflow(
        "finalize",
        "--state",
        str(state_path),
    )
    assert finalized.returncode == 0, finalized.stderr
    assert not task_temp_root.exists()


def test_skill_update_workflow_preserves_baseline_runs_checks_once_and_finalizes(
    tmp_path: pathlib.Path,
) -> None:
    worktree, scope, task_temp_root = prepare_skill_update_workflow_worktree(tmp_path)
    baseline = worktree / "preexisting.txt"
    baseline.write_text("keep me\n", encoding="utf-8", newline="\n")
    check_log = scope / "check.log"
    check_script = scope / "check-once.py"
    check_script.write_text(
        "import pathlib\n"
        "import sys\n"
        "path = pathlib.Path(__file__).with_name('check.log')\n"
        "prior = path.read_text(encoding='utf-8') if path.exists() else ''\n"
        "path.write_text(prior + 'run\\n', encoding='utf-8')\n"
        "sys.stdout.buffer.write('מלא\\n'.encode('utf-8'))\n",
        encoding="utf-8",
        newline="\n",
    )
    request_path = task_temp_root / "request.json"
    state_path = task_temp_root / "state.json"
    evidence_path = task_temp_root / "evidence.json"
    request = {
        "schema": "ceratops-skill-update-request.v2",
        "repo_root": str(worktree),
        "task_temp_root": str(task_temp_root),
        "evidence_output": str(evidence_path),
        "disposable_artifacts": ["request", "state", "evidence"],
        "selected_skills": ["alpha-tool"],
        "allowed_paths": [
            "skills/alpha-tool/scripts/tool.py",
        ],
        "change_groups": [
            {
                "name": "helper-runtime",
                "paths": ["skills/alpha-tool/scripts/tool.py"],
            }
        ],
        "checks": [
            {
                "kind": "search",
                "pattern": "FORBIDDEN",
                "paths": ["skills/alpha-tool/scripts/tool.py"],
                "expected_matches": 0,
            },
            {"kind": "command", "argv": [sys.executable, str(check_script)]},
            {
                "kind": "pytest",
                "nodes": ["tests/test_helper.py::test_helper_value"],
            },
        ],
    }
    request_path.write_text(
        json.dumps(request) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    invalid_request_path = task_temp_root / "invalid-request.json"
    invalid_state_path = task_temp_root / "invalid-state.json"
    invalid_evidence_path = task_temp_root / "invalid-evidence.json"
    invalid_request = json.loads(json.dumps(request))
    invalid_request["evidence_output"] = str(invalid_evidence_path)
    invalid_request["checks"][-1]["nodes"] = [
        "tests/test_helper.py::test_missing_helper_value"
    ]
    invalid_request_path.write_text(
        json.dumps(invalid_request) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    invalid_prepare = run_skill_update_workflow(
        "prepare",
        "--request",
        str(invalid_request_path),
        "--state",
        str(invalid_state_path),
    )
    assert invalid_prepare.returncode == 2
    assert invalid_prepare.stdout == ""
    assert "pytest node collection failed" in invalid_prepare.stderr
    assert "test_missing_helper_value" in invalid_prepare.stderr
    assert not invalid_state_path.exists()
    assert not invalid_evidence_path.exists()
    assert invalid_request_path.is_file()

    prepared = run_skill_update_workflow(
        "prepare",
        "--request",
        str(request_path),
        "--state",
        str(state_path),
    )
    assert prepared.returncode == 0, prepared.stderr
    assert prepared.stdout.strip() == "OK"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["schema"] == "ceratops-skill-update-state.v2"
    assert "preexisting.txt" in state["baseline_dirty"]
    incomplete = run_skill_update_workflow(
        "finalize",
        "--state",
        str(state_path),
    )
    assert incomplete.returncode == 2
    assert "before successful verification" in incomplete.stderr
    assert request_path.is_file() and state_path.is_file()
    assert not evidence_path.exists()

    helper = worktree / "skills" / "alpha-tool" / "scripts" / "tool.py"
    helper.write_text("VALUE = 2\n", encoding="utf-8", newline="\n")
    baseline.write_text("changed\n", encoding="utf-8", newline="\n")
    baseline_failure = run_skill_update_workflow(
        "verify",
        "--state",
        str(state_path),
        "--evidence-output",
        str(evidence_path),
    )
    assert baseline_failure.returncode == 2
    assert "pre-existing dirty path changed" in baseline_failure.stderr
    assert json.loads(evidence_path.read_text(encoding="utf-8"))["status"] == "failed"
    assert request_path.is_file() and state_path.is_file() and evidence_path.is_file()
    assert not check_log.exists()

    baseline.write_text("keep me\n", encoding="utf-8", newline="\n")
    rogue_path = worktree / "rogue.txt"
    rogue_path.write_text("rogue\n", encoding="utf-8", newline="\n")
    rogue_failure = run_skill_update_workflow(
        "verify",
        "--state",
        str(state_path),
        "--evidence-output",
        str(evidence_path),
    )
    assert rogue_failure.returncode == 2
    assert "undeclared working-tree change" in rogue_failure.stderr
    assert request_path.is_file() and state_path.is_file() and evidence_path.is_file()
    assert not check_log.exists()
    rogue_path.unlink()

    verified = run_skill_update_workflow(
        "verify",
        "--state",
        str(state_path),
        "--evidence-output",
        str(evidence_path),
    )
    assert verified.returncode == 0, verified.stderr
    assert verified.stdout.strip() == "OK"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["schema"] == "ceratops-skill-update-evidence.v2"
    assert evidence["status"] == "passed"
    assert evidence["changed_paths"] == ["skills/alpha-tool/scripts/tool.py"]
    assert [check["kind"] for check in evidence["checks"]] == [
        "search",
        "command",
        "pytest",
    ]
    assert evidence["checks"][0]["actual_matches"] == 0
    assert evidence["checks"][1]["stdout"] == "מלא\n"
    assert check_log.read_text(encoding="utf-8").splitlines() == ["run"]
    assert baseline.read_text(encoding="utf-8") == "keep me\n"

    unchanged = run_skill_update_workflow(
        "verify",
        "--state",
        str(state_path),
        "--evidence-output",
        str(evidence_path),
    )
    assert unchanged.returncode == 2
    assert "has not changed since successful verification" in unchanged.stderr
    assert check_log.read_text(encoding="utf-8").splitlines() == ["run"]

    outside_scope = worktree / "skills" / "beta-tool" / "notes.txt"
    outside_scope.write_text("Changed notes\n", encoding="utf-8", newline="\n")
    assert run_git(worktree, "add", "skills/beta-tool/notes.txt").returncode == 0
    assert run_git(worktree, "commit", "-m", "outside scope").returncode == 0
    broadened = run_skill_update_workflow(
        "verify",
        "--state",
        str(state_path),
        "--evidence-output",
        str(evidence_path),
    )
    assert broadened.returncode == 2
    assert "committed path is outside prepared scope" in broadened.stderr
    pending_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert pending_state["verification"]["status"] == "pending"
    assert pending_state["verification"]["generation"] == 1
    assert check_log.read_text(encoding="utf-8").splitlines() == ["run"]
    blocked_pending = run_skill_update_workflow(
        "finalize",
        "--state",
        str(state_path),
    )
    assert blocked_pending.returncode == 2
    assert "before successful verification" in blocked_pending.stderr
    assert run_git(worktree, "revert", "--no-edit", "HEAD").returncode == 0

    helper.write_text(
        "VALUE = 2\n# lint correction\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(
        worktree,
        "add",
        "skills/alpha-tool/scripts/tool.py",
    ).returncode == 0
    assert run_git(worktree, "commit", "-m", "lint correction").returncode == 0
    corrected = run_skill_update_workflow(
        "verify",
        "--state",
        str(state_path),
        "--evidence-output",
        str(evidence_path),
    )
    assert corrected.returncode == 0, corrected.stderr
    corrected_state_text = state_path.read_text(encoding="utf-8")
    corrected_evidence_text = evidence_path.read_text(encoding="utf-8")
    corrected_state = json.loads(corrected_state_text)
    assert corrected_state["verification"]["status"] == "passed"
    assert corrected_state["verification"]["generation"] == 1
    assert check_log.read_text(encoding="utf-8").splitlines() == ["run", "run"]

    helper.write_text(
        "VALUE = 2\n# later change\n",
        encoding="utf-8",
        newline="\n",
    )
    exhausted = run_skill_update_workflow(
        "verify",
        "--state",
        str(state_path),
        "--evidence-output",
        str(evidence_path),
    )
    assert exhausted.returncode == 2
    assert "changed after the correction generation" in exhausted.stderr
    assert check_log.read_text(encoding="utf-8").splitlines() == ["run", "run"]
    blocked_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert blocked_state["verification"]["status"] == "invalidated"
    assert blocked_state["verification"]["generation"] == 1
    blocked_finalize = run_skill_update_workflow(
        "finalize",
        "--state",
        str(state_path),
    )
    assert blocked_finalize.returncode == 2
    assert "before successful verification" in blocked_finalize.stderr
    helper.write_text(
        "VALUE = 2\n# lint correction\n",
        encoding="utf-8",
        newline="\n",
    )
    state_path.write_text(corrected_state_text, encoding="utf-8", newline="\n")
    evidence_path.write_text(
        corrected_evidence_text,
        encoding="utf-8",
        newline="\n",
    )

    undeclared_input = task_temp_root / "user-input.txt"
    undeclared_input.write_text("preserve\n", encoding="utf-8", newline="\n")
    outside_evidence = scope / "outside-evidence.json"
    outside_evidence.write_text("preserve\n", encoding="utf-8", newline="\n")
    verified_state_text = state_path.read_text(encoding="utf-8")
    escaped_state = json.loads(verified_state_text)
    next(
        artifact
        for artifact in escaped_state["cleanup"]["owned_artifacts"]
        if artifact["role"] == "evidence"
    )["path"] = str(outside_evidence)
    state_path.write_text(
        json.dumps(escaped_state) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    escaped = run_skill_update_workflow(
        "finalize",
        "--state",
        str(state_path),
    )
    assert escaped.returncode == 2
    assert "escapes task_temp_root" in escaped.stderr
    assert request_path.is_file() and state_path.is_file() and evidence_path.is_file()
    assert outside_evidence.is_file() and undeclared_input.is_file()
    state_path.write_text(verified_state_text, encoding="utf-8", newline="\n")

    finalized = run_skill_update_workflow(
        "finalize",
        "--state",
        str(state_path),
    )
    assert finalized.returncode == 0, finalized.stderr
    assert finalized.stdout.strip() == "OK"
    assert not request_path.exists()
    assert not state_path.exists()
    assert not evidence_path.exists()
    assert undeclared_input.is_file() and outside_evidence.is_file()

    empty_task_temp_root = task_temp_root.parent / "empty-finalization"
    empty_task_temp_root.mkdir()
    empty_request_path = empty_task_temp_root / "request.json"
    empty_state_path = empty_task_temp_root / "state.json"
    empty_evidence_path = empty_task_temp_root / "evidence.json"
    empty_request = json.loads(json.dumps(request))
    empty_request["task_temp_root"] = str(empty_task_temp_root)
    empty_request["evidence_output"] = str(empty_evidence_path)
    empty_request_path.write_text(
        json.dumps(empty_request) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    prepared_empty = run_skill_update_workflow(
        "prepare",
        "--request",
        str(empty_request_path),
        "--state",
        str(empty_state_path),
    )
    assert prepared_empty.returncode == 0, prepared_empty.stderr
    helper.write_text(
        "VALUE = 2\n# second verified change\n",
        encoding="utf-8",
        newline="\n",
    )
    verified_empty = run_skill_update_workflow(
        "verify",
        "--state",
        str(empty_state_path),
        "--evidence-output",
        str(empty_evidence_path),
    )
    assert verified_empty.returncode == 0, verified_empty.stderr
    finalized_empty = run_skill_update_workflow(
        "finalize",
        "--state",
        str(empty_state_path),
    )
    assert finalized_empty.returncode == 0, finalized_empty.stderr
    assert finalized_empty.stdout.strip() == "OK"
    assert not empty_task_temp_root.exists()

    removed_task_temp_root = task_temp_root.parent / "removed-worktree-finalization"
    removed_task_temp_root.mkdir()
    removed_request_path = removed_task_temp_root / "request.json"
    removed_state_path = removed_task_temp_root / "state.json"
    removed_evidence_path = removed_task_temp_root / "evidence.json"
    removed_request = json.loads(json.dumps(request))
    removed_request["task_temp_root"] = str(removed_task_temp_root)
    removed_request["evidence_output"] = str(removed_evidence_path)
    removed_request["checks"] = [
        {
            "kind": "search",
            "pattern": "FORBIDDEN",
            "paths": ["skills/alpha-tool/scripts/tool.py"],
            "expected_matches": 0,
        }
    ]
    removed_request_path.write_text(
        json.dumps(removed_request) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    prepared = run_skill_update_workflow(
        "prepare",
        "--request",
        str(removed_request_path),
        "--state",
        str(removed_state_path),
    )
    assert prepared.returncode == 0, prepared.stderr
    helper.write_text(
        "VALUE = 2\n# third verified change\n",
        encoding="utf-8",
        newline="\n",
    )
    verified = run_skill_update_workflow(
        "verify",
        "--state",
        str(removed_state_path),
        "--evidence-output",
        str(removed_evidence_path),
    )
    assert verified.returncode == 0, verified.stderr

    source = scope / task_temp_root.parent.name
    removed = run_git(source, "worktree", "remove", "--force", str(worktree))
    assert removed.returncode == 0, removed.stderr
    finalized = run_skill_update_workflow(
        "finalize", "--state", str(removed_state_path)
    )

    assert finalized.returncode == 0, finalized.stderr
    assert finalized.stdout.strip() == "OK"
    assert not removed_task_temp_root.exists()
