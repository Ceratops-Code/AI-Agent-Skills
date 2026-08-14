from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

import pytest

from tests.credit_analysis.models import (
    FakeCreditModelRunner,
    holistic_model_catalog,
    load_credit_analysis_workflow_module,
)
from tests.credit_analysis.paths import (
    CREDIT_ANALYSIS_CONTRACT,
)
from tests.credit_analysis.sessions import (
    credit_analysis_request,
    finding_record,
    surface_result_record,
    write_json_file,
)
from tests.credit_analysis.workflow import run_credit_analysis_workflow


def test_bounded_largest_runs_selection_uses_anchor_size_and_positional_successors() -> None:
    workflow = load_credit_analysis_workflow_module()
    inventory = [
        {"turn_id": "a", "original_order": 1, "evidence_chars": 100},
        {"turn_id": "b", "original_order": 2, "evidence_chars": 1},
        {"turn_id": "c", "original_order": 3, "evidence_chars": 90},
        {"turn_id": "d", "original_order": 4, "evidence_chars": 80},
    ]

    def fits(_: list[str]) -> dict[str, Any]:
        return {"fits": True, "luna": {"fits": True}, "sol": {"fits": True}}

    selection = workflow._bounded_select_run_bundles(inventory, fits)

    # Anchor a ranks before c even though c+d is the larger pair. Its tiny
    # positional follower b remains indivisible from a.
    assert [row["turn_id"] for row in selection["anchor_order"]] == [
        "a",
        "c",
        "d",
        "b",
    ]
    assert selection["selected_bundles"][0] == {
        "anchor_rank": 1,
        "anchor_turn_id": "a",
        "companion_turn_id": "b",
    }
    # Companion b later acts as an anchor and still brings successor c. The
    # final run d also remains a valid anchor without a successor.
    assert selection["selected_bundles"][-1] == {
        "anchor_rank": 4,
        "anchor_turn_id": "b",
        "companion_turn_id": "c",
    }
    assert any(
        row["anchor_turn_id"] == "d" and row["companion_turn_id"] is None
        for row in selection["selected_bundles"]
    )
    assert selection["selected_run_ids"] == ["a", "b", "c", "d"]


def test_bounded_largest_runs_capacity_blocks_initial_bundle_and_skips_later() -> None:
    workflow = load_credit_analysis_workflow_module()
    inventory = [
        {
            "turn_id": turn_id,
            "episode_id": f"episode.{turn_id}",
            "original_order": order,
            "started_at": f"2026-08-01T00:00:0{order}Z",
            "evidence_chars": size,
            "candidate_count": 1,
        }
        for order, (turn_id, size) in enumerate(
            [("a", 100), ("b", 1), ("c", 90), ("d", 1), ("e", 2)],
            start=1,
        )
    ]
    evaluated: list[list[str]] = []

    def capacity(selected_ids: list[str]) -> dict[str, Any]:
        evaluated.append(list(selected_ids))
        selected_size = sum(
            row["evidence_chars"]
            for row in inventory
            if row["turn_id"] in set(selected_ids)
        )
        fits = selected_size <= 103
        return {
            "fits": fits,
            "luna": {
                "fits": fits,
                "planned_input_chars": selected_size,
                "input_char_capacity": 103,
                "output_reserve_tokens": 1,
            },
            "sol": {
                "fits": fits,
                "planned_input_chars": selected_size,
                "input_char_capacity": 103,
                "output_reserve_tokens": 1,
            },
        }

    selection = workflow._bounded_select_run_bundles(inventory, capacity)
    repeated = workflow._bounded_select_run_bundles(inventory, capacity)
    assert selection == repeated
    assert [row["anchor_turn_id"] for row in selection["selected_bundles"]] == [
        "a",
        "e",
    ]
    assert selection["skipped_bundles"][0]["anchor_turn_id"] == "c"
    assert selection["selected_run_ids"] == ["a", "b", "e"]

    manifest = workflow._bounded_selection_document(
        analysis_id="analysis-selection",
        run_inventory=inventory,
        selection=selection,
    )
    assert manifest["coverage"] == {
        "selected_anchor_count": 2,
        "companion_count": 1,
        "unique_selected_runs": 3,
        "total_eligible_runs": 5,
        "selected_evidence_chars": 103,
        "total_evidence_chars": 194,
        "coverage_percentage": 53.09,
    }
    assert [row["turn_id"] for row in manifest["omitted_runs"]] == ["c", "d"]
    assert all(
        set(row) == {
            "turn_id",
            "original_order",
            "evidence_chars",
            "candidate_count",
        }
        for row in manifest["omitted_runs"]
    )

    initial_evaluations: list[list[str]] = []
    model_calls: list[str] = []

    def initial_too_large(selected_ids: list[str]) -> dict[str, Any]:
        initial_evaluations.append(list(selected_ids))
        return {"fits": False}

    with pytest.raises(
        workflow.CreditAnalysisError,
        match="capacity blocker: the largest anchor and its immediate successor",
    ):
        workflow._bounded_select_run_bundles(inventory, initial_too_large)
    assert initial_evaluations == [["a", "b"]]
    assert model_calls == []


def test_bounded_largest_runs_plan_reports_coverage_and_resumes_idempotently(
    tmp_path: pathlib.Path,
) -> None:
    workflow = load_credit_analysis_workflow_module()
    request, session_path, _ = credit_analysis_request(
        tmp_path,
        action="bounded-largest-runs-analysis",
    )
    catalog = holistic_model_catalog()
    plan = workflow.command_plan_orchestration(
        request,
        available_models=catalog,
    )

    assert plan["action"] == "bounded-largest-runs-analysis"
    assert plan["mode"] == "bounded-largest-runs-analysis"
    assert plan["analysis_scope_label"] == "bounded largest-runs analysis"
    assert plan["projected_luna_calls"] == 1
    assert plan["projected_sol_calls"] == 1
    assert plan["projected_semantic_calls"] == 2
    manifest = json.loads(
        pathlib.Path(plan["manifest_path"]).read_text(encoding="utf-8")
    )
    selection_path = pathlib.Path(manifest["selection_manifest"]["path"])
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    compact = json.loads(
        pathlib.Path(manifest["compact_evidence"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    assert len(manifest["luna_tasks"]) == 1
    assert selection["coverage"] == plan["selection_coverage"]
    assert selection["coverage"]["unique_selected_runs"] <= selection["coverage"][
        "total_eligible_runs"
    ]
    assert selection["coverage"]["selected_evidence_chars"] <= selection[
        "coverage"
    ]["total_evidence_chars"]
    for role in ("luna", "sol"):
        proof = selection["budget_proof"][role]
        assert proof["fits"] is True
        assert proof["planned_input_chars"] <= proof["input_char_capacity"]
        assert proof["output_reserve_tokens"] > 0
    assert selection["budget_proof"]["sol"][
        "maximum_accepted_luna_output_chars"
    ] > 0
    assert [row["turn_id"] for row in selection["selected_runs"]] == [
        episode["turn_id"] for episode in compact["episodes"]
    ]
    assert [row["started_at"] for row in selection["selected_runs"]] == [
        episode["started_at"] for episode in compact["episodes"]
    ]
    assert all(
        set(row) == {
            "turn_id",
            "original_order",
            "evidence_chars",
            "candidate_count",
        }
        for row in selection["omitted_runs"]
    )

    retained_evidence = pathlib.Path(plan["evidence_path"]).read_bytes()
    session_path.rename(session_path.with_suffix(".collected"))
    runner = FakeCreditModelRunner(temporary_controls=False)
    state_path = pathlib.Path(plan["state_path"])
    after_luna = workflow.command_execute_orchestration(
        state_path,
        runner=runner,
        available_models=runner.available_models,
        task_limit=1,
    )
    assert after_luna["next_task"] == "sol.adjudication"
    completed = workflow.command_execute_orchestration(
        state_path,
        runner=runner,
        available_models=runner.available_models,
    )
    assert completed["complete"] is True
    assert len(runner.calls) == 2
    assert [call["phase"] for call in runner.calls] == [
        "luna-discovery",
        "sol-adjudication",
    ]
    assert "bounded largest-runs analysis" in runner.calls[-1]["prompt"]
    assert "selected_original_evidence" in runner.calls[-1]["input_payload"]
    assert "selection_coverage" in runner.calls[-1]["input_payload"]
    assert pathlib.Path(plan["evidence_path"]).read_bytes() == retained_evidence

    final = json.loads(
        pathlib.Path(completed["final_result_path"]).read_text(encoding="utf-8")
    )
    report = pathlib.Path(completed["report_path"]).read_text(encoding="utf-8")
    assert final["analysis_scope_label"] == "bounded largest-runs analysis"
    assert final["selection_coverage"] == selection["coverage"]
    assert final["deterministic_totals"]["model_calls"] == len(
        manifest["candidate_ids"]
    )
    assert report.startswith("Bounded largest-runs analysis.\n")
    assert "Omitted runs were not reviewed" in report
    assert "# Selected-call accounting" in report

    accepted_call_count = len(runner.calls)
    repeated_status = workflow.command_execute_orchestration(
        state_path,
        runner=runner,
        available_models=runner.available_models,
    )
    assert repeated_status["complete"] is True
    assert len(runner.calls) == accepted_call_count
    assert pathlib.Path(plan["evidence_path"]).read_bytes() == retained_evidence

    run_base = tmp_path / "end-to-end-run"
    run_base.mkdir()
    run_request, run_session, _ = credit_analysis_request(
        run_base,
        action="bounded-largest-runs-analysis",
    )
    run_runner = FakeCreditModelRunner(temporary_controls=False)

    def unexpected_catalog_read() -> dict[str, dict[str, Any]]:
        raise AssertionError("injected runner catalog should be reused")

    workflow._codex_model_catalog = unexpected_catalog_read
    paused = workflow.command_run_orchestration(
        run_request,
        runner=run_runner,
        task_limit=1,
    )
    assert paused["next_task"] == "sol.adjudication"
    assert len(run_runner.calls) == 1
    run_evidence = pathlib.Path(paused["evidence_path"])
    retained_run_evidence = run_evidence.read_bytes()
    run_session.rename(run_session.with_suffix(".collected"))

    run_completed = workflow.command_run_orchestration(
        run_request,
        runner=run_runner,
    )
    assert run_completed["complete"] is True
    assert [call["phase"] for call in run_runner.calls] == [
        "luna-discovery",
        "sol-adjudication",
    ]
    assert run_evidence.read_bytes() == retained_run_evidence

    repeated_run = workflow.command_run_orchestration(
        run_request,
        runner=run_runner,
    )
    assert repeated_run["complete"] is True
    assert len(run_runner.calls) == 2
    assert run_evidence.read_bytes() == retained_run_evidence

    copied_request = run_base / "copied-request.json"
    write_json_file(
        copied_request,
        json.loads(run_request.read_text(encoding="utf-8")),
    )
    with pytest.raises(
        workflow.CreditAnalysisError,
        match="request does not own the existing orchestration state",
    ):
        workflow.command_run_orchestration(
            copied_request,
            runner=run_runner,
        )
    assert len(run_runner.calls) == 2
    assert workflow.build_parser().parse_args(
        ["run", "--request", str(run_request)]
    ).command == "run"


def test_credit_analysis_workflow_full_analysis_persists_every_finding(
    tmp_path: pathlib.Path,
) -> None:
    request, session, task_root = credit_analysis_request(tmp_path)
    prepared = run_credit_analysis_workflow("prepare", "--request", str(request))
    assert prepared.returncode == 0, prepared.stderr
    status = json.loads(prepared.stdout)
    assert status["pending_surface"] == "helper-contracts"
    state_path = pathlib.Path(status["state_path"])
    evidence = json.loads(pathlib.Path(status["evidence_path"]).read_text(encoding="utf-8"))
    collection = evidence["collection"]
    assert {
        key: collection[key]
        for key in (
            "session_reads",
            "completed_runs",
            "model_calls",
            "user_messages",
        )
    } == {
        "session_reads": 1,
        "completed_runs": 3,
        "model_calls": 6,
        "user_messages": 3,
    }
    assert evidence["redaction"] == {
        "method": "pattern-based-replacement",
        "targets": [
            "credential-like-values",
            "user-profile-roots",
            "local-paths",
        ],
        "complete_secret_detection_guaranteed": False,
        "semantic_classification": "none",
    }
    model_review = evidence["model_review"]
    assert collection["model_review_records"] == len(model_review["records"])
    assert model_review["preparation"] == {
        "name": "prepared-model-review-evidence",
        "transformations": [
            "credential-pattern-replacement",
            "workspace-path-normalization",
            "external-path-withholding",
            "binary-body-hashing",
            "structured-normalization",
        ],
        "full_prepared_content_retained": True,
        "private_reasoning_collected": False,
        "duplicate_ui_messages_collected": False,
        "complete_secret_detection_guaranteed": False,
        "semantic_classification": "none",
    }
    record_ids = [record["record_id"] for record in model_review["records"]]
    assert len(record_ids) == len(set(record_ids))
    review_text = json.dumps(model_review, sort_keys=True)
    for sentinel in (
        "BASE_CONTROL_SENTINEL",
        "WORLD_STATE_CONTROL_SENTINEL",
        "COMPACTION_CONTEXT_SENTINEL",
        "DEVELOPER_CONTROL_SENTINEL",
        "ASSISTANT_ANSWER_SENTINEL",
        "TOOL_RESULT_TAIL_SENTINEL",
    ):
        assert sentinel in review_text
    assert "PRIVATE_REASONING_SENTINEL" not in review_text
    assert "inactive history must not be copied" not in review_text
    assert model_review["excluded_by_design"] == {
        "binary_bodies_hashed": 0,
        "private_reasoning_records_excluded": 1,
        "duplicate_ui_message_events_excluded": 0,
        "compaction_history_items_not_copied": 1,
    }
    tool_call_record = next(
        record
        for record in model_review["records"]
        if record["kind"] == "tool-call" and record["call_id"] == "read-1"
    )
    assert "<workspace:" in json.dumps(tool_call_record["content"])
    assert any(
        reference["kind"] == "workspace"
        and reference["workspace_relative_paths_resolvable"] is True
        for reference in model_review["canonical_path_references"]
    )
    assert "private" in json.dumps(tool_call_record["content"])
    tool_result_record = next(
        record
        for record in model_review["records"]
        if record["kind"] == "tool-result" and record["call_id"] == "read-1"
    )
    assert tool_result_record["available_to_model_call_index"] == 2
    assert "TOOL_RESULT_TAIL_SENTINEL" in json.dumps(
        tool_result_record["content"]
    )
    assert tool_result_record["preview_truncated"] is True
    assert "TOOL_RESULT_TAIL_SENTINEL" in tool_result_record["preview"]
    assert tool_result_record["record_id"] in model_review["call_record_ids"][
        "turn-1"
    ]["1"]
    assert tool_result_record["record_id"] in model_review["call_record_ids"][
        "turn-1"
    ]["2"]
    first_message = evidence["runs"][0]["user_messages"][0]
    assert "correct the earlier plan" in first_message["text"]
    assert "apply my approval" in first_message["text"]
    assert "<local-path>" in first_message["text"]
    assert "<redacted>" in first_message["text"]
    assert "kind" not in first_message
    assert evidence["runs"][0]["calls"][1]["user_message_ids"] == [
        first_message["message_id"]
    ]
    assert evidence["semantic_coverage"]["run_ids"] == [
        "turn-1",
        "turn-2",
        "turn-3",
    ]
    assert evidence["semantic_coverage"]["covered_percent"] == 100.0
    fingerprint = evidence["evidence_fingerprint"]
    session.rename(tmp_path / "session-collected-once.jsonl")

    contract = json.loads(CREDIT_ANALYSIS_CONTRACT.read_text(encoding="utf-8"))
    helper_categories = contract["helper_categories"]
    helper_finding = finding_record(
        "helper-gap",
        ["turn-1:1", "turn-1:2"],
        producer_type="script",
        owner="scripts/run-helper.py",
        helper_categories=[
            "missing-dependency-handling",
            "insufficient-error-handling",
        ],
    )
    context_finding = finding_record(
        "context-gap",
        ["turn-1:2"],
        producer_type="skill",
        owner="skills/example/SKILL.md",
        complexity="Minimal",
    )
    rework_finding = finding_record(
        "rework-gap",
        ["turn-1:1", "turn-1:2"],
        producer_type="script",
        owner="scripts/run-helper.py",
    )
    instruction_finding = finding_record(
        "instruction-gap",
        ["turn-1:3"],
        producer_type="prompt",
        owner="request prompt",
        status="implemented",
    )
    volume_finding = finding_record(
        "oversized-tool-output",
        ["turn-1:1"],
        producer_type="tool-choice",
        owner="synthetic command",
        waste_kind="context-volume",
        complexity="Minimal",
    )
    expected_order = [
        "helper-contracts",
        "context-evidence",
        "rework-validation",
        "tool-flow",
        "instruction-reasoning",
        "synthesis",
    ]
    observed_order: list[str] = []
    first_result: dict[str, Any] | None = None
    first_result_path: pathlib.Path | None = None

    while status["pending_surface"] != "synthesis":
        surface = status["pending_surface"]
        observed_order.append(surface)
        context = json.loads(pathlib.Path(status["context_path"]).read_text(encoding="utf-8"))
        assert context["model_review_preparation"] == model_review["preparation"]
        assert context["model_review_records"]
        assert all(
            "content" not in record
            and record["evidence_ref"].startswith("evidence://review/")
            and record["full_content_retained"] is True
            for record in context["model_review_records"]
        )
        if surface == "helper-contracts":
            projected_tool_result = next(
                record
                for record in context["model_review_records"]
                if record["kind"] == "tool-result"
                and record["call_id"] == "read-1"
            )
            assert projected_tool_result["context_content_mode"] == "preview"
            assert "TOOL_RESULT_TAIL_SENTINEL" in projected_tool_result[
                "context_content"
            ]
        if surface == "instruction-reasoning":
            assert [
                message["message_id"] for message in context["user_messages"]
            ] == [
                "turn-1:user:1",
                "turn-2:user:1",
                "turn-3:user:1",
            ]
            assert all("kind" not in message for message in context["user_messages"])
            assert all(
                call["user_message_ids"]
                for call in context["candidate_evidence"]
            )
        kwargs: dict[str, Any] = {}
        if surface == "helper-contracts":
            reviews = [
                {
                    "category": category,
                    "status": (
                        "applies"
                        if category in helper_finding["helper_categories"]
                        else "not-applicable"
                    ),
                    "finding_ids": (
                        ["helper-gap"]
                        if category in helper_finding["helper_categories"]
                        else []
                    ),
                    "reason": "reviewed synthetic helper contract",
                }
                for category in helper_categories
            ]
            kwargs = {
                "findings": [helper_finding],
                "exclusions": [
                    {
                        "call_id": "turn-2:1",
                        "reason_code": "protocol-overhead",
                        "reason": "required wait protocol",
                    }
                ],
                "helper_reviews": reviews,
                "remediation_groups": [
                    {
                        "owner": "scripts/run-helper.py",
                        "finding_ids": ["helper-gap"],
                        "proposed_control": "compose dependency and error checks",
                        "targeted_verification": ["verify-helper-gap"],
                    }
                ],
            }
        elif surface == "context-evidence":
            kwargs = {"findings": [context_finding]}
        elif surface == "rework-validation":
            kwargs = {"findings": [rework_finding]}
        elif surface == "tool-flow":
            kwargs = {
                "findings": [volume_finding],
                "risks": [
                    {
                        "id": "tool-poll-risk",
                        "description": "wait may have been avoidable",
                        "observed_sequence": (
                            "The workflow waited after the external result was available."
                        ),
                        "competing_explanations": [
                            "The wait was unnecessary because completion was already visible.",
                            "The wait was required because completion had not propagated yet.",
                        ],
                        "missing_fact": (
                            "The retained timestamps do not show when completion became visible"
                        ),
                        "affected_call_ids": ["turn-2:1"],
                        "evidence_refs": ["evidence://calls/turn-2:1"],
                        "verification_needed": ["verify external completion timing"],
                    }
                ],
                "exclusions": [
                    {
                        "call_id": "turn-2:1",
                        "reason_code": "protocol-overhead",
                        "reason": "required conversational wait protocol",
                    }
                ],
            }
        else:
            kwargs = {
                "findings": [instruction_finding],
                "exclusions": [
                    {
                        "call_id": call_id,
                        "reason_code": "required-workflow",
                        "reason": "required final answers",
                    }
                    for call_id in ("turn-2:2", "turn-3:1")
                ],
            }
        result = surface_result_record(status, context, fingerprint, **kwargs)
        result_path = pathlib.Path(status["required_result_path"])
        if surface == "helper-contracts":
            malformed_finding = dict(helper_finding)
            malformed_finding.pop("problem_summary")
            write_json_file(
                result_path,
                {**result, "confirmed_findings": [malformed_finding]},
            )
            malformed = run_credit_analysis_workflow(
                "advance",
                "--state",
                str(state_path),
                "--result",
                str(result_path),
            )
            assert malformed.returncode == 2
            assert "missing problem_summary" in malformed.stderr
        write_json_file(result_path, result)
        advanced = run_credit_analysis_workflow(
            "advance",
            "--state",
            str(state_path),
            "--result",
            str(result_path),
        )
        assert advanced.returncode == 0, advanced.stderr
        next_status = json.loads(advanced.stdout)
        resumed = run_credit_analysis_workflow("status", "--state", str(state_path))
        assert resumed.returncode == 0, resumed.stderr
        assert json.loads(resumed.stdout) == next_status
        if surface == "helper-contracts":
            first_result = result
            first_result_path = result_path
            idempotent = run_credit_analysis_workflow(
                "advance",
                "--state",
                str(state_path),
                "--result",
                str(result_path),
            )
            assert idempotent.returncode == 0, idempotent.stderr
            assert json.loads(idempotent.stdout) == next_status
            conflicting = task_root / "conflicting-helper-result.json"
            conflict_value = {**result, "confirmed_findings": [{**helper_finding, "title": "changed"}]}
            write_json_file(conflicting, conflict_value)
            rejected = run_credit_analysis_workflow(
                "advance",
                "--state",
                str(state_path),
                "--result",
                str(conflicting),
            )
            assert rejected.returncode == 2
            assert "conflicting resubmission" in rejected.stderr
        status = next_status

    observed_order.append(status["pending_surface"])
    assert observed_order == expected_order
    synthesis_context = json.loads(
        pathlib.Path(status["context_path"]).read_text(encoding="utf-8")
    )
    assert [
        item["inventory_position"] for item in synthesis_context["call_inventory"]
    ] == [1, 2, 3, 4, 5, 6]
    assert synthesis_context["classification_group_contract"] == {
        "fields": [
            "classification",
            "inventory_positions",
            "primary_finding_id",
            "reason",
            "reason_code",
        ],
        "position_base": 1,
        "coverage": "every-inventory-position-once",
        "semantic_scope": "group-level-approximate",
        "classifications": [
            "necessary",
            "avoidable_implemented",
            "avoidable_unimplemented",
            "reviewed_no_confirmed_waste",
            "unassessed",
        ],
        "necessary_reason_codes": contract["necessary_reason_codes"],
    }
    assert [
        item["surface_id"] for item in synthesis_context["accepted_surface_results"]
    ] == expected_order[:-1]
    synthesis = {
        "schema": "ceratops-credit-analysis-synthesis-result.v1",
        "analysis_id": status["analysis_id"],
        "pass_id": status["pass_id"],
        "surface_id": "synthesis",
        "evidence_fingerprint": fingerprint,
        "artifact_paths": {
            "state": status["state_path"],
            "evidence": status["evidence_path"],
            "context": status["context_path"],
            "result": status["required_result_path"],
        },
        "finding_order": [
            "helper-gap",
            "context-gap",
            "rework-gap",
            "instruction-gap",
            "oversized-tool-output",
        ],
        "risk_order": ["tool-poll-risk"],
        "finding_dispositions": [
            {
                "finding_id": "helper-gap",
                "primary_call_ids": ["turn-1:1"],
                "secondary_call_ids": ["turn-1:2"],
            },
            {
                "finding_id": "context-gap",
                "primary_call_ids": ["turn-1:2"],
                "secondary_call_ids": [],
            },
            {
                "finding_id": "rework-gap",
                "primary_call_ids": [],
                "secondary_call_ids": ["turn-1:1", "turn-1:2"],
            },
            {
                "finding_id": "instruction-gap",
                "primary_call_ids": ["turn-1:3"],
                "secondary_call_ids": [],
            },
            {
                "finding_id": "oversized-tool-output",
                "primary_call_ids": [],
                "secondary_call_ids": [],
            },
        ],
        "classification_groups": [
            {
                "classification": "avoidable_unimplemented",
                "inventory_positions": [1],
                "primary_finding_id": "helper-gap",
                "reason_code": None,
                "reason": "helper producer gap",
            },
            {
                "classification": "avoidable_unimplemented",
                "inventory_positions": [2],
                "primary_finding_id": "context-gap",
                "reason_code": None,
                "reason": "duplicate evidence read",
            },
            {
                "classification": "avoidable_implemented",
                "inventory_positions": [3],
                "primary_finding_id": "instruction-gap",
                "reason_code": None,
                "reason": "implemented prompt control",
            },
            {
                "classification": "necessary",
                "inventory_positions": [4],
                "primary_finding_id": None,
                "reason_code": "protocol-overhead",
                "reason": "required wait protocol",
            },
            {
                "classification": "necessary",
                "inventory_positions": [5, 6],
                "primary_finding_id": None,
                "reason_code": "required-workflow",
                "reason": "required final answers",
            },
        ],
        "secondary_call_mappings": [
            {"call_id": "turn-1:1", "finding_ids": ["rework-gap"]},
            {
                "call_id": "turn-1:2",
                "finding_ids": ["helper-gap", "rework-gap"],
            },
        ],
        "producer_groups": [
            {
                "id": "helper-owner-group",
                "producer_type": "script",
                "owner": "scripts/run-helper.py",
                "finding_ids": ["helper-gap", "rework-gap"],
                "recommended_control": "combine helper preflight and validation",
                "targeted_verification": ["verify-helper-gap", "verify-rework-gap"],
            },
            {
                "id": "context-owner-group",
                "producer_type": "skill",
                "owner": "skills/example/SKILL.md",
                "finding_ids": ["context-gap"],
                "recommended_control": "reuse the retained evidence boundary",
                "targeted_verification": ["verify-context-gap"],
            },
            {
                "id": "prompt-owner-group",
                "producer_type": "prompt",
                "owner": "request prompt",
                "finding_ids": ["instruction-gap"],
                "recommended_control": "retain the implemented prompt control",
                "targeted_verification": ["verify-instruction-gap"],
            },
            {
                "id": "output-volume-group",
                "producer_type": "tool-choice",
                "owner": "synthetic command",
                "finding_ids": ["oversized-tool-output"],
                "recommended_control": "bound the synthetic command output",
                "targeted_verification": ["verify-oversized-tool-output"],
            },
        ],
    }
    synthesis_path = pathlib.Path(status["required_result_path"])
    invalid_syntheses = [
        (
            {
                **synthesis,
                "classification_groups": synthesis["classification_groups"][:-1],
            },
            "cover every inventory position",
        ),
        (
            {
                **synthesis,
                "classification_groups": [
                    *synthesis["classification_groups"],
                    {
                        "classification": "necessary",
                        "inventory_positions": [1],
                        "primary_finding_id": None,
                        "reason_code": "required-workflow",
                        "reason": "duplicate accounting group",
                    },
                ],
            },
            "assigned more than once",
        ),
        (
            {
                **synthesis,
                "classification_groups": [
                    *synthesis["classification_groups"][:-1],
                    {
                        **synthesis["classification_groups"][-1],
                        "inventory_positions": [5, 6, 7],
                    },
                ],
            },
            "outside the inventory",
        ),
    ]
    for invalid_synthesis, expected_error in invalid_syntheses:
        write_json_file(synthesis_path, invalid_synthesis)
        rejected = run_credit_analysis_workflow(
            "finalize",
            "--state",
            str(state_path),
            "--result",
            str(synthesis_path),
        )
        assert rejected.returncode == 2
        assert expected_error in rejected.stderr
    write_json_file(synthesis_path, synthesis)
    finalized = run_credit_analysis_workflow(
        "finalize",
        "--state",
        str(state_path),
        "--result",
        str(synthesis_path),
    )
    assert finalized.returncode == 0, finalized.stderr
    assert finalized.stdout.strip() == "OK"

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["finalized"] is True
    assert [record["surface_id"] for record in state["completed"]] == expected_order
    index_records = [
        json.loads(line)
        for line in pathlib.Path(state["paths"]["index"]).read_text(encoding="utf-8").splitlines()
    ]
    assert [record["surface_id"] for record in index_records] == expected_order
    assert len(list(pathlib.Path(state["paths"]["findings_dir"]).glob("*.json"))) == 6
    assert not pathlib.Path(state["paths"]["context_dir"]).exists()
    assert not pathlib.Path(state["paths"]["pending_dir"]).exists()
    accepted_synthesis = json.loads(
        pathlib.Path(state["completed"][-1]["path"]).read_text(encoding="utf-8")
    )
    assert "call_classifications" not in accepted_synthesis
    assert len(accepted_synthesis["classification_groups"]) == 5
    final_result = json.loads(
        pathlib.Path(state["final_result"]["path"]).read_text(encoding="utf-8")
    )
    assert [
        item["call_id"] for item in final_result["primary_call_mappings"]
    ] == evidence["call_inventory"]
    assert [item["id"] for item in final_result["confirmed_findings"]] == synthesis[
        "finding_order"
    ]
    assert final_result["totals"] == {
        "total_model_calls": 6,
        "necessary_calls": 3,
        "protocol_overhead_calls": 1,
        "reviewed_no_confirmed_waste_calls": 0,
        "unassessed_calls": 0,
        "avoidable_calls": 3,
        "avoidable_implemented_calls": 1,
        "avoidable_unimplemented_calls": 2,
        "confirmed_findings": 5,
        "plausible_risks": 1,
    }
    assert final_result["helper_category_totals"] == {
        "insufficient-error-handling": 1,
        "missing-dependency-handling": 1,
    }
    assert next(
        item for item in final_result["confirmed_findings"] if item["id"] == "rework-gap"
    )["deduplicated_avoidable_call_count"] == 0
    context_result = next(
        item for item in final_result["confirmed_findings"] if item["id"] == "context-gap"
    )
    assert context_result["complexity"] == "Minimal"
    assert context_result["problem_summary"] == context_finding["problem_summary"]
    volume_result = next(
        item
        for item in final_result["confirmed_findings"]
        if item["id"] == "oversized-tool-output"
    )
    assert volume_result["waste_kind"] == "context-volume"
    assert volume_result["deduplicated_avoidable_call_count"] == 0
    assert final_result["secondary_call_mappings"] == synthesis[
        "secondary_call_mappings"
    ]
    assert final_result["priced_cost"] is None
    final_packet = json.loads(
        run_credit_analysis_workflow(
            "status", "--state", str(state_path), "--packet"
        ).stdout
    )
    report = final_packet["report_markdown"]
    assert (
        "Observed: The workflow waited after the external result was available."
        in report
    )
    assert (
        "Unknown: The wait was unnecessary because completion was already visible.; "
        "The wait was required because completion had not propagated yet."
        in report
    )
    assert (
        "Why not confirmed: The retained timestamps do not show when completion "
        "became visible; choosing between the competing explanations would be "
        "speculation."
        in report
    )
    assert first_result is not None and first_result_path is not None


def test_credit_analysis_workflow_end_to_end_uses_two_semantic_calls(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = load_credit_analysis_workflow_module()
    codex_home = tmp_path / "codex-home"
    automation_root = codex_home / "automations" / "credits-saving-analysis"
    installed_skill_root = (
        codex_home / "skills" / "ceratops-credit-savings-analysis"
    )
    automation_root.mkdir(parents=True)
    installed_skill_root.mkdir(parents=True)
    (codex_home / "AGENTS.md").write_text(
        "CURRENT_GLOBAL_CONTROL_SENTINEL\n",
        encoding="utf-8",
        newline="\n",
    )
    (automation_root / "automation.toml").write_text(
        'prompt = "CURRENT_AUTOMATION_CONTROL_SENTINEL"\n',
        encoding="utf-8",
        newline="\n",
    )
    (installed_skill_root / "SKILL.md").write_text(
        "# CURRENT_SKILL_CONTROL_SENTINEL\n",
        encoding="utf-8",
        newline="\n",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    request, session_path, task_root = credit_analysis_request(
        tmp_path,
        extra_completed_turns=3,
        extra_calls_per_turn=4,
        oversized_user_message_chars=5_000,
    )
    canonical_artifact = tmp_path / "scripts" / "run_form.py"
    canonical_artifact.parent.mkdir()
    canonical_artifact.write_text("print('canonical')\n", encoding="utf-8")
    session_rows = [
        json.loads(line)
        for line in session_path.read_text(encoding="utf-8").splitlines()
    ]
    for row in session_rows:
        payload = row.get("payload", {})
        if row.get("type") == "session_meta":
            payload["base_instructions"] += (
                "\nAutomation ID: credits-saving-analysis\n"
                "Check $CODEX_HOME/skills/ceratops-credit-savings-analysis/SKILL.md."
            )
        if (
            payload.get("type") == "function_call_output"
            and payload.get("call_id") == "read-1"
        ):
            output = json.loads(payload["output"])
            output.update(
                {
                    "canonical_context_reference": f"{canonical_artifact}-13-",
                    "canonical_exact_reference": str(canonical_artifact),
                    "canonical_match_reference": f"{canonical_artifact}:12:",
                }
            )
            payload["output"] = json.dumps(output)
    session_path.write_text(
        "".join(json.dumps(row) + "\n" for row in session_rows),
        encoding="utf-8",
        newline="\n",
    )
    plan = workflow.command_plan_orchestration(
        request,
        available_models=holistic_model_catalog(),
    )
    assert plan["phase"] == "planned"
    assert plan["action"] == "full-analysis"
    assert plan["mode"] == "full-analysis"
    assert plan["analysis_scope_label"] == "exhaustive full analysis"
    assert plan["projected_luna_calls"] == 1
    assert plan["projected_sol_calls"] == 1
    assert plan["projected_semantic_calls"] == 2
    assert plan["shared_candidate_count"] > 8
    assert len(json.dumps(plan)) < 20_000

    state_path = pathlib.Path(plan["state_path"])
    manifest = json.loads(
        pathlib.Path(plan["manifest_path"]).read_text(encoding="utf-8")
    )
    assert "selection_manifest" not in manifest
    evidence = json.loads(
        pathlib.Path(plan["evidence_path"]).read_text(encoding="utf-8")
    )
    compact = json.loads(
        pathlib.Path(manifest["compact_evidence"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    canonical_records = [
        record
        for record in compact["canonical_state"]
        if record["artifact_reference"].endswith("/scripts/run_form.py")
    ]
    assert len(canonical_records) == 1
    canonical_record = canonical_records[0]
    assert canonical_record["status"] == "captured"
    assert canonical_record["source_reference_count"] == 3
    assert canonical_record["source_sha256"] == hashlib.sha256(
        canonical_artifact.read_bytes()
    ).hexdigest()
    assert {
        (location["line"], location["relation"])
        for location in canonical_record["locations"]
    } == {(12, "match"), (13, "context")}
    canonical_reference = canonical_record["artifact_reference"]
    call_artifact_references = [
        reference
        for record in compact["records"]
        for reference in record["canonical_artifact_references"]
    ]
    assert canonical_reference in call_artifact_references
    assert not any(
        "run_form.py:" in reference or "run_form.py-" in reference
        for reference in call_artifact_references
    )
    canonical_by_reference = {
        record["artifact_reference"]: record
        for record in compact["canonical_state"]
    }
    for reference, sentinel in (
        ("<codex-home>/AGENTS.md", "CURRENT_GLOBAL_CONTROL_SENTINEL"),
        (
            "<codex-home>/automations/credits-saving-analysis/automation.toml",
            "CURRENT_AUTOMATION_CONTROL_SENTINEL",
        ),
        (
            "<codex-home>/skills/ceratops-credit-savings-analysis/SKILL.md",
            "CURRENT_SKILL_CONTROL_SENTINEL",
        ),
    ):
        record = canonical_by_reference[reference]
        assert record["status"] == "captured"
        assert sentinel in json.dumps(record["projection"])
    retained_canonical = json.loads(
        pathlib.Path(manifest["canonical_state"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    retained_records = [
        record
        for record in retained_canonical["records"]
        if record["artifact_reference"].endswith("/scripts/run_form.py")
    ]
    assert len(retained_records) == 1
    assert len(retained_records[0]["observed_references"]) == 3
    assert evidence["collection"]["session_reads"] == 1
    assert evidence["analysis_lineage"]["source_selection_uses_prompt_markers"] is False
    assert "TOOL_RESULT_TAIL_SENTINEL" in json.dumps(evidence)
    assert "OVERSIZED_USER_EVIDENCE_SENTINEL" in json.dumps(evidence)
    assert any(
        message["text"]["mode"] == "retained-projection"
        and message["text"]["chars"] > 12_000
        and message["text"]["sha256"]
        for record in compact["records"]
        for message in record["user_messages"]
    )
    assert all("candidate_pairs" not in task for task in manifest["luna_tasks"])
    assert "shared_consolidation_task_ids" not in manifest
    flattened = [
        candidate_id
        for task in manifest["luna_tasks"]
        for candidate_id in task["candidate_ids"]
    ]
    assert flattened == manifest["candidate_ids"]
    assert len(flattened) == len(set(flattened))

    runner = FakeCreditModelRunner()
    untouched = task_root / "caller-owned-retained.txt"
    untouched.write_text("retain\n", encoding="utf-8", newline="\n")
    paused = workflow.command_execute_orchestration(
        state_path,
        runner=runner,
        available_models=runner.available_models,
        task_limit=0,
    )
    assert paused["completed_tasks"] == 0
    assert runner.calls == []
    after_luna = workflow.command_execute_orchestration(
        state_path,
        runner=runner,
        available_models=runner.available_models,
        task_limit=1,
    )
    assert after_luna["completed_tasks"] == 1
    assert after_luna["next_task"] == "sol.adjudication"
    assert [(call["model"], call["reasoning_effort"]) for call in runner.calls] == [
        ("gpt-5.6-luna", "medium")
    ]
    after_luna_state = json.loads(state_path.read_text(encoding="utf-8"))
    accepted_luna = json.loads(
        pathlib.Path(
            after_luna_state["execution"]["luna.discovery.0001"]["result"]["path"]
        ).read_text(encoding="utf-8")
    )
    assert all(
        candidate["surface_ids"]
        == [
            surface
            for surface in manifest["surface_order"]
            if surface in set(candidate["surface_ids"])
        ]
        for candidate in accepted_luna["candidates"]
    )
    completed = workflow.command_execute_orchestration(
        state_path,
        runner=runner,
        available_models=runner.available_models,
    )
    assert completed["complete"] is True
    assert [(call["model"], call["reasoning_effort"]) for call in runner.calls] == [
        ("gpt-5.6-luna", "medium"),
        ("gpt-5.6-sol", "max"),
    ]
    assert [call["phase"] for call in runner.calls] == [
        "luna-discovery",
        "sol-adjudication",
    ]
    sol_call = runner.calls[-1]
    sol_packet_text = json.dumps(sol_call["input_payload"], ensure_ascii=False)
    assert not any(
        candidate_id in sol_packet_text for candidate_id in manifest["candidate_ids"]
    )
    assert not any(call_id in sol_packet_text for call_id in manifest["call_ids"])
    assert set(sol_call["schema"]["properties"]) == {
        "candidate_decisions",
        "confirmed_findings",
        "plausible_risks",
        "temporary_control_reviews",
        "temporary_control_merges",
        "helper_category_reviews",
        "call_classifications",
    }
    assert sol_call["schema"]["title"] == (
        "ceratops-credit-analysis-sol-transport.v1"
    )
    assert "maxItems" not in sol_call["schema"]["properties"][
        "confirmed_findings"
    ]
    assert (
        sol_call["schema"]["properties"]["candidate_decisions"]["items"]
        ["properties"]["reason"]["maxLength"]
        == 320
    )
    assert all(
        "Do not use tools" in call["prompt"]
        and "Intentional full skill-body injection" in call["prompt"]
        and "Never recommend a reasoning" in call["prompt"]
        and "CERATOPS_CREDIT_ANALYSIS_CHILD" not in call["prompt"]
        for call in runner.calls
    )
    assert "frozen current canonical state" in runner.calls[-1]["prompt"]
    assert runner.calls[-1]["input_payload"]["analysis_policy"] == {
        "implementation_status_source": "frozen-current-canonical-state",
        "existing_control_classification": (
            "implemented-compliance-or-runtime-gap"
        ),
        "excluded_waste": ["intentional-full-skill-body-injection"],
        "prohibited_recommendations": ["reasoning-settings-or-levels"],
        "external_research": "targeted-official-sources-only",
        "broader_research_handoff": "paste-ready-prompt",
        "mutation_authority": False,
        "outstanding_finding_cap": None,
    }
    final_path = pathlib.Path(completed["final_result_path"])
    final_before = final_path.read_bytes()
    final = json.loads(final_before)
    assert final["analysis_scope_label"] == "exhaustive full analysis"
    completed_state = json.loads(state_path.read_text(encoding="utf-8"))
    sol_result_record = completed_state["execution"]["sol.adjudication"]["result"]
    aliases_path = pathlib.Path(
        completed_state["manifest"]["sol_task"]["artifacts"]["aliases"]
    )
    aliases = json.loads(aliases_path.read_text(encoding="utf-8"))
    assert aliases["input_sha256"] == sol_result_record["input_sha256"]
    assert aliases["aliases"]["calls"]
    assert sol_result_record["aliases_sha256"] == hashlib.sha256(
        aliases_path.read_bytes()
    ).hexdigest()
    assert sol_result_record["output_telemetry"] == {
        "planned_output_reserve_tokens": 48_000,
        "raw_result_chars": sol_result_record["output_telemetry"][
            "raw_result_chars"
        ],
        "accepted_result_chars": sol_result_record["output_telemetry"][
            "accepted_result_chars"
        ],
        "duration_ms": sol_result_record["output_telemetry"]["duration_ms"],
        "visible_output_tokens": 360,
        "reasoning_output_tokens": 1_100,
        "total_output_tokens": 1_460,
        "token_usage_available": True,
    }
    assert sol_result_record["output_telemetry"]["raw_result_chars"] > 0
    assert sol_result_record["output_telemetry"]["accepted_result_chars"] > 0
    assert sol_result_record["output_budget_warnings"] == []
    raw_sol = json.loads(
        pathlib.Path(
            completed_state["execution"]["sol.adjudication"]["attempts"][-1]
            ["raw_output_path"]
        ).read_text(encoding="utf-8")
    )
    assert "surface_summaries" not in raw_sol
    assert "analysis_summary" not in raw_sol
    assert "schema" not in raw_sol
    assert [decision["luna_candidate_id"] for decision in final["candidate_decisions"]]
    assert all(
        decision["luna_candidate_id"].startswith("luna.")
        for decision in final["candidate_decisions"]
    )
    assert final["model_calls"] == {
        "actual_luna": 1,
        "actual_sol": 1,
        "accepted_luna": 1,
        "accepted_sol": 1,
        "bookkeeping": 0,
    }
    assert final["manifest"]["unclassified_calls"] == 0
    assert final["classification_totals"]["unassessed"] == 0
    assert sum(
        final["classification_totals"][key]
        for key in (
            "necessary",
            "avoidable_implemented",
            "avoidable_unimplemented",
            "reviewed_no_confirmed_waste",
            "unassessed",
        )
    ) == final["manifest"]["shared_candidate_count"]
    assert {
        review["disposition"] for review in final["temporary_control_reviews"]
    } == {
        "transient-by-design",
        "permanently-implemented",
        "run-only-useful",
        "durable-control-missing",
        "final-state-unclear",
    }
    assert len(final["temporary_control_merges"]) == 1
    assert len(final["temporary_control_merges"][0]["review_ids"]) == 2
    assert all(
        review["finding_id"] is None
        for review in final["temporary_control_reviews"]
        if review["disposition"]
        in {"transient-by-design", "permanently-implemented", "run-only-useful"}
    )
    assert all(
        review["recurrence_inputs"]["likely"]
        and review["savings_inputs"]["justifies_maintenance"]
        for review in final["temporary_control_reviews"]
        if review["finding_id"] is not None
    )
    volume_findings = [
        finding
        for finding in final["confirmed_findings"]
        if finding["waste_kind"] == "context-volume"
    ]
    assert volume_findings
    assert volume_findings[0]["volume"]["input_tokens"] > 0
    assert volume_findings[0]["volume"]["output_tokens"] > 0
    implemented_findings = [
        finding
        for finding in final["confirmed_findings"]
        if finding["implementation_status"] == "implemented"
    ]
    outstanding_findings = [
        finding
        for finding in final["confirmed_findings"]
        if finding["implementation_status"] == "unimplemented"
    ]
    assert len(implemented_findings) == 1
    assert len(outstanding_findings) > 5
    report = pathlib.Path(completed_state["paths"]["report"]).read_text(
        encoding="utf-8"
    )
    report_lines = set(report.splitlines())
    assert "already addressed: 1" in report
    assert f"## {implemented_findings[0]['title']}" not in report_lines
    assert all(
        f"## {finding['title']}" in report_lines
        for finding in outstanding_findings
    )
    assert len(final["candidate_decisions"]) == final["luna_discovery"][
        "candidate_count"
    ]
    assert untouched.is_file()
    assert not pathlib.Path(
        json.loads(state_path.read_text(encoding="utf-8"))["paths"]["transient"]
    ).exists()

    call_count = len(runner.calls)
    repeated = workflow.command_execute_orchestration(
        state_path,
        runner=runner,
        available_models=runner.available_models,
    )
    assert repeated["complete"] is True
    assert len(runner.calls) == call_count
    assert final_path.read_bytes() == final_before
