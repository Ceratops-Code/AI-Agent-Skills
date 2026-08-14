from __future__ import annotations

import json
import os
import pathlib
import subprocess
from typing import Any, Mapping

import pytest

from tests.credit_analysis.models import (
    FakeCreditModelRunner,
    holistic_model_catalog,
    load_credit_analysis_workflow_module,
)
from tests.credit_analysis.sessions import (
    credit_analysis_request,
    write_json_file,
)


def test_credit_analysis_recovers_packet_local_luna_evidence_without_a_retry(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = load_credit_analysis_workflow_module()
    request, _, _ = credit_analysis_request(
        tmp_path,
        extra_completed_turns=2,
        extra_calls_per_turn=5,
    )
    plan = workflow.command_plan_orchestration(
        request,
        available_models=holistic_model_catalog(),
    )
    state_path = pathlib.Path(plan["state_path"])
    state, evidence, contract, compact = workflow._holistic_read_state(state_path)
    task = workflow._holistic_task_map(state["manifest"])["luna.discovery.0001"]
    payload, input_sha, prompt_path, schema_path, _ = (
        workflow._holistic_prepare_task(
            state,
            evidence,
            contract,
            compact,
            task,
        )
    )

    class PacketLocalEvidenceRunner(FakeCreditModelRunner):
        def _luna(
            self,
            task: Mapping[str, Any],
            packet: Mapping[str, Any],
            digest: str,
        ) -> dict[str, Any]:
            result = super()._luna(task, packet, digest)
            records = self._records(packet)
            assert result["candidates"] and len(records) > 1
            result["candidates"][0]["evidence_refs"].extend(
                [records[1]["candidate_id"], records[1]["evidence_refs"][0]]
            )
            return result

    runner = PacketLocalEvidenceRunner()
    attempt_dir = pathlib.Path(task["artifacts"]["attempts"]) / "attempt-001"
    _, attempt = workflow._invoke_injected_runner(
        runner,
        model="gpt-5.6-luna",
        task={**task, "reasoning_effort": "medium"},
        prompt_path=prompt_path,
        schema_path=schema_path,
        input_payload=payload,
        input_sha256=input_sha,
        attempt_dir=attempt_dir,
    )
    attempt = workflow._bind_attempt_record(
        {**attempt, "reasoning_effort": "medium"},
        state=state,
        task=task,
        input_sha256=input_sha,
        attempt_number=1,
    )
    validation_attempt = {
        **attempt,
        "outcome": "validation-error",
        "error": "simulated older packet-local evidence rejection",
    }
    state["execution"][task["task_id"]]["attempts"].extend(
        [
            validation_attempt,
            {
                **validation_attempt,
                "attempt_number": 2,
                "outcome": "runner-error",
                "error": "simulated interrupted later attempt",
                "artifacts": {
                    **validation_attempt["artifacts"],
                    "raw_output": None,
                },
            },
        ]
    )
    state["model_attempts"]["luna"] = 2
    workflow._holistic_sync_child_lineage(state)
    workflow._holistic_save_state(state)
    monkeypatch.setattr(
        workflow,
        "_holistic_prompt",
        lambda **_: pytest.fail("resume regenerated a frozen model prompt"),
    )

    calls_before_resume = len(runner.calls)
    resumed = workflow.command_execute_orchestration(
        state_path,
        runner=runner,
        available_models=runner.available_models,
        task_limit=1,
    )
    assert resumed["next_task"] == "sol.adjudication"
    assert len(runner.calls) == calls_before_resume
    recovered_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert recovered_state["model_attempts"] == {"luna": 2, "sol": 0}
    assert recovered_state["model_calls"] == {"luna": 1, "sol": 0}
    assert len(recovered_state["child_lineage"]) == 2
    result_record = recovered_state["execution"][task["task_id"]]["result"]
    assert result_record["recovered_without_model_call"] is True
    result = json.loads(
        pathlib.Path(result_record["path"]).read_text(encoding="utf-8")
    )
    assert len(result["candidates"][0]["candidate_ids"]) == 2
    assert all(
        ref.startswith(("evidence://", "analysis://"))
        for ref in result["candidates"][0]["evidence_refs"]
    )


def test_credit_analysis_normalizes_sol_transport_without_changing_judgments(
    tmp_path: pathlib.Path,
) -> None:
    workflow = load_credit_analysis_workflow_module()
    normalized_groups, classifications, unassessed = (
        workflow._holistic_call_classifications(
            [
                {
                    "call_ids": ["call-1", "call-2"],
                    "classification": "necessary",
                    "reason_code": "required-workflow",
                    "rationale": "Both calls complete the selected workflow.",
                    "evidence_refs": ["evidence://review/test:000001"],
                    "workstream": "producer",
                }
            ],
            contract=workflow._load_contract(),
            call_order=["call-1", "call-2"],
            workstreams={
                "call-1": "producer",
                "call-2": "analysis-overhead",
            },
        )
    )
    assert [group["call_ids"] for group in normalized_groups] == [
        ["call-1"],
        ["call-2"],
    ]
    assert [group["workstream"] for group in normalized_groups] == [
        "producer",
        "analysis-overhead",
    ]
    assert classifications == {"call-1": "necessary", "call-2": "necessary"}
    assert unassessed == 0

    request, _, _ = credit_analysis_request(
        tmp_path,
        extra_completed_turns=3,
        extra_calls_per_turn=4,
    )
    plan = workflow.command_plan_orchestration(
        request,
        available_models=holistic_model_catalog(),
    )

    class TransportVariationRunner(FakeCreditModelRunner):
        def _luna(
            self,
            task: Mapping[str, Any],
            packet: Mapping[str, Any],
            digest: str,
        ) -> dict[str, Any]:
            result = super()._luna(task, packet, digest)
            self.colliding_luna_ids = {
                str(candidate["candidate_ids"][0])
                for candidate in result["candidates"]
            }
            for candidate in result["candidates"]:
                candidate["id"] = str(candidate["candidate_ids"][0])
            return result

        def _sol(
            self,
            task: Mapping[str, Any],
            packet: Mapping[str, Any],
            digest: str,
        ) -> dict[str, Any]:
            result = super()._sol(task, packet, digest)
            call_order = [row[1] for row in packet["call_inventory"]["rows"]]
            packet_candidates = [
                candidate
                for luna_result in packet["luna_results"]
                for candidate in luna_result["candidates"]
            ]
            self.reclassified_candidate_index = next(
                index
                for index, candidate in enumerate(packet_candidates)
                if candidate["kind"] == "plausible-risk"
            )
            plausible_candidate_id = str(
                packet_candidates[self.reclassified_candidate_index]["id"]
            )
            moved_review = result["temporary_control_reviews"].pop(2)
            result["temporary_control_reviews"][0][
                "source_luna_candidate_ids"
            ].extend(
                [
                    plausible_candidate_id,
                    *moved_review["source_luna_candidate_ids"],
                ]
            )
            volume_call = next(
                call_id
                for item in result["confirmed_findings"]
                if item["waste_kind"] == "context-volume"
                for call_id in item["affected_call_ids"]
            )
            finding = next(
                item
                for item in result["confirmed_findings"]
                if item["waste_kind"] == "model-calls"
                and len(item["affected_call_ids"]) > 1
            )
            nonavoidable_call = next(
                call_id
                for group in result["call_classifications"]
                if not group["classification"].startswith("avoidable_")
                for call_id in group["call_ids"]
                if call_id != volume_call
            )
            finding_calls = set(finding["affected_call_ids"])
            finding_calls.add(nonavoidable_call)
            finding["affected_call_ids"] = [
                call_id for call_id in call_order if call_id in finding_calls
            ]

            implemented_call = next(
                call_id
                for call_id in finding["affected_call_ids"]
                if call_id != nonavoidable_call
            )
            split_groups: list[dict[str, Any]] = []
            for group in result["call_classifications"]:
                if implemented_call not in group["call_ids"]:
                    split_groups.append(group)
                    continue
                remaining = [
                    call_id
                    for call_id in group["call_ids"]
                    if call_id != implemented_call
                ]
                if remaining:
                    split_groups.append({**group, "call_ids": remaining})
                split_groups.append(
                    {
                        **group,
                        "call_ids": [implemented_call],
                        "classification": "avoidable_implemented",
                    }
                )
            result["call_classifications"] = list(reversed(split_groups))
            orphaned_groups: list[dict[str, Any]] = []
            for group in result["call_classifications"]:
                if volume_call not in group["call_ids"]:
                    orphaned_groups.append(group)
                    continue
                remaining = [
                    call_id
                    for call_id in group["call_ids"]
                    if call_id != volume_call
                ]
                if remaining:
                    orphaned_groups.append({**group, "call_ids": remaining})
                orphaned_groups.append(
                    {
                        **group,
                        "call_ids": [volume_call],
                        "classification": "avoidable_implemented",
                        "reason_code": None,
                    }
                )
            result["call_classifications"] = orphaned_groups
            implemented_finding = next(
                item
                for item in result["confirmed_findings"]
                if item["waste_kind"] == "model-calls"
                and item["implementation_status"] == "implemented"
            )
            historical_source = result["temporary_control_reviews"][0][
                "source_luna_candidate_ids"
            ][0]
            historical_decision = next(
                item
                for item in result["candidate_decisions"]
                if item["luna_candidate_id"] == historical_source
            )
            historical_decision["disposition"] = "confirmed-finding"
            historical_decision["finding_ids"] = [implemented_finding["id"]]
            historical_decision["risk_ids"] = []

            review = next(
                item
                for item in result["temporary_control_reviews"]
                if item["disposition"] == "permanently-implemented"
            )
            review["finding_id"] = finding["id"]
            review["no_finding_reason"] = None
            source_id = review["source_luna_candidate_ids"][0]
            decision = next(
                item
                for item in result["candidate_decisions"]
                if item["luna_candidate_id"] == source_id
            )
            decision["disposition"] = "confirmed-finding"
            decision["finding_ids"] = [finding["id"]]
            decision["risk_ids"] = []
            result["temporary_control_merges"].append(
                {
                    "control_key": "implemented-control-is-not-a-gap",
                    "owning_producer": review["owning_producer"],
                    "review_ids": [review["id"]],
                    "finding_id": finding["id"],
                }
            )
            return result

    runner = TransportVariationRunner()
    completed = workflow.command_execute_orchestration(
        pathlib.Path(plan["state_path"]),
        runner=runner,
        available_models=runner.available_models,
    )
    assert completed["complete"] is True
    assert len(runner.calls) == 2
    final = json.loads(
        pathlib.Path(completed["final_result_path"]).read_text(encoding="utf-8")
    )
    final_luna_ids = {
        str(decision["luna_candidate_id"])
        for decision in final["candidate_decisions"]
    }
    assert final_luna_ids.isdisjoint(runner.colliding_luna_ids)
    assert all(
        candidate_id.startswith(f"luna.{final['analysis_id']}.")
        for candidate_id in final_luna_ids
    )
    flattened = [
        call_id
        for group in final["call_classifications"]
        for call_id in group["call_ids"]
    ]
    manifest = json.loads(
        pathlib.Path(final["manifest"]["path"]).read_text(encoding="utf-8")
    )
    assert flattened == manifest["call_ids"]
    assert sum(
        len(group["call_ids"])
        for group in final["call_classifications"]
        if group["classification"] == "unassessed"
    ) == 1
    reviewed_sources = [
        candidate_id
        for review in final["temporary_control_reviews"]
        for candidate_id in review["source_luna_candidate_ids"]
    ]
    assert len(reviewed_sources) == 7
    assert len(reviewed_sources) == len(set(reviewed_sources))
    assert (
        final["candidate_decisions"][runner.reclassified_candidate_index][
            "luna_candidate_id"
        ]
        in reviewed_sources
    )
    final_findings = {
        finding["id"]: finding for finding in final["confirmed_findings"]
    }
    transient_review = next(
        review
        for review in final["temporary_control_reviews"]
        if review["disposition"] == "transient-by-design"
    )
    assert any(
        decision["disposition"] == "confirmed-finding"
        and all(
            final_findings[finding_id]["implementation_status"] == "implemented"
            for finding_id in decision["finding_ids"]
        )
        for decision in final["candidate_decisions"]
        if decision["luna_candidate_id"]
        in transient_review["source_luna_candidate_ids"]
    )
    assert all(
        finding["observed_avoidable_call_count"]
        == len(finding["affected_call_ids"])
        for finding in final["confirmed_findings"]
        if finding["waste_kind"] == "model-calls"
    )
    normalized_review = next(
        item
        for item in final["temporary_control_reviews"]
        if item["disposition"] == "permanently-implemented"
    )
    assert normalized_review["finding_id"] is None
    assert normalized_review["no_finding_reason"]
    normalized_decision = next(
        item
        for item in final["candidate_decisions"]
        if item["luna_candidate_id"]
        == normalized_review["source_luna_candidate_ids"][0]
    )
    assert normalized_decision["disposition"] == "dismissed-candidate"
    assert all(
        merge["control_key"] != "implemented-control-is-not-a-gap"
        for merge in final["temporary_control_merges"]
    )


def test_credit_analysis_model_catalog_decodes_cli_as_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = load_credit_analysis_workflow_module()
    monkeypatch.setattr(workflow.shutil, "which", lambda _: "codex")

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert kwargs["encoding"] == "utf-8"
        payload = {
            "models": [
                {
                    "slug": "gpt-5.6-luna",
                    "supported_reasoning_levels": [
                        {"effort": "low"},
                        {"effort": "medium"},
                        {"effort": "max"},
                    ],
                    "context_window": 272000,
                    "effective_context_window_percent": 95,
                },
                {
                    "slug": "gpt-5.6-sol",
                    "supported_reasoning_levels": [{"effort": "max"}],
                    "context_window": 272000,
                    "effective_context_window_percent": 95,
                },
            ]
        }
        return subprocess.CompletedProcess(args[0], 0, json.dumps(payload), "")

    monkeypatch.setattr(workflow.subprocess, "run", fake_run)
    catalog = workflow._codex_model_catalog()
    assert catalog["gpt-5.6-luna"]["effective_context_tokens"] == 258400
    specs = workflow._holistic_model_specs(workflow._load_contract(), catalog)
    assert specs["luna"]["reasoning_effort"] == "medium"
    assert specs["sol"]["reasoning_effort"] == "max"
    assert specs["luna"]["evidence_token_budget"] > 200_000
    assert specs["sol"]["output_reserve_tokens"] == 48_000
    assert specs["sol"]["evidence_token_budget"] > 160_000


def test_credit_analysis_child_command_places_global_approval_before_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = load_credit_analysis_workflow_module()
    command = workflow._codex_child_command(
        executable="codex",
        model="gpt-5.6-luna",
        reasoning_effort="medium",
        schema_path=pathlib.Path("schema.json"),
        raw_output=pathlib.Path("result.json"),
        orchestration_root=pathlib.Path("."),
    )
    assert command.index("--ask-for-approval") < command.index("exec")
    assert 'model_reasoning_effort="medium"' in command
    assert "--ephemeral" in command
    assert "--sandbox" in command
    assert command[command.index("--sandbox") + 1] == "read-only"

    calls: list[list[str]] = []

    class FakeProcess:
        pid = 424242
        returncode = None

        def poll(self) -> None:
            return None

        def wait(self, timeout: int) -> int:
            self.returncode = 1
            return 1

        def kill(self) -> None:
            self.returncode = 1

        def terminate(self) -> None:
            self.returncode = 1

    process = FakeProcess()
    if os.name == "nt":
        def fake_taskkill(
            argv: list[str], **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, "", "")

        monkeypatch.setattr(
            workflow.subprocess,
            "run",
            fake_taskkill,
        )
        assert workflow._terminate_process_tree(process) == 1
        assert calls == [
            ["taskkill", "/PID", "424242", "/T", "/F"]
        ]
    else:
        signals: list[tuple[int, int]] = []
        monkeypatch.setattr(
            workflow.os,
            "killpg",
            lambda pid, sent_signal: signals.append((pid, sent_signal)),
        )
        assert workflow._terminate_process_tree(process) == 1
        assert signals == [(424242, workflow.signal.SIGTERM)]


def test_credit_analysis_workflow_rejects_invalid_and_conflicting_passes(
    tmp_path: pathlib.Path,
) -> None:
    workflow = load_credit_analysis_workflow_module()
    noncanonical_scope = tmp_path / "noncanonical-task-root"
    noncanonical_scope.mkdir()
    noncanonical_base = tmp_path / "noncanonical-request"
    noncanonical_base.mkdir()
    noncanonical_request, _, _ = credit_analysis_request(
        noncanonical_base
    )
    noncanonical_payload = json.loads(
        noncanonical_request.read_text(encoding="utf-8")
    )
    noncanonical_payload["task_temp_root"] = str(noncanonical_scope)
    noncanonical_payload["evidence_output"] = str(
        noncanonical_scope / "evidence.json"
    )
    write_json_file(noncanonical_request, noncanonical_payload)
    with pytest.raises(
        workflow.CreditAnalysisError,
        match="must match <repo-parent>/tmp/<repo-name>/<thread-name>",
    ):
        workflow.command_plan_orchestration(
            noncanonical_request,
            available_models=holistic_model_catalog(),
        )
    assert not (noncanonical_scope / "state.json").exists()

    escaped_scope = tmp_path / "escaped-single-output"
    escaped_scope.mkdir()
    escaped_request, _, escaped_task_root = credit_analysis_request(escaped_scope)
    escaped_payload = json.loads(escaped_request.read_text(encoding="utf-8"))
    escaped_evidence = escaped_scope / "outside-evidence.json"
    escaped_payload["evidence_output"] = str(escaped_evidence)
    write_json_file(escaped_request, escaped_payload)
    with pytest.raises(
        workflow.CreditAnalysisError,
        match="evidence output must be inside task_temp_root",
    ):
        workflow.command_plan_orchestration(
            escaped_request,
            available_models=holistic_model_catalog(),
        )
    assert not escaped_evidence.exists()
    assert not (escaped_task_root / "state.json").exists()

    request, _, _ = credit_analysis_request(
        tmp_path,
        extra_completed_turns=2,
        extra_calls_per_turn=5,
    )
    plan = workflow.command_plan_orchestration(
        request,
        available_models=holistic_model_catalog(),
    )
    state_path = pathlib.Path(plan["state_path"])

    class BadCoverageRunner(FakeCreditModelRunner):
        def _luna(
            self,
            task: Mapping[str, Any],
            packet: Mapping[str, Any],
            digest: str,
        ) -> dict[str, Any]:
            result = super()._luna(task, packet, digest)
            result["coverage"]["candidate_count"] -= 1
            return result

    bad_luna = BadCoverageRunner()
    with pytest.raises(
        workflow.CreditAnalysisError,
        match="coverage attestation",
    ):
        workflow.command_execute_orchestration(
            state_path,
            runner=bad_luna,
            available_models=bad_luna.available_models,
            task_limit=1,
        )
    failed_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert failed_state["model_attempts"] == {"luna": 1, "sol": 0}
    assert failed_state["model_calls"] == {"luna": 0, "sol": 0}
    assert failed_state["execution"]["luna.discovery.0001"]["attempts"][0][
        "outcome"
    ] == "validation-error"

    good = FakeCreditModelRunner()
    resumed = workflow.command_execute_orchestration(
        state_path,
        runner=good,
        available_models=good.available_models,
        task_limit=1,
    )
    assert resumed["next_task"] == "sol.adjudication"
    resumed_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert resumed_state["model_attempts"]["luna"] == 2
    assert resumed_state["model_calls"]["luna"] == 1

    class VerboseRationaleRunner(FakeCreditModelRunner):
        def _sol(
            self,
            task: Mapping[str, Any],
            packet: Mapping[str, Any],
            digest: str,
        ) -> dict[str, Any]:
            result = super()._sol(task, packet, digest)
            result["candidate_decisions"][0]["reason"] = "x" * 321
            return result

    verbose_sol = VerboseRationaleRunner()
    with pytest.raises(
        workflow.CreditAnalysisError,
        match="320-character semantic bound",
    ):
        workflow.command_execute_orchestration(
            state_path,
            runner=verbose_sol,
            available_models=verbose_sol.available_models,
        )

    class ExcessiveUnassessedRunner(FakeCreditModelRunner):
        def _sol(
            self,
            task: Mapping[str, Any],
            packet: Mapping[str, Any],
            digest: str,
        ) -> dict[str, Any]:
            result = super()._sol(task, packet, digest)
            for group in result["call_classifications"]:
                group["classification"] = "unassessed"
                group["reason_code"] = None
                group["rationale"] = "A synthetic decision-blocking gap remains."
            return result

    bad_sol = ExcessiveUnassessedRunner()
    with pytest.raises(
        workflow.CreditAnalysisError,
        match="unassessed calls exceed",
    ):
        workflow.command_execute_orchestration(
            state_path,
            runner=bad_sol,
            available_models=bad_sol.available_models,
        )
    failed_sol_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert failed_sol_state["model_attempts"]["sol"] == 2
    assert failed_sol_state["model_calls"]["sol"] == 0

    completed = workflow.command_execute_orchestration(
        state_path,
        runner=good,
        available_models=good.available_models,
    )
    assert completed["complete"] is True
    final = json.loads(
        pathlib.Path(completed["final_result_path"]).read_text(encoding="utf-8")
    )
    assert final["classification_totals"]["unassessed"] == 0
    assert final["manifest"]["unclassified_calls"] == 0

    compact = json.loads(
        pathlib.Path(
            json.loads(state_path.read_text(encoding="utf-8"))["manifest"][
                "compact_evidence"
            ]["path"]
        ).read_text(encoding="utf-8")
    )
    episodes = workflow._holistic_episodes(compact)
    one_packet_chars = workflow._json_chars(
        workflow._holistic_luna_payload(
            analysis_id=compact["analysis_id"],
            task_id="luna.discovery.0001",
            ordinal=1,
            episodes=episodes,
            bundle=compact,
        )
    )
    packets = workflow._holistic_partition(
        analysis_id=compact["analysis_id"],
        episodes=episodes,
        bundle=compact,
        budget_chars=max(8_000, one_packet_chars // 2),
    )
    assert len(packets) >= 2
    assert [
        candidate_id
        for packet in packets
        for episode in packet
        for candidate_id in episode["candidate_ids"]
    ] == compact["candidate_ids"]

    synthetic_ids = [f"candidate.synthetic.{index}" for index in range(5)]
    synthetic_records = [
        {"candidate_id": candidate_id, "workstream": "producer"}
        for candidate_id in synthetic_ids
    ]
    synthetic_bundle = {
        "surface_order": compact["surface_order"],
        "analysis_policy": compact["analysis_policy"],
        "canonical_state": [],
        "analysis_generated_activity": [],
        "records": synthetic_records,
        "candidate_ids": synthetic_ids,
    }
    synthetic_episodes = [
        {
            "episode_id": f"episode.synthetic.{index}",
            "turn_id": f"turn.synthetic.{index}",
            "candidate_ids": [candidate_id],
            "user_messages": [],
            "calls": [
                {"candidate_id": candidate_id, "semantic_evidence": "x" * 4_000}
            ],
        }
        for index, candidate_id in enumerate(synthetic_ids, start=1)
    ]
    five_packet_budget = max(
        workflow._json_chars(
            workflow._holistic_luna_payload(
                analysis_id=compact["analysis_id"],
                task_id="luna.discovery.0001",
                ordinal=1,
                episodes=[episode],
                bundle=synthetic_bundle,
            )
        )
        for episode in synthetic_episodes
    )
    five_packets = workflow._holistic_partition(
        analysis_id=compact["analysis_id"],
        episodes=synthetic_episodes,
        bundle=synthetic_bundle,
        budget_chars=five_packet_budget,
    )
    assert len(five_packets) == 5
    assert [
        candidate_id
        for packet in five_packets
        for episode in packet
        for candidate_id in episode["candidate_ids"]
    ] == synthetic_ids

    manifest = json.loads(pathlib.Path(plan["manifest_path"]).read_text(encoding="utf-8"))
    first = manifest["luna_tasks"][0]
    assert len(first["candidate_ids"]) > 1
    split = dict(first)
    midpoint = len(first["candidate_ids"]) // 2
    first["candidate_ids"] = first["candidate_ids"][:midpoint]
    split["candidate_ids"] = split["candidate_ids"][midpoint:]
    split["task_id"] = "luna.discovery.unnecessary"
    manifest["luna_tasks"].insert(1, split)
    manifest["projected_luna_calls"] += 1
    manifest["projected_semantic_calls"] += 1
    manifest["sol_task"]["dependencies"].insert(1, split["task_id"])
    expected_packets = workflow._holistic_partition(
        analysis_id=compact["analysis_id"],
        episodes=episodes,
        bundle=compact,
        budget_chars=json.loads(state_path.read_text(encoding="utf-8"))[
            "model_specs"
        ]["luna"]["evidence_char_budget"],
    )
    with pytest.raises(
        workflow.CreditAnalysisError,
        match="minimum ordered partition",
    ):
        workflow._validate_holistic_manifest(
            manifest,
            workflow._load_contract(),
            expected_packets=expected_packets,
        )

    manifest_path = pathlib.Path(plan["manifest_path"])
    manifest_bytes = manifest_path.read_bytes()
    manifest_value = json.loads(manifest_bytes)
    manifest_value["candidate_ids"] = list(reversed(manifest_value["candidate_ids"]))
    manifest_path.write_text(
        json.dumps(manifest_value),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(
        workflow.CreditAnalysisError,
        match="immutable artifact changed",
    ):
        workflow.command_orchestration_status(state_path)
    manifest_path.write_bytes(manifest_bytes)
