from __future__ import annotations

import hashlib
import json
import pathlib
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
    canonical_credit_task_root,
    credit_analysis_batch_request,
    credit_analysis_request,
    indexed_credit_analysis_session,
    write_json_file,
)
from tests.credit_analysis.workflow import run_credit_analysis_workflow


@pytest.mark.parametrize(
    "action",
    [
        "helper-contracts",
        "context-evidence",
        "rework-validation",
        "tool-flow",
        "instruction-reasoning",
    ],
)
def test_credit_analysis_workflow_each_surface_is_independently_callable(
    tmp_path: pathlib.Path,
    action: str,
) -> None:
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
    assert plan["projected_semantic_calls"] == 2
    complete = workflow.command_execute_orchestration(
        pathlib.Path(plan["state_path"]),
        runner=runner,
        available_models=runner.available_models,
    )
    assert complete["complete"] is True
    assert [call["phase"] for call in runner.calls] == [
        "luna-discovery",
        "sol-adjudication",
    ]
    assert "supplied fixed lenses" in runner.calls[0]["prompt"]
    assert "every supplied surface section" in runner.calls[1]["prompt"]
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
                "expected_surface_contract_version": 5,
                "mutation_authority": False,
            },
        )
        return request

    current = run_credit_analysis_workflow(
        "prepare",
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
        "prepare",
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
        "prepare",
        "--request",
        str(request_for("ambiguous", {"thread_name": "Named Thread"})),
    )
    assert ambiguous.returncode == 2
    assert "ambiguous" in ambiguous.stderr

    monkeypatch.delenv("CODEX_THREAD_ID")
    missing_current = run_credit_analysis_workflow(
        "prepare",
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
                "ceratops-credit-analysis-orchestration-state.v4"
            )
            assert child_state["manifest"]["projected_semantic_calls"] == 2
            assert child_state["task_order"] == [
                "luna.discovery.0001",
                "sol.adjudication",
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


def test_credit_analysis_batch_resumes_and_preserves_every_thread_finding(
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
    status = workflow.command_prepare_batch(request)
    state_path = pathlib.Path(status["batch_state_path"])
    prepared_state = json.loads(state_path.read_text(encoding="utf-8"))
    prepared_items = prepared_state["items"]
    pathlib.Path(prepared_state["paths"]["manifest"]).unlink()
    prepared_state["phase"] = "preparing"
    prepared_state["candidate_index"] = 0
    prepared_state["items"] = []
    prepared_state["immutable_artifacts"]["manifest"] = None
    write_json_file(state_path, prepared_state)
    for index, session in enumerate(sessions):
        session.rename(session.with_name(f"retired-{index}.jsonl"))
    status = workflow.command_prepare_batch(request)
    resumed_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert resumed_state["items"] == prepared_items

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
    assert batch_finding_ids == [
        f"{ids[0]}:finding-model-1",
        f"{ids[0]}:finding-volume-2",
        f"{ids[1]}:finding-model-1",
        f"{ids[1]}:finding-volume-2",
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
        "finding-model-1",
        "finding-volume-2",
        "finding-model-1",
        "finding-volume-2",
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
    assert group["deduplicated_avoidable_call_count"] == 2
    assert len(group["affected_calls"]) == 2
    assert final["totals"]["analyzed_threads"] == 2
    assert final["totals"]["session_collections"] == 2
    assert final["totals"]["avoidable_calls"] == 2
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
