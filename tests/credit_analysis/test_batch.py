from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import pathlib
import subprocess
from typing import Any

import pytest

from tests.credit_analysis.models import (
    FakeCreditModelRunner,
    complete_holistic_credit_analysis,
    holistic_model_catalog,
    load_credit_analysis_workflow_module,
)
from tests.credit_analysis.paths import (
    CREDIT_ANALYSIS_CONTRACT,
)
from tests.credit_analysis.sessions import (
    _attach_persistent_descendants,
    canonical_credit_task_root,
    credit_analysis_batch_request,
    credit_analysis_request,
    indexed_credit_analysis_session,
    write_json_file,
)
from tests.credit_analysis.workflow import run_credit_analysis_workflow


@pytest.mark.parametrize(
    "action,correction",
    [
        ("helper-contracts", None),
        ("context-evidence", None),
        ("rework-validation", None),
        ("tool-flow", None),
        ("instruction-reasoning", None),
        *[("full-analysis", case) for case in (
            "estimate", "final-estimate", "withdraw", "withdraw-temporary",
            "conflict", "protected", "foreign-call", "malformed",
        )],
    ],
)
def test_credit_analysis_workflow_each_surface_is_independently_callable(
    tmp_path: pathlib.Path,
    action: str,
    correction: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if correction is not None:
        _exercise_corrective_cli(tmp_path, monkeypatch, correction)
        return
    request, _, _ = credit_analysis_request(tmp_path, action=action)
    workflow = load_credit_analysis_workflow_module()
    runner = FakeCreditModelRunner(temporary_controls=False)
    plan = workflow.command_plan_orchestration(
        request,
        available_models=runner.available_models,
    )
    manifest = json.loads(
        pathlib.Path(plan["manifest_path"]).read_text(encoding="utf-8")
    )
    assert manifest["surface_order"] == [action]
    assert plan["projected_semantic_calls"] == len(manifest["luna_tasks"]) + 7
    complete = workflow.command_execute_orchestration(
        pathlib.Path(plan["state_path"]),
        runner=runner,
        available_models=runner.available_models,
    )
    assert complete["complete"] is True
    phases = [call["phase"] for call in runner.calls]
    assert phases.count("luna-discovery") == len(manifest["luna_tasks"])
    assert phases.count("sol-adjudication") == len(manifest["luna_tasks"])
    assert phases.count("sol-direct-evidence") == 1
    assert phases.count("sol-final") == 1
    assert "supplied fixed lenses" in next(
        call["prompt"] for call in runner.calls if call["phase"] == "luna-discovery"
    )
    assert "every supplied surface section" in next(
        call["prompt"] for call in runner.calls if call["phase"] == "sol-adjudication"
    )
    final = json.loads(
        pathlib.Path(complete["final_result_path"]).read_text(encoding="utf-8")
    )
    assert [item["surface_id"] for item in final["surface_summaries"]] == [
        action
    ]


def test_credit_analysis_workflow_resolves_current_and_named_threads(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    current_id = "00000000-0000-4000-8000-000000000001"
    named_id = "00000000-0000-4000-8000-000000000002"
    indexed_credit_analysis_session(
        codex_home,
        thread_id=current_id,
        thread_name="Current Thread",
        updated_at="2026-08-07T17:00:00Z",
        project_name="alpha",
    )
    indexed_credit_analysis_session(
        codex_home,
        thread_id=named_id,
        thread_name="Named Thread",
        updated_at="2026-08-07T16:00:00Z",
        project_name="alpha",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_THREAD_ID", current_id)
    catalog = holistic_model_catalog()
    catalog_json = json.dumps(
        {
            "models": [
                {
                    "slug": slug,
                    "supported_reasoning_levels": [
                        {"effort": effort}
                        for effort in sorted(spec["reasoning_efforts"])
                    ],
                    "context_window": spec["effective_context_tokens"],
                    "effective_context_window_percent": 100,
                }
                for slug, spec in catalog.items()
            ]
        },
        separators=(",", ":"),
    )
    fake_bin = tmp_path / "fake-codex-bin"
    fake_bin.mkdir()
    if os.name == "nt":
        fake_codex = fake_bin / "codex.cmd"
        fake_codex.write_text(f"@echo {catalog_json}\n", encoding="utf-8")
    else:
        fake_codex = fake_bin / "codex"
        fake_codex.write_text(
            f"#!/bin/sh\nprintf '%s\\n' '{catalog_json}'\n", encoding="utf-8"
        )
        fake_codex.chmod(0o755)
    # pytest's tmp_path fixture owns and removes the fake executable.
    monkeypatch.setenv(
        "PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}"
    )

    def request_for(name: str, source: dict[str, Any]) -> pathlib.Path:
        root = canonical_credit_task_root(tmp_path, f"single-{name}")
        request = tmp_path / f"single-request-{name}.json"
        write_json_file(
            request,
            {
                "schema": "ceratops-credit-analysis-request.v1",
                "action": "full-analysis",
                "mode": "full-analysis",
                "source": source,
                "window": {
                    "mode": "full_thread",
                    "last_runs": None,
                    "turn_ids": [],
                },
                "task_temp_root": str(root),
                "evidence_output": str(root / "evidence.json"),
                "pricing_profile": None,
                "expected_surface_contract_version": 8,
                "mutation_authority": False,
            },
        )
        return request

    current = run_credit_analysis_workflow(
        "plan",
        "--request",
        str(request_for("current", {"current_thread": True})),
    )
    assert current.returncode == 0, current.stderr
    current_state = json.loads(
        pathlib.Path(json.loads(current.stdout)["state_path"]).read_text(
            encoding="utf-8"
        )
    )
    assert current_state["source"]["kind"] == "current_thread"
    assert current_state["source"]["value"] == current_id

    named = run_credit_analysis_workflow(
        "plan",
        "--request",
        str(request_for("named", {"thread_name": "named thread"})),
    )
    assert named.returncode == 0, named.stderr
    named_state = json.loads(
        pathlib.Path(json.loads(named.stdout)["state_path"]).read_text(
            encoding="utf-8"
        )
    )
    assert named_state["source"]["kind"] == "thread_name"
    assert named_state["source"]["thread_id"] == named_id
    assert len(named_state["source"]["thread_index_fingerprint"]) == 64

    duplicate_id = "00000000-0000-4000-8000-000000000003"
    indexed_credit_analysis_session(
        codex_home,
        thread_id=duplicate_id,
        thread_name="NAMED THREAD",
        updated_at="2026-08-07T15:00:00Z",
        project_name="beta",
    )
    ambiguous = run_credit_analysis_workflow(
        "plan",
        "--request",
        str(request_for("ambiguous", {"thread_name": "Named Thread"})),
    )
    assert ambiguous.returncode == 2
    assert "ambiguous" in ambiguous.stderr

    monkeypatch.delenv("CODEX_THREAD_ID")
    missing_current = run_credit_analysis_workflow(
        "plan",
        "--request",
        str(request_for("missing-current", {"current_thread": True})),
    )
    assert missing_current.returncode == 2
    assert "CODEX_THREAD_ID" in missing_current.stderr


def test_credit_analysis_batch_selects_recent_threads_and_projects_once(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = load_credit_analysis_workflow_module()
    monkeypatch.setattr(
        workflow,
        "_codex_model_catalog",
        lambda: holistic_model_catalog(),
    )
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    thread_ids = {
        "alpha_new": "00000000-0000-4000-8000-000000000011",
        "alpha_old": "00000000-0000-4000-8000-000000000012",
        "beta_old": "00000000-0000-4000-8000-000000000013",
        "alpha_stale": "00000000-0000-4000-8000-000000000014",
        "beta_new": "00000000-0000-4000-8000-000000000015",
        "gamma_mid": "00000000-0000-4000-8000-000000000017",
        "gamma_edge": "00000000-0000-4000-8000-000000000018",
        "boundary": "00000000-0000-4000-8000-000000000019",
        "future": "00000000-0000-4000-8000-00000000001a",
    }
    indexed_credit_analysis_session(
        codex_home,
        thread_id=thread_ids["alpha_new"],
        thread_name="Alpha new",
        updated_at="2026-08-07T17:00:00Z",
        project_name="alpha",
    )
    indexed_credit_analysis_session(
        codex_home,
        thread_id=thread_ids["alpha_old"],
        thread_name="Alpha old",
        updated_at="2026-08-06T17:00:00Z",
        project_name="alpha",
    )
    indexed_credit_analysis_session(
        codex_home,
        thread_id=thread_ids["beta_old"],
        thread_name="Beta old",
        updated_at="2026-08-05T17:00:00Z",
        project_name="beta",
    )
    indexed_credit_analysis_session(
        codex_home,
        thread_id=thread_ids["alpha_stale"],
        thread_name="Alpha stale",
        updated_at="2026-08-01T17:00:00Z",
        project_name="alpha",
    )
    indexed_credit_analysis_session(
        codex_home,
        thread_id=thread_ids["beta_new"],
        thread_name="Beta new",
        updated_at="2026-08-07T17:00:00Z",
        project_name="beta",
    )
    indexed_credit_analysis_session(
        codex_home,
        thread_id=thread_ids["gamma_mid"],
        thread_name="Gamma mid",
        updated_at="2026-08-06T12:00:00Z",
        project_name="gamma",
    )
    indexed_credit_analysis_session(
        codex_home,
        thread_id=thread_ids["gamma_edge"],
        thread_name="Gamma edge",
        updated_at="2026-08-04T19:00:00Z",
        project_name="gamma",
    )
    indexed_credit_analysis_session(
        codex_home,
        thread_id=thread_ids["boundary"],
        thread_name="Boundary inclusive",
        updated_at="2026-08-04T18:00:00Z",
        project_name="boundary",
    )
    indexed_credit_analysis_session(
        codex_home,
        thread_id=thread_ids["future"],
        thread_name="Future excluded",
        updated_at="2026-08-07T18:00:01Z",
        project_name="future",
    )
    with (codex_home / "session_index.jsonl").open(
        "a", encoding="utf-8", newline="\n"
    ) as handle:
        handle.write(
            json.dumps(
                {
                    "id": thread_ids["alpha_new"],
                    "thread_name": "stale name",
                    "updated_at": "2026-08-01T00:00:00Z",
                }
            )
            + "\n"
        )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    cases: list[tuple[str, dict[str, Any], list[str]]] = [
        (
            "count-overall",
            {
                "kind": "recent_threads",
                "count": 2,
                "days": None,
                "project": None,
            },
            [thread_ids["alpha_new"], thread_ids["beta_new"]],
        ),
        (
            "days-overall",
            {
                "kind": "recent_days",
                "count": None,
                "days": 3,
                "project": None,
            },
            [
                thread_ids["alpha_new"],
                thread_ids["beta_new"],
                thread_ids["alpha_old"],
                thread_ids["gamma_mid"],
                thread_ids["beta_old"],
                thread_ids["gamma_edge"],
                thread_ids["boundary"],
            ],
        ),
        (
            "count-project",
            {
                "kind": "recent_threads",
                "count": 2,
                "days": None,
                "project": {"kind": "name", "value": "alpha"},
            },
            [thread_ids["alpha_new"], thread_ids["alpha_old"]],
        ),
        (
            "days-project",
            {
                "kind": "recent_days",
                "count": None,
                "days": 3,
                "project": {"kind": "name", "value": "alpha"},
            },
            [thread_ids["alpha_new"], thread_ids["alpha_old"]],
        ),
    ]
    for name, selector, expected_ids in cases:
        request = credit_analysis_batch_request(
            tmp_path,
            selector=selector,
            name=name,
        )
        if name == "count-overall":
            task_root = pathlib.Path(
                json.loads(request.read_text(encoding="utf-8"))["task_temp_root"]
            )
            task_root.rmdir()
        status = workflow.command_prepare_batch(request)
        if name == "count-overall":
            assert task_root.is_dir()
        manifest = json.loads(
            pathlib.Path(status["manifest_path"]).read_text(encoding="utf-8")
        )
        assert [item["thread_id"] for item in manifest["items"]] == expected_ids
        assert manifest["as_of"] == "2026-08-07T18:00:00Z"
        if name == "days-overall":
            assert manifest["selection"]["selected_count"] == 7
            assert len(manifest["items"]) == 7
            assert all(item["source_fingerprint"] for item in manifest["items"])
        for item in manifest["items"]:
            assert pathlib.Path(item["evidence_path"]).parent == pathlib.Path(
                item["state_path"]
            ).parent
            evidence = json.loads(
                pathlib.Path(item["evidence_path"]).read_text(encoding="utf-8")
            )
            assert evidence["collection"]["session_reads"] == 1
            assert evidence["collection"]["completed_runs"] == 3
            assert evidence["semantic_coverage"]["covered_percent"] == 100.0
            assert "correct the earlier plan" in json.dumps(
                evidence["runs"][0]["user_messages"]
            )
            child_state = json.loads(
                pathlib.Path(item["state_path"]).read_text(encoding="utf-8")
            )
            assert child_state["schema"] == (
                "ceratops-credit-analysis-orchestration-state.v5"
            )
            assert child_state["manifest"]["projected_semantic_calls"] == (
                len(child_state["manifest"]["luna_tasks"]) + 7
            )
            assert child_state["task_order"] == [
                *[
                    task["task_id"]
                    for task in child_state["manifest"]["luna_tasks"]
                ],
                *[
                    task["task_id"]
                    for task in child_state["manifest"]["sol_tasks"]
                ],
            ]
            assert "queue" not in child_state
        assert workflow.command_prepare_batch(request) == status

    escaped_scope = tmp_path / "escaped-batch-output"
    escaped_scope.mkdir()
    escaped_request = credit_analysis_batch_request(
        escaped_scope,
        selector={
            "kind": "recent_threads",
            "count": 1,
            "days": None,
            "project": None,
        },
        name="escaped",
    )
    escaped_payload = json.loads(escaped_request.read_text(encoding="utf-8"))
    escaped_manifest = escaped_scope / "outside-manifest.json"
    escaped_payload["manifest_output"] = str(escaped_manifest)
    write_json_file(escaped_request, escaped_payload)
    with pytest.raises(
        workflow.CreditAnalysisError,
        match="batch manifest escapes task_temp_root",
    ):
        workflow.command_prepare_batch(escaped_request)
    assert not escaped_manifest.exists()
    assert not (
        escaped_scope / "batch-escaped" / "batch-state.json"
    ).exists()

    indexed_credit_analysis_session(
        codex_home,
        thread_id="00000000-0000-4000-8000-000000000016",
        thread_name="Other alpha",
        updated_at="2026-08-07T16:30:00Z",
        project_name="alpha",
        repository_owner="other",
    )
    ambiguous_request = credit_analysis_batch_request(
        tmp_path,
        selector={
            "kind": "recent_days",
            "count": None,
            "days": 3,
            "project": {"kind": "name", "value": "alpha"},
        },
        name="ambiguous-project",
    )
    with pytest.raises(workflow.CreditAnalysisError, match="project name is ambiguous"):
        workflow.command_prepare_batch(ambiguous_request)


@pytest.mark.parametrize(
    "api_failure_event,include_descendant",
    [(None, False), (None, True), ("error", False), ("turn.failed", False)],
)
def test_credit_analysis_batch_resumes_and_preserves_every_thread_finding(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    api_failure_event: str | None,
    include_descendant: bool,
) -> None:
    workflow = load_credit_analysis_workflow_module()
    monkeypatch.setattr(
        workflow,
        "_codex_model_catalog",
        lambda: holistic_model_catalog(),
    )
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    ids = [
        "00000000-0000-4000-8000-000000000021",
        "00000000-0000-4000-8000-000000000022",
    ]
    sessions = [
        indexed_credit_analysis_session(
            codex_home,
            thread_id=thread_id,
            thread_name=f"Batch thread {index}",
            updated_at=f"2026-08-07T1{8 - index}:00:00Z",
            project_name="alpha",
        )
        for index, thread_id in enumerate(ids, start=1)
    ]
    if include_descendant:
        descendant_id = "00000000-0000-4000-8000-000000000023"
        sessions.append(indexed_credit_analysis_session(
            codex_home,
            thread_id=descendant_id,
            thread_name="Persistent child",
            updated_at="2026-08-01T00:00:00Z",
            project_name="alpha",
        ))
        _attach_persistent_descendants(
            sessions[0], child_session_ids=[descendant_id, descendant_id],
        )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    request = credit_analysis_batch_request(
        tmp_path,
        selector={
            "kind": "recent_threads",
            "count": 2,
            "days": None,
            "project": None,
        },
        name="finalize",
    )
    if include_descendant:
        # Per-session enforcement belongs to collection, before tree merging.
        collector = workflow._load_evidence_collector()
        collect = collector.collect_session_evidence_from_rows
        for index, overread_session in enumerate((sessions[0], sessions[-1])):
            def overread(*args: Any, **kwargs: Any) -> dict[str, Any]:
                result = collect(*args, **kwargs)
                if pathlib.Path(kwargs["session"]) == overread_session:
                    result["collection"]["session_reads"] = 2
                return result

            with monkeypatch.context() as faulty_collector:
                faulty_collector.setattr(
                    collector, "collect_session_evidence_from_rows", overread,
                )
                faulty_request = credit_analysis_batch_request(
                    tmp_path,
                    selector=json.loads(request.read_text(encoding="utf-8"))["selector"],
                    name=f"overread-{index}",
                )
                with pytest.raises(workflow.CreditAnalysisError, match="exactly one read"):
                    workflow.command_prepare_batch(faulty_request)
    status = workflow.command_prepare_batch(request)
    state_path = pathlib.Path(status["batch_state_path"])
    prepared_state = json.loads(state_path.read_text(encoding="utf-8"))
    prepared_items = prepared_state["items"]
    if include_descendant:
        evidence_path = pathlib.Path(prepared_items[0]["evidence_path"])
        original_evidence = evidence_path.read_bytes()
        evidence = json.loads(original_evidence)
        assert evidence["collection"]["session_reads"] == 2
        assert evidence["analysis_lineage"]["included_session_reads"] == 2
        assert len(evidence["analysis_lineage"]["included_descendant_sessions"]) == 1
    pathlib.Path(prepared_state["paths"]["manifest"]).unlink()
    prepared_state["phase"] = "preparing"
    prepared_state["candidate_index"] = 0
    prepared_state["items"] = []
    prepared_state["immutable_artifacts"]["manifest"] = None
    write_json_file(state_path, prepared_state)
    for index, session in enumerate(sessions):
        session.rename(session.with_name(f"retired-{index}.jsonl"))
    if include_descendant:
        # Recovery must reject altered evidence, then reuse the frozen tree
        # even when neither the parent nor its persistent child is available.
        evidence["collection"]["session_reads"] = 1
        write_json_file(evidence_path, evidence)
        with pytest.raises(workflow.CreditAnalysisError, match="immutable artifact changed: evidence"):
            workflow.command_prepare_batch(request)
        evidence_path.write_bytes(original_evidence)
    status = workflow.command_prepare_batch(request)
    resumed_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert resumed_state["items"] == prepared_items
    if include_descendant:
        assert evidence_path.read_bytes() == original_evidence
        return

    if api_failure_event is not None:
        runner = FakeCreditModelRunner()
        original_invoke = workflow._invoke_injected_runner
        checked_patterns: set[str] = set()

        def check_patterns(value: Any) -> None:
            if isinstance(value, dict):
                pattern = value.get("pattern")
                if isinstance(pattern, str) and pattern not in checked_patterns:
                    # Ripgrep uses a non-backtracking engine like the API's
                    # documented failure boundary. Check actual compilation.
                    compiled = subprocess.run(
                        ["rg", "--null-data", "--quiet", "--regexp", pattern],
                        input="", text=True, capture_output=True, check=False,
                    )
                    assert compiled.returncode in {0, 1}, compiled.stderr
                    checked_patterns.add(pattern)
                for child in value.values():
                    check_patterns(child)
            elif isinstance(value, list):
                for child in value:
                    check_patterns(child)

        def reject_schema(*args: Any, **kwargs: Any) -> tuple[None, dict[str, Any]]:
            _, attempt = original_invoke(*args, **kwargs)
            check_patterns(json.loads(pathlib.Path(attempt["schema_path"]).read_text(encoding="utf-8")))
            message = json.dumps({
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "code": "invalid_json_schema",
                    "message": "Invalid JSON schema: unsupported response pattern",
                    "param": "text.format.schema",
                },
                "status": 400,
            })
            event = (
                {"type": "error", "message": message}
                if api_failure_event == "error"
                else {"type": "turn.failed", "error": {"message": message}}
            )
            pathlib.Path(attempt["events_path"]).write_text(
                json.dumps(event) + "\n", encoding="utf-8",
            )
            pathlib.Path(attempt["raw_output_path"]).unlink()
            return None, {**attempt, "exit_code": 1, "error": "unrelated CLI startup warning"}

        monkeypatch.setattr(workflow, "_invoke_injected_runner", reject_schema)
        child_state = pathlib.Path(status["child_status"]["state_path"])
        with pytest.raises(workflow.CreditAnalysisError, match="invalid_json_schema"):
            workflow.command_execute_orchestration(child_state, runner=runner)
        failed = json.loads(child_state.read_text(encoding="utf-8"))
        assert checked_patterns
        assert failed["phase"] != "complete"
        assert not failed["omissions"]
        assert failed["model_attempts"]["sol"] == 0
        assert any(
            "unsupported response pattern" in attempt["error"]
            for execution in failed["execution"].values()
            for attempt in execution["attempts"]
        )
        call_count = len(runner.calls)
        with pytest.raises(workflow.CreditAnalysisError, match="invalid_json_schema"):
            workflow.command_execute_orchestration(child_state, runner=runner)
        assert len(runner.calls) == call_count
        blocked_batch = run_credit_analysis_workflow("status-batch", "--state", str(state_path))
        assert blocked_batch.returncode == 0, blocked_batch.stderr
        assert json.loads(blocked_batch.stdout)["pending_thread_id"] == ids[0]
        cli_resume = run_credit_analysis_workflow("execute", "--state", str(child_state))
        assert cli_resume.returncode == 2
        assert "invalid_json_schema" in cli_resume.stderr
        return

    first_final = complete_holistic_credit_analysis(
        workflow,
        status["child_status"],
    )
    before_recovery = json.loads(state_path.read_text(encoding="utf-8"))
    first_payload = json.loads(first_final.read_text(encoding="utf-8"))
    first_content_hash = hashlib.sha256(
        (
            json.dumps(
                first_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            + "\n"
        ).encode("utf-8")
    ).hexdigest()
    with pathlib.Path(before_recovery["paths"]["index"]).open(
        "a", encoding="utf-8", newline="\n"
    ) as handle:
        handle.write(
            json.dumps(
                {
                    "schema": "ceratops-credit-analysis-batch-index-record.v1",
                    "ordinal": 1,
                    "thread_id": ids[0],
                    "path": str(first_final.resolve()),
                    "sha256": hashlib.sha256(first_final.read_bytes()).hexdigest(),
                    "content_hash": first_content_hash,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
    recovered = run_credit_analysis_workflow(
        "status-batch", "--state", str(state_path)
    )
    assert recovered.returncode == 0, recovered.stderr
    second_status = json.loads(recovered.stdout)
    assert second_status["pending_thread_id"] == ids[1]
    idempotent = run_credit_analysis_workflow(
        "advance-batch",
        "--state",
        str(state_path),
        "--result",
        str(first_final),
    )
    assert idempotent.returncode == 0, idempotent.stderr
    assert json.loads(idempotent.stdout) == second_status
    resumed = run_credit_analysis_workflow(
        "status-batch", "--state", str(state_path)
    )
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout) == second_status

    second_final = complete_holistic_credit_analysis(
        workflow,
        second_status["child_status"],
    )
    ready = run_credit_analysis_workflow(
        "advance-batch",
        "--state",
        str(state_path),
        "--result",
        str(second_final),
    )
    assert ready.returncode == 0, ready.stderr
    summary_status = json.loads(ready.stdout)
    assert summary_status["pending_phase"] == "batch-summary"
    summary_path = pathlib.Path(summary_status["required_result_path"])
    summary_context_path = pathlib.Path(summary_status["context_path"])
    assert summary_path.name == "batch-summary.json"
    context = json.loads(summary_context_path.read_text(encoding="utf-8"))
    batch_finding_ids = [item["batch_finding_id"] for item in context["findings"]]
    child_finding_ids = [
        "sol.adjudication.0001.finding-model-1",
        "sol.adjudication.0001.finding-volume-2",
    ]
    assert batch_finding_ids == [
        *[f"{ids[0]}:{finding_id}" for finding_id in child_finding_ids],
        *[f"{ids[1]}:{finding_id}" for finding_id in child_finding_ids],
    ]
    assert all(item["problem_summary"] for item in context["findings"])
    assert [item["thread_id"] for item in context["thread_totals"]] == ids
    assert "call_inventory" not in context
    assert context["result_contract"]["fields"] == [
        "batch_id",
        "pass_id",
        "finding_fingerprint",
        "artifact_paths",
        "groups",
    ]
    resumed_summary = run_credit_analysis_workflow(
        "status-batch", "--state", str(state_path)
    )
    assert resumed_summary.returncode == 0, resumed_summary.stderr
    assert json.loads(resumed_summary.stdout) == summary_status
    premature = run_credit_analysis_workflow(
        "finalize-batch", "--state", str(state_path)
    )
    assert premature.returncode == 2
    assert "batch summary is not accepted" in premature.stderr

    summary = {
        "batch_id": summary_status["batch_id"],
        "pass_id": summary_status["pass_id"],
        "finding_fingerprint": context["finding_fingerprint"],
        "artifact_paths": context["artifact_paths"],
        "groups": [
            {
                "id": "shared-holistic-control",
                "title": "Shared holistic control",
                "producer_type": "workflow",
                "owner": "workflow:synthetic",
                "finding_ids": batch_finding_ids,
                "recommended_control": context["findings"][0][
                    "proposed_durable_control"
                ],
                "material_variants": [],
                "confidence": 0.9,
            }
        ],
    }
    assert "schema" not in summary
    assert "version" not in summary
    write_json_file(
        summary_path,
        {**summary, "finding_fingerprint": "stale-fingerprint"},
    )
    stale = run_credit_analysis_workflow(
        "advance-batch",
        "--state",
        str(state_path),
        "--result",
        str(summary_path),
    )
    assert stale.returncode == 2
    assert "finding_fingerprint does not match" in stale.stderr
    write_json_file(
        summary_path,
        {
            **summary,
            "groups": [
                {
                    **summary["groups"][0],
                    "finding_ids": batch_finding_ids[:1],
                }
            ],
        },
    )
    incomplete = run_credit_analysis_workflow(
        "advance-batch",
        "--state",
        str(state_path),
        "--result",
        str(summary_path),
    )
    assert incomplete.returncode == 2
    assert "partition every finding exactly once" in incomplete.stderr
    write_json_file(summary_path, summary)
    accepted = run_credit_analysis_workflow(
        "advance-batch",
        "--state",
        str(state_path),
        "--result",
        str(summary_path),
    )
    assert accepted.returncode == 0, accepted.stderr
    ready_to_finalize = json.loads(accepted.stdout)
    assert ready_to_finalize["ready_to_finalize"] is True
    assert ready_to_finalize["batch_summary_result_path"] == str(summary_path)
    idempotent_summary = run_credit_analysis_workflow(
        "advance-batch",
        "--state",
        str(state_path),
        "--result",
        str(summary_path),
    )
    assert idempotent_summary.returncode == 0, idempotent_summary.stderr
    assert json.loads(idempotent_summary.stdout) == ready_to_finalize
    write_json_file(
        summary_path,
        {
            **summary,
            "groups": [
                {**summary["groups"][0], "title": "Conflicting summary"}
            ],
        },
    )
    conflict = run_credit_analysis_workflow(
        "advance-batch",
        "--state",
        str(state_path),
        "--result",
        str(summary_path),
    )
    assert conflict.returncode == 2
    assert "accepted batch summary changed" in conflict.stderr
    write_json_file(summary_path, summary)
    finalized = run_credit_analysis_workflow(
        "finalize-batch", "--state", str(state_path)
    )
    assert finalized.returncode == 0, finalized.stderr
    assert finalized.stdout.strip() == "OK"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    final = json.loads(
        pathlib.Path(state["final_result"]["path"]).read_text(encoding="utf-8")
    )
    assert "schema" not in final
    assert "version" not in final
    assert [item["thread_id"] for item in final["confirmed_findings"]] == [
        ids[0],
        ids[0],
        ids[1],
        ids[1],
    ]
    assert [item["finding"]["id"] for item in final["confirmed_findings"]] == [
        *child_finding_ids,
        *child_finding_ids,
    ]
    assert [item["thread_id"] for item in final["per_thread_totals"]] == ids
    assert len(final["summary_groups"]) == 1
    group = final["summary_groups"][0]
    assert group["id"] == "shared-holistic-control"
    assert [item["batch_finding_id"] for item in group["findings"]] == (
        batch_finding_ids
    )
    assert group["threads"] == ids
    assert group["contributing_surfaces"] == json.loads(
        CREDIT_ANALYSIS_CONTRACT.read_text(encoding="utf-8")
    )["surface_order"]
    assert group["deduplicated_avoidable_call_count"] == 6
    assert len(group["affected_calls"]) == 6
    assert final["totals"]["analyzed_threads"] == 2
    assert final["totals"]["session_collections"] == 2
    assert final["totals"]["avoidable_calls"] == 6
    assert "grouped only for presentation" in final["scope_limitation"]
    assert len(
        pathlib.Path(state["paths"]["index"]).read_text(encoding="utf-8").splitlines()
    ) == 2
    assert state["cleanup"]["transient_paths"] == [str(summary_context_path)]
    assert not summary_context_path.exists()
    assert summary_path.is_file()
    assert final["retained_paths"]["batch_summary_result"] == str(summary_path)
    for item in state["items"]:
        child_root = pathlib.Path(item["state_path"]).parent
        assert (child_root / "orchestration").is_dir()
        assert not (child_root / "orchestration" / "transient").exists()
        assert pathlib.Path(item["request_path"]).is_file()
        assert pathlib.Path(item["evidence_path"]).is_file()
    complete = run_credit_analysis_workflow(
        "status-batch", "--state", str(state_path)
    )
    assert complete.returncode == 0, complete.stderr
    assert json.loads(complete.stdout)["complete"] is True


def _exercise_corrective_cli(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, defect: str,
) -> None:
    """Exercise public CLI routing, queue, feedback, validation and checkpoints.

    Only model transport is injected; no live model or API call is permitted.
    pytest owns and removes the synthetic session and retained attempt files.
    """
    workflow = load_credit_analysis_workflow_module()
    from credit_analysis import luna_sol_analysis as analysis
    from credit_analysis import orchestration_execution as execution

    request, _, _ = credit_analysis_request(tmp_path, extra_completed_turns=1)
    plan = workflow.command_plan_orchestration(request, available_models=holistic_model_catalog())
    state_path = pathlib.Path(plan["state_path"])

    class CorrectingRunner(FakeCreditModelRunner):
        def __init__(self) -> None:
            super().__init__()
            self.target: str | None = None
            self.responses: list[dict[str, Any]] = []
            self.feedback: dict[str, Any] | None = None
            self.withdrawn: str | None = None

        def run(self, **kwargs: Any) -> dict[str, Any]:
            raw = super().run(**kwargs)
            task = kwargs["task"]
            phase = "sol-adjudication" if defect in {"foreign-call", "withdraw", "withdraw-temporary"} else "sol-final"
            eligible = True
            if defect in {"withdraw", "withdraw-temporary"}:
                eligible = sum(item["waste_kind"] == "model-calls" for item in raw.get("confirmed_findings", [])) >= 2
                if defect == "withdraw-temporary":
                    eligible = eligible and any(item["id"].endswith("temporary-control-gap") for item in raw.get("confirmed_findings", []))
            if task["phase"] == phase and self.target is None and eligible:
                self.target = task["task_id"]
            if task["task_id"] != self.target:
                return raw
            findings = [item for item in raw["confirmed_findings"] if item["waste_kind"] == "model-calls"]
            assert len(findings) >= (1 if defect == "foreign-call" else 2)
            selected = next((item for item in findings if item["id"].endswith("temporary-control-gap")), findings[0]) if defect == "withdraw-temporary" else findings[0]
            if not self.responses:
                if defect == "foreign-call":
                    aliases = analysis._holistic_read_sol_aliases(task, kwargs["input_sha256"])
                    calls = aliases["aliases"]["calls"]
                    allowed = kwargs["schema"]["properties"]["confirmed_findings"]["items"]["properties"]["affected_call_ids"]["items"]["enum"]
                    assert {calls[item] for item in allowed} == set(task["call_ids"])
                    foreign = next(value for value in calls.values() if value not in task["call_ids"])
                    raw["call_classifications"][0]["call_ids"].append(foreign)
                elif defect == "malformed":
                    raw["call_classifications"] = None
                elif defect == "conflict":
                    groups = []
                    for group in raw["call_classifications"]:
                        for identity in group["call_ids"]:
                            part = {**group, "call_ids": [identity]}
                            if identity in selected["affected_call_ids"]:
                                part.update(classification="reviewed_no_confirmed_waste", reason_code=None)
                            groups.append(part)
                    raw["call_classifications"] = groups
                else:
                    targets = findings[:2] if defect in {"estimate", "final-estimate"} else [selected]
                    for finding in targets:
                        recurrence = finding["recurrence"]
                        recurrence["additional_recurring_calls_per_affected_run"] = recurrence["calls_saved_per_affected_run"]
            else:
                self.feedback = json.loads(kwargs["prompt"].split("\nCorrection request:\n", 1)[1])
                if defect in {"withdraw", "withdraw-temporary"}:
                    self.withdrawn = selected["id"]
                    raw["confirmed_findings"] = [item for item in raw["confirmed_findings"] if item["id"] != self.withdrawn]
                    for decision in raw["candidate_decisions"]:
                        if self.withdrawn in decision["finding_ids"]:
                            decision["finding_ids"].remove(self.withdrawn)
                            decision["disposition"] = "confirmed-finding" if decision["finding_ids"] else "plausible-risk" if decision["risk_ids"] else "dismissed-candidate"
                            decision["reason"] = "Retained evidence does not support positive recurring savings."
                    for review in raw["temporary_control_reviews"]:
                        if review["finding_id"] == self.withdrawn:
                            review["finding_id"] = None
                            review["no_finding_reason"] = "Positive savings remain unconfirmed."
                    raw["temporary_control_merges"] = [item for item in raw["temporary_control_merges"] if item["finding_id"] != self.withdrawn]
                elif defect == "protected":
                    other = next(item for item in findings if item["id"] != selected["id"])
                    other["recurrence"]["calls_saved_per_affected_run"] += 3
                elif defect == "estimate":
                    # Regrouping carries no new judgment and must not break repair.
                    raw["call_classifications"] = [
                        {**group, "call_ids": [identity]}
                        for group in reversed(raw["call_classifications"])
                        for identity in reversed(group["call_ids"])
                    ]
            self.responses.append(copy.deepcopy(raw))
            return raw

    runner = CorrectingRunner()
    original = execution._holistic_model_attempt

    def model_boundary(**kwargs: Any) -> Any:
        kwargs["runner"] = runner
        return original(**kwargs)

    monkeypatch.setattr(execution, "_holistic_model_attempt", model_boundary)
    output, errors = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        exit_code = workflow.main(["execute", "--state", str(state_path)])
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert runner.target is not None
    target = saved["execution"][runner.target]
    attempts = target["attempts"]
    assert len(attempts) == 2, (errors.getvalue(), attempts)
    assert attempts[0]["outcome"] == "validation-error"
    assert runner.feedback is not None
    scope = runner.feedback["correction_scope"]
    if defect in {"estimate", "final-estimate"}:
        assert len(scope["invalid_recurrence_finding_ids"]) == 2
    if defect == "conflict":
        assert len(scope["conflicting_call_finding_ids"]) >= 1
    if defect == "protected":
        assert attempts[1]["outcome"] == "validation-error"
        assert "protected response field" in attempts[1]["error"]
        assert target["status"] == "pending"
        assert exit_code != 0
    else:
        assert attempts[1]["outcome"] == "accepted", (errors.getvalue(), attempts)
        accepted = json.loads(pathlib.Path(target["result"]["path"]).read_text(encoding="utf-8"))
        assert len(accepted["candidate_decisions"]) == len(runner.responses[0]["candidate_decisions"])
        if runner.withdrawn:
            assert runner.withdrawn not in {item["id"] for item in accepted["confirmed_findings"]}
            assert len(accepted["confirmed_findings"]) == len(runner.responses[0]["confirmed_findings"]) - 1
            assert len(accepted["temporary_control_reviews"]) == len(runner.responses[0]["temporary_control_reviews"])
        assert exit_code == 0, errors.getvalue()
    before = len(runner.calls)
    workflow.command_execute_orchestration(state_path, runner=runner, task_limit=0)
    assert len(runner.calls) == before
    assert max(len(item["attempts"]) for item in saved["execution"].values()) <= 2
