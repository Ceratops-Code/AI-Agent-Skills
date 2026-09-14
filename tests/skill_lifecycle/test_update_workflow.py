from __future__ import annotations

import json
import os
import pathlib
import runpy
import shlex
import stat
import sys
from contextlib import contextmanager
from typing import Any

import pytest

from tests.skill_lifecycle.support import (
    SKILL_UPDATE_WORKFLOW,
    prepare_skill_update_workflow_worktree,
    run_skill_update_workflow,
)
from tests.support.repositories import (
    run_git,
)


@pytest.mark.parametrize(
    "outcome", ["passed", "collection_failed", "command_failed", "pytest_failed", "cleanup_failed"]
)
def test_skill_update_scratch_is_owned_through_collection_and_verification(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    case_root = tmp_path / "paths with spaces"
    case_root.mkdir()
    worktree, scope, task_temp_root = prepare_skill_update_workflow_worktree(case_root)
    log = scope / "scratch-paths.jsonl"
    caller_temp = scope / "caller pytest"
    caller_temp.mkdir()
    sentinel = caller_temp / "keep.txt"
    sentinel.write_text("caller-owned", encoding="utf-8")
    retained = task_temp_root / "keep.txt"
    retained.write_text("unrelated", encoding="utf-8")
    monkeypatch.setenv("SCRATCH_CHECK_LOG", str(log))
    inherited_options = "--maxfail=1 --basetemp " + shlex.quote(str(caller_temp))
    monkeypatch.setenv("PYTEST_ADDOPTS", inherited_options)
    monkeypatch.setenv("PYTEST_DEBUG_TEMPROOT", str(caller_temp))
    probe = (
        "import json, os, pathlib, stat, tempfile\n"
        "def record(phase, pytest_path=None):\n"
        "    folder = pathlib.Path(tempfile.mkdtemp(prefix='generated-'))\n"
        "    generated = folder / 'readonly.txt'\n"
        "    generated.write_text('generated', encoding='utf-8')\n"
        "    generated.chmod(stat.S_IREAD)\n"
        "    value = {'phase': phase, 'folder': str(folder), 'root': tempfile.gettempdir(), "
        "'pytest': str(pytest_path) if pytest_path else None}\n"
        "    with pathlib.Path(os.environ['SCRATCH_CHECK_LOG']).open('a', encoding='utf-8') as log:\n"
        "        log.write(json.dumps(value) + '\\n')\n"
    )
    test_file = worktree / "tests" / "test_helper.py"
    test_file.write_text(
        probe + "record('collection')\n"
        + ("raise RuntimeError('collection failed')\n" if outcome == "collection_failed" else "")
        + "def test_helper_value(tmp_path):\n"
        + "    record('test', tmp_path)\n"
        + f"    assert {outcome != 'pytest_failed'}\n",
        encoding="utf-8", newline="\n",
    )
    check_script = scope / "check.py"
    check_script.write_text(
        probe + "record('command')\nprint('probe-finished')\n"
        + f"raise SystemExit({7 if outcome == 'command_failed' else 0})\n",
        encoding="utf-8", newline="\n",
    )
    request_path = task_temp_root / "request.json"
    state_path = task_temp_root / "state.json"
    evidence_path = task_temp_root / "evidence.json"
    source_path = "skills/alpha-tool/scripts/tool.py"
    request_path.write_text(json.dumps({
        "schema": "ceratops-skill-update-request.v2",
        "repo_root": str(worktree), "task_temp_root": str(task_temp_root),
        "evidence_output": str(evidence_path),
        "disposable_artifacts": ["request", "state", "evidence"],
        "selected_skills": ["alpha-tool"], "allowed_paths": [source_path],
        "change_groups": [{"name": "helper", "paths": [source_path]}],
        "checks": [
            {"kind": "command", "argv": [sys.executable, str(check_script)]},
            {"kind": "pytest", "nodes": ["tests/test_helper.py::test_helper_value"]},
        ],
    }) + "\n", encoding="utf-8", newline="\n")
    prepared = run_skill_update_workflow(
        "prepare", "--request", str(request_path), "--state", str(state_path),
    )
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert not pathlib.Path(records[0]["root"]).exists()
    assert sentinel.read_text(encoding="utf-8") == "caller-owned"
    if outcome == "collection_failed":
        assert prepared.returncode == 2
        assert "pytest node collection failed" in prepared.stderr
        assert not state_path.exists() and not evidence_path.exists()
        assert sorted(path.name for path in task_temp_root.iterdir()) == ["keep.txt", "request.json"]
        return
    assert prepared.returncode == 0, prepared.stderr
    (worktree / source_path).write_text("VALUE = 2\n", encoding="utf-8", newline="\n")
    if outcome == "cleanup_failed":
        monkeypatch.syspath_prepend(str(SKILL_UPDATE_WORKFLOW.parent))
        workflow = runpy.run_path(str(SKILL_UPDATE_WORKFLOW))
        namespace = workflow["command_verify"].__globals__
        original_environment = namespace["check_environment"]

        @contextmanager
        def failed_cleanup(root: pathlib.Path):
            with original_environment(root) as environment:
                yield environment
            raise OSError("simulated scratch cleanup failure")

        monkeypatch.setitem(namespace, "check_environment", failed_cleanup)
        with pytest.raises(workflow["UpdateExecutionError"], match="scratch cleanup failure"):
            workflow["command_verify"](state_path, evidence_path)
    else:
        verified = run_skill_update_workflow(
            "verify", "--state", str(state_path), "--evidence-output", str(evidence_path),
        )
        assert verified.returncode == (0 if outcome == "passed" else 2), verified.stderr
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["status"] == ("passed" if outcome == "passed" else "failed")
    assert evidence["checks"][0]["returncode"] == (7 if outcome == "command_failed" else 0)
    assert "probe-finished" in evidence["checks"][0]["stdout"]
    if outcome == "cleanup_failed":
        assert len(evidence["checks"]) == 2
        assert all(check["returncode"] == 0 for check in evidence["checks"])
        assert evidence["failures"] == ["simulated scratch cleanup failure"]
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    for record in records:
        scratch = pathlib.Path(record["root"])
        assert scratch.parent == task_temp_root
        assert pathlib.Path(record["folder"]).is_relative_to(scratch)
        assert not scratch.exists()
        if record["pytest"]:
            assert pathlib.Path(record["pytest"]).is_relative_to(scratch)
    assert not list(task_temp_root.glob("check-*"))
    assert not list(task_temp_root.glob(".check-*.cleanup.json"))
    assert os.environ["PYTEST_ADDOPTS"] == inherited_options
    assert sentinel.read_text(encoding="utf-8") == "caller-owned"
    finalized = run_skill_update_workflow("finalize", "--state", str(state_path))
    if outcome == "passed":
        assert finalized.returncode == 0, finalized.stderr
        assert sorted(path.name for path in task_temp_root.iterdir()) == ["keep.txt"]
    else:
        assert finalized.returncode == 2
        assert state_path.exists() and evidence_path.exists() and request_path.exists()
    assert retained.read_text(encoding="utf-8") == "unrelated"


@pytest.mark.parametrize("failure", ["body", "cleanup", "residual"])
def test_skill_update_scratch_handles_exceptions_and_cleanup_errors(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    module = runpy.run_path(str(SKILL_UPDATE_WORKFLOW.with_name("skill_update_scratch.py")))
    check_environment = module["check_environment"]
    filesystem = module["shutil"]
    original_rmtree = filesystem.rmtree
    if failure != "body":
        def leave_residue(*args, **kwargs):
            if failure == "cleanup":
                raise PermissionError("locked file")
        monkeypatch.setattr(filesystem, "rmtree", leave_residue)
    expected = ValueError if failure == "body" else OSError
    with pytest.raises(expected) as captured:
        with check_environment(tmp_path) as environment:
            scratch = pathlib.Path(environment["TEMP"])
            generated = scratch / "readonly.txt"
            generated.write_text("generated", encoding="utf-8")
            generated.chmod(stat.S_IREAD)
            if failure == "body":
                raise ValueError("test body failed")
    if failure == "body":
        assert not scratch.exists()
    else:
        assert scratch.exists()
        assert str(scratch) in str(captured.value)
        assert "cleanup" in str(captured.value)
        records = list(tmp_path.glob(".check-*.cleanup.json"))
        assert len(records) == 1
        with pytest.raises(OSError):
            with check_environment(tmp_path):
                pytest.fail("new checks started before unfinished cleanup")
        assert records[0].exists()
        monkeypatch.setattr(filesystem, "rmtree", original_rmtree)
        with check_environment(tmp_path):
            assert not scratch.exists()
            assert not records[0].exists()
        assert not list(tmp_path.glob(".check-*.cleanup.json"))
        assert not list(tmp_path.glob("check-*"))


@pytest.mark.parametrize("invalid", ["path", "json", "options"])
def test_skill_update_scratch_preserves_unowned_paths(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, invalid: str,
) -> None:
    module = runpy.run_path(str(SKILL_UPDATE_WORKFLOW.with_name("skill_update_scratch.py")))
    root = tmp_path / "task"
    root.mkdir()
    outside = tmp_path / "caller"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    unrecorded = root / "check-caller"
    unrecorded.mkdir()
    marker = root / ".check-retained.cleanup.json"
    if invalid == "path":
        marker.write_text(json.dumps({
            "schema": module["SCRATCH_SCHEMA"], "path": str(outside),
        }), encoding="utf-8")
    elif invalid == "json":
        marker.write_text("{", encoding="utf-8")
    else:
        monkeypatch.setenv("PYTEST_ADDOPTS", "'unterminated")
    with pytest.raises(OSError):
        with module["check_environment"](root):
            pytest.fail("invalid scratch ownership or options were accepted")
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert unrecorded.is_dir()
    assert set(root.iterdir()) == ({unrecorded} if invalid == "options" else {unrecorded, marker})


@pytest.mark.parametrize("declaration", [
    "skill-section", "action-section", "payload", "payload-glob", "payload-directory",
    "wildcard-payload", "wildcard-glob", "new-payload", "deleted-payload", "manifest",
    "unrelated-skill", "extra-skill", "unmanaged-skill", "target-only", "wrong-glob",
    "mapped-directory", "unsafe-payload", "unsafe-section", "invalid-json", "missing-manifest",
])
def test_skill_update_workflow_resolves_manifest_source_owners(
    tmp_path: pathlib.Path, declaration: str,
) -> None:
    worktree, _scope, task_temp_root = prepare_skill_update_workflow_worktree(tmp_path)
    shared = "skills/sections/shared.md" if declaration in {"skill-section", "action-section", "unsafe-section"} else "skills/sections/scripts/shared.py"
    source = worktree / shared
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    manifest_path = worktree / "skills/skill-sections.json"
    manifest: dict[str, Any] = {
        "runtime_source_id": "example/shared-ownership", "validation_profile": "ceratops-compatible",
        "sections": {"shared": shared}, "skills": {"alpha-tool": [], "beta-tool": []},
        "actions": {}, "runtime_payloads": {},
    }
    selected = ["alpha-tool"]
    allowed = [shared]
    rejection = None
    payload = {"source": shared, "target": "scripts/shared.py"}
    manifest["runtime_payloads"] = {"alpha-tool": [payload]}
    if declaration in {"skill-section", "action-section", "unsafe-section"}:
        manifest["runtime_payloads"] = {}
        if declaration == "action-section":
            manifest["actions"] = {"alpha-tool": {"references/change.md": ["shared"]}}
        else:
            manifest["skills"]["alpha-tool"] = ["shared"]
        if declaration == "unsafe-section":
            manifest["sections"]["shared"] = "../outside.md"
            rejection = "section source"
    elif declaration == "payload-glob":
        manifest["runtime_payloads"] = {"alpha-tool": ["skills/sections/**/*.py"]}
    elif declaration == "payload-directory":
        manifest["runtime_payloads"] = {"alpha-tool": ["skills/sections"]}
    elif declaration in {"wildcard-payload", "wildcard-glob", "unmanaged-skill"}:
        selected = ["alpha-tool", "beta-tool"]
        manifest["runtime_payloads"] = {"*": ["skills/sections/**/*.py" if declaration == "wildcard-glob" else payload]}
        if declaration == "unmanaged-skill":
            del manifest["skills"]["beta-tool"]
            rejection = "selected skill has no allowed source path: beta-tool"
    elif declaration == "new-payload":
        source.unlink()
    elif declaration == "manifest":
        selected = ["alpha-tool", "beta-tool"]
        allowed = ["skills/skill-sections.json"]
    elif declaration in {"unrelated-skill", "extra-skill"}:
        selected = ["beta-tool"] if declaration == "unrelated-skill" else ["alpha-tool", "beta-tool"]
        rejection = "selected skill has no allowed source path: beta-tool"
    elif declaration in {"target-only", "wrong-glob", "mapped-directory"}:
        manifest["runtime_payloads"] = {"alpha-tool": [
            {"source": "skills/sections/other.py", "target": shared} if declaration == "target-only"
            else {"source": "skills/sections/scripts", "target": "scripts/shared"} if declaration == "mapped-directory"
            else "skills/sections/*.py"
        ]}
        rejection = "selected skill has no allowed source path"
    elif declaration == "unsafe-payload":
        payload["source"] = "../outside.py"
        rejection = "unsafe exact mapping"
    elif declaration == "invalid-json":
        rejection = "section manifest is unreadable"
    elif declaration == "missing-manifest":
        rejection = "selected skill has no allowed source path"
    if declaration != "missing-manifest":
        manifest_path.write_text("{" if declaration == "invalid-json" else json.dumps(manifest) + "\n", encoding="utf-8")
    assert run_git(worktree, "add", "skills").returncode == 0
    assert run_git(worktree, "commit", "-m", "declare shared source consumers").returncode == 0
    request_path = task_temp_root / "request.json"
    state_path = task_temp_root / "state.json"
    evidence_path = task_temp_root / "evidence.json"
    request_path.write_text(json.dumps({
        "schema": "ceratops-skill-update-request.v2", "repo_root": str(worktree),
        "task_temp_root": str(task_temp_root), "evidence_output": str(evidence_path),
        "disposable_artifacts": ["request", "state", "evidence"],
        "selected_skills": selected, "allowed_paths": allowed,
        "change_groups": [{"name": "shared-source", "paths": allowed}],
        "checks": [{"kind": "command", "argv": [sys.executable, "-c", "print('OK')"]}],
    }) + "\n", encoding="utf-8")
    prepared = run_skill_update_workflow("prepare", "--request", str(request_path), "--state", str(state_path))
    if rejection is not None:
        assert prepared.returncode == 2 and rejection in prepared.stderr, prepared.stderr
        assert sorted(path.name for path in task_temp_root.iterdir()) == ["request.json"]
        return
    assert prepared.returncode == 0, prepared.stderr
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["selected_skills"] == selected and state["allowed_paths"] == allowed
    if declaration == "deleted-payload":
        source.unlink()
        assert run_git(worktree, "add", shared).returncode == 0
    elif declaration == "manifest":
        manifest["maintenance_workflows"] = {"skill_local_or_metadata_changes": []}
        manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    else:
        source.write_text("VALUE = 2\n", encoding="utf-8")
        # Ownership must not let an undeclared manifest edit authorize verification.
        original_manifest = manifest_path.read_bytes()
        manifest["runtime_source_id"] = "example/changed"
        manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        rejected = run_skill_update_workflow("verify", "--state", str(state_path), "--evidence-output", str(evidence_path))
        assert rejected.returncode == 2, rejected.stdout
        assert state_path.exists() and request_path.exists()
        manifest_path.write_bytes(original_manifest)
    verified = run_skill_update_workflow("verify", "--state", str(state_path), "--evidence-output", str(evidence_path))
    assert verified.returncode == 0, verified.stderr
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["changed_paths"] == allowed
    assert evidence["status"] == "passed"
    finalized = run_skill_update_workflow("finalize", "--state", str(state_path))
    assert finalized.returncode == 0, finalized.stderr
    assert not task_temp_root.exists()


@pytest.mark.parametrize("new_source", ["skills/sections/scripts/shared-helper.py", "scripts/example_helper.py", "unowned/new.py"])
def test_skill_update_workflow_accepts_new_shared_section_source(
    tmp_path: pathlib.Path,
    new_source: str,
) -> None:
    worktree, _scope, task_temp_root = prepare_skill_update_workflow_worktree(
        tmp_path
    )
    shared_source = worktree / new_source
    shared_source.parent.mkdir(parents=True, exist_ok=True)
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
            new_source,
        ],
        "change_groups": [
            {
                "name": "shared-helper",
                "paths": [
                    "skills/alpha-tool/scripts/tool.py",
                    new_source,
                ],
            }
        ],
        "checks": [
            {
                "kind": "search",
                "pattern": "SHARED_PAYLOAD",
                "paths": [new_source],
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
    if new_source.startswith("unowned/"):
        assert prepared.returncode != 0
        assert "allowed path must be" in prepared.stderr
        assert not state_path.exists()
        return
    assert prepared.returncode == 0, prepared.stderr
    retention_marker = task_temp_root / ".ceratops-skill-update-active.json"
    assert json.loads(retention_marker.read_text(encoding="utf-8")) == {
        "schema": "ceratops-skill-update-retention.v1",
        "state": str(state_path.resolve()),
    }
    prepared_state = json.loads(state_path.read_text(encoding="utf-8"))
    retention_record = next(
        artifact
        for artifact in prepared_state["cleanup"]["owned_artifacts"]
        if artifact["role"] == "retention"
    )
    assert retention_record["path"] == str(retention_marker.resolve())
    assert len(retention_record["sha256"]) == 64
    shared_source.write_text(
        "SHARED_PAYLOAD = True\n\n",
        encoding="utf-8",
        newline="\n",
    )
    for placement in ("untracked", "staged"):
        if placement == "staged":
            assert run_git(worktree, "add", str(shared_source)).returncode == 0
        rejected = run_skill_update_workflow(
            "verify", "--state", str(state_path),
            "--evidence-output", str(evidence_path),
        )
        assert rejected.returncode == 2, (placement, rejected.stderr)
        assert "new blank line at EOF" in rejected.stderr
        failed = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert failed["status"] == "failed"
        assert failed["checks"] == []
        assert shared_source.read_text(encoding="utf-8") == "SHARED_PAYLOAD = True\n\n"
    shared_source.write_text("SHARED_PAYLOAD = True\n", encoding="utf-8", newline="\n")
    staged_failure = run_skill_update_workflow(
        "verify", "--state", str(state_path),
        "--evidence-output", str(evidence_path),
    )
    assert staged_failure.returncode == 2
    assert "new blank line at EOF" in staged_failure.stderr
    assert json.loads(evidence_path.read_text(encoding="utf-8"))["checks"] == []
    assert run_git(worktree, "add", str(shared_source)).returncode == 0
    verified = run_skill_update_workflow(
        "verify",
        "--state",
        str(state_path),
        "--evidence-output",
        str(evidence_path),
    )
    assert verified.returncode == 0, verified.stderr
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["changed_paths"] == [new_source]
    shared_source.write_text("SHARED_PAYLOAD = True\n\n", encoding="utf-8", newline="\n")
    assert run_git(worktree, "add", str(shared_source)).returncode == 0
    assert run_git(worktree, "commit", "-m", "new helper").returncode == 0
    committed_failure = run_skill_update_workflow(
        "verify", "--state", str(state_path),
        "--evidence-output", str(evidence_path),
    )
    assert committed_failure.returncode == 2
    assert "new blank line at EOF" in committed_failure.stderr
    assert json.loads(evidence_path.read_text(encoding="utf-8"))["checks"] == []
    assert json.loads(state_path.read_text(encoding="utf-8"))["verification"]["status"] == "pending"
    shared_source.write_text("SHARED_PAYLOAD = True\n", encoding="utf-8", newline="\n")
    assert run_git(worktree, "add", str(shared_source)).returncode == 0
    corrected = run_skill_update_workflow(
        "verify", "--state", str(state_path),
        "--evidence-output", str(evidence_path),
    )
    assert corrected.returncode == 0, corrected.stderr
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

    helper.write_text("VALUE = 2 \n", encoding="utf-8", newline="\n")
    whitespace_failure = run_skill_update_workflow(
        "verify", "--state", str(state_path),
        "--evidence-output", str(evidence_path),
    )
    assert whitespace_failure.returncode == 2
    assert "trailing whitespace" in whitespace_failure.stderr
    assert json.loads(evidence_path.read_text(encoding="utf-8"))["checks"] == []
    assert not check_log.exists()
    helper.write_text("VALUE = 2\n", encoding="utf-8", newline="\n")

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


@pytest.mark.parametrize("placement", ["staged-deletion", "committed-deletion", "staged-addition"])
def test_skill_update_workflow_preserves_declared_ancillary_changes(
    tmp_path: pathlib.Path, placement: str,
) -> None:
    worktree, _scope, task_temp_root = prepare_skill_update_workflow_worktree(tmp_path)
    ancillary = worktree / "repository-helper.py"
    ancillary.write_text("VALUE = 1\n", encoding="utf-8")
    assert run_git(worktree, "add", ancillary.name).returncode == 0
    if placement != "staged-addition":
        assert run_git(worktree, "commit", "-m", "add ancillary helper").returncode == 0
    request_path = task_temp_root / "request.json"
    state_path = task_temp_root / "state.json"
    evidence_path = task_temp_root / "evidence.json"
    paths = ["skills/alpha-tool/scripts/tool.py", ancillary.name]
    request = {
        "schema": "ceratops-skill-update-request.v2",
        "repo_root": str(worktree), "task_temp_root": str(task_temp_root),
        "evidence_output": str(evidence_path),
        "disposable_artifacts": ["request", "state", "evidence"],
        "selected_skills": ["alpha-tool"], "allowed_paths": paths,
        "change_groups": [{"name": "remove-ancillary-helper", "paths": paths}],
        "checks": [{"kind": "command", "argv": [
            sys.executable, "-c", "import pathlib,sys; assert pathlib.Path(sys.argv[1]).exists() == (sys.argv[2] == 'staged-addition')", str(ancillary), placement,
        ]}],
    }
    request_path.write_text(json.dumps(request) + "\n", encoding="utf-8")
    prepared = run_skill_update_workflow("prepare", "--request", str(request_path), "--state", str(state_path))
    assert prepared.returncode == 0, prepared.stderr
    if placement == "staged-addition":
        ancillary.write_text("VALUE = 2\n", encoding="utf-8")
    else:
        ancillary.unlink()
    assert run_git(worktree, "add", ancillary.name).returncode == 0
    verified = run_skill_update_workflow("verify", "--state", str(state_path), "--evidence-output", str(evidence_path))
    assert verified.returncode == 0, verified.stderr
    assert json.loads(evidence_path.read_text())["changed_paths"] == [ancillary.name]
    if placement == "committed-deletion":
        assert run_git(worktree, "commit", "-m", "remove ancillary helper").returncode == 0
        committed = run_skill_update_workflow("verify", "--state", str(state_path), "--evidence-output", str(evidence_path))
        assert committed.returncode == 0, committed.stderr
        assert json.loads(evidence_path.read_text())["generation"] == 1
    finalized = run_skill_update_workflow("finalize", "--state", str(state_path))
    assert finalized.returncode == 0, finalized.stderr
    assert not task_temp_root.exists()
    assert ancillary.exists() == (placement == "staged-addition")
