from __future__ import annotations

import copy
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
from tests.credit_analysis.sessions import (
    credit_analysis_request,
    credit_analysis_session,
)
from tests.support.repositories import run_git


def test_final_assembly_keeps_accepted_decisions_and_derives_new_one() -> None:
    load_credit_analysis_workflow_module()
    from credit_analysis.report_bookkeeping import _assemble_final_transport
    from credit_analysis.single_thread_analysis import CreditAnalysisError

    prior = {
        "candidate_decisions": [{
            "luna_candidate_id": "old", "disposition": "dismissed-candidate",
            "reason": "Required work", "evidence_refs": ["e1"],
            "finding_ids": [], "risk_ids": [],
        }],
        "confirmed_findings": [], "plausible_risks": [],
        "temporary_control_reviews": [], "temporary_control_merges": [],
        "helper_category_reviews": [],
        "call_classifications": [{
            "call_ids": ["c1", "c2"], "classification": "necessary",
            "reason_code": "required_for_task", "rationale": "Required work",
            "evidence_refs": ["e1"], "workstream": "producer",
        }],
    }
    packet = {
        "luna_candidate_ids": ["old", "new"],
        "call_inventory": {"rows": [["x", "c1", "producer"], ["x", "c2", "producer"]]},
        "prior_adjudication_results": [prior],
        "recovery_result": None,
        "deep_review_evidence": [],
    }
    delta = {
        "candidate_decisions": [{
            "luna_candidate_id": "new", "reason": "Possible repeated call",
            "evidence_refs": ["e2"], "finding_ids": [], "risk_ids": ["risk-1"],
        }],
        "confirmed_findings": [],
        "plausible_risks": [{
            "id": "risk-1", "description": "Possible repeated call",
            "affected_call_ids": ["c2"], "evidence_refs": ["e2"],
            "competing_explanations": ["The call may be needed"],
            "missing_fact": "Whether state changed", "verification_needed": ["Check state"],
        }],
        "temporary_control_reviews": [], "temporary_control_merges": [],
        "helper_category_reviews": [], "call_classifications": [],
    }
    assembled = _assemble_final_transport(delta, packet)
    assert [item["disposition"] for item in assembled["candidate_decisions"]] == [
        "dismissed-candidate", "plausible-risk",
    ]
    assert assembled["candidate_decisions"][0]["risk_ids"] == []
    assert assembled["plausible_risks"][0]["id"] == "risk-1"
    assert assembled["call_classifications"][0]["call_ids"] == ["c1", "c2"]

    # The saved failure was a restated dismissed candidate with a stray risk ID.
    contradictory = {**delta, "candidate_decisions": [
        *delta["candidate_decisions"],
        {"luna_candidate_id": "old", "reason": "Required work",
         "evidence_refs": ["e1"], "finding_ids": [], "risk_ids": ["risk-1"]},
    ]}
    with pytest.raises(CreditAnalysisError, match="new candidate exactly once"):
        _assemble_final_transport(contradictory, packet)


def test_final_schema_accepts_only_new_candidate_judgments() -> None:
    workflow = load_credit_analysis_workflow_module()
    from credit_analysis.model_response_contract import build_sol_schema

    schema = build_sol_schema(
        contract=workflow._load_contract(),
        luna_aliases=["l0001", "l0002"],
        call_aliases=["c0001"],
        evidence_aliases=["e0001"],
        final_synthesis=True,
        final_decision_aliases=["l0002"],
    )
    decisions = schema["properties"]["candidate_decisions"]
    assert decisions["minItems"] == decisions["maxItems"] == 1
    fields = decisions["items"]["properties"]
    assert fields["luna_candidate_id"]["enum"] == ["l0002"]
    assert "disposition" not in fields
    shard = build_sol_schema(
        contract=workflow._load_contract(),
        luna_aliases=["l0001"], call_aliases=["c0001"],
        evidence_aliases=["e0001"],
    )
    assert "disposition" not in shard["properties"]["candidate_decisions"]["items"]["properties"]


def test_restored_aliases_keep_identifier_boundaries_after_split() -> None:
    load_credit_analysis_workflow_module()
    from credit_analysis.model_response_contract import _holistic_restore_alias_value

    restored = _holistic_restore_alias_value(
        {"id": "l0007", "text": "l0007 and xl0007 and l0007.suffix"},
        {"l0007": "luna.source.0007"},
    )
    assert restored == {
        "id": "luna.source.0007",
        "text": "luna.source.0007 and xl0007 and l0007.suffix",
    }


def test_final_assembly_merges_exact_prior_findings_without_model_copy() -> None:
    load_credit_analysis_workflow_module()
    from credit_analysis.report_bookkeeping import _assemble_final_transport
    from credit_analysis.single_thread_analysis import CreditAnalysisError

    def source(candidate: str, call: str, finding_id: str) -> dict[str, Any]:
        return {
            "candidate_decisions": [{
                "luna_candidate_id": candidate, "disposition": "confirmed-finding",
                "reason": "Repeated call", "evidence_refs": [f"e-{call}"],
                "finding_ids": [finding_id], "risk_ids": [],
            }],
            "confirmed_findings": [{
                "id": finding_id, "producer_owner": "same owner",
                "proposed_durable_control": "same control",
                "problem_summary": "same problem", "waste_kind": "model-calls",
                "implementation_status": "unimplemented", "workstream": "producer",
                "affected_call_ids": [call], "evidence_refs": [f"e-{call}"],
                "recurrence": {"calls_saved_per_affected_run": 1},
            }],
            "plausible_risks": [], "temporary_control_reviews": [],
            "temporary_control_merges": [], "helper_category_reviews": [],
            "call_classifications": [{
                "call_ids": [call], "classification": "avoidable_unimplemented",
                "reason_code": None, "rationale": "Repeated call",
                "evidence_refs": [f"e-{call}"], "workstream": "producer",
            }],
        }

    packet: dict[str, Any] = {
        "luna_candidate_ids": ["l1", "l2"],
        "call_inventory": {"rows": [["x", "c1", "producer"], ["x", "c2", "producer"]]},
        "prior_adjudication_results": [source("l1", "c1", "f1"), source("l2", "c2", "f2")],
        "recovery_result": None, "deep_review_evidence": [],
    }
    delta: dict[str, Any] = {key: [] for key in (
        "candidate_decisions", "confirmed_findings", "plausible_risks",
        "temporary_control_reviews", "temporary_control_merges",
        "helper_category_reviews", "call_classifications",
    )}
    assembled = _assemble_final_transport(delta, packet)
    assert len(assembled["confirmed_findings"]) == 1
    assert assembled["confirmed_findings"][0]["affected_call_ids"] == ["c1", "c2"]
    assert [decision["finding_ids"] for decision in assembled["candidate_decisions"]] == [
        ["f1"], ["f1"],
    ]

    packet["deep_review_evidence"] = [{"finding_id": "f1"}]
    revision = {
        **packet["prior_adjudication_results"][0]["confirmed_findings"][0],
        "problem_summary": "More precise problem",
        "affected_call_ids": ["c2"], "evidence_refs": ["e-c2"],
    }
    revised = _assemble_final_transport(
        {**delta, "confirmed_findings": [revision]}, packet
    )
    assert revised["confirmed_findings"][0]["problem_summary"] == "More precise problem"
    assert revised["confirmed_findings"][0]["affected_call_ids"] == ["c1", "c2"]
    assert revised["confirmed_findings"][0]["evidence_refs"] == ["e-c1", "e-c2"]

    # Unsupported final call overrides are rejected together while accepted
    # findings and their original classifications remain authoritative.
    protected = copy.deepcopy(packet)
    protected["deep_review_evidence"] = []
    protected["prior_adjudication_results"][1]["confirmed_findings"][0]["producer_owner"] = "second owner"
    for result in protected["prior_adjudication_results"]:
        result["confirmed_findings"][0]["implementation_status"] = "implemented"
        result["call_classifications"][0]["classification"] = "avoidable_implemented"
    conflicting = copy.deepcopy(delta)
    conflicting["call_classifications"] = [
        {"call_ids": [call], "classification": "avoidable_unimplemented",
         "reason_code": None, "rationale": "Different explanation",
         "evidence_refs": [f"e-{call}"]}
        for call in ("c1", "c2")
    ]
    preserved = _assemble_final_transport(conflicting, protected)
    assert [group["classification"] for group in preserved["call_classifications"]] == [
        "avoidable_implemented", "avoidable_implemented",
    ]
    assert [finding["implementation_status"] for finding in preserved["confirmed_findings"]] == [
        "implemented", "implemented",
    ]

    # An explicit compatible revision may supersede the earlier status.
    protected["deep_review_evidence"] = [{"finding_id": "f1"}]
    revision = {
        **protected["prior_adjudication_results"][0]["confirmed_findings"][0],
        "implementation_status": "unimplemented",
    }
    changed = _assemble_final_transport(
        {**conflicting, "confirmed_findings": [revision],
         "call_classifications": conflicting["call_classifications"][:1]}, protected,
    )
    assert changed["confirmed_findings"][0]["implementation_status"] == "unimplemented"
    assert changed["call_classifications"][0]["classification"] == "avoidable_unimplemented"
    assert changed["call_classifications"][1]["classification"] == "avoidable_implemented"

    # A call move needs a source revision, one complete destination, and an
    # explicit call judgment; partial source revisions still preserve calls.
    move_packet = copy.deepcopy(protected)
    move_packet["prior_adjudication_results"] = [source("l1", "c1", "f1")]
    move_packet["prior_adjudication_results"][0]["confirmed_findings"][0]["affected_call_ids"] = ["c1", "c2"]
    move_packet["prior_adjudication_results"][0]["confirmed_findings"][0]["implementation_status"] = "implemented"
    move_packet["prior_adjudication_results"][0]["call_classifications"][0]["call_ids"] = ["c1", "c2"]
    move_packet["prior_adjudication_results"][0]["call_classifications"][0]["classification"] = "avoidable_implemented"
    moved_from = {**move_packet["prior_adjudication_results"][0]["confirmed_findings"][0], "affected_call_ids": ["c1"]}
    moved_to = {**moved_from, "id": "f3", "affected_call_ids": ["c2"],
                "producer_owner": "new cause", "implementation_status": "unimplemented"}
    move_delta = {**delta,
                  "candidate_decisions": [{"luna_candidate_id": "l2", "reason": "New cause",
                                           "evidence_refs": ["e-c2"], "finding_ids": ["f3"], "risk_ids": []}],
                  "plausible_risks": [], "confirmed_findings": [moved_from, moved_to],
                  "call_classifications": conflicting["call_classifications"][1:]}
    move_packet["luna_candidate_ids"] = ["l1", "l2"]
    moved = _assemble_final_transport(move_delta, move_packet)
    assert {item["id"]: item["affected_call_ids"] for item in moved["confirmed_findings"]} == {
        "f1": ["c1"], "f3": ["c2"],
    }

    # Incompatible deep-review revisions revert together to accepted results.
    protected["deep_review_evidence"] = [{"finding_id": "f1"}, {"finding_id": "f2"}]
    bad_revisions = [
        copy.deepcopy(result["confirmed_findings"][0])
        for result in protected["prior_adjudication_results"]
    ]
    restored = _assemble_final_transport(
        {**conflicting, "confirmed_findings": bad_revisions}, protected,
    )
    assert [item["implementation_status"] for item in restored["confirmed_findings"]] == [
        "implemented", "implemented",
    ]
    assert [item["classification"] for item in restored["call_classifications"]] == [
        "avoidable_implemented", "avoidable_implemented",
    ]

    # Exact repetitions are no-ops. Divergent final restatements all yield to
    # earlier accepted risks, reviews, and owner/control associations.
    repeated = copy.deepcopy(protected)
    repeated["deep_review_evidence"] = []
    risk = {"id": "r1", "description": "Possible issue", "affected_call_ids": ["c1"],
            "missing_fact": "Cause", "verification_needed": ["Check cause"]}
    review = {"id": "t1", "finding_id": "f1", "no_finding_reason": None}
    merge = {"owning_producer": "owner", "control_key": "control",
             "finding_id": "f1", "review_ids": ["t1"]}
    repeated["prior_adjudication_results"][0]["plausible_risks"] = [risk]
    repeated["prior_adjudication_results"][0]["temporary_control_reviews"] = [review]
    repeated["prior_adjudication_results"][0]["temporary_control_merges"] = [merge]
    duplicate_delta = {**delta,
                       "confirmed_findings": [copy.deepcopy(repeated["prior_adjudication_results"][0]["confirmed_findings"][0])],
                       "plausible_risks": [copy.deepcopy(risk)],
                       "temporary_control_reviews": [copy.deepcopy(review)],
                       "temporary_control_merges": [copy.deepcopy(merge)]}
    duplicate = _assemble_final_transport(duplicate_delta, repeated)
    assert len(duplicate["plausible_risks"]) == 1
    assert len(duplicate["temporary_control_reviews"]) == 1
    assert len(duplicate["temporary_control_merges"]) == 1
    divergent_delta = copy.deepcopy(duplicate_delta)
    divergent_delta["plausible_risks"][0]["description"] = "Different issue"
    divergent_delta["temporary_control_reviews"][0]["no_finding_reason"] = "Different review"
    divergent_delta["temporary_control_merges"][0]["finding_id"] = "f2"
    reconciled = _assemble_final_transport(divergent_delta, repeated)
    assert reconciled["plausible_risks"][0]["description"] == "Possible issue"
    assert reconciled["temporary_control_reviews"][0]["no_finding_reason"] is None
    assert reconciled["temporary_control_merges"][0]["finding_id"] == "f1"
    conflicting_merge = _assemble_final_transport(
        {**delta,
         "temporary_control_reviews": [{
             "id": "t2", "finding_id": "f2", "no_finding_reason": None,
         }],
         "temporary_control_merges": [{
             **merge, "finding_id": "f2", "review_ids": ["t2"],
         }]},
        repeated,
    )
    assert conflicting_merge["temporary_control_merges"][0]["finding_id"] == "f1"
    assert conflicting_merge["temporary_control_reviews"][1]["finding_id"] is None

    # A new finding with incompatible per-call accounting is withdrawn along
    # with its new candidate link, without changing the accepted finding.
    new_packet = copy.deepcopy(protected)
    new_packet["deep_review_evidence"] = []
    new_packet["prior_adjudication_results"] = [source("l1", "c1", "f1")]
    new_packet["luna_candidate_ids"] = ["l1", "l2"]
    new_finding = {
        **new_packet["prior_adjudication_results"][0]["confirmed_findings"][0],
        "id": "f3", "producer_owner": "new cause", "affected_call_ids": ["c2"],
    }
    new_delta = {
        **delta,
        "candidate_decisions": [{
            "luna_candidate_id": "l2", "reason": "A claimed second finding",
            "evidence_refs": ["e-c2"], "finding_ids": ["f3"], "risk_ids": [],
        }],
        "confirmed_findings": [new_finding],
        "temporary_control_reviews": [{
            "id": "t3", "finding_id": "f3", "no_finding_reason": None,
        }],
        "call_classifications": [{
            "call_ids": ["c2"], "classification": "necessary",
            "reason_code": "required_for_task", "rationale": "Required work",
            "evidence_refs": ["e-c2"],
        }],
    }
    withdrawn = _assemble_final_transport(new_delta, new_packet)
    assert [item["id"] for item in withdrawn["confirmed_findings"]] == ["f1"]
    assert withdrawn["candidate_decisions"][1]["finding_ids"] == []
    assert withdrawn["candidate_decisions"][1]["disposition"] == "dismissed-candidate"
    assert "omitted" in withdrawn["candidate_decisions"][1]["reason"]
    assert withdrawn["temporary_control_reviews"][0]["finding_id"] is None
    assert "conflicted" in withdrawn["temporary_control_reviews"][0]["no_finding_reason"]

    ambiguous = _assemble_final_transport(
        {**new_delta,
         "confirmed_findings": [new_finding, {**new_finding, "problem_summary": "Another cause"}],
         "temporary_control_reviews": []},
        new_packet,
    )
    assert [item["id"] for item in ambiguous["confirmed_findings"]] == ["f1"]
    assert ambiguous["candidate_decisions"][1]["finding_ids"] == []
    duplicate_call = _assemble_final_transport(
        {**new_delta,
         "call_classifications": [
             *new_delta["call_classifications"],
             {**new_delta["call_classifications"][0],
              "classification": "avoidable_unimplemented", "reason_code": None},
         ],
         "temporary_control_reviews": []},
        new_packet,
    )
    assert duplicate_call["candidate_decisions"][1]["finding_ids"] == []


@pytest.mark.parametrize("outcome", ["success", "failure", "interruption"])
def test_completion_checkpoint_precedes_slow_sibling_and_replays(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    """Observe durable publication while an earlier reviewer is still blocked."""
    workflow = load_credit_analysis_workflow_module()
    request, _, _ = credit_analysis_request(tmp_path, extra_completed_turns=2)
    plan = workflow.command_plan_orchestration(request, available_models=holistic_model_catalog())
    state_path = pathlib.Path(plan["state_path"])
    runner = FakeCreditModelRunner()
    workflow.command_execute_orchestration(
        state_path, runner=runner, task_limit=plan["projected_luna_calls"],
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    tasks = [item for item in state["manifest"]["sol_tasks"] if item["phase"] == "sol-adjudication"]
    slow_id, fast_id = tasks[0]["task_id"], tasks[1]["task_id"]
    slow_entered, release_slow, checkpointed, observed = (
        threading.Event(), threading.Event(), threading.Event(), threading.Event()
    )
    owner_ids: set[int] = set()
    observed_failures: list[BaseException] = []
    launches: list[str] = []
    original_run = runner.run
    original_save = workflow._holistic_save_state
    original_accept = workflow._holistic_accept_result

    def run(**kwargs: Any) -> dict[str, Any]:
        task_id = kwargs["task"]["task_id"]
        launches.append(task_id)
        if task_id == slow_id:
            slow_entered.set()
            assert release_slow.wait(10), "test did not release slow reviewer"
        if task_id == fast_id and outcome == "failure":
            raise RuntimeError("synthetic sibling failure")
        return original_run(**kwargs)

    def save(current: Mapping[str, Any]) -> None:
        owner_ids.add(threading.get_ident())
        original_save(current)
        execution = current["execution"][fast_id]
        if execution["status"] == "complete" or execution["attempts"]:
            checkpointed.set()
            assert observed.wait(10), "test did not finish reading the published checkpoint"

    def accept(**kwargs: Any) -> None:
        original_accept(**kwargs)
        if kwargs["task"]["task_id"] == fast_id and outcome == "interruption":
            raise KeyboardInterrupt("synthetic controller interruption")

    monkeypatch.setattr(runner, "run", run)
    monkeypatch.setattr(workflow, "_holistic_save_state", save)
    monkeypatch.setattr(workflow, "_holistic_accept_result", accept)

    def execute() -> None:
        try:
            workflow.command_execute_orchestration(state_path, runner=runner, task_limit=len(tasks))
        except BaseException as error:
            observed_failures.append(error)

    owner = threading.Thread(target=execute)
    owner.start()
    try:
        assert slow_entered.wait(10)
        assert checkpointed.wait(10), "completed sibling was not checkpointed until slow child finished"
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        assert saved["execution"][slow_id]["status"] == "pending"
        assert saved["execution"][fast_id]["attempts"][-1]["outcome"] == (
            "runner-error" if outcome == "failure" else "accepted"
        )
        assert owner.is_alive()
        assert owner_ids == {owner.ident}
    finally:
        observed.set()
        release_slow.set()
        owner.join(15)
    assert not owner.is_alive()
    if outcome == "success":
        assert not observed_failures
    else:
        assert len(observed_failures) == 1
        assert isinstance(observed_failures[0], KeyboardInterrupt if outcome == "interruption" else workflow.CreditAnalysisError)
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["execution"][slow_id]["status"] == "complete", [str(error) for error in observed_failures]
    retained = {
        task_id: execution["result"]["sha256"]
        for task_id, execution in saved["execution"].items() if execution["status"] == "complete"
    }
    monkeypatch.setattr(runner, "run", original_run)
    monkeypatch.setattr(workflow, "_holistic_save_state", original_save)
    monkeypatch.setattr(workflow, "_holistic_accept_result", original_accept)
    completed = workflow.command_execute_orchestration(state_path, runner=runner)
    assert completed["complete"]
    final_state = json.loads(state_path.read_text(encoding="utf-8"))
    for task_id, digest in retained.items():
        assert final_state["execution"][task_id]["result"]["sha256"] == digest
        assert len(final_state["execution"][task_id]["attempts"]) == 1
    assert launches.count(slow_id) == launches.count(fast_id) == 1
    call_count = len(runner.calls)
    assert workflow.command_execute_orchestration(state_path, runner=runner)["complete"]
    assert len(runner.calls) == call_count


@pytest.mark.parametrize("outcome", ["recovered", "timed-out-twice", "other-error"])
def test_sol_timeout_retries_only_once_for_no_result(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    workflow = load_credit_analysis_workflow_module()
    request, _, _ = credit_analysis_request(tmp_path)
    plan = workflow.command_plan_orchestration(request, available_models=holistic_model_catalog())
    state_path = pathlib.Path(plan["state_path"])
    runner = FakeCreditModelRunner()
    workflow.command_execute_orchestration(
        state_path, runner=runner, task_limit=plan["projected_luna_calls"],
    )
    original_invoke = workflow._invoke_injected_runner
    launches: list[str] = []

    def invoke(runner_arg: Any, **kwargs: Any) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        raw, attempt = original_invoke(runner_arg, **kwargs)
        if kwargs["task"]["phase"] != "sol-adjudication":
            return raw, attempt
        launches.append(pathlib.Path(kwargs["attempt_dir"]).name)
        if outcome == "recovered" and len(launches) == 2:
            return raw, attempt
        pathlib.Path(attempt["raw_output_path"]).unlink()
        events = pathlib.Path(attempt["events_path"])
        events.write_text(
            '{"type":"thread.started","thread_id":"synthetic"}\n'
            '{"type":"turn.started"}\n',
            encoding="utf-8", newline="\n",
        )
        attempt.update(
            timed_out=outcome != "other-error",
            terminated=True,
            exit_code=1,
            error="timed out after 600s" if outcome != "other-error" else "other runner error",
            event_summary=workflow._jsonl_event_summary(events),
        )
        return None, attempt

    monkeypatch.setattr(workflow, "_invoke_injected_runner", invoke)
    if outcome == "recovered":
        workflow.command_execute_orchestration(
            state_path, runner=runner, task_limit=1, stop_on_validation_error=True,
        )
    else:
        message = "timed out" if outcome == "timed-out-twice" else "other runner error"
        with pytest.raises(workflow.CreditAnalysisError, match=message):
            workflow.command_execute_orchestration(
                state_path, runner=runner, task_limit=1, stop_on_validation_error=True,
            )
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    task_id = next(
        task["task_id"] for task in saved["manifest"]["sol_tasks"]
        if task["phase"] == "sol-adjudication"
    )
    attempts = saved["execution"][task_id]["attempts"]
    assert len(attempts) == (1 if outcome == "other-error" else 2)
    assert launches == [f"attempt-{index:03d}" for index in range(1, len(attempts) + 1)]
    assert attempts[0]["outcome"] == "runner-error"
    assert attempts[0]["artifacts"]["raw_output"] is None
    if outcome == "recovered":
        assert saved["execution"][task_id]["status"] == "complete"
        assert attempts[1]["outcome"] == "accepted"
        assert attempts[0]["input_sha256"] == attempts[1]["input_sha256"]
        assert attempts[0]["prompt_path"] == attempts[1]["prompt_path"]
    elif outcome == "timed-out-twice":
        assert attempts[1]["outcome"] == "runner-error"
        assert saved["execution"][task_id]["status"] == "pending"
        with pytest.raises(workflow.CreditAnalysisError, match="timed out twice"):
            workflow.command_execute_orchestration(state_path, runner=runner, task_limit=1)
        assert len(launches) == 2


def test_sol_timeout_is_ten_minutes_without_changing_luna(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from credit_analysis import luna_sol_analysis
    from credit_analysis.orchestration_execution import _holistic_model_attempt

    deadlines: list[int] = []

    def capture(**kwargs: Any) -> None:
        deadlines.append(kwargs["timeout_seconds"])
        raise RuntimeError("captured child deadline")

    monkeypatch.setattr(luna_sol_analysis, "_run_codex_child", capture)
    for phase, role in (("luna-discovery", "luna"), ("sol-adjudication", "sol")):
        task_id = f"{role}.test"
        task = {
            "task_id": task_id, "phase": phase,
            "artifacts": {"attempts": str(tmp_path / task_id)},
            "execution_cwd": str(tmp_path),
        }
        state = {
            "analysis_id": "test", "execution": {task_id: {"attempts": []}},
            "model_specs": {role: {"model": f"gpt-5.6-{role}", "reasoning_effort": "max"}},
        }
        with pytest.raises(RuntimeError, match="captured child deadline"):
            _holistic_model_attempt(
                runner=None, state=state, task=task, payload={}, input_sha="test",
                prompt_path=tmp_path / "prompt.md", schema_path=tmp_path / "schema.json",
                attempt_number=1,
            )
    assert deadlines == [1200, 600]


@pytest.mark.parametrize("defect", ["reason", "judgment", "interrupted", "legacy"])
def test_correction_feedback_retains_rejected_response_and_exact_errors(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, defect: str,
) -> None:
    workflow = load_credit_analysis_workflow_module()
    request, _, _ = credit_analysis_request(tmp_path)
    plan = workflow.command_plan_orchestration(request, available_models=holistic_model_catalog())
    state_path = pathlib.Path(plan["state_path"])

    class CorrectingRunner(FakeCreditModelRunner):
        def __init__(self) -> None:
            super().__init__()
            self.responses: list[dict[str, Any]] = []
            self.feedback: dict[str, Any] | None = None

        def run(self, **kwargs: Any) -> dict[str, Any]:
            raw = super().run(**kwargs)
            if kwargs["task"]["phase"] != "sol-adjudication":
                return raw
            if not self.responses:
                group = next(item for item in raw["call_classifications"] if item["classification"] == "avoidable_implemented")
                group["reason_code"] = "ordinary-model-error"
            elif self.feedback is None:
                self.feedback = json.loads(kwargs["prompt"].split("\nCorrection request:\n", 1)[1])
                assert self.feedback["prior_response"] == self.responses[0]
                if defect == "judgment":
                    group = next(item for item in raw["call_classifications"] if item["classification"] == "avoidable_implemented")
                    group["classification"] = "reviewed_no_confirmed_waste"
            self.responses.append(json.loads(json.dumps(raw)))
            return raw

    runner = CorrectingRunner()
    workflow.command_execute_orchestration(state_path, runner=runner, task_limit=plan["projected_luna_calls"])
    if defect == "legacy":
        original_prepare = workflow._holistic_prepare_task

        def legacy_schema(*args: Any, **kwargs: Any) -> Any:
            prepared = original_prepare(*args, **kwargs)
            schema_path = prepared[3]
            schema = json.loads(schema_path.read_text(encoding="utf-8"))

            def weaken(value: Any) -> Any:
                if isinstance(value, list):
                    return [weaken(item) for item in value]
                if not isinstance(value, dict):
                    return value
                if "anyOf" in value:
                    first_branch, second_branch = value["anyOf"]
                    result = json.loads(json.dumps(first_branch))
                    result["properties"]["classification"]["enum"] += second_branch["properties"]["classification"]["enum"]
                    result["properties"]["reason_code"]["type"] = ["string", "null"]
                    result["properties"]["reason_code"]["enum"].append(None)
                    return result
                return {key: weaken(item) for key, item in value.items() if key != "pattern"}

            schema_path.write_text(json.dumps(weaken(schema)), encoding="utf-8")
            return prepared

        monkeypatch.setattr(workflow, "_holistic_prepare_task", legacy_schema)
    if defect == "interrupted":
        original_bind = workflow._bind_attempt_record

        def interrupt_binding(*args: Any, **kwargs: Any) -> Any:
            if kwargs["attempt_number"] == 2:
                raise KeyboardInterrupt("corrective child finished before checkpoint")
            return original_bind(*args, **kwargs)

        monkeypatch.setattr(workflow, "_bind_attempt_record", interrupt_binding)
        with pytest.raises(KeyboardInterrupt, match="before checkpoint"):
            workflow.command_execute_orchestration(state_path, runner=runner, task_limit=1)
        monkeypatch.setattr(workflow, "_bind_attempt_record", original_bind)
        before_replay = len(runner.calls)
        workflow.command_execute_orchestration(state_path, runner=runner, task_limit=1)
        assert len(runner.calls) == before_replay
    else:
        workflow.command_execute_orchestration(state_path, runner=runner, task_limit=1)
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    task = next(item for item in saved["manifest"]["sol_tasks"] if item["phase"] == "sol-adjudication")
    execution = saved["execution"][task["task_id"]]
    first, second = execution["attempts"][:2]
    assert runner.feedback is not None
    assert runner.feedback["validation_errors"] == [first["error"]]
    assert first["outcome"] == "validation-error"
    assert pathlib.Path(first["raw_output_path"]).read_text(encoding="utf-8")
    assert first["input_sha256"] == second["input_sha256"]
    assert first["prompt_path"] != second["prompt_path"]
    assert "retry-002" in second["prompt_path"]
    if defect == "legacy":
        from jsonschema import Draft202012Validator

        assert first["schema_path"] != second["schema_path"]
        assert "retry-002" in second["schema_path"]
        assert Draft202012Validator(json.loads(pathlib.Path(first["schema_path"]).read_text(encoding="utf-8"))).is_valid(runner.responses[0])
        assert not Draft202012Validator(json.loads(pathlib.Path(second["schema_path"]).read_text(encoding="utf-8"))).is_valid(runner.responses[0])
    assert runner.feedback["prior_attempt"] == 1
    if defect == "judgment":
        assert second["outcome"] == "validation-error"
        assert "classification" in second["error"]
        assert execution["status"] == "omitted"
    else:
        assert second["outcome"] == "accepted"
        if defect == "interrupted":
            assert second["recovered_unrecorded_attempt"]
            assert second["artifacts"]["prompt"]["sha256"] == hashlib.sha256(
                pathlib.Path(second["prompt_path"]).read_bytes()
            ).hexdigest()
        count = len(runner.calls)
        assert workflow.command_execute_orchestration(state_path, runner=runner, task_limit=0)
        assert len(runner.calls) == count
    from credit_analysis.orchestration_execution import _corrective_prompt

    # Extra feedback must fit in the existing envelope without truncating the
    # retained response or creating an attempt that could consume another call.
    saved["model_specs"]["sol"]["input_byte_budget"] = 1
    prompt_path = pathlib.Path(task["artifacts"]["prompt"])
    oversized_path = prompt_path.with_name(f"{prompt_path.stem}.retry-999.md")
    with pytest.raises(workflow.CreditAnalysisError, match="byte envelope"):
        _corrective_prompt(
            state=saved, task=dict(task), input_sha=first["input_sha256"],
            prompt_path=prompt_path, schema_path=pathlib.Path(task["artifacts"]["schema"]),
            attempt_number=999,
        )
    assert not oversized_path.exists()


def test_full_analysis_uses_run_windows_parallel_tiers_and_exact_coverage(
    tmp_path: pathlib.Path,
) -> None:
    _assert_sol_budget_boundaries(tmp_path)
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
    assert len(manifest["sol_tasks"]) == 8
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
    assert phases.count("sol-direct-evidence") == 1
    assert phases.count("sol-final") == 1
    final_call = next(call for call in runner.calls if call["phase"] == "sol-final")
    final_task = next(
        task
        for task in manifest["sol_tasks"]
        if task["phase"] == "sol-final"
    )
    final_prompt = pathlib.Path(final_task["artifacts"]["prompt"]).read_text(
        encoding="utf-8"
    )
    final_schema = json.loads(
        pathlib.Path(final_task["artifacts"]["schema"]).read_text(
            encoding="utf-8"
        )
    )
    assert (
        len(final_prompt.encode("utf-8")) + workflow._json_bytes(final_schema)
        <= state["model_specs"]["sol"]["input_byte_budget"]
    )
    assert final_call["input_payload"]["canonical_state"] == []
    assert final_call["input_payload"]["surface_contracts"] == {}
    assert all(
        "surface_summaries" not in result and "analysis_summary" not in result
        for result in final_call["input_payload"]["prior_adjudication_results"]
    )
    assert all(
        row[3:6] == [[], [], {}]
        for row in final_call["input_payload"]["call_inventory"]["rows"]
    )
    final = json.loads(
        pathlib.Path(completed["final_result_path"]).read_text(encoding="utf-8")
    )
    assert final["deep_review_finding_ids"] == [
        item["finding_id"]
        for item in final_call["input_payload"]["deep_review_evidence"]
    ]
    completed_state = json.loads(
        pathlib.Path(plan["state_path"]).read_text(encoding="utf-8")
    )
    prior_findings = [
        finding
        for task in manifest["sol_tasks"][:6]
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
    assert "| Run started | Total model calls | Avoidable calls | Unassessed calls |" in report
    assert all(line.startswith("|") and line.endswith("|") for line in report.splitlines())
    assert len(report.splitlines()) == len(final["run_accounting"]) + 3
    assert " UTC |" in report
    assert sum(row["unassessed_calls"] for row in final["run_accounting"]) == final["classification_totals"]["unassessed"]
    assert "Problem:" in completed["presentation_contract"]
    assert "Proposed fix:" in completed["presentation_contract"]
    assert "Benefit and effort:" in completed["presentation_contract"]

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
    assert sol_capacity_omissions == []
    assert not any(
        omission.get("reason") == "sol-capacity"
        for omission in capacity_final["omissions"]
    )
    routing = json.loads(
        pathlib.Path(capacity_state["routing"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    reviewer_plan = capacity_state["manifest"]["sol_reviewer_plan"]
    assert all(
        reviewer["planned_routing_bytes"]
        <= reviewer_plan["capacity_bytes_per_reviewer"]
        for reviewer in reviewer_plan["reviewers"]
    )
    assert all(
        shard["routing_bytes"] <= routing["capacity_bytes_per_adjudicator"]
        for shard in routing["shards"]
    )
    assert {
        task["task_id"]
        for task in capacity_state["manifest"]["luna_tasks"]
        if capacity_state["execution"][task["task_id"]]["status"] == "complete"
    } == {
        task_id
        for shard in routing["shards"]
        for task_id in shard["luna_task_ids"]
    }

    class UnassessedPreliminaryRunner(FakeCreditModelRunner):
        def _sol(
            self,
            task: Mapping[str, Any],
            packet: Mapping[str, Any],
            digest: str,
        ) -> dict[str, Any]:
            result = super()._sol(task, packet, digest)
            if task.get("review_kind") == "unassessed-recovery":
                return result
            for group in result["call_classifications"]:
                if group["classification"] == "reviewed_no_confirmed_waste":
                    group["classification"] = "unassessed"
                    group["rationale"] = "The preliminary review lacked context."
            return result

    recovery_root = tmp_path / "unassessed-recovery"
    recovery_root.mkdir()
    recovery_request, _, _ = credit_analysis_request(
        recovery_root,
        extra_completed_turns=2,
        extra_calls_per_turn=8,
    )
    recovery_runner = UnassessedPreliminaryRunner(temporary_controls=False)
    recovery_plan = workflow.command_plan_orchestration(
        recovery_request,
        available_models=recovery_runner.available_models,
    )
    recovery_completed = workflow.command_execute_orchestration(
        pathlib.Path(recovery_plan["state_path"]),
        runner=recovery_runner,
        available_models=recovery_runner.available_models,
    )
    recovery_calls = [
        call
        for call in recovery_runner.calls
        if call["review_kind"] == "unassessed-recovery"
    ]
    assert recovery_completed["complete"] is True
    assert len(recovery_calls) == 1
    assert recovery_calls[0]["input_payload"]["recovery_run_parts"]
    assert {
        row[1]
        for row in recovery_calls[0]["input_payload"]["call_inventory"]["rows"]
    }
    recovery_final_call = next(
        call for call in recovery_runner.calls if call["phase"] == "sol-final"
    )
    assert recovery_final_call["input_payload"]["recovery_result"] is not None
    recovery_final = json.loads(
        pathlib.Path(recovery_completed["final_result_path"]).read_text(
            encoding="utf-8"
        )
    )
    assert recovery_final["classification_totals"]["unassessed"] <= (
        recovery_final["manifest"]["candidate_count"] // 5
    )

    shipped_scope = tmp_path / "shipped-worktree-recovery"
    shipped_scope.mkdir()
    repository_parent = shipped_scope / "projects"
    repository_parent.mkdir()
    primary_checkout = repository_parent / "source-repo"
    primary_checkout.mkdir()
    repository_url = "https://example.test/example/source-repo.git"
    initialized = run_git(primary_checkout, "init")
    assert initialized.returncode == 0, initialized.stderr
    remote_added = run_git(
        primary_checkout,
        "remote",
        "add",
        "origin",
        repository_url,
    )
    assert remote_added.returncode == 0, remote_added.stderr
    (primary_checkout / "AGENTS.md").write_text(
        "# Recovered source controls\n",
        encoding="utf-8",
        newline="\n",
    )
    missing_worktree = (
        repository_parent
        / "worktrees"
        / primary_checkout.name
        / "shipped-task"
    )
    recovered_request, recovered_session, _ = credit_analysis_request(
        shipped_scope
    )
    credit_analysis_session(
        recovered_session,
        cwd=missing_worktree,
        repository_url=repository_url,
    )
    recovered_runner = FakeCreditModelRunner(temporary_controls=False)
    recovered_plan = workflow.command_plan_orchestration(
        recovered_request,
        available_models=recovered_runner.available_models,
    )
    recovered_state_path = pathlib.Path(recovered_plan["state_path"])
    recovered_state = json.loads(
        recovered_state_path.read_text(encoding="utf-8")
    )
    resolved_primary = str(primary_checkout.resolve())
    assert recovered_state["execution_context"]["primary_cwd"] == resolved_primary
    assert recovered_state["execution_context"]["cwd_substitutions"] == [
        {
            "recorded_cwd": str(missing_worktree.resolve(strict=False)),
            "resolved_cwd": resolved_primary,
            "repository_url": repository_url,
            "reason": "missing-canonical-worktree",
        }
    ]
    assert all(
        task["execution_cwd"] == resolved_primary
        for task in [
            *recovered_state["manifest"]["luna_tasks"],
            *recovered_state["manifest"]["sol_tasks"],
        ]
    )
    recovered_completed = workflow.command_execute_orchestration(
        recovered_state_path,
        runner=recovered_runner,
        available_models=recovered_runner.available_models,
    )
    assert recovered_completed["complete"] is True

    mismatch_scope = tmp_path / "shipped-worktree-mismatch"
    mismatch_scope.mkdir()
    mismatch_request, mismatch_session, _ = credit_analysis_request(
        mismatch_scope
    )
    credit_analysis_session(
        mismatch_session,
        cwd=missing_worktree,
        repository_url="https://example.test/other/source-repo.git",
    )
    with pytest.raises(
        workflow.CreditAnalysisError,
        match="repository identity does not match",
    ):
        workflow.command_plan_orchestration(
            mismatch_request,
            available_models=holistic_model_catalog(),
        )


def test_final_payload_accounts_for_schema_and_prompt_overhead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = load_credit_analysis_workflow_module()
    globals_ = workflow.command_plan_orchestration.__globals__
    monkeypatch.setitem(
        globals_,
        "_holistic_sol_schema",
        lambda **_: {"schema_padding": "s" * 300},
    )
    monkeypatch.setitem(
        globals_,
        "_holistic_prompt",
        lambda **kwargs: (
            "p" * 200
            + json.dumps(
                kwargs["input_payload"],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        ),
    )
    state = {
        "model_specs": {
            "sol": {
                "evidence_byte_budget": 900,
                "input_byte_budget": 1_000,
            }
        }
    }
    canonical_payload = {
        "fixed": "x" * 100,
        "deep_review_evidence": [{"record": "excluded-from-base"}],
    }
    base_payload = {**canonical_payload, "deep_review_evidence": []}
    schema = {"schema_padding": "s" * 300}
    expected = min(
        900,
        1_000 - 200 - workflow._json_bytes(schema),
    )

    budget = globals_["_final_payload_byte_budget"](
        state=state,
        task={},
        contract={},
        canonical_payload=canonical_payload,
        luna_candidate_ids=[],
        aliases={},
        canonical_to_alias={},
    )

    assert budget == expected
    assert workflow._json_bytes(base_payload) < budget < 900


def test_removed_bounded_action_is_rejected(tmp_path: pathlib.Path) -> None:
    workflow = load_credit_analysis_workflow_module()
    request, _, _ = credit_analysis_request(
        tmp_path, action="bounded-largest-" "runs-analysis"
    )
    with pytest.raises(workflow.CreditAnalysisError, match="not public"):
        workflow.command_plan_orchestration(
            request, available_models=holistic_model_catalog()
        )


def test_luna_admission_caps_at_seventy_attempts_and_fifteen_workers(
    tmp_path: pathlib.Path,
) -> None:
    workflow = load_credit_analysis_workflow_module()
    request, _, _ = credit_analysis_request(
        tmp_path, extra_completed_turns=72, extra_calls_per_turn=1
    )

    class ConcurrentRunner(FakeCreditModelRunner):
        def __init__(self) -> None:
            super().__init__(temporary_controls=False)
            self.lock = threading.Lock()
            self.active = 0
            self.maximum_active = 0
            self.started = 0
            self.first_wave = threading.Barrier(15)

        def _luna(
            self,
            task: Mapping[str, Any],
            packet: Mapping[str, Any],
            digest: str,
        ) -> dict[str, Any]:
            with self.lock:
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
                self.started += 1
                wait_for_first_wave = self.started <= 15
            try:
                if wait_for_first_wave:
                    self.first_wave.wait(timeout=2)
                time.sleep(0.01)
                return super()._luna(task, packet, digest)
            finally:
                with self.lock:
                    self.active -= 1

    runner = ConcurrentRunner()
    plan = workflow.command_plan_orchestration(
        request, available_models=runner.available_models
    )
    planned_state = json.loads(
        pathlib.Path(plan["state_path"]).read_text(encoding="utf-8")
    )
    admitted = [
        task
        for task in planned_state["manifest"]["luna_tasks"]
        if planned_state["execution"][task["task_id"]]["status"] == "pending"
    ]
    reviewer_plan = planned_state["manifest"]["sol_reviewer_plan"]
    assert {
        task["task_id"] for task in admitted
    } == {
        task_id
        for reviewer in reviewer_plan["reviewers"]
        for task_id in reviewer["luna_task_ids"]
    }
    assert all(
        1_000 <= int(task["output_byte_limit"]) <= 64_000
        and task["sol_reviewer_task_id"]
        and task["planned_routing_bytes"]
        for task in admitted
    )
    assert all(
        reviewer["planned_routing_bytes"]
        <= reviewer_plan["capacity_bytes_per_reviewer"]
        for reviewer in reviewer_plan["reviewers"]
    )
    selector = workflow.command_plan_orchestration.__globals__["select_luna_tasks"]
    priority_tasks = [
        {
            "task_id": "a.1",
            "turn_id": "a",
            "run_window_ordinal": 1,
            "input_bytes": 100,
            "evidence_bytes": 100,
            "capacity_omitted": False,
        },
        *[
            {
                "task_id": f"b.{ordinal}",
                "turn_id": "b",
                "run_window_ordinal": ordinal,
                "input_bytes": 1_000,
                "evidence_bytes": 1_000,
                "capacity_omitted": False,
            }
            for ordinal in range(1, 4)
        ],
        {
            "task_id": "c.1",
            "turn_id": "c",
            "run_window_ordinal": 1,
            "input_bytes": 200,
            "evidence_bytes": 200,
            "capacity_omitted": False,
        },
    ]
    assert selector(priority_tasks, maximum_attempts=2) == {"b.1", "c.1"}
    planner = workflow.command_plan_orchestration.__globals__["plan_luna_reviewers"]
    bins = planner(
        [
            {
                "task_id": f"task-{ordinal}",
                "inventory_bytes": size,
                "run_ordinal": ordinal,
                "run_window_ordinal": 1,
            }
            for ordinal, size in enumerate(
                (4_000, 4_000, 4_000, 4_000, 2_000, 2_000, 1_000, 1_000, 1_000),
                start=1,
            )
        ],
        bin_count=6,
        capacity_bytes=6_000,
        per_report_framing_bytes=0,
    )
    assert sorted(
        sorted(group["inventory_bytes"] for group in group_bin)
        for group_bin in bins
    ) == [[1_000, 1_000, 1_000], [2_000, 2_000], [4_000], [4_000], [4_000], [4_000]]
    assert all(
        sum(group["planned_routing_bytes"] for group in group_bin) <= 6_000
        for group_bin in bins
    )
    fitter = workflow.command_plan_orchestration.__globals__[
        "_fit_final_supplemental_evidence"
    ]
    selected_evidence, capacity_omissions = fitter(
        base_payload={"deep_review_evidence": [], "fixed": "value"},
        evidence_groups=[
            {
                "finding_id": "f1",
                "producer_owner": "one",
                "proposed_durable_control": "control-one",
                "original_evidence": [
                    {"call_id": "too-large", "text": "x" * 1_000},
                    {"call_id": "small-one", "text": "one"},
                ],
            },
            {
                "finding_id": "f2",
                "producer_owner": "two",
                "proposed_durable_control": "control-two",
                "original_evidence": [
                    {"call_id": "small-two", "text": "two"},
                ],
            },
        ],
        byte_budget=500,
        transform=lambda value: value,
    )
    assert [
        record["call_id"]
        for group in selected_evidence
        for record in group["original_evidence"]
    ] == ["small-one", "small-two"]
    assert [
        omission["omitted_window_task_ids"] for omission in capacity_omissions
    ] == [["too-large"]]
    completed = workflow.command_execute_orchestration(
        pathlib.Path(plan["state_path"]),
        runner=runner,
        available_models=runner.available_models,
    )
    assert completed["actual_luna_calls"] == 70
    assert runner.maximum_active == 15
    final = json.loads(
        pathlib.Path(completed["final_result_path"]).read_text(encoding="utf-8")
    )
    capped = [
        item for item in final["omissions"]
        if item["reason"] == "luna-attempt-cap"
    ]
    assert len(capped) == 5
    assert all(item["candidate_ids"] for item in capped)
    assert final["coverage"]["analyzed_runs"] == 70
    assert final["coverage"]["eligible_runs"] == 75
    report = pathlib.Path(completed["report_path"]).read_text(encoding="utf-8")
    omitted_runs = [row for row in final["run_accounting"] if row["review_status"] == "not reviewed"]
    assert len(omitted_runs) == 5
    for row in omitted_runs:
        omitted_label = f"not reviewed ({row['total_model_calls']} omitted)"
        assert f"| {omitted_label} | {omitted_label} |" in report
    assert len(report.splitlines()) == 78


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

    final = json.loads(pathlib.Path(completed["final_result_path"]).read_text(encoding="utf-8"))
    assert "not reviewed (" in pathlib.Path(completed["report_path"]).read_text(encoding="utf-8")
    # Independent arithmetic cases cover both renderers, omitted evidence and
    # semantic uncertainty; finding memberships must never be counted as calls.
    display = json.loads(json.dumps(final))
    display["run_accounting"] = [
        {
            "turn_id": "private-run-identifier",
            "started_at": "2026-09-10T03:00:00+03:00",
            "total_model_calls": 4, "reviewed_model_calls": 4,
            "avoidable_calls_fix_implemented": 1,
            "avoidable_calls_fix_unimplemented": 1, "unassessed_calls": 1,
            "tokens": {"input_tokens": 80, "cached_input_tokens": 20,
                       "output_tokens": 20, "reasoning_output_tokens": 5, "total_tokens": 100},
        },
        {
            "started_at": "2026-09-10T00:00:00-04:00",
            "total_model_calls": 6, "reviewed_model_calls": 4,
            "avoidable_calls_fix_implemented": 1,
            "avoidable_calls_fix_unimplemented": 1, "unassessed_calls": 1,
            "tokens": {"input_tokens": 70, "cached_input_tokens": 70,
                       "output_tokens": 30, "reasoning_output_tokens": 15, "total_tokens": 100},
        },
        {
            "started_at": None, "total_model_calls": 2, "reviewed_model_calls": 0,
            "avoidable_calls_fix_implemented": 0,
            "avoidable_calls_fix_unimplemented": 0, "unassessed_calls": 0, "tokens": {},
        },
    ]
    before_display = json.dumps(display, sort_keys=True)
    report = workflow._render_holistic_report(display)
    assert report.splitlines()[2:] == [
        "| 2026-09-10 00:00:00 UTC | 4 | 2 | 1 | 100; 80.00% / 25.00% / 20.00% / 25.00% |",
        "| 2026-09-10 04:00:00 UTC | 6 | 2 (4 reviewed; 2 omitted) | 1 (4 reviewed; 2 omitted) | 100; 70.00% / 100.00% / 30.00% / 50.00% |",
        "| not recorded | 2 | not reviewed (2 omitted) | not reviewed (2 omitted) | 0; 0.00% / 0.00% / 0.00% / 0.00% |",
        "| **Total** | **12** | **4 (8 reviewed; 4 omitted)** | **2 (8 reviewed; 4 omitted)** | **200; 75.00% / 60.00% / 25.00% / 40.00%** |",
    ]
    assert json.dumps(display, sort_keys=True) == before_display
    omitted_only = workflow._render_holistic_report({**display, "run_accounting": display["run_accounting"][2:]})
    assert "| **Total** | **2** | **not reviewed (2 omitted)** | **not reviewed (2 omitted)** |" in omitted_only
    empty = workflow._render_holistic_report({**display, "run_accounting": []})
    assert len(empty.splitlines()) == 3
    assert "| **Total** | **0** | **0** | **0** | **0; 0.00%" in empty

    legacy = {
        "mode": "full-analysis",
        "confirmed_findings": display["confirmed_findings"],
        "plausible_risks": display["plausible_risks"],
        "primary_call_mappings": [
            {"call_id": f"call-{index}", "classification": classification}
            for index, classification in enumerate([
                "avoidable_implemented", "avoidable_unimplemented", "unassessed", "necessary",
            ])
        ],
    }
    retained_evidence = {"runs": [{
        "started_at": "2026-09-10T03:00:00+03:00",
        "calls": [{"call_id": f"call-{index}", "tokens": display["run_accounting"][0]["tokens"] if index == 0 else {}}
                  for index in range(5)],
    }]}
    legacy_before = json.dumps([legacy, retained_evidence], sort_keys=True)
    report = workflow._render_final_report(legacy, retained_evidence)
    assert "| 2026-09-10 00:00:00 UTC | 5 | 2 (4 reviewed; 1 omitted) | 1 (4 reviewed; 1 omitted) | 100;" in report
    packet_path = tmp_path / "display-final.json"
    packet_path.write_text(json.dumps(legacy), encoding="utf-8")
    packet_state = {"finalized": True, "mode": "full-analysis", "analysis_id": "display",
                    "final_result": {"path": str(packet_path)}, "evidence": {"path": "retained-evidence.json"}}
    packet = workflow._final_packet(packet_state, retained_evidence, {})
    assert packet["report_markdown"] == report
    assert "still-actionable" in packet["presentation_contract"]
    assert "earlier runs" in packet["presentation_contract"]
    assert "Retain every finding" in packet["presentation_contract"]
    assert json.dumps([legacy, retained_evidence], sort_keys=True) == legacy_before
    assert json.loads(packet_path.read_text(encoding="utf-8")) == legacy
    standalone = {**legacy, "mode": "standalone", "scope_limitation": "Conclusions cover only tool and handoff flow and are not a whole-thread credit reconciliation."}
    assert workflow._render_final_report(standalone, retained_evidence) == standalone["scope_limitation"] + "\n"
    assert workflow._render_holistic_report(standalone) == standalone["scope_limitation"] + "\n"


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
    global_rules = codex_home / "AGENTS.md"
    global_rules.write_text(
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
    alternate_rules = alternate_cwd / "AGENTS.md"
    alternate_rules.write_text(
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
    assert plan["projected_sol_calls"] == 7
    assert plan["maximum_planned_sol_calls"] == 8
    assert plan["maximum_sol_attempts"] == 16
    assert plan["projected_semantic_calls"] == 13
    assert plan["candidate_count"] > 8
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
    global_rules.write_text(
        "LATER_GLOBAL_CONTROL_SENTINEL\n",
        encoding="utf-8",
        newline="\n",
    )
    alternate_rules.write_text(
        "LATER_RUN_LOCAL_CONTROL_SENTINEL\n",
        encoding="utf-8",
        newline="\n",
    )
    drifted_status = workflow.command_orchestration_status(state_path)
    assert drifted_status["completed_tasks"] == 1
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
    assert sum(call["phase"] == "sol-adjudication" for call in runner.calls) == 6
    assert sum(call["phase"] == "sol-direct-evidence" for call in runner.calls) == 1
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
    assert all(
        "Do not independently re-read the source evidence" in call["prompt"]
        and call["input_payload"]["candidate_original_evidence"] == []
        and call["input_payload"]["canonical_state"] == []
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
    assert not any(
        "LATER_RUN_LOCAL_CONTROL_SENTINEL" in item["text"]
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
    assert any(
        pathlib.Path(item["path"]) == global_rules.resolve()
        and item["text"] == "CURRENT_GLOBAL_CONTROL_SENTINEL\n"
        and item["sha256"]
        == hashlib.sha256(item["text"].encode("utf-8")).hexdigest()
        for item in frozen_rule_files
    )
    assert global_rules.read_text(encoding="utf-8") == (
        "LATER_GLOBAL_CONTROL_SENTINEL\n"
    )
    corrupted_context = json.loads(
        json.dumps(completed_state["execution_context"])
    )
    corrupted_context["instruction_chains"][0]["files"][0]["text"] += "changed"
    with pytest.raises(
        workflow.CreditAnalysisError,
        match="frozen instruction file identity changed",
    ):
        workflow.command_orchestration_status.__globals__[
            "_validate_execution_context"
        ](corrupted_context)
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
            assert attempt["ephemeral"] is False
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
        "actual_sol": 8,
        "accepted_luna": 6,
        "accepted_sol": 8,
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
    ) == final["manifest"]["candidate_count"]
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
    assert "| Run started | Total model calls | Avoidable calls | Unassessed calls |" in report
    assert all(line.startswith("|") and line.endswith("|") for line in report.splitlines())
    assert len(report.splitlines()) == len(final["run_accounting"]) + 3
    assert all(finding["proposed_durable_control"] not in report for finding in outstanding_findings)
    assert all(run["turn_id"] not in report for run in final["run_accounting"])
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
        def __init__(self) -> None:
            super().__init__()
            self.invalidated = False

        def _sol(
            self,
            task: Mapping[str, Any],
            packet: Mapping[str, Any],
            digest: str,
        ) -> dict[str, Any]:
            result = super()._sol(task, packet, digest)
            if (
                task["task_id"] == "sol.adjudication.0001"
                and not self.invalidated
            ):
                self.invalidated = True
                result["candidate_decisions"][0]["reason"] = "x" * 321
            return result

    failure_runner = OneInvalidSolRunner()
    failure_state_path = pathlib.Path(failure_plan["state_path"])
    recovered = workflow.command_execute_orchestration(
        failure_state_path,
        runner=failure_runner,
        available_models=failure_runner.available_models,
    )
    assert recovered["complete"] is True
    failure_state = json.loads(failure_state_path.read_text(encoding="utf-8"))
    assert [
        attempt["outcome"]
        for attempt in failure_state["execution"]["sol.adjudication.0001"][
            "attempts"
        ]
    ] == ["validation-error", "accepted"]
    assert all(
        failure_state["execution"][task_id]["status"] == "complete"
        for task_id in (
            "sol.adjudication.0001",
            "sol.adjudication.0002",
            "sol.adjudication.0003",
            "sol.adjudication.0004",
            "sol.adjudication.0005",
            "sol.adjudication.0006",
            "sol.final",
        )
    )
    assert failure_state["execution"]["sol.direct-evidence"]["status"] == "complete"
    assert failure_state["model_attempts"]["sol"] == 9
    assert failure_state["omissions"] == []
    failure_call_count = len(failure_runner.calls)
    assert workflow.command_execute_orchestration(
        failure_state_path,
        runner=failure_runner,
        available_models=failure_runner.available_models,
    )["complete"] is True
    assert len(failure_runner.calls) == failure_call_count

    capped_root = tmp_path / "saved-final-after-validation-retry"
    capped_root.mkdir()
    capped_request, _, _ = credit_analysis_request(
        capped_root, extra_completed_turns=3, extra_calls_per_turn=4,
    )
    capped_plan = workflow.command_plan_orchestration(
        capped_request, available_models=holistic_model_catalog(),
    )
    capped_state_path = pathlib.Path(capped_plan["state_path"])

    capped_runner = FakeCreditModelRunner()
    current_validator = workflow._validate_holistic_task_result

    def previous_validator(raw: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
        if kwargs["task"]["phase"] == "sol-final":
            raise workflow.CreditAnalysisError("simulated final-result validation failure")
        return current_validator(raw, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(workflow, "_validate_holistic_task_result", previous_validator)
        with pytest.raises(workflow.CreditAnalysisError, match="simulated final-result validation failure"):
            workflow.command_execute_orchestration(
                capped_state_path, runner=capped_runner,
                available_models=capped_runner.available_models,
            )
        capped_state = json.loads(capped_state_path.read_text(encoding="utf-8"))
        assert capped_state["model_attempts"]["sol"] == 9
        final_attempts = capped_state["execution"]["sol.final"]["attempts"]
        assert [attempt["outcome"] for attempt in final_attempts] == ["validation-error", "validation-error"]
        capped_call_count = len(capped_runner.calls)
        # Invalid saved output cannot buy a third final call.
        with pytest.raises(workflow.CreditAnalysisError, match="failed validation after its automatic retry"):
            workflow.command_execute_orchestration(
                capped_state_path, runner=capped_runner,
                available_models=capped_runner.available_models,
            )
        assert len(capped_runner.calls) == capped_call_count

    raw_path = pathlib.Path(final_attempts[-1]["artifacts"]["raw_output"]["path"])
    frozen_raw = raw_path.read_bytes()
    raw_path.write_bytes(frozen_raw + b"\n")
    with pytest.raises(workflow.CreditAnalysisError, match="changed|hash"):
        workflow.command_execute_orchestration(
            capped_state_path, runner=capped_runner,
            available_models=capped_runner.available_models,
        )
    raw_path.write_bytes(frozen_raw)
    recovered_final = workflow.command_execute_orchestration(
        capped_state_path, runner=capped_runner,
        available_models=capped_runner.available_models,
    )
    assert recovered_final["complete"] is True
    assert len(capped_runner.calls) == capped_call_count
    recovered_state = json.loads(capped_state_path.read_text(encoding="utf-8"))
    assert recovered_state["model_attempts"] == capped_state["model_attempts"]
    assert recovered_state["execution"]["sol.final"]["attempts"] == final_attempts
    assert recovered_state["execution"]["sol.final"]["result"]["recovered_without_model_call"] is True
    assert raw_path.read_bytes() == frozen_raw
    recovered_result_path = pathlib.Path(recovered_final["final_result_path"])
    final_bytes = recovered_result_path.read_bytes()
    assert any(risk["source_risks"] for risk in json.loads(final_bytes)["plausible_risks"])
    assert workflow.command_execute_orchestration(
        capped_state_path, runner=capped_runner,
        available_models=capped_runner.available_models,
    )["complete"] is True
    assert recovered_result_path.read_bytes() == final_bytes
    assert len(capped_runner.calls) == capped_call_count

    mechanical_root = tmp_path / "mechanical-sol-repair"
    mechanical_root.mkdir()
    mechanical_request, _, _ = credit_analysis_request(
        mechanical_root,
        extra_completed_turns=3,
        extra_calls_per_turn=4,
    )
    mechanical_plan = workflow.command_plan_orchestration(
        mechanical_request,
        available_models=holistic_model_catalog(),
    )

    class MechanicalSolRunner(FakeCreditModelRunner):
        def __init__(self) -> None:
            super().__init__()
            self.rationale_task_id: str | None = None
            self.review_task_id: str | None = None
            self.invalid_review_id = "Invalid Review ID"

        def _sol(
            self,
            task: Mapping[str, Any],
            packet: Mapping[str, Any],
            digest: str,
        ) -> dict[str, Any]:
            result = super()._sol(task, packet, digest)
            if self.rationale_task_id is None and result["call_classifications"]:
                self.rationale_task_id = str(task["task_id"])
                result["call_classifications"][0]["rationale"] = "r" * 400
            if self.review_task_id is None and result["temporary_control_reviews"]:
                self.review_task_id = str(task["task_id"])
                referenced = {
                    review_id
                    for merge in result["temporary_control_merges"]
                    for review_id in merge["review_ids"]
                }
                review = next(
                    (
                        item
                        for item in result["temporary_control_reviews"]
                        if item["id"] in referenced
                    ),
                    result["temporary_control_reviews"][0],
                )
                original_id = review["id"]
                review["id"] = self.invalid_review_id
                for merge in result["temporary_control_merges"]:
                    merge["review_ids"] = [
                        self.invalid_review_id if item == original_id else item
                        for item in merge["review_ids"]
                    ]
            return result

    mechanical_runner = MechanicalSolRunner()
    mechanical_state_path = pathlib.Path(mechanical_plan["state_path"])
    mechanical_status = workflow.command_execute_orchestration(
        mechanical_state_path,
        runner=mechanical_runner,
        available_models=mechanical_runner.available_models,
    )
    assert mechanical_status["complete"] is True
    assert mechanical_runner.rationale_task_id is not None
    assert mechanical_runner.review_task_id is not None
    mechanical_state = json.loads(
        mechanical_state_path.read_text(encoding="utf-8")
    )
    assert (
        mechanical_state["model_attempts"]["sol"]
        == mechanical_state["model_calls"]["sol"]
    )
    rationale_execution = mechanical_state["execution"][
        mechanical_runner.rationale_task_id
    ]
    assert [item["outcome"] for item in rationale_execution["attempts"]] == [
        "accepted"
    ]
    raw_rationale = json.loads(
        pathlib.Path(
            rationale_execution["attempts"][0]["artifacts"]["raw_output"]["path"]
        ).read_text(encoding="utf-8")
    )
    accepted_rationale = json.loads(
        pathlib.Path(rationale_execution["result"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    assert len(raw_rationale["call_classifications"][0]["rationale"]) == 400
    assert all(
        len(item["rationale"]) <= 240
        for item in accepted_rationale["call_classifications"]
    )
    review_execution = mechanical_state["execution"][
        mechanical_runner.review_task_id
    ]
    assert [item["outcome"] for item in review_execution["attempts"]] == [
        "accepted"
    ]
    raw_review = json.loads(
        pathlib.Path(
            review_execution["attempts"][0]["artifacts"]["raw_output"]["path"]
        ).read_text(encoding="utf-8")
    )
    accepted_review = json.loads(
        pathlib.Path(review_execution["result"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    assert mechanical_runner.invalid_review_id in {
        item["id"] for item in raw_review["temporary_control_reviews"]
    }
    accepted_review_ids = {
        item["id"] for item in accepted_review["temporary_control_reviews"]
    }
    assert mechanical_runner.invalid_review_id not in accepted_review_ids
    assert "review-0001" in accepted_review_ids
    assert all(
        set(merge["review_ids"]).issubset(accepted_review_ids)
        for merge in accepted_review["temporary_control_merges"]
    )

    zero_review_root = tmp_path / "zero-accepted-reviewers"
    zero_review_root.mkdir()
    zero_review_request, _, _ = credit_analysis_request(zero_review_root)
    zero_review_plan = workflow.command_plan_orchestration(
        zero_review_request,
        available_models=holistic_model_catalog(),
    )

    class AllInvalidSolRunner(FakeCreditModelRunner):
        def _sol(
            self,
            task: Mapping[str, Any],
            packet: Mapping[str, Any],
            digest: str,
        ) -> dict[str, Any]:
            result = super()._sol(task, packet, digest)
            result["candidate_decisions"][0]["reason"] = "x" * 321
            return result

    zero_review_runner = AllInvalidSolRunner()
    zero_review_state_path = pathlib.Path(zero_review_plan["state_path"])
    zero_review_status = workflow.command_execute_orchestration(
        zero_review_state_path,
        runner=zero_review_runner,
        available_models=zero_review_runner.available_models,
    )
    assert zero_review_status["phase"] == "incomplete"
    assert zero_review_status["complete"] is False
    assert zero_review_status["next_task"] is None
    assert zero_review_status["final_result_path"] is None
    assert zero_review_status["report_path"] is None
    assert not any(
        call["phase"] == "sol-final" for call in zero_review_runner.calls
    )
    zero_review_state = json.loads(
        zero_review_state_path.read_text(encoding="utf-8")
    )
    assert zero_review_state["execution"]["sol.final"]["status"] == "skipped"
    assert not any(
        zero_review_state["execution"][task["task_id"]]["status"] == "complete"
        for task in zero_review_state["manifest"]["sol_tasks"]
        if task["phase"] == "sol-adjudication"
    )
    assert any(
        item["reason"] == "sol-invalid-output"
        for item in zero_review_state["omissions"]
    )
    zero_review_call_count = len(zero_review_runner.calls)
    assert workflow.command_execute_orchestration(
        zero_review_state_path,
        runner=zero_review_runner,
        available_models=zero_review_runner.available_models,
    )["phase"] == "incomplete"
    assert len(zero_review_runner.calls) == zero_review_call_count

    persistent_root = tmp_path / "persistent-invalid-sol"
    persistent_root.mkdir()
    persistent_request, _, _ = credit_analysis_request(
        persistent_root,
        extra_completed_turns=1,
        extra_calls_per_turn=4,
    )
    persistent_plan = workflow.command_plan_orchestration(
        persistent_request,
        available_models=holistic_model_catalog(),
    )

    class PersistentInvalidSolRunner(FakeCreditModelRunner):
        def __init__(self) -> None:
            super().__init__()
            self.invalid_task_id: str | None = None

        def _sol(
            self,
            task: Mapping[str, Any],
            packet: Mapping[str, Any],
            digest: str,
        ) -> dict[str, Any]:
            result = super()._sol(task, packet, digest)
            if task["task_id"] == self.invalid_task_id:
                result["candidate_decisions"][0]["reason"] = "x" * 321
            return result

    persistent_runner = PersistentInvalidSolRunner()
    persistent_state_path = pathlib.Path(persistent_plan["state_path"])
    persistent_planned_state = json.loads(
        persistent_state_path.read_text(encoding="utf-8")
    )
    workflow.command_execute_orchestration(
        persistent_state_path,
        runner=persistent_runner,
        available_models=persistent_runner.available_models,
        task_limit=len(persistent_planned_state["manifest"]["luna_tasks"]),
    )
    persistent_routed_state = json.loads(
        persistent_state_path.read_text(encoding="utf-8")
    )
    persistent_routing = json.loads(
        pathlib.Path(persistent_routed_state["routing"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    audit_luna_task_id = persistent_routing["audit_windows"][0]["luna_task_id"]
    persistent_runner.invalid_task_id = next(
        shard["task_id"]
        for shard in persistent_routing["shards"]
        if audit_luna_task_id in shard["luna_task_ids"]
    )
    assert persistent_runner.invalid_task_id is not None
    persistent_status = workflow.command_execute_orchestration(
        persistent_state_path,
        runner=persistent_runner,
        available_models=persistent_runner.available_models,
    )
    assert persistent_status["complete"] is True
    persistent_state = json.loads(
        persistent_state_path.read_text(encoding="utf-8")
    )
    rejected_execution = persistent_state["execution"][
        persistent_runner.invalid_task_id
    ]
    assert rejected_execution["status"] == "omitted"
    assert [attempt["outcome"] for attempt in rejected_execution["attempts"]] == [
        "validation-error",
        "validation-error",
    ]
    invalid_omission = next(
        omission
        for omission in persistent_state["omissions"]
        if omission.get("task_id") == persistent_runner.invalid_task_id
    )
    assert invalid_omission["reason"] == "sol-invalid-output"
    assert invalid_omission["candidate_ids"]
    assert invalid_omission["call_ids"]
    assert invalid_omission["input_bytes"] > 0
    assert invalid_omission["output_bytes"] > 0
    assert persistent_state["execution"]["sol.direct-evidence"]["status"] == "complete"
    assert persistent_state["execution"]["sol.final"]["status"] == "complete"
    assert persistent_state["model_attempts"]["sol"] == 7
    persistent_final_call = next(
        call for call in persistent_runner.calls if call["phase"] == "sol-final"
    )
    assert persistent_final_call["input_payload"]["audit_result"] is None
    final_task = next(
        task
        for task in persistent_state["manifest"]["sol_tasks"]
        if task["phase"] == "sol-final"
    )
    final_aliases = json.loads(
        pathlib.Path(final_task["artifacts"]["aliases"]).read_text(encoding="utf-8")
    )
    assert set(invalid_omission["call_ids"]).isdisjoint(
        final_aliases["aliases"]["calls"].values()
    )
    persistent_final = json.loads(
        pathlib.Path(persistent_status["final_result_path"]).read_text(
            encoding="utf-8"
        )
    )
    assert persistent_final["coverage"]["analyzed_calls"] < persistent_final[
        "coverage"
    ]["eligible_calls"]


def _assert_sol_budget_boundaries(tmp_path: pathlib.Path) -> None:
    """Exercise real scheduling, retry accounting, and interrupted-state resume."""

    workflow = load_credit_analysis_workflow_module()

    class BudgetRunner(FakeCreditModelRunner):
        def __init__(self, *, all_tasks: bool, final_failure: bool = False) -> None:
            super().__init__(temporary_controls=False)
            self.all_tasks = all_tasks
            self.final_failure = final_failure
            self.sol_attempts: dict[str, int] = {}

        def run(self, **kwargs: Any) -> dict[str, Any]:
            result = super().run(**kwargs)
            task = kwargs["task"]
            if not task["phase"].startswith("sol-"):
                return result
            task_id = task["task_id"]
            self.sol_attempts[task_id] = self.sol_attempts.get(task_id, 0) + 1
            if self.final_failure and task["phase"] == "sol-final":
                raise RuntimeError("synthetic invoked final failure")
            selected = self.all_tasks or task_id in {
                "sol.adjudication.0001", "sol.adjudication.0002", "sol.final"
            }
            if selected and self.sol_attempts[task_id] == 1:
                return {}
            return result

    for name, extra_runs, planned_calls, actual_calls in (
        ("motivating-final-correction", 1, 6, 9),
        ("all-eight-tasks-retried", 3, 8, 16),
    ):
        scenario = tmp_path / name
        scenario.mkdir()
        request, _, _ = credit_analysis_request(
            scenario, extra_completed_turns=extra_runs, extra_calls_per_turn=4
        )
        runner = BudgetRunner(all_tasks=planned_calls == 8)
        plan = workflow.command_plan_orchestration(
            request, available_models=runner.available_models
        )
        state_path = pathlib.Path(plan["state_path"])
        state = json.loads(state_path.read_text(encoding="utf-8"))
        contract = workflow._load_contract()
        assert contract["semantic_call_contract"]["sol_max_planned_calls"] == 8
        assert contract["semantic_call_contract"]["sol_max_attempts"] == 16
        assert plan["maximum_planned_sol_calls"] == 8
        assert plan["maximum_sol_attempts"] == 16
        oversized = json.loads(json.dumps(state["manifest"]))
        oversized["sol_tasks"].append({"task_id": "sol.ninth"})
        with pytest.raises(workflow.CreditAnalysisError, match="Sol task slots"):
            workflow._validate_holistic_manifest(oversized, contract)
        assert runner.calls == []
        completed = workflow.command_execute_orchestration(
            state_path, runner=runner, available_models=runner.available_models
        )
        assert completed["complete"] is True
        assert len(runner.sol_attempts) == planned_calls
        assert sum(runner.sol_attempts.values()) == actual_calls
        assert runner.sol_attempts["sol.final"] == 2
        assert completed["actual_sol_calls"] == actual_calls
        assert completed["accepted_sol_calls"] == planned_calls
        assert completed["omissions"] == []
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["execution"]["sol.direct-evidence"]["status"] == "complete"
        assert sum(
            attempt["model_invoked"]
            for task in state["manifest"]["sol_tasks"]
            for attempt in state["execution"][task["task_id"]]["attempts"]
        ) == actual_calls
        count = len(runner.calls)
        assert workflow.command_execute_orchestration(
            state_path, runner=runner, available_models=runner.available_models
        )["complete"] is True
        assert len(runner.calls) == count

        if actual_calls == 16:
            # Simulate an interrupted state publication after the paid-for final
            # task result was retained. Recovery must work even at the hard cap.
            pathlib.Path(completed["final_result_path"]).unlink()
            pathlib.Path(completed["report_path"]).unlink()
            state["phase"] = "executing"
            state["final_result"] = None
            state["execution"]["sol.final"]["status"] = "pending"
            state["execution"]["sol.final"]["result"] = None
            state["model_calls"]["sol"] -= 1
            state_path.write_text(json.dumps(state), encoding="utf-8")
            recovered = workflow.command_execute_orchestration(
                state_path, runner=runner, available_models=runner.available_models
            )
            assert recovered["complete"] is True
            assert recovered["actual_sol_calls"] == 16
            assert recovered["accepted_sol_calls"] == 8
            assert len(runner.calls) == count

        # The new contract never silently expands a previously frozen contract.
        retained = state_path.read_text(encoding="utf-8")
        stale = json.loads(retained)
        stale["surface_contract_version"] = contract["surface_contract_version"] - 1
        state_path.write_text(json.dumps(stale), encoding="utf-8")
        with pytest.raises(workflow.CreditAnalysisError, match="contract version changed"):
            workflow.command_execute_orchestration(
                state_path, runner=runner, available_models=runner.available_models
            )
        state_path.write_text(retained, encoding="utf-8")
        assert len(runner.calls) == count
        stale = json.loads(retained)
        stale["immutable_artifacts"]["surface_contract"]["sha256"] = "0" * 64
        state_path.write_text(json.dumps(stale), encoding="utf-8")
        with pytest.raises(workflow.CreditAnalysisError, match="immutable artifact changed: surface_contract"):
            workflow.command_execute_orchestration(
                state_path, runner=runner, available_models=runner.available_models
            )
        state_path.write_text(retained, encoding="utf-8")
        assert len(runner.calls) == count

    exhausted_root = tmp_path / "no-seventeenth-invocation"
    exhausted_root.mkdir()
    request, _, _ = credit_analysis_request(
        exhausted_root, extra_completed_turns=3, extra_calls_per_turn=4
    )
    runner = BudgetRunner(all_tasks=True, final_failure=True)
    plan = workflow.command_plan_orchestration(
        request, available_models=runner.available_models
    )
    state_path = pathlib.Path(plan["state_path"])
    for expected_calls in (15, 16):
        with pytest.raises(workflow.CreditAnalysisError, match="synthetic invoked final failure"):
            workflow.command_execute_orchestration(
                state_path, runner=runner, available_models=runner.available_models
            )
        assert sum(runner.sol_attempts.values()) == expected_calls
        assert workflow.command_orchestration_status(state_path)["actual_sol_calls"] == expected_calls
    count = len(runner.calls)
    with pytest.raises(workflow.CreditAnalysisError, match="Sol attempt ceiling"):
        workflow.command_execute_orchestration(
            state_path, runner=runner, available_models=runner.available_models
        )
    assert len(runner.calls) == count
    assert sum(runner.sol_attempts.values()) == 16
    assert len(runner.sol_attempts) == 8
    retained = state_path.read_text(encoding="utf-8")
    for value, message in ((15, "disagrees with retained attempts"), (17, "attempt cap"), (True, "count is invalid")):
        state = json.loads(retained)
        state["model_attempts"]["sol"] = value
        state_path.write_text(json.dumps(state), encoding="utf-8")
        with pytest.raises(workflow.CreditAnalysisError, match=message):
            workflow.command_execute_orchestration(
                state_path, runner=runner, available_models=runner.available_models
            )
        assert len(runner.calls) == count
    state_path.write_text(retained, encoding="utf-8")
