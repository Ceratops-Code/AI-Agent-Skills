from __future__ import annotations

import importlib.util
import pathlib
import sys
from typing import Any, Mapping

from tests.credit_analysis.paths import CREDIT_ANALYSIS_WORKFLOW


def load_credit_analysis_workflow_module() -> Any:
    """Load the controller so fake runners exercise the real state machine."""

    spec = importlib.util.spec_from_file_location(
        "credit_analysis_workflow_under_test",
        CREDIT_ANALYSIS_WORKFLOW,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(spec.name)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(spec.name, None)
        else:
            sys.modules[spec.name] = previous
    return module


def holistic_model_catalog(context_tokens: int = 258_000) -> dict[str, dict[str, Any]]:
    """Return deterministic local-catalog data for injected model runs."""

    return {
        "gpt-5.6-luna": {
            "reasoning_efforts": {"low", "medium", "high", "max"},
            "effective_context_tokens": context_tokens,
        },
        "gpt-5.6-sol": {
            "reasoning_efforts": {"low", "medium", "high", "max"},
            "effective_context_tokens": context_tokens,
        },
    }


class FakeCreditModelRunner:
    """Return sparse Luna discovery and one complete Sol adjudication."""

    available_models = holistic_model_catalog()
    usage_by_phase = {
        "luna-discovery": {
            "input_tokens": 800,
            "cached_input_tokens": 0,
            "output_tokens": 180,
            "reasoning_output_tokens": 420,
        },
        "sol-adjudication": {
            "input_tokens": 1_200,
            "cached_input_tokens": 0,
            "output_tokens": 360,
            "reasoning_output_tokens": 1_100,
        },
    }

    def __init__(self, *, temporary_controls: bool = True) -> None:
        self.calls: list[dict[str, Any]] = []
        self.temporary_controls = temporary_controls

    @staticmethod
    def _records(packet: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [
            dict(call)
            for episode in packet["episodes"]
            for call in episode["calls"]
        ]

    def _luna(
        self,
        task: Mapping[str, Any],
        packet: Mapping[str, Any],
        digest: str,
    ) -> dict[str, Any]:
        records = self._records(packet)
        candidates: list[dict[str, Any]] = []

        def add(
            suffix: str,
            kind: str,
            record: Mapping[str, Any],
            surfaces: list[str],
        ) -> None:
            candidates.append(
                {
                    "id": f"luna.{int(task['ordinal']):04d}.{suffix}",
                    "kind": kind,
                    "title": suffix.replace("-", " "),
                    "hypothesis": (
                        "The compact causal record supports focused final "
                        "adjudication without a per-action dismissal."
                    ),
                    "surface_ids": list(reversed(surfaces)),
                    "candidate_ids": [str(record["candidate_id"])],
                    "evidence_refs": [str(record["evidence_refs"][0])],
                    "producer_owner_hint": "workflow:synthetic",
                }
            )

        surfaces = list(packet["surface_order"])
        if records:
            add("model-waste", "provisional-finding", records[0], surfaces)
        if len(records) > 1:
            add("volume-waste", "provisional-finding", records[1], surfaces)
        if len(records) > 2:
            add("uncertain-wait", "plausible-risk", records[2], surfaces)
        for index, record in enumerate(records[9:], start=1):
            add(
                f"uncapped-model-waste-{index}",
                "provisional-finding",
                record,
                surfaces,
            )
        if self.temporary_controls and len(records) > 8:
            dispositions = [
                ("temporary.transient", records[3], ["rework-validation"]),
                (
                    "temporary.implemented",
                    records[4],
                    ["helper-contracts", "rework-validation"],
                ),
                ("temporary.run-only", records[5], ["rework-validation"]),
                (
                    "temporary.durable-a",
                    records[6],
                    ["helper-contracts", "rework-validation"],
                ),
                (
                    "temporary.durable-b",
                    records[7],
                    ["rework-validation", "tool-flow"],
                ),
                ("temporary.unclear", records[8], ["rework-validation"]),
            ]
            allowed = set(surfaces)
            for suffix, record, requested_surfaces in dispositions:
                selected = [
                    surface
                    for surface in surfaces
                    if surface in requested_surfaces and surface in allowed
                ]
                if selected:
                    add(suffix, "temporary-control", record, selected)
        return {
            "schema": "ceratops-credit-analysis-luna-result.v4",
            "analysis_id": packet["analysis_id"],
            "task_id": task["task_id"],
            "input_sha256": digest,
            "coverage": {
                "candidate_count": len(task["candidate_ids"]),
                "candidate_ids_sha256": task["candidate_ids_sha256"],
                "first_candidate_id": task["candidate_ids"][0],
                "last_candidate_id": task["candidate_ids"][-1],
            },
            "candidates": candidates,
        }

    @staticmethod
    def _recurrence(call_count: int, *, volume_only: bool) -> dict[str, Any]:
        return {
            "calls_saved_per_affected_run": (
                0.0 if volume_only else float(call_count)
            ),
            "additional_recurring_calls_per_affected_run": 0.0,
            "affected_similar_run_frequency": 0.5,
            "affected_similar_run_frequency_range": [0.25, 0.75],
            "assumptions": ["synthetic recurrence evidence"],
        }

    @classmethod
    def _finding(
        cls,
        finding_id: str,
        candidate: Mapping[str, Any],
        inventory: Mapping[str, Mapping[str, Any]],
        *,
        volume_only: bool = False,
        status: str = "unimplemented",
        candidate_ids: list[str] | None = None,
        candidates_by_id: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        source_candidates = candidate_ids or [str(candidate["id"])]
        candidate_records = [
            (candidates_by_id or {str(candidate["id"]): candidate})[item]
            for item in source_candidates
        ]
        call_ids = list(
            dict.fromkeys(
                inventory[candidate_id]["call_id"]
                for item in candidate_records
                for candidate_id in item["candidate_ids"]
            )
        )
        return {
            "id": finding_id,
            "title": finding_id.replace("-", " "),
            "problem_summary": (
                "Synthetic original evidence confirms recurring avoidable work "
                "owned by the workflow."
            ),
            "waste_kind": "context-volume" if volume_only else "model-calls",
            "affected_call_ids": call_ids,
            "evidence_refs": [
                str(candidate_records[0]["evidence_refs"][0])
            ],
            "producer_type": "workflow",
            "producer_owner": "workflow:synthetic",
            "proposed_durable_control": (
                "Make the deterministic workflow complete to its final boundary."
            ),
            "implementation_status": status,
            "targeted_verification": [
                "verify the workflow prevents the repeated causal episode"
            ],
            "recurrence": cls._recurrence(
                len(call_ids),
                volume_only=volume_only,
            ),
            "confidence": 0.9,
            "complexity": "Low",
            "one_time_implementation_cost": {
                "estimated_model_calls": 1.0,
                "description": "one targeted producer update",
            },
            "helper_categories": [],
        }

    def _sol(
        self,
        task: Mapping[str, Any],
        packet: Mapping[str, Any],
        digest: str,
    ) -> dict[str, Any]:
        candidates = [
            dict(candidate)
            for result in packet["luna_results"]
            for candidate in result["candidates"]
        ]
        candidates_by_id = {str(item["id"]): item for item in candidates}
        fields = packet["call_inventory"]["fields"]
        inventory = {
            str(row[0]): dict(zip(fields, row, strict=True))
            for row in packet["call_inventory"]["rows"]
        }
        findings: list[dict[str, Any]] = []
        risks: list[dict[str, Any]] = []
        reviews: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        durable_candidates = [
            str(item["id"])
            for item in candidates
            if str(item["title"]).rsplit(".", 1)[-1].replace(" ", "-")
            in {"durable-a", "durable-b"}
        ]
        if durable_candidates:
            first_durable = candidates_by_id[durable_candidates[0]]
            findings.append(
                self._finding(
                    "temporary-control-gap",
                    first_durable,
                    inventory,
                    candidate_ids=durable_candidates,
                    candidates_by_id=candidates_by_id,
                )
            )
        for index, candidate in enumerate(candidates, start=1):
            candidate_id = str(candidate["id"])
            semantic_suffix = str(candidate["title"]).rsplit(".", 1)[-1].replace(
                " ", "-"
            )
            evidence_refs = [str(candidate["evidence_refs"][0])]
            finding_ids: list[str] = []
            risk_ids: list[str] = []
            if candidate["kind"] == "provisional-finding":
                finding_id = (
                    f"finding-volume-{index}"
                    if semantic_suffix == "volume-waste"
                    else f"finding-model-{index}"
                )
                findings.append(
                    self._finding(
                        finding_id,
                        candidate,
                        inventory,
                        volume_only=semantic_suffix == "volume-waste",
                        status=(
                            "implemented"
                            if semantic_suffix == "model-waste"
                            else "unimplemented"
                        ),
                    )
                )
                finding_ids = [finding_id]
                disposition = "confirmed-finding"
            elif candidate["kind"] == "plausible-risk":
                candidate_key = str(candidate["candidate_ids"][0])
                risk_id = f"risk-{index}"
                risks.append(
                    {
                        "id": risk_id,
                        "description": (
                            "The wait may have continued after completion became visible."
                        ),
                        "affected_call_ids": [inventory[candidate_key]["call_id"]],
                        "evidence_refs": evidence_refs,
                        "competing_explanations": [
                            "completion was already visible",
                            "completion had not propagated",
                        ],
                        "missing_fact": "the exact visibility timestamp is absent",
                        "verification_needed": [
                            "record completion visibility before waiting"
                        ],
                    }
                )
                risk_ids = [risk_id]
                disposition = "plausible-risk"
            elif candidate_id in durable_candidates:
                finding_ids = ["temporary-control-gap"]
                disposition = "confirmed-finding"
            else:
                disposition = "dismissed-candidate"
            decisions.append(
                {
                    "luna_candidate_id": candidate_id,
                    "disposition": disposition,
                    "reason": "Original evidence was checked in the final pass.",
                    "evidence_refs": evidence_refs,
                    "finding_ids": finding_ids,
                    "risk_ids": risk_ids,
                }
            )
            if candidate["kind"] != "temporary-control":
                continue
            disposition_by_suffix = {
                "transient": "transient-by-design",
                "implemented": "permanently-implemented",
                "run-only": "run-only-useful",
                "durable-a": "durable-control-missing",
                "durable-b": "durable-control-missing",
                "unclear": "final-state-unclear",
            }
            temporary_disposition = disposition_by_suffix[semantic_suffix]
            durable = temporary_disposition == "durable-control-missing"
            candidate_key = str(candidate["candidate_ids"][0])
            reviews.append(
                {
                    "id": f"review.{candidate_id}",
                    "source_luna_candidate_ids": [candidate_id],
                    "problem_solved": "Synthetic temporary orchestration",
                    "affected_call_ids": [inventory[candidate_key]["call_id"]],
                    "observed_temporary_control": (
                        "A run-only deterministic orchestration step"
                    ),
                    "final_canonical_evidence_refs": [
                        (
                            packet["canonical_state"][0]["evidence_ref"]
                            if packet["canonical_state"]
                            else evidence_refs[0]
                        )
                    ],
                    "disposition": temporary_disposition,
                    "owning_producer": (
                        "workflow:shared"
                        if durable
                        else f"workflow:{temporary_disposition}"
                    ),
                    "recurrence_inputs": {
                        "likely": durable,
                        "frequency_range": [0.5, 1.0] if durable else [0.0, 0.1],
                        "basis": "synthetic recurrence evidence",
                    },
                    "savings_inputs": {
                        "expected_calls_saved": 2.0 if durable else 0.0,
                        "maintenance_model_calls": 0.25 if durable else 0.0,
                        "justifies_maintenance": durable,
                        "basis": "synthetic maintenance-adjusted savings",
                    },
                    "finding_id": "temporary-control-gap" if durable else None,
                    "no_finding_reason": (
                        None
                        if durable
                        else "The selected disposition does not justify a defect."
                    ),
                }
            )
        durable_reviews = [
            review["id"]
            for review in reviews
            if review["disposition"] == "durable-control-missing"
        ]
        merges = (
            [
                {
                    "control_key": "shared-temporary-orchestration",
                    "owning_producer": "workflow:shared",
                    "review_ids": durable_reviews,
                    "finding_id": "temporary-control-gap",
                }
            ]
            if durable_reviews
            else []
        )
        implemented_calls = {
            call_id
            for finding in findings
            if finding["waste_kind"] == "model-calls"
            and finding["implementation_status"] == "implemented"
            for call_id in finding["affected_call_ids"]
        }
        unimplemented_calls = {
            call_id
            for finding in findings
            if finding["waste_kind"] == "model-calls"
            and finding["implementation_status"] == "unimplemented"
            for call_id in finding["affected_call_ids"]
        }
        groups: list[dict[str, Any]] = []
        previous_signature: tuple[str, str] | None = None
        for row in packet["call_inventory"]["rows"]:
            item = dict(zip(fields, row, strict=True))
            classification = (
                "avoidable_unimplemented"
                if item["call_id"] in unimplemented_calls
                else (
                    "avoidable_implemented"
                    if item["call_id"] in implemented_calls
                    else "reviewed_no_confirmed_waste"
                )
            )
            signature = (classification, item["workstream"])
            if groups and previous_signature == signature:
                groups[-1]["call_ids"].append(item["call_id"])
            else:
                groups.append(
                    {
                        "call_ids": [item["call_id"]],
                        "classification": classification,
                        "reason_code": None,
                        "rationale": (
                            "The final pass checked this source-order call group."
                        ),
                        "evidence_refs": [item["primary_evidence_ref"]],
                    }
                )
                previous_signature = signature
        return {
            "candidate_decisions": decisions,
            "confirmed_findings": findings,
            "plausible_risks": risks,
            "temporary_control_reviews": reviews,
            "temporary_control_merges": merges,
            "helper_category_reviews": [
                {
                    "category": category,
                    "applies": False,
                    "evidence_refs": [],
                    "reason": "Synthetic evidence found no category-specific gap.",
                }
                for category in packet["helper_categories"]
            ],
            "call_classifications": groups,
        }

    def run(
        self,
        *,
        model: str,
        task: Mapping[str, Any],
        prompt: str,
        schema: Mapping[str, Any],
        input_payload: Mapping[str, Any],
        input_sha256: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "model": model,
                "phase": task["phase"],
                "reasoning_effort": task["reasoning_effort"],
                "input_sha256": input_sha256,
                "input_payload": input_payload,
                "prompt": prompt,
                "schema": schema,
            }
        )
        if task["phase"] == "luna-discovery":
            return self._luna(task, input_payload, input_sha256)
        return self._sol(task, input_payload, input_sha256)


def complete_holistic_credit_analysis(
    workflow: Any,
    child_status: Mapping[str, Any],
) -> pathlib.Path:
    """Execute one batch child through the same holistic controller as one source."""

    runner = FakeCreditModelRunner(temporary_controls=False)
    status = workflow.command_execute_orchestration(
        pathlib.Path(child_status["state_path"]),
        runner=runner,
        available_models=runner.available_models,
    )
    assert status["complete"] is True
    assert status["actual_luna_calls"] == 1
    assert status["actual_sol_calls"] == 1
    assert len(runner.calls) == 2
    return pathlib.Path(status["final_result_path"])
