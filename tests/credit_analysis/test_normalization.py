from __future__ import annotations

import json
import os
import pathlib
import subprocess
import threading
from collections.abc import Mapping
from typing import Any

import pytest
from jsonschema import Draft202012Validator

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
    assert resumed["next_task"] == "luna.discovery.0002"
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
    monkeypatch: pytest.MonkeyPatch,
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
        extra_calls_per_turn=12,
    )
    plan = workflow.command_plan_orchestration(
        request,
        available_models=holistic_model_catalog(),
    )

    class TransportVariationRunner(FakeCreditModelRunner):
        def __init__(self) -> None:
            super().__init__()
            self.variation_lock = threading.Lock()
            self.variation_applied = False
            self.colliding_luna_ids: set[str] = set()
            self.reclassified_candidate_id: str | None = None
            self.normalized_review_source: str | None = None
            self.variation_task_id: str | None = None
            self.expected_unassessed = 0
            self.shard_local_unassessed_limit = 0

        def _luna(
            self,
            task: Mapping[str, Any],
            packet: Mapping[str, Any],
            digest: str,
        ) -> dict[str, Any]:
            result = super()._luna(task, packet, digest)
            with self.variation_lock:
                self.colliding_luna_ids.update(
                    str(candidate["candidate_ids"][0])
                    for candidate in result["candidates"]
                )
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
            for review in result["helper_category_reviews"]:
                review["reason"] += f" Source: {task['task_id']}."
            result["helper_category_reviews"][0].update(
                applies=task["task_id"].endswith("0001"),
                evidence_refs=result["candidate_decisions"][0]["evidence_refs"],
            )
            call_order = [row[1] for row in packet["call_inventory"]["rows"]]
            packet_candidates = [
                candidate
                for luna_result in packet["luna_results"]
                for candidate in luna_result["candidates"]
            ]
            try:
                reclassified_candidate_index = next(
                    index
                    for index, candidate in enumerate(packet_candidates)
                    if candidate["kind"] == "plausible-risk"
                )
                finding = next(
                    item
                    for item in result["confirmed_findings"]
                    if item["waste_kind"] == "model-calls"
                    and len(item["affected_call_ids"]) > 1
                )
                implemented_finding = next(
                    item
                    for item in result["confirmed_findings"]
                    if item["waste_kind"] == "model-calls"
                    and item["implementation_status"] == "implemented"
                )
                model_call_finding_calls = {
                    call_id
                    for item in result["confirmed_findings"]
                    if item["waste_kind"] == "model-calls"
                    for call_id in item["affected_call_ids"]
                }
                volume_call = next(
                    call_id
                    for item in result["confirmed_findings"]
                    if item["waste_kind"] == "context-volume"
                    for call_id in item["affected_call_ids"]
                    if call_id not in model_call_finding_calls
                )
                review = next(
                    item
                    for item in result["temporary_control_reviews"]
                    if item["disposition"] == "permanently-implemented"
                )
                nonavoidable_call = next(
                    call_id
                    for group in result["call_classifications"]
                    if not group["classification"].startswith("avoidable_")
                    for call_id in group["call_ids"]
                    if call_id != volume_call
                )
            except StopIteration:
                return result
            if len(result["temporary_control_reviews"]) < 3:
                return result
            classification_by_call = {
                call_id: group["classification"]
                for group in result["call_classifications"]
                for call_id in group["call_ids"]
            }
            coverage_fraction = float(
                workflow._load_contract()["coverage"][
                    "maximum_unassessed_fraction"
                ]
            )
            shard_local_limit = int(len(call_order) * coverage_fraction)
            orphan_pool = [
                volume_call,
                *[
                    call_id
                    for call_id in call_order
                    if call_id not in model_call_finding_calls
                    and call_id not in {volume_call, nonavoidable_call}
                    and not classification_by_call[call_id].startswith("avoidable_")
                ],
            ]
            orphan_calls = orphan_pool[: shard_local_limit + 1]
            if len(orphan_calls) <= shard_local_limit:
                return result
            with self.variation_lock:
                if self.variation_applied:
                    return result
                self.variation_applied = True
                self.expected_unassessed = len(orphan_calls)
                self.shard_local_unassessed_limit = shard_local_limit
                self.reclassified_candidate_id = str(
                    packet_candidates[reclassified_candidate_index]["id"]
                )
                self.variation_task_id = str(task["task_id"])
            plausible_candidate_id = str(
                packet_candidates[reclassified_candidate_index]["id"]
            )
            moved_review = result["temporary_control_reviews"][2]
            result["temporary_control_reviews"][0][
                "source_luna_candidate_ids"
            ].extend(
                [
                    plausible_candidate_id,
                    *moved_review["source_luna_candidate_ids"],
                ]
            )
            mixed_decision = next(
                item
                for item in result["candidate_decisions"]
                if item["luna_candidate_id"] == plausible_candidate_id
            )
            mixed_decision["finding_ids"] = [implemented_finding["id"]]
            mixed_decision["reason"] = (
                "The candidate has a confirmed subclaim and a separate unresolved risk."
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
            orphan_call_set = set(orphan_calls)
            orphaned_groups: list[dict[str, Any]] = []
            for group in result["call_classifications"]:
                selected = [
                    call_id
                    for call_id in group["call_ids"]
                    if call_id in orphan_call_set
                ]
                if not selected:
                    orphaned_groups.append(group)
                    continue
                remaining = [
                    call_id
                    for call_id in group["call_ids"]
                    if call_id not in orphan_call_set
                ]
                if remaining:
                    orphaned_groups.append({**group, "call_ids": remaining})
                orphaned_groups.append(
                    {
                        **group,
                        "call_ids": selected,
                        "classification": "avoidable_implemented",
                        "reason_code": None,
                    }
                )
            result["call_classifications"] = orphaned_groups
            historical_source = result["temporary_control_reviews"][0][
                "source_luna_candidate_ids"
            ][0]
            historical_decision = next(
                item
                for item in result["candidate_decisions"]
                if item["luna_candidate_id"] == historical_source
            )
            historical_decision["finding_ids"] = [implemented_finding["id"]]
            historical_decision["risk_ids"] = []

            review["finding_id"] = finding["id"]
            review["no_finding_reason"] = None
            source_id = review["source_luna_candidate_ids"][0]
            self.normalized_review_source = source_id
            decision = next(
                item
                for item in result["candidate_decisions"]
                if item["luna_candidate_id"] == source_id
            )
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
    assert runner.variation_applied is True
    assert sum(call["phase"] == "sol-adjudication" for call in runner.calls) == 3
    assert sum(call["phase"] == "sol-direct-evidence" for call in runner.calls) == 1
    assert sum(call["phase"] == "sol-final" for call in runner.calls) == 1
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
    assert flattened == [
        call_id for call_id in manifest["call_ids"] if call_id in set(flattened)
    ]
    assert len(flattened) == final["coverage"]["analyzed_calls"]
    assert sum(
        len(group["call_ids"])
        for group in final["call_classifications"]
        if group["classification"] == "unassessed"
    ) == 0
    assert runner.expected_unassessed > runner.shard_local_unassessed_limit
    finding_calls = {
        call_id
        for finding in final["confirmed_findings"]
        if finding["waste_kind"] == "model-calls"
        for call_id in finding["affected_call_ids"]
    }
    observed_without_finding = {
        call_id
        for group in final["call_classifications"]
        if group["classification"].startswith("avoidable_")
        for call_id in group["call_ids"]
        if call_id not in finding_calls
    }
    assert len(observed_without_finding) >= runner.expected_unassessed
    state = json.loads(pathlib.Path(plan["state_path"]).read_text(encoding="utf-8"))
    assert runner.variation_task_id is not None
    shard_record = state["execution"][runner.variation_task_id]["result"]
    shard = json.loads(
        pathlib.Path(shard_record["path"]).read_text(encoding="utf-8")
    )
    mixed_decision = next(
        item
        for item in shard["candidate_decisions"]
        if "separate unresolved risk" in item["reason"]
    )
    assert mixed_decision["disposition"] == "confirmed-finding"
    assert mixed_decision["finding_ids"]
    assert mixed_decision["risk_ids"]
    shard_reviewed_sources = [
        candidate_id
        for review in shard["temporary_control_reviews"]
        for candidate_id in review["source_luna_candidate_ids"]
    ]
    assert len(shard_reviewed_sources) > len(set(shard_reviewed_sources))
    reviewed_sources = [
        candidate_id
        for review in final["temporary_control_reviews"]
        for candidate_id in review["source_luna_candidate_ids"]
    ]
    duplicate_review_sources = {
        candidate_id
        for candidate_id in reviewed_sources
        if reviewed_sources.count(candidate_id) > 1
    }
    assert duplicate_review_sources
    for candidate_id in duplicate_review_sources:
        owner_controls = [
            (review["owning_producer"], review["observed_temporary_control"])
            for review in final["temporary_control_reviews"]
            if candidate_id in review["source_luna_candidate_ids"]
        ]
        assert len(owner_controls) == len(set(owner_controls))
    assert any(
        decision["disposition"] == "confirmed-finding"
        and decision["finding_ids"]
        and decision["risk_ids"]
        and decision["luna_candidate_id"] in reviewed_sources
        for decision in final["candidate_decisions"]
    )
    transient_review = next(
        review
        for review in final["temporary_control_reviews"]
        if review["disposition"] == "transient-by-design"
    )
    assert transient_review["finding_id"] is None
    assert transient_review["no_finding_reason"]
    assert all(
        finding["observed_avoidable_call_count"]
        == len(finding["affected_call_ids"])
        for finding in final["confirmed_findings"]
        if finding["waste_kind"] == "model-calls"
    )
    normalized_review = next(
        item
        for item in shard["temporary_control_reviews"]
        if item["disposition"] == "permanently-implemented"
    )
    assert normalized_review["finding_id"] is None
    assert normalized_review["no_finding_reason"]
    normalized_decision = next(
        item
        for item in shard["candidate_decisions"]
        if item["luna_candidate_id"]
        == normalized_review["source_luna_candidate_ids"][0]
    )
    assert normalized_decision["disposition"] == "confirmed-finding"
    assert normalized_decision["finding_ids"]
    shard_findings = {
        finding["id"]: finding for finding in shard["confirmed_findings"]
    }
    assert any(
        shard_findings[finding_id]["implementation_status"] == "unimplemented"
        for finding_id in normalized_decision["finding_ids"]
    )
    assert all(
        merge["control_key"] != "implemented-control-is-not-a-gap"
        for merge in final["temporary_control_merges"]
    )

    final_execution = state["execution"]["sol.final"]
    assert len(final_execution["attempts"]) == 1
    raw_path = pathlib.Path(final_execution["attempts"][0]["artifacts"]["raw_output"]["path"])
    raw_bytes = raw_path.read_bytes()
    assert json.loads(raw_bytes)["temporary_control_merges"] == []
    canonical = json.loads(
        pathlib.Path(final_execution["result"]["path"]).read_text(encoding="utf-8")
    )
    active, evidence, contract, compact = workflow._holistic_read_state(
        pathlib.Path(plan["state_path"])
    )
    task = workflow._holistic_task_map(active["manifest"])["sol.final"]
    _, digest, _, _, candidate_ids = workflow._holistic_prepare_task(
        active, evidence, contract, compact, task
    )

    def validate_report(report: dict[str, Any]) -> dict[str, Any]:
        return workflow._validate_holistic_task_result(
            report, state=active, task=task, input_sha256=digest,
            contract=contract, compact=compact, luna_candidate_ids=candidate_ids,
        )

    def report_copy() -> dict[str, Any]:
        return json.loads(json.dumps(canonical))

    prior_results = []
    for shard_task in active["manifest"]["sol_tasks"][:6]:
        record = active["execution"][shard_task["task_id"]]["result"]
        if record is not None:
            prior_results.append(workflow._thread_review_orchestration._namespaced_adjudication_result(
                json.loads(pathlib.Path(record["path"]).read_text(encoding="utf-8")),
                shard_task["task_id"],
            ))
    expected_findings = {
        finding["id"]: finding for prior in prior_results for finding in prior["confirmed_findings"]
    }
    finding_sources = [
        source for finding in canonical["confirmed_findings"] for source in finding["source_findings"]
    ]
    assert {source["id"]: source for source in finding_sources} == expected_findings
    assert len(finding_sources) == len(expected_findings)
    assert any(len(finding["source_findings"]) > 1 for finding in canonical["confirmed_findings"])
    assert all("source_findings" not in finding for finding in json.loads(raw_bytes)["confirmed_findings"])
    assert {finding["id"]: finding["source_findings"] for finding in final["confirmed_findings"]} == {
        finding["id"]: finding["source_findings"] for finding in canonical["confirmed_findings"]
    }

    changed_source = report_copy()
    changed_source["confirmed_findings"][0]["source_findings"][0]["proposed_durable_control"] = "Replaced original control."
    with pytest.raises(workflow.CreditAnalysisError, match="source records changed"):
        validate_report(changed_source)
    omitted_source = report_copy()
    omitted_source["confirmed_findings"][0]["source_findings"].pop()
    with pytest.raises(workflow.CreditAnalysisError, match="source records changed"):
        validate_report(omitted_source)

    preserve_findings = workflow._thread_review_orchestration._holistic_preserve_finding_sources

    def preserve_report_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
        return preserve_findings(report["confirmed_findings"], report["candidate_decisions"], prior_results)

    missing_finding_owner = report_copy()
    merged_finding = missing_finding_owner["confirmed_findings"][0]
    for decision in missing_finding_owner["candidate_decisions"]:
        decision["finding_ids"] = [value for value in decision["finding_ids"] if value != merged_finding["id"]]
    with pytest.raises(workflow.CreditAnalysisError, match="final ownership is missing"):
        preserve_report_findings(missing_finding_owner)

    for field in ("affected_call_ids", "evidence_refs"):
        incomplete_finding = report_copy()
        finding = incomplete_finding["confirmed_findings"][0]
        finding[field].remove(finding["source_findings"][0][field][0])
        with pytest.raises(workflow.CreditAnalysisError, match="evidence coverage is incomplete"):
            preserve_report_findings(incomplete_finding)

    ambiguous_finding = report_copy()
    first_finding = ambiguous_finding["confirmed_findings"][0]
    duplicate_finding = {**first_finding, "id": "another-combined-finding"}
    duplicate_finding.pop("source_findings")
    ambiguous_finding["confirmed_findings"].append(duplicate_finding)
    for decision in ambiguous_finding["candidate_decisions"]:
        if first_finding["id"] in decision["finding_ids"]:
            decision["finding_ids"].append(duplicate_finding["id"])
    with pytest.raises(workflow.CreditAnalysisError, match="final ownership is ambiguous"):
        preserve_report_findings(ambiguous_finding)

    source = expected_findings[next(iter(expected_findings))]
    with pytest.raises(workflow.CreditAnalysisError, match="unknown source_findings"):
        workflow._thread_review_orchestration._validate_holistic_finding(
            {**source, "source_findings": []}, contract=contract,
            call_order=active["manifest"]["call_ids"],
            workstreams=workflow._thread_review_orchestration._holistic_workstream_by_call(compact),
            surface_order=active["manifest"]["surface_order"], label="non-final finding",
        )

    missing = report_copy()
    missing["temporary_control_merges"] = []
    missing_before = json.dumps(missing, sort_keys=True)
    assert validate_report(missing)["temporary_control_merges"]
    assert json.dumps(missing, sort_keys=True) == missing_before
    assert validate_report(report_copy()) == canonical
    assert raw_path.read_bytes() == raw_bytes

    merge = canonical["temporary_control_merges"][0]
    linked_ids = merge["review_ids"]
    assert len(linked_ids) >= 2
    linked = {
        review["id"]: review for review in canonical["temporary_control_reviews"]
        if review["id"] in linked_ids
    }
    assert merge["owning_producer"] == linked[linked_ids[0]]["owning_producer"]
    finding = next(
        item for item in canonical["confirmed_findings"] if item["id"] == merge["finding_id"]
    )
    assert merge["control_key"]
    assert finding["proposed_durable_control"]
    partial = report_copy()
    partial["temporary_control_merges"][0]["review_ids"] = linked_ids[:-1]
    assert set(linked_ids).issubset({
        review_id
        for item in validate_report(partial)["temporary_control_merges"]
        for review_id in item["review_ids"]
    })

    # Bad supplied ownership must fail before the missing-link repair runs.
    for field, value, error in (
        ("review_ids", ["unknown-review"], "review ownership is invalid"),
        ("finding_id", "unknown-finding", "finding ownership is invalid"),
        ("finding_id", [], "finding ownership is invalid"),
        ("owning_producer", "different-owner", "producer ownership is invalid"),
        ("owning_producer", None, "owning_producer is invalid"),
        ("control_key", " ", "control_key is invalid"),
    ):
        invalid = report_copy()
        invalid["temporary_control_merges"][0][field] = value
        with pytest.raises(workflow.CreditAnalysisError, match=error):
            validate_report(invalid)

    duplicate = report_copy()
    duplicate["temporary_control_merges"].append(dict(merge))
    with pytest.raises(workflow.CreditAnalysisError, match="owner/control is merged twice"):
        validate_report(duplicate)
    duplicate["temporary_control_merges"][-1]["control_key"] = "another-control"
    with pytest.raises(workflow.CreditAnalysisError, match="review ownership is invalid"):
        validate_report(duplicate)

    for owner, error in (
        ("different-owner", "merge ownership is ambiguous"),
        (" ", "owner is invalid"),
    ):
        ambiguous = report_copy()
        ambiguous["temporary_control_merges"] = []
        next(
            item for item in ambiguous["temporary_control_reviews"] if item["id"] == linked_ids[0]
        )["owning_producer"] = owner
        with pytest.raises(workflow.CreditAnalysisError, match=error):
            validate_report(ambiguous)

    ambiguous = report_copy()
    ambiguous["temporary_control_merges"] = [
        {**merge, "review_ids": linked_ids[:1]},
        {**merge, "review_ids": linked_ids[1:], "control_key": "another-control"},
    ]
    ambiguous["temporary_control_reviews"].append(
        {**linked[linked_ids[0]], "id": "extra-review-without-a-merge"}
    )
    with pytest.raises(workflow.CreditAnalysisError, match="merge ownership is ambiguous"):
        validate_report(ambiguous)

    contradictory = report_copy()
    contradictory["temporary_control_merges"] = []
    for group in contradictory["call_classifications"]:
        group["classification"] = "necessary"
        group["reason_code"] = "required-workflow"
    with pytest.raises(workflow.CreditAnalysisError, match="model-call finding has no avoidable call evidence"):
        validate_report(contradictory)

    rewritten_risk = report_copy()
    rewritten_risk["temporary_control_merges"] = []
    risk = rewritten_risk["plausible_risks"][0]
    prior_id = risk["id"]
    risk["id"] = "renamed-prior-risk"
    risk["description"] += " Rephrased without retaining its original identity."
    for item in [*rewritten_risk["candidate_decisions"], *rewritten_risk["surface_summaries"]]:
        item["risk_ids"] = [risk["id"] if value == prior_id else value for value in item["risk_ids"]]
    preserved = validate_report(rewritten_risk)
    assert preserved["plausible_risks"][0]["source_risks"] == risk["source_risks"]
    assert len(risk["source_risks"]) >= 3
    assert len({source["id"] for source in risk["source_risks"]}) == len(risk["source_risks"])
    report_text = workflow._render_holistic_report(final)
    retained_risk_sources = [
        source for retained in final["plausible_risks"]
        for source in retained["source_risks"]
    ]
    for source in risk["source_risks"]:
        assert source in retained_risk_sources
        assert source["description"] not in report_text
        assert source["missing_fact"] not in report_text

    tampered = report_copy()
    tampered["plausible_risks"][0]["source_risks"][0]["missing_fact"] = "Silently replaced uncertainty."
    with pytest.raises(workflow.CreditAnalysisError, match="source records changed"):
        validate_report(tampered)

    for field in ("affected_call_ids", "evidence_refs"):
        incomplete = report_copy()
        source_value = incomplete["plausible_risks"][0]["source_risks"][0][field][0]
        incomplete["plausible_risks"][0][field].remove(source_value)
        with pytest.raises(workflow.CreditAnalysisError, match="evidence coverage is incomplete"):
            validate_report(incomplete)

    missing_owner = report_copy()
    decision = next(item for item in missing_owner["candidate_decisions"] if item["risk_ids"])
    decision["risk_ids"] = []
    decision["disposition"] = "confirmed-finding" if decision["finding_ids"] else "dismissed-candidate"
    with pytest.raises(workflow.CreditAnalysisError, match="final ownership is missing"):
        validate_report(missing_owner)

    ambiguous = report_copy()
    duplicate_risk = {**ambiguous["plausible_risks"][0], "id": "another-combined-risk"}
    duplicate_risk.pop("source_risks")
    ambiguous["plausible_risks"].append(duplicate_risk)
    for decision in ambiguous["candidate_decisions"]:
        if decision["risk_ids"]:
            decision["risk_ids"].append(duplicate_risk["id"])
    with pytest.raises(workflow.CreditAnalysisError, match="final ownership is ambiguous"):
        validate_report(ambiguous)

    # One candidate can independently support a merged risk and a narrower
    # risk. Only a destination covering the entire source can preserve it.
    source_risk = {**canonical["plausible_risks"][0], "id": "source-risk"}
    source_risk.pop("source_risks")
    assert len(source_risk["affected_call_ids"]) > 1
    full_risk = {**source_risk, "id": "full-risk"}
    narrow_risk = {
        **source_risk, "id": "narrow-risk",
        "affected_call_ids": source_risk["affected_call_ids"][:1],
        "evidence_refs": source_risk["evidence_refs"][:1],
    }
    preserve_risks = workflow._thread_review_orchestration._holistic_preserve_risk_sources
    source_risk_results = [{
        "plausible_risks": [source_risk],
        "candidate_decisions": [{"luna_candidate_id": "risk-candidate", "risk_ids": ["source-risk"]}],
    }]
    risk_decisions = [{"luna_candidate_id": "risk-candidate", "risk_ids": ["full-risk", "narrow-risk"]}]
    preserved_risks = preserve_risks([full_risk, narrow_risk], risk_decisions, source_risk_results)
    assert preserved_risks[0]["source_risks"] == [source_risk]
    assert preserved_risks[1]["source_risks"] == []
    assert preserve_risks(preserved_risks, risk_decisions, source_risk_results) == preserved_risks
    for full_destination in (
        {**full_risk, "affected_call_ids": narrow_risk["affected_call_ids"]},
        {**full_risk, "evidence_refs": narrow_risk["evidence_refs"]},
    ):
        with pytest.raises(workflow.CreditAnalysisError, match="evidence coverage is incomplete"):
            preserve_risks([full_destination, narrow_risk], risk_decisions, source_risk_results)
    with pytest.raises(workflow.CreditAnalysisError, match="final ownership is ambiguous"):
        preserve_risks([full_risk, {**full_risk, "id": "narrow-risk"}], risk_decisions, source_risk_results)
    retained_id = {**narrow_risk, "id": "source-risk"}
    with pytest.raises(workflow.CreditAnalysisError, match="evidence coverage is incomplete"):
        preserve_risks([full_risk, retained_id], [{**risk_decisions[0], "risk_ids": ["full-risk", "source-risk"]}], source_risk_results)

    categories = canonical["helper_category_reviews"]
    assert [item["category"] for item in categories] == contract["helper_categories"]
    assert json.loads(raw_bytes)["helper_category_reviews"] == []
    category = categories[0]
    assert {source["review"]["applies"] for source in category["source_reviews"]} == {False, True}
    assert category["applies"] is True
    assert set(category["evidence_refs"]) == {
        ref for source in category["source_reviews"] for ref in source["review"]["evidence_refs"]
    }
    for source in category["source_reviews"]:
        record = active["execution"][source["task_id"]]["result"]
        prior = json.loads(pathlib.Path(record["path"]).read_text(encoding="utf-8"))
        assert source["review"] in prior["helper_category_reviews"]

    duplicates = report_copy()
    negative = next(source["review"] for source in category["source_reviews"] if not source["review"]["applies"])
    duplicates["helper_category_reviews"] = [*categories[1:], dict(negative), dict(negative)]
    assert validate_report(duplicates) == canonical

    for field, value, error in (
        ("category", "unknown-category", "unknown category"),
        ("applies", "yes", "applicability is invalid"),
        ("reason", "", "reason is empty"),
    ):
        invalid = report_copy()
        invalid["helper_category_reviews"][0][field] = value
        with pytest.raises(workflow.CreditAnalysisError, match=error):
            validate_report(invalid)
    missing_category = report_copy()
    missing_category["helper_category_reviews"].pop()
    with pytest.raises(workflow.CreditAnalysisError, match="category reviews are missing"):
        validate_report(missing_category)
    tampered_category = report_copy()
    tampered_category["helper_category_reviews"][0]["source_reviews"][0]["review"]["reason"] = "Rewritten source."
    with pytest.raises(workflow.CreditAnalysisError, match="source records changed"):
        validate_report(tampered_category)
    conflicting_category = report_copy()
    conflicting_category["helper_category_reviews"][0].update(applies=False, reason="No issue anywhere.")
    with pytest.raises(workflow.CreditAnalysisError, match="dropped supported applicability"):
        validate_report(conflicting_category)
    untraceable = report_copy()
    untraceable["helper_category_reviews"] = [
        *categories[1:], dict(negative), {**negative, "reason": "A new conflicting assessment."},
    ]
    with pytest.raises(workflow.CreditAnalysisError, match="untraceable repeated assessments"):
        validate_report(untraceable)

    snapshot = pathlib.Path(active["immutable_artifacts"]["surface_contract"]["path"])
    assert snapshot.parent == pathlib.Path(active["paths"]["orchestration_root"])
    original_contract = snapshot.read_bytes()
    assert original_contract == workflow.CONTRACT_PATH.read_bytes()
    try:
        snapshot.write_bytes(original_contract + b"\n")
        with pytest.raises(workflow.CreditAnalysisError, match="immutable artifact changed: surface_contract"):
            workflow._holistic_read_state(pathlib.Path(plan["state_path"]))
    finally:
        snapshot.write_bytes(original_contract)

    implementation = workflow._thread_review_orchestration
    build_audit = implementation._holistic_audit_input
    for reject_all in (False, True):
        routing_state = json.loads(json.dumps(active))
        routing_state.update(routing=None, omissions=[])
        routing_state["model_attempts"]["sol"] = 0
        routing_root = tmp_path / ("no-audit-fits" if reject_all else "next-audit-fits")
        routing_root.mkdir()
        routing_state["paths"]["orchestration_root"] = str(routing_root)
        probes: list[str] = []

        def measured_audit(
            *, reject_all=reject_all, probes=probes,
            budget=routing_state["model_specs"]["sol"]["evidence_byte_budget"], **kwargs,
        ):
            payload = build_audit(**kwargs)
            if reject_all or not probes:
                payload["fixture_overhead"] = "x" * budget
            probes.append(kwargs["task"]["audit_windows"][0]["luna_task_id"])
            return payload

        with monkeypatch.context() as patch:
            patch.setattr(implementation, "_holistic_audit_input", measured_audit)
            implementation._freeze_sol_routing(routing_state, compact, contract)
        selected = json.loads(pathlib.Path(routing_state["routing"]["path"]).read_text(encoding="utf-8"))
        assert len(probes) > 1
        if reject_all:
            assert selected["audit_windows"] == []
            assert len(routing_state["omissions"]) == len(probes)
        else:
            assert [item["luna_task_id"] for item in selected["audit_windows"]] == [probes[1]]
            selected_task = next(item for item in active["manifest"]["luna_tasks"] if item["task_id"] == probes[1])
            assert selected["audit_candidate_ids"] == selected_task["candidate_ids"]
            assert len(routing_state["omissions"]) == 1
        for omission in routing_state["omissions"]:
            original_task = next(item for item in active["manifest"]["luna_tasks"] if item["task_id"] == omission["task_id"])
            assert omission["reason"] == "direct-evidence-capacity"
            assert omission["candidate_ids"] == original_task["candidate_ids"]

    retained_review = next(
        review for review in canonical["temporary_control_reviews"]
        if review["source_reviews"] and review["disposition"] == "final-state-unclear"
    )
    expected_reviews = {}
    for shard_task in active["manifest"]["sol_tasks"][:6]:
        record = active["execution"][shard_task["task_id"]]["result"]
        if record is not None:
            prior = workflow._thread_review_orchestration._namespaced_adjudication_result(
                json.loads(pathlib.Path(record["path"]).read_text(encoding="utf-8")), shard_task["task_id"]
            )
            expected_reviews.update({review["id"]: review for review in prior["temporary_control_reviews"]})
    sources = [source for review in canonical["temporary_control_reviews"] for source in review["source_reviews"]]
    assert {source["id"]: source for source in sources} == expected_reviews
    assert len(sources) == len(expected_reviews)

    def review_copy() -> tuple[dict[str, Any], dict[str, Any]]:
        report = report_copy()
        review = next(item for item in report["temporary_control_reviews"] if item["id"] == retained_review["id"])
        return report, review

    tampered, review = review_copy()
    review["source_reviews"][0]["no_finding_reason"] = "Replaced original judgment."
    with pytest.raises(workflow.CreditAnalysisError, match="source records changed"):
        validate_report(tampered)


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
    assert specs["luna"]["reasoning_effort"] == "max"
    assert specs["sol"]["reasoning_effort"] == "max"
    assert specs["luna"]["evidence_token_budget"] > 200_000
    assert specs["sol"]["output_reserve_tokens"] == 48_000
    assert specs["sol"]["evidence_token_budget"] > 160_000


@pytest.mark.parametrize(
    ("timed_out", "exit_code", "startup_log", "expected_error"),
    [
        (True, 1, "unrelated startup warning\n",
         "Codex child failed for test-review with exit 1: timed out after 1200s"),
        (True, 0, "unrelated startup warning\n",
         "Codex child failed for test-review with exit 0: timed out after 1200s"),
        (False, 7, "actual child failure\n",
         "Codex child failed for test-review with exit 7: actual child failure"),
        (False, 7, "", "Codex child failed for test-review with exit 7"),
        (False, 0, "unrelated startup warning\n", None),
    ],
)
def test_credit_analysis_child_command_places_global_approval_before_exec(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    timed_out: bool,
    exit_code: int,
    startup_log: str,
    expected_error: str | None,
) -> None:
    workflow = load_credit_analysis_workflow_module()
    command = workflow._codex_child_command(
        executable="codex",
        model="gpt-5.6-luna",
        reasoning_effort="medium",
        schema_path=pathlib.Path("schema.json"),
        raw_output=pathlib.Path("result.json"),
        execution_cwd=pathlib.Path("."),
    )
    assert command.index("--ask-for-approval") < command.index("exec")
    assert 'model_reasoning_effort="medium"' in command
    assert "--ephemeral" not in command
    assert "--sandbox" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    persistent = workflow._codex_child_command(
        executable="codex",
        model="gpt-5.6-sol",
        reasoning_effort="max",
        schema_path=pathlib.Path("schema.json"),
        raw_output=pathlib.Path("result.json"),
        execution_cwd=pathlib.Path("."),
    )
    assert "--ephemeral" not in persistent
    assert persistent[persistent.index("--cd") + 1] == "."

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

    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("Read-only review.", encoding="utf-8")
    attempt_dir = tmp_path / "attempt"
    runner_process = FakeProcess()
    clock = [0.0]
    terminated: list[FakeProcess] = []

    def fake_popen(*args: Any, **kwargs: Any) -> FakeProcess:
        kwargs["stderr"].write(startup_log)
        (attempt_dir / "last-message.json").write_text(
            '{"value": 1}', encoding="utf-8"
        )
        clock[0] = 1200.0
        return runner_process

    def terminate_child(child: FakeProcess) -> int:
        terminated.append(child)
        return exit_code

    with monkeypatch.context() as child_patch:
        child_patch.setattr(workflow.shutil, "which", lambda name: "codex")
        child_patch.setattr(workflow.subprocess, "Popen", fake_popen)
        child_patch.setattr(workflow.time, "monotonic", lambda: clock[0])
        child_patch.setattr(
            workflow.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        )
        child_patch.setattr(workflow, "_process_is_alive", lambda pid: True)
        child_patch.setattr(workflow, "_terminate_process_tree", terminate_child)
        child_patch.setattr(
            runner_process, "poll", lambda: None if timed_out else exit_code
        )
        result, attempt = workflow._run_codex_child(
            analysis_id="test-analysis",
            model="gpt-5.6-sol",
            task={"task_id": "test-review"},
            prompt_path=prompt_path,
            schema_path=tmp_path / "schema.json",
            attempt_dir=attempt_dir,
            execution_cwd=tmp_path,
        )

    assert result == ({"value": 1} if expected_error is None else None)
    assert attempt["error"] == expected_error
    assert attempt["timed_out"] is timed_out
    assert attempt["terminated"] is timed_out
    if timed_out:
        assert attempt["duration_ms"] == 1_200_000
    assert attempt["model_invoked"] is True
    assert attempt["exit_code"] == exit_code
    assert terminated == ([runner_process] if timed_out else [])
    assert pathlib.Path(attempt["stderr_path"]).read_text(encoding="utf-8") == startup_log


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
    failed = workflow.command_execute_orchestration(
        state_path,
        runner=bad_luna,
        available_models=bad_luna.available_models,
        task_limit=1,
    )
    assert failed["next_task"] == "luna.discovery.0002"
    failed_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert failed_state["model_attempts"] == {"luna": 2, "sol": 0}
    assert failed_state["model_calls"] == {"luna": 0, "sol": 0}
    failed_attempts = failed_state["execution"]["luna.discovery.0001"][
        "attempts"
    ]
    assert [attempt["outcome"] for attempt in failed_attempts] == [
        "validation-error",
        "validation-error",
    ]
    assert failed_attempts[1]["output_byte_limit"] < failed_attempts[0][
        "output_byte_limit"
    ]
    assert failed_state["execution"]["luna.discovery.0001"]["status"] == "omitted"
    assert any(
        omission["task_id"] == "luna.discovery.0001"
        and omission["reason"] == "luna-invalid-output"
        for omission in failed_state["omissions"]
    )

    good = FakeCreditModelRunner()
    pending_luna = sum(
        failed_state["execution"][task["task_id"]]["status"] == "pending"
        for task in failed_state["manifest"]["luna_tasks"]
    )
    resumed = workflow.command_execute_orchestration(
        state_path,
        runner=good,
        available_models=good.available_models,
        task_limit=pending_luna,
    )
    assert resumed["next_task"] == "sol.adjudication.0001"
    resumed_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert resumed_state["model_attempts"]["luna"] == 2 + pending_luna
    assert resumed_state["model_calls"]["luna"] == pending_luna

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
    active_state, evidence, contract, compact = workflow._holistic_read_state(
        state_path
    )
    base_task = workflow._holistic_task_map(active_state["manifest"])[
        "sol.adjudication.0001"
    ]
    routing = json.loads(
        pathlib.Path(active_state["routing"]["path"]).read_text(encoding="utf-8")
    )
    sol_task = {
        **base_task,
        **next(
            shard
            for shard in routing["shards"]
            if shard["task_id"] == base_task["task_id"]
        ),
    }
    payload, digest, _, _, candidate_ids = workflow._holistic_prepare_task(
        active_state, evidence, contract, compact, sol_task
    )
    verbose_raw = verbose_sol._sol(sol_task, payload, digest)
    with pytest.raises(
        workflow.CreditAnalysisError,
        match="320-character semantic bound",
    ):
        workflow._validate_holistic_task_result(
            verbose_raw,
            state=active_state,
            task=sol_task,
            input_sha256=digest,
            contract=contract,
            compact=compact,
            luna_candidate_ids=candidate_ids,
        )

    schema = json.loads(
        pathlib.Path(sol_task["artifacts"]["schema"]).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    schema_validator = Draft202012Validator(schema)
    response = good._sol(sol_task, payload, digest)
    original_response = json.dumps(response, sort_keys=True)

    result_id_schema = schema["properties"]["confirmed_findings"]["items"]["properties"]["id"]
    for identifier in ("f01", "0", "finding.with-parts_2", "F01", "", "bad id", "/bad", "f01\n", "f01\r\n", "f01\u2028"):
        assert Draft202012Validator(result_id_schema).is_valid(identifier) == (
            workflow.IDENTIFIER_RE.fullmatch(identifier) is not None
        )

    def validate_response(value: dict[str, Any]) -> dict[str, Any]:
        return workflow._validate_holistic_task_result(
            value, state=active_state, task=sol_task, input_sha256=digest,
            contract=contract, compact=compact, luna_candidate_ids=candidate_ids,
        )

    def rename_result_id(value: Any, old: str, new: str) -> Any:
        if isinstance(value, dict):
            return {key: rename_result_id(item, old, new) for key, item in value.items()}
        if isinstance(value, list):
            return [rename_result_id(item, old, new) for item in value]
        return new if value == old else value

    # The recorded uppercase ID must fail the supplied schema and the Python
    # boundary alike, while the corrected ID keeps every reference and judgment.
    original_id = response["confirmed_findings"][0]["id"]
    invalid_id = rename_result_id(response, original_id, "F01")
    assert not schema_validator.is_valid(invalid_id)
    with pytest.raises(workflow.CreditAnalysisError, match=r"confirmed_findings\[0\]\.id must match pattern"):
        validate_response(invalid_id)
    corrected_id = rename_result_id(invalid_id, "F01", "f01")
    schema_validator.validate(corrected_id)
    accepted_id = validate_response(corrected_id)
    accepted_finding = next(item for item in accepted_id["confirmed_findings"] if item["id"] == "f01")
    for field in ("problem_summary", "waste_kind", "proposed_durable_control"):
        assert accepted_finding[field] == response["confirmed_findings"][0][field]
    from credit_analysis import model_response_contract as response_contract
    response_contract.validate_response_correction(invalid_id, corrected_id, schema)

    inconsistent_id = json.loads(json.dumps(corrected_id))
    linked_decision = next(item for item in inconsistent_id["candidate_decisions"] if "f01" in item["finding_ids"])
    linked_decision["finding_ids"] = ["other-id" if value == "f01" else value for value in linked_decision["finding_ids"]]
    schema_validator.validate(inconsistent_id)
    with pytest.raises(workflow.CreditAnalysisError, match="protected response field"):
        response_contract.validate_response_correction(invalid_id, inconsistent_id, schema)

    for field, changed_value in (
        ("waste_kind", next(value for value in contract["waste_kinds"] if value != response["confirmed_findings"][0]["waste_kind"])),
        ("proposed_durable_control", "A different proposed control."),
        ("evidence_refs", [next(value for value in schema["properties"]["confirmed_findings"]["items"]["properties"]["evidence_refs"]["items"]["enum"] if value not in response["confirmed_findings"][0]["evidence_refs"])]),
    ):
        changed_judgment = json.loads(json.dumps(corrected_id))
        changed_judgment["confirmed_findings"][0][field] = changed_value
        schema_validator.validate(changed_judgment)
        with pytest.raises(workflow.CreditAnalysisError, match="protected response field"):
            response_contract.validate_response_correction(invalid_id, changed_judgment, schema)
    changed_risk = json.loads(json.dumps(corrected_id))
    assert changed_risk["plausible_risks"]
    changed_risk["plausible_risks"][0]["missing_fact"] = "A different missing fact."
    schema_validator.validate(changed_risk)
    with pytest.raises(workflow.CreditAnalysisError, match="missing_fact"):
        response_contract.validate_response_correction(invalid_id, changed_risk, schema)

    missing_and_extra = json.loads(original_response)
    del missing_and_extra["confirmed_findings"][0]["title"]
    missing_and_extra["unexpected_field"] = "Remove this invalid extra field."
    response_contract.validate_response_correction(missing_and_extra, response, schema)
    changed_valid_child = json.loads(original_response)
    changed_valid_child["confirmed_findings"][0]["problem_summary"] = "Changed valid child of an invalid parent."
    with pytest.raises(workflow.CreditAnalysisError, match="problem_summary"):
        response_contract.validate_response_correction(missing_and_extra, changed_valid_child, schema)
    response_contract.validate_response_correction(verbose_raw, response, schema)
    shortened_valid_text = json.loads(original_response)
    shortened_valid_text["confirmed_findings"][0]["problem_summary"] = "Shorter but different."
    with pytest.raises(workflow.CreditAnalysisError, match="problem_summary"):
        response_contract.validate_response_correction(response, shortened_valid_text, schema)

    # Every classification/reason pair uses the same nested form in the schema
    # and canonical validator, including the recorded avoidable/reason mismatch.
    classification_schema = schema["properties"]["call_classifications"]["items"]
    classification_validator = Draft202012Validator(classification_schema)
    sample_group = response["call_classifications"][0]
    for classification in contract["call_classifications"]:
        for reason_code in [None, *contract["necessary_reason_codes"]]:
            group = {**sample_group, "classification": classification, "reason_code": reason_code}
            valid = (classification == "necessary") == (reason_code is not None)
            assert classification_validator.is_valid(group) is valid
            if valid:
                response_contract.validate_classification_reason(group, contract, "group")
            else:
                with pytest.raises(workflow.CreditAnalysisError, match="reason_code"):
                    response_contract.validate_classification_reason(group, contract, "group")
    recorded_group = {**sample_group, "classification": "avoidable_implemented", "reason_code": "ordinary-model-error"}
    assert not classification_validator.is_valid(recorded_group)
    with pytest.raises(workflow.CreditAnalysisError, match="reason_code must have type 'null'"):
        response_contract._validate_holistic_transport_value(recorded_group, classification_schema, "group")
    corrected_group = {**recorded_group, "reason_code": None}
    classification_validator.validate(corrected_group)
    response_contract.validate_classification_reason(corrected_group, contract, "group")
    response_contract.validate_response_correction(recorded_group, corrected_group, classification_schema)
    assert corrected_group["classification"] == "avoidable_implemented"
    switched_classification = {**recorded_group, "classification": "necessary"}
    classification_validator.validate(switched_classification)
    with pytest.raises(workflow.CreditAnalysisError, match="classification"):
        response_contract.validate_response_correction(recorded_group, switched_classification, classification_schema)

    invalid_reason = json.loads(original_response)
    invalid_reason["call_classifications"][0]["reason_code"] = "ordinary-model-error"
    assert not schema_validator.is_valid(invalid_reason)
    with pytest.raises(workflow.CreditAnalysisError, match=r"call_classifications\[0\]\.reason_code"):
        validate_response(invalid_reason)
    invalid_reason["call_classifications"][0]["reason_code"] = None
    schema_validator.validate(invalid_reason)
    accepted_reason = validate_response(invalid_reason)
    assert accepted_reason["call_classifications"][0]["classification"] == sample_group["classification"]
    assert json.dumps(response, sort_keys=True) == original_response

    # Structural validity cannot bypass independent exact coverage and evidence
    # checks; the same well-formed response remains incomplete after this edit.
    missing_call = json.loads(original_response)
    missing_call["call_classifications"].pop()
    schema_validator.validate(missing_call)
    with pytest.raises(workflow.CreditAnalysisError, match="missing or cross-analysis"):
        validate_response(missing_call)
    with pytest.raises(workflow.CreditAnalysisError, match="call_classifications"):
        response_contract.validate_response_correction(response, missing_call, schema)

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
    assert final["manifest"]["unclassified_calls"] == (
        final["coverage"]["eligible_calls"] - final["coverage"]["analyzed_calls"]
    )
    assert final["coverage"]["omitted_runs"] == 1

    compact = json.loads(
        pathlib.Path(
            json.loads(state_path.read_text(encoding="utf-8"))["manifest"][
                "compact_evidence"
            ]["path"]
        ).read_text(encoding="utf-8")
    )
    episodes = workflow._holistic_episodes(compact)
    one_packet_bytes = workflow._json_bytes(
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
        budget_bytes=max(8_000, one_packet_bytes // 2),
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
        workflow._json_bytes(
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
        budget_bytes=five_packet_budget,
    )
    assert len(five_packets) == 5
    assert [
        candidate_id
        for packet in five_packets
        for episode in packet
        for candidate_id in episode["candidate_ids"]
    ] == synthetic_ids

    oversized_id = "candidate.synthetic.oversized"
    oversized_bundle = {
        **synthetic_bundle,
        "records": [{"candidate_id": oversized_id, "workstream": "producer"}],
        "candidate_ids": [oversized_id],
    }
    oversized_episode = {
        "episode_id": "episode.synthetic.oversized",
        "turn_id": "turn.synthetic.oversized",
        "candidate_ids": [oversized_id],
        "user_messages": [],
        "calls": [
            {
                "candidate_id": oversized_id,
                "call_id": "call.synthetic.oversized",
                "turn_id": "turn.synthetic.oversized",
                "workstream": "producer",
                "surface_lenses": compact["surface_order"],
                "user_message_ids": [],
                "evidence_refs": ["evidence://calls/synthetic-oversized"],
                "semantic_evidence": "x" * 100_000,
            }
        ],
    }
    oversized_packets = workflow._holistic_partition(
        analysis_id=compact["analysis_id"],
        episodes=[oversized_episode],
        bundle=oversized_bundle,
        budget_bytes=10_000,
    )
    assert len(oversized_packets) == 1
    assert oversized_packets[0][0]["candidate_ids"] == [oversized_id]
    assert oversized_packets[0][0]["calls"][0]["capacity_reduced"] is True
    assert workflow._json_bytes(
        workflow._holistic_luna_payload(
            analysis_id=compact["analysis_id"],
            task_id="luna.discovery.oversized",
            ordinal=1,
            episodes=oversized_packets[0],
            bundle=oversized_bundle,
        )
    ) <= 10_000

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
    for sol_task_record in manifest["sol_tasks"][:-1]:
        sol_task_record["dependencies"].insert(1, split["task_id"])
    expected_packets = workflow._holistic_partition(
        analysis_id=compact["analysis_id"],
        episodes=episodes,
        bundle=compact,
        budget_bytes=json.loads(state_path.read_text(encoding="utf-8"))[
            "model_specs"
        ]["luna"]["evidence_byte_budget"],
    )
    with pytest.raises(
        workflow.CreditAnalysisError,
        match="run-part boundaries",
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
