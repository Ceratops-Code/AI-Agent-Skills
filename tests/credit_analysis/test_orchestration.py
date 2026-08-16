from __future__ import annotations

import hashlib
import json
import pathlib
import threading
import time
from typing import Any, Mapping

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


def test_full_analysis_uses_run_windows_parallel_tiers_and_exact_coverage(
    tmp_path: pathlib.Path,
) -> None:
    workflow = load_credit_analysis_workflow_module()
    request, _, _ = credit_analysis_request(tmp_path)
    runner = FakeCreditModelRunner(temporary_controls=False)
    plan = workflow.command_plan_orchestration(
        request, available_models=runner.available_models
    )
    state = json.loads(pathlib.Path(plan["state_path"]).read_text(encoding="utf-8"))
    manifest = state["manifest"]
    assert state["model_specs"]["luna"]["reasoning_effort"] == "max"
    assert "input_byte_budget" in state["model_specs"]["luna"]
    assert (
        state["model_specs"]["luna"]["input_byte_budget"]
        - state["model_specs"]["luna"]["evidence_byte_budget"]
        == state["model_specs"]["luna"]["visible_task_reserve_bytes"]
    )
    assert len(manifest["sol_tasks"]) == 6
    assert state["execution_context"]["instruction_chains"]
    chains_by_cwd = {
        chain["cwd"]: chain
        for chain in state["execution_context"]["instruction_chains"]
    }
    assert all(
        task["instruction_chain_sha256"]
        == chains_by_cwd[task["execution_cwd"]]["chain_sha256"]
        for task in [*manifest["luna_tasks"], *manifest["sol_tasks"]]
    )
    assert all(
        task["execution_cwd"] == state["execution_context"]["primary_cwd"]
        for task in manifest["sol_tasks"]
    )
    completed = workflow.command_execute_orchestration(
        pathlib.Path(plan["state_path"]),
        runner=runner,
        available_models=runner.available_models,
    )
    phases = [call["phase"] for call in runner.calls]
    assert completed["complete"] is True
    assert phases.count("sol-adjudication") == 3
    assert phases.count("sol-audit") == 1
    assert phases.count("sol-final") == 1
    final_call = next(call for call in runner.calls if call["phase"] == "sol-final")
    assert final_call["input_payload"]["canonical_state"] == []
    final = json.loads(
        pathlib.Path(completed["final_result_path"]).read_text(encoding="utf-8")
    )
    completed_state = json.loads(
        pathlib.Path(plan["state_path"]).read_text(encoding="utf-8")
    )
    prior_findings = [
        finding
        for task in manifest["sol_tasks"][:4]
        if completed_state["execution"][task["task_id"]]["status"] == "complete"
        for finding in json.loads(
            pathlib.Path(
                completed_state["execution"][task["task_id"]]["result"]["path"]
            ).read_text(encoding="utf-8")
        )["confirmed_findings"]
    ]
    assert all(
        any(
            retained["producer_owner"] == finding["producer_owner"]
            and retained["proposed_durable_control"]
            == finding["proposed_durable_control"]
            and set(finding["affected_call_ids"])
            <= set(retained["affected_call_ids"])
            for retained in final["confirmed_findings"]
        )
        for finding in prior_findings
    )
    task_by_id = {
        task["task_id"]: task
        for task in [*manifest["luna_tasks"], *manifest["sol_tasks"]]
    }
    assert all(
        attempt["instruction_chain_sha256"]
        == task_by_id[task_id]["instruction_chain_sha256"]
        for task_id, execution in completed_state["execution"].items()
        for attempt in execution["attempts"]
    )
    assert final["coverage"]["analyzed_runs"] == final["coverage"]["eligible_runs"]
    assert final["omissions"] == []
    report = pathlib.Path(completed["report_path"]).read_text(encoding="utf-8")
    assert "| Run | Window | Records | Input bytes |" in report
    assert "| Completed run | Total model calls |" in report
    assert "| Proposed control | Calls saved per affected run |" in report

    capacity_root = tmp_path / "sol-capacity"
    capacity_root.mkdir()
    capacity_request, _, _ = credit_analysis_request(
        capacity_root,
        extra_completed_turns=3,
        extra_calls_per_turn=12,
    )
    capacity_catalog = holistic_model_catalog(context_tokens=132_000)
    capacity_runner = FakeCreditModelRunner()
    capacity_runner.available_models = capacity_catalog
    capacity_plan = workflow.command_plan_orchestration(
        capacity_request,
        available_models=capacity_catalog,
    )
    capacity_completed = workflow.command_execute_orchestration(
        pathlib.Path(capacity_plan["state_path"]),
        runner=capacity_runner,
        available_models=capacity_catalog,
    )
    capacity_state = json.loads(
        pathlib.Path(capacity_plan["state_path"]).read_text(encoding="utf-8")
    )
    capacity_final = json.loads(
        pathlib.Path(capacity_completed["final_result_path"]).read_text(
            encoding="utf-8"
        )
    )
    sol_capacity_omissions = [
        omission
        for omission in capacity_state["omissions"]
        if omission.get("reason") == "sol-capacity"
    ]
    assert capacity_completed["complete"] is True
    assert sol_capacity_omissions
    assert sol_capacity_omissions == [
        omission
        for omission in capacity_final["omissions"]
        if omission.get("reason") == "sol-capacity"
    ]
    omitted_luna_candidate_ids = {
        candidate["id"]
        for omission in sol_capacity_omissions
        for task_id in omission["task_ids"]
        for candidate in json.loads(
            pathlib.Path(
                capacity_state["execution"][task_id]["result"]["path"]
            ).read_text(encoding="utf-8")
        )["candidates"]
    }
    assert omitted_luna_candidate_ids.isdisjoint(
        decision["luna_candidate_id"]
        for decision in capacity_final["candidate_decisions"]
    )


def test_removed_bounded_action_is_rejected(tmp_path: pathlib.Path) -> None:
    workflow = load_credit_analysis_workflow_module()
    request, _, _ = credit_analysis_request(
        tmp_path, action="bounded-largest-" "runs-analysis"
    )
    with pytest.raises(workflow.CreditAnalysisError, match="not public"):
        workflow.command_plan_orchestration(
            request, available_models=holistic_model_catalog()
        )


def test_luna_admission_caps_at_fifty_attempts_and_ten_workers(
    tmp_path: pathlib.Path,
) -> None:
    workflow = load_credit_analysis_workflow_module()
    request, _, _ = credit_analysis_request(
        tmp_path, extra_completed_turns=52, extra_calls_per_turn=1
    )

    class ConcurrentRunner(FakeCreditModelRunner):
        def __init__(self) -> None:
            super().__init__(temporary_controls=False)
            self.lock = threading.Lock()
            self.active = 0
            self.maximum_active = 0

        def _luna(
            self,
            task: Mapping[str, Any],
            packet: Mapping[str, Any],
            digest: str,
        ) -> dict[str, Any]:
            with self.lock:
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
            try:
                time.sleep(0.01)
                return super()._luna(task, packet, digest)
            finally:
                with self.lock:
                    self.active -= 1

    runner = ConcurrentRunner()
    plan = workflow.command_plan_orchestration(
        request, available_models=runner.available_models
    )
    completed = workflow.command_execute_orchestration(
        pathlib.Path(plan["state_path"]),
        runner=runner,
        available_models=runner.available_models,
    )
    assert completed["actual_luna_calls"] == 50
    assert runner.maximum_active == 10
    final = json.loads(
        pathlib.Path(completed["final_result_path"]).read_text(encoding="utf-8")
    )
    capped = [
        item for item in final["omissions"]
        if item["reason"] == "luna-attempt-cap"
    ]
    assert len(capped) == 5
    assert all(item["candidate_ids"] for item in capped)
    assert final["coverage"]["analyzed_runs"] == 50
    assert final["coverage"]["eligible_runs"] == 55


def test_luna_schema_retry_is_single_and_omission_is_exact(
    tmp_path: pathlib.Path,
) -> None:
    workflow = load_credit_analysis_workflow_module()
    request, _, _ = credit_analysis_request(tmp_path)

    class InvalidFirstWindowRunner(FakeCreditModelRunner):
        def _luna(
            self,
            task: Mapping[str, Any],
            packet: Mapping[str, Any],
            digest: str,
        ) -> dict[str, Any]:
            result = super()._luna(task, packet, digest)
            if task["task_id"] == "luna.discovery.0001":
                result["coverage"]["candidate_count"] -= 1
            return result

    runner = InvalidFirstWindowRunner(temporary_controls=False)
    plan = workflow.command_plan_orchestration(
        request, available_models=runner.available_models
    )
    completed = workflow.command_execute_orchestration(
        pathlib.Path(plan["state_path"]),
        runner=runner,
        available_models=runner.available_models,
    )
    state = json.loads(pathlib.Path(plan["state_path"]).read_text(encoding="utf-8"))
    failed = state["execution"]["luna.discovery.0001"]
    assert completed["complete"] is True
    assert failed["status"] == "omitted"
    assert len(failed["attempts"]) == 2
    omission = next(
        item for item in state["omissions"]
        if item.get("task_id") == "luna.discovery.0001"
    )
    assert omission["reason"] == "luna-invalid-output"
    assert omission["candidate_ids"] == state["manifest"]["luna_tasks"][0]["candidate_ids"]


def test_credit_analysis_workflow_end_to_end_uses_sharded_semantic_calls(
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
    alternate_cwd = tmp_path / "alternate-cwd"
    alternate_cwd.mkdir()
    (alternate_cwd / "AGENTS.md").write_text(
        "RUN_LOCAL_CONTROL_SENTINEL\n",
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
            row.get("type") == "turn_context"
            and payload.get("turn_id") == "turn-extra-3"
        ):
            payload["cwd"] = str(alternate_cwd)
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
    assert plan["analysis_scope_label"] == "full all-run analysis"
    assert plan["projected_luna_calls"] == 6
    assert plan["projected_sol_calls"] == 5
    assert plan["projected_semantic_calls"] == 11
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
    assert after_luna["next_task"] == "luna.discovery.0002"
    assert [(call["model"], call["reasoning_effort"]) for call in runner.calls] == [
        ("gpt-5.6-luna", "max")
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
    after_luna_tier = workflow.command_execute_orchestration(
        state_path,
        runner=runner,
        available_models=runner.available_models,
        task_limit=5,
    )
    assert after_luna_tier["next_task"] == "sol.adjudication.0001"
    orphan_state, orphan_evidence, orphan_contract, orphan_compact = (
        workflow._holistic_read_state(state_path)
    )
    orphan_base_task = workflow._holistic_task_map(orphan_state["manifest"])[
        "sol.adjudication.0001"
    ]
    orphan_routing = json.loads(
        pathlib.Path(orphan_state["routing"]["path"]).read_text(encoding="utf-8")
    )
    orphan_task = {
        **orphan_base_task,
        **next(
            shard
            for shard in orphan_routing["shards"]
            if shard["task_id"] == orphan_base_task["task_id"]
        ),
    }
    (
        orphan_payload,
        orphan_digest,
        orphan_prompt,
        orphan_schema,
        _,
    ) = workflow._holistic_prepare_task(
        orphan_state,
        orphan_evidence,
        orphan_contract,
        orphan_compact,
        orphan_task,
    )
    orphan_raw, _ = workflow._invoke_injected_runner(
        runner,
        model=orphan_state["model_specs"]["sol"]["model"],
        task={
            **orphan_task,
            "reasoning_effort": orphan_state["model_specs"]["sol"][
                "reasoning_effort"
            ],
        },
        prompt_path=orphan_prompt,
        schema_path=orphan_schema,
        input_payload=orphan_payload,
        input_sha256=orphan_digest,
        attempt_dir=(
            pathlib.Path(orphan_task["artifacts"]["attempts"]) / "attempt-001"
        ),
    )
    assert orphan_raw is not None
    assert orphan_state["execution"][orphan_task["task_id"]]["attempts"] == []
    completed = workflow.command_execute_orchestration(
        state_path,
        runner=runner,
        available_models=runner.available_models,
    )
    assert completed["complete"] is True
    assert all(call["reasoning_effort"] == "max" for call in runner.calls)
    assert sum(call["phase"] == "luna-discovery" for call in runner.calls) == 6
    assert sum(call["phase"] == "sol-adjudication" for call in runner.calls) == 3
    assert sum(call["phase"] == "sol-audit" for call in runner.calls) == 1
    assert sum(call["phase"] == "sol-final" for call in runner.calls) == 1
    assert sum(
        call["input_sha256"] == orphan_digest for call in runner.calls
    ) == 1
    completed_state = json.loads(state_path.read_text(encoding="utf-8"))
    recovered_execution = completed_state["execution"][orphan_task["task_id"]]
    assert len(recovered_execution["attempts"]) == 1
    assert recovered_execution["attempts"][0][
        "recovered_unrecorded_attempt"
    ] is True
    assert recovered_execution["attempts"][0]["duration_ms"] is None
    assert recovered_execution["result"]["recovered_without_model_call"] is True
    sol_call = next(
        call for call in runner.calls if call["phase"] == "sol-adjudication"
    )
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
    assert any(
        "frozen current canonical state" in call["prompt"]
        for call in runner.calls
        if call["phase"] == "sol-adjudication"
    )
    assert sol_call["input_payload"]["analysis_policy"] == {
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
    rule_context = sol_call["input_payload"]["execution_rule_context"]
    assert rule_context["task_chain_sha256"]
    assert rule_context["primary_chain_sha256"]
    assert rule_context["source_chains"]
    assert any(
        "RUN_LOCAL_CONTROL_SENTINEL" in item["text"]
        for chain in rule_context["source_chains"]
        for item in chain["differing_from_primary"]
    )
    final_path = pathlib.Path(completed["final_result_path"])
    final_before = final_path.read_bytes()
    final = json.loads(final_before)
    assert final["analysis_scope_label"] == "full all-run analysis"
    completed_state = json.loads(state_path.read_text(encoding="utf-8"))
    frozen_rule_files = [
        item
        for chain in completed_state["execution_context"]["instruction_chains"]
        for item in chain["files"]
    ]
    global_rules = codex_home / "AGENTS.md"
    assert any(
        pathlib.Path(item["path"]) == global_rules.resolve()
        and item["sha256"] == hashlib.sha256(global_rules.read_bytes()).hexdigest()
        for item in frozen_rule_files
    )
    tasks_by_id = {
        item["task_id"]: item
        for item in [
            *completed_state["manifest"]["luna_tasks"],
            *completed_state["manifest"]["sol_tasks"],
        ]
    }
    for task_id, execution in completed_state["execution"].items():
        task = tasks_by_id[task_id]
        for attempt in execution["attempts"]:
            assert attempt["execution_cwd"] == task["execution_cwd"]
            assert attempt["ephemeral"] is (task["phase"] == "luna-discovery")
            assert (
                attempt["instruction_chain_sha256"]
                == task["instruction_chain_sha256"]
            )
    sol_result_record = completed_state["execution"]["sol.adjudication.0001"]["result"]
    aliases_path = pathlib.Path(
        completed_state["manifest"]["sol_tasks"][0]["artifacts"]["aliases"]
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
            completed_state["execution"]["sol.adjudication.0001"]["attempts"][-1]
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
        "actual_luna": 6,
        "actual_sol": 5,
        "accepted_luna": 6,
        "accepted_sol": 5,
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
    assert implemented_findings
    assert outstanding_findings
    report = pathlib.Path(completed_state["paths"]["report"]).read_text(
        encoding="utf-8"
    )
    assert "| Completed run | Total model calls |" in report
    assert "| Proposed control | Calls saved per affected run |" in report
    assert all(
        f"| {finding['proposed_durable_control']} |" in report
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

    parallel_failure_root = tmp_path / "parallel-failure"
    parallel_failure_root.mkdir()
    failure_request, _, _ = credit_analysis_request(
        parallel_failure_root,
        extra_completed_turns=3,
        extra_calls_per_turn=4,
    )
    failure_plan = workflow.command_plan_orchestration(
        failure_request,
        available_models=holistic_model_catalog(),
    )

    class OneInvalidSolRunner(FakeCreditModelRunner):
        def _sol(
            self,
            task: Mapping[str, Any],
            packet: Mapping[str, Any],
            digest: str,
        ) -> dict[str, Any]:
            result = super()._sol(task, packet, digest)
            if task["task_id"] == "sol.adjudication.0001":
                result["candidate_decisions"][0]["reason"] = "x" * 321
            return result

    failure_runner = OneInvalidSolRunner()
    failure_state_path = pathlib.Path(failure_plan["state_path"])
    with pytest.raises(
        workflow.CreditAnalysisError,
        match="320-character semantic bound",
    ):
        workflow.command_execute_orchestration(
            failure_state_path,
            runner=failure_runner,
            available_models=failure_runner.available_models,
        )
    failure_state = json.loads(failure_state_path.read_text(encoding="utf-8"))
    assert failure_state["execution"]["sol.adjudication.0001"]["attempts"][0][
        "outcome"
    ] == "validation-error"
    assert all(
        failure_state["execution"][task_id]["status"] == "complete"
        for task_id in (
            "sol.adjudication.0002",
            "sol.adjudication.0003",
            "sol.audit",
        )
    )
