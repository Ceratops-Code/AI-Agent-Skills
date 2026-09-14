from __future__ import annotations

import hashlib
import json
import pathlib
import runpy
import subprocess
import sys
from typing import Any
from unittest import mock

import pytest

from tests.governance_lifecycle.support import (
    ITERATION_CONTROLLER,
    PROPOSAL_WORKFLOW,
    target_repository_markdown_policy,
)
from tests.support.repositories import ROOT


@pytest.mark.parametrize("target_name", ["contract.md", "automation.toml"])
@pytest.mark.parametrize("prepare_mode", ["request", "construct"])
def test_proposal_workflow_validates_context_and_owns_iteration_transition(
    tmp_path: pathlib.Path,
    target_name: str,
    prepare_mode: str,
) -> None:
    constructing = prepare_mode == "construct"
    task_temp_root = tmp_path / "task-temp"
    task_temp_root.mkdir()
    original = task_temp_root / ("proposal-original.json" if constructing else "original.md")
    regressions = task_temp_root / ("proposal-regressions.md" if constructing else "regressions.md")
    target_dir = tmp_path / "governed"
    target_dir.mkdir()
    target = target_dir / target_name
    is_toml = target.suffix == ".toml"
    request_path = task_temp_root / "proposal-request.json"
    state = task_temp_root / "proposal-state.json"
    evidence = task_temp_root / "proposal-context.json"
    champion_output = task_temp_root / "validated-champion.json"
    iterations = task_temp_root / "iterations"
    undeclared_input = task_temp_root / "user-owned.md"
    if not constructing:
        original.write_text("Observed failure\n", encoding="utf-8", newline="\n")
        regressions.write_text("Preserve current scope\n", encoding="utf-8", newline="\n")
    undeclared_input.write_text("Preserve me\n", encoding="utf-8", newline="\n")
    target.write_text(
        'prompt = "Current exact target."\n' if is_toml else "# Contract\n\nCurrent exact target.\n",
        encoding="utf-8",
        newline="\n",
    )
    target_repository_markdown_policy(target_dir)
    current_text = (
        "- [SKILLS-GOV-01] Before proposing or editing a repository control surface,\n"
        "  including `AGENTS.md`, `automation.toml`, `SKILL.md`, skill manifests, shared\n"
        "  sections, or helper contracts, re-open the relevant files from disk and use\n"
        "  the current contents as the source of truth.\n"
        "  - self: list-heavy"
    )
    assert current_text in (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    history_source: dict[str, object] = {
        "rules": str(ROOT / "AGENTS.md"),
        "history": str(ROOT / "AGENTS.history.json"),
        "rule_ids": ["SKILLS-GOV-01"],
        "expected_text": [current_text],
        "candidate_target": False,
        "markdown_policy": None,
    }
    target_source: dict[str, Any] = {
        "rules": str(target),
        "history": None,
        "rule_ids": [],
        "expected_text": ["Current exact target."],
        "candidate_target": True,
        "markdown_policy": None,
    }
    request: dict[str, object] = {
        "schema": "ceratops-governance-proposal-request.v3",
        "task_temp_root": str(task_temp_root),
        "iteration_artifacts": str(iterations),
        "disposable_artifacts": [
            "request",
            "original",
            "regressions",
            "evidence",
            "state",
            "iterations",
        ],
        "state": str(state),
        "original": str(original),
        "regressions": str(regressions),
        "evidence_output": str(evidence),
        "champion_output": str(champion_output),
        "max_iterations": 1,
        "mutation_authorized": False,
        "expected_side_effects": [
            "write context evidence",
            "write controller artifacts",
        ],
        "sources": [history_source, target_source],
    }
    spec_path = tmp_path / "caller-spec.json"
    spec: dict[str, Any] = {
        "schema": "ceratops-governance-proposal-spec.v1",
        "task_temp_root": str(task_temp_root),
        "failure": "Observed failure",
        "regressions": "Preserve current scope",
        "max_iterations": 1,
        "mutation_authorized": False,
        "expected_side_effects": request["expected_side_effects"],
        "sources": [
            {"rules": history_source["rules"], "history": history_source["history"],
             "rule_ids": history_source["rule_ids"], "replacements": []},
            {"rules": str(target), "history": None, "rule_ids": [], "replacements": []},
        ],
    }

    def prepare_proposal():
        """Exercise both public entry points against the same workflow contract."""
        if constructing:
            spec["sources"][1]["replacements"] = [
                {"expected_old": target_source["expected_text"][0],
                 "replacement": "Seeded exact replacement."},
            ]
            spec_path.write_text(json.dumps(spec) + "\n", encoding="utf-8")
            arguments = ["construct", "--spec", str(spec_path)]
        else:
            request_path.write_text(json.dumps(request) + "\n", encoding="utf-8")
            arguments = ["prepare", "--request", str(request_path)]
        return subprocess.run([sys.executable, str(PROPOSAL_WORKFLOW), *arguments],
                              capture_output=True, text=True, check=False)

    if constructing:
        # A bad exact source must leave no generated inputs. An unrelated file
        # and the caller's spec remain available for correction.
        target_source["expected_text"] = ["Missing current target."]
        rejected = prepare_proposal()
        assert rejected.returncode == 2 and "found 0" in rejected.stderr
        assert set(task_temp_root.iterdir()) == {undeclared_input}
        assert spec_path.is_file()
        target_source["expected_text"] = ["Current exact target."]
        spec["sources"][0]["rule_ids"] = ["MISSING-01"]
        rejected = prepare_proposal()
        assert rejected.returncode == 2 and "unknown context rule ID" in rejected.stderr
        assert set(task_temp_root.iterdir()) == {undeclared_input}
        spec["sources"][0]["rule_ids"] = history_source["rule_ids"]
        request_path.write_text("Caller-owned output\n", encoding="utf-8")
        rejected = prepare_proposal()
        assert rejected.returncode == 2 and "refusing to overwrite" in rejected.stderr
        assert request_path.read_text(encoding="utf-8") == "Caller-owned output\n"
        request_path.unlink()
    if not is_toml:
        valid_text = target.read_text(encoding="utf-8")
        # The first error is inside the planned edit. It must not hide a later
        # unchanged error, and rejection must precede controller artifacts.
        broken = "Current exact target. " + ("long word " * 18).rstrip()
        target_source["expected_text"] = [broken]
        target.write_text(valid_text.replace("Current exact target.", broken)
                          + "\nUntouched " + ("word " * 25).rstrip() + "\n", encoding="utf-8")
        rejected = prepare_proposal()
        assert rejected.returncode != 0
        assert "line=5" in rejected.stderr and "MD013" in rejected.stderr
        assert not state.exists() and not evidence.exists() and not iterations.exists()
        assert not list(task_temp_root.glob(".rule-candidate-*"))
        # Keeping only the in-range error is permitted; advance repairs it.
        target.write_text(valid_text.replace("Current exact target.", broken), encoding="utf-8")
    target_before_prepare = target.read_bytes()
    prepared = prepare_proposal()
    assert prepared.returncode == 0, prepared.stderr
    assert target.read_bytes() == target_before_prepare
    pending = json.loads(prepared.stdout)
    assert pending["iteration"] == 1
    if constructing:
        assert pathlib.Path(pending["state"]) == state
        assert pathlib.Path(pending["champion_output"]) == champion_output
        original_spec = json.loads(original.read_text(encoding="utf-8"))
        assert original_spec == json.loads(spec_path.read_text(encoding="utf-8"))
        generated_request = json.loads(request_path.read_text(encoding="utf-8"))
        assert generated_request["mutation_authorized"] is False
        assert "Before proposing or editing" in generated_request["sources"][0]["expected_text"][0]
    context = json.loads(evidence.read_text(encoding="utf-8"))
    assert context["schema"] == "ceratops-governance-proposal-context.v3"
    assert context["history_lookup"]["unknown"] == []
    assert context["sources"][1]["history"] is None
    assert context["candidate_validation"]["targets"][0]["rules"] == str(
        target.resolve()
    )
    policy = context["candidate_validation"]["targets"][0]["markdown_policy"]
    if is_toml:
        assert policy is None
    else:
        assert pathlib.Path(policy["configuration"]) == (
            ROOT / "skills" / "ceratops-governance-lifecycle"
            / "references" / ".markdownlint.json"
        )
    incomplete = subprocess.run(
        [
            sys.executable,
            str(PROPOSAL_WORKFLOW),
            "finalize",
            "--state",
            str(state),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert incomplete.returncode == 2
    assert "incomplete proposal" in incomplete.stderr
    assert all(
        path.is_file()
        for path in (request_path, original, regressions, evidence, state)
    )
    assert iterations.is_dir() and undeclared_input.is_file()
    candidate_path = pathlib.Path(pending["candidate"])
    candidate_value = json.loads(candidate_path.read_text(encoding="utf-8"))
    if constructing:
        assert candidate_value["targets"][0]["replacements"][0]["replacement"] == "Seeded exact replacement."
    candidate_value["targets"][0]["replacements"][0]["replacement"] = (
        'Broken"quote' if is_toml else "https://example.test/" + "x" * 80
    )
    candidate_path.write_text(
        json.dumps(candidate_value, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    pathlib.Path(pending["assessment"]).write_text(
        "Regression assessment\n",
        encoding="utf-8",
        newline="\n",
    )
    candidate_before_failure = candidate_path.read_bytes()
    mechanical_failure = subprocess.run(
        [
            sys.executable,
            str(PROPOSAL_WORKFLOW),
            "advance",
            "--state",
            str(state),
            "--outcome",
            "improved",
            "--regressions",
            "passed",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert mechanical_failure.returncode == 2
    assert ("invalid TOML" if is_toml else "indivisible token") in mechanical_failure.stderr
    failed_state = json.loads(state.read_text(encoding="utf-8"))
    assert failed_state["records"] == []
    assert failed_state["pending"]["iteration"] == 1
    assert candidate_path.read_bytes() == candidate_before_failure
    candidate_value["targets"][0]["replacements"][0]["replacement"] = (
        "Validated candidate prose is safely wrapped before the controller "
        "records its exact post-validation hash."
    )
    candidate_path.write_text(
        json.dumps(candidate_value, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    advanced = subprocess.run(
        [
            sys.executable,
            str(PROPOSAL_WORKFLOW),
            "advance",
            "--state",
            str(state),
            "--outcome",
            "improved",
            "--regressions",
            "passed",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert advanced.returncode == 0, advanced.stderr
    status = json.loads(advanced.stdout)
    assert status["complete"] is True
    assert status["pending"] is None
    completed_state = json.loads(state.read_text(encoding="utf-8"))
    record = completed_state["records"][0]
    assert record["candidate_sha256"] == hashlib.sha256(
        candidate_path.read_bytes()
    ).hexdigest()
    fixed_candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    replacement = fixed_candidate["targets"][0]["replacements"][0]["replacement"]
    assert ("\n" in replacement) is not is_toml
    assert pathlib.Path(record["validation_evidence"]).is_file()
    champion_bytes = candidate_path.read_bytes()
    completed_state_text = state.read_text(encoding="utf-8")
    escaped_state = json.loads(completed_state_text)
    outside_evidence = tmp_path / "outside-evidence.json"
    outside_evidence.write_text("Preserve\n", encoding="utf-8", newline="\n")
    next(
        artifact
        for artifact in escaped_state["proposal_cleanup"]["owned_artifacts"]
        if artifact["role"] == "evidence"
    )["path"] = str(outside_evidence)
    state.write_text(
        json.dumps(escaped_state) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    escaped = subprocess.run(
        [
            sys.executable,
            str(PROPOSAL_WORKFLOW),
            "finalize",
            "--state",
            str(state),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert escaped.returncode == 2
    assert "escapes task_temp_root" in escaped.stderr
    assert all(
        path.is_file()
        for path in (request_path, original, regressions, evidence, state)
    )
    assert iterations.is_dir() and undeclared_input.is_file()
    assert outside_evidence.is_file()
    state.write_text(completed_state_text, encoding="utf-8", newline="\n")
    finalized = subprocess.run(
        [
            sys.executable,
            str(PROPOSAL_WORKFLOW),
            "finalize",
            "--state",
            str(state),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert finalized.returncode == 0, finalized.stderr
    assert finalized.stdout.strip() == "OK"
    assert champion_output.is_file()
    assert champion_output.read_bytes() == champion_bytes
    assert hashlib.sha256(champion_output.read_bytes()).hexdigest() == record[
        "candidate_sha256"
    ]
    assert not state.exists()
    assert not iterations.exists()
    assert not request_path.exists()
    assert not original.exists() and not regressions.exists() and not evidence.exists()
    assert undeclared_input.is_file() and outside_evidence.is_file()
    if constructing:
        assert spec_path.is_file()

    invalid_request = dict(request)
    invalid_run = task_temp_root / "invalid-run"
    invalid_run.mkdir()
    invalid_original = invalid_run / "original.md"
    invalid_regressions = invalid_run / "regressions.md"
    invalid_original.write_text("Failure\n", encoding="utf-8", newline="\n")
    invalid_regressions.write_text("Boundary\n", encoding="utf-8", newline="\n")
    invalid_state = invalid_run / "state.json"
    invalid_evidence = invalid_run / "context.json"
    invalid_champion = invalid_run / "champion.json"
    invalid_iterations = invalid_run / "iterations"
    invalid_request["state"] = str(invalid_state)
    invalid_request["original"] = str(invalid_original)
    invalid_request["regressions"] = str(invalid_regressions)
    invalid_request["evidence_output"] = str(invalid_evidence)
    invalid_request["champion_output"] = str(invalid_champion)
    invalid_request["iteration_artifacts"] = str(invalid_iterations)
    invalid_request["sources"] = [
        {
            **history_source,
            "expected_text": [current_text, "missing exact current text"],
        }
    ]
    invalid_path = invalid_run / "request.json"
    invalid_path.write_text(
        json.dumps(invalid_request) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    rejected = subprocess.run(
        [
            sys.executable,
            str(PROPOSAL_WORKFLOW),
            "prepare",
            "--request",
            str(invalid_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode == 2
    assert "source 1 expected_text[1] must occur exactly once; found 0" in rejected.stderr
    assert not invalid_state.exists()
    assert not invalid_evidence.exists()
    assert not invalid_iterations.exists()
    assert invalid_path.is_file()
    assert invalid_original.is_file() and invalid_regressions.is_file()

    if constructing:
        # A failed candidate write occurs after controller state exists. Keep
        # that state and its inputs recoverable through advance/finalize.
        recovery_root = task_temp_root / "recovery"
        recovery_root.mkdir()
        recovery_spec = {**spec, "task_temp_root": str(recovery_root)}
        spec_path.write_text(json.dumps(recovery_spec) + "\n", encoding="utf-8")
        with mock.patch.object(sys, "path", [str(PROPOSAL_WORKFLOW.parent), *sys.path]):
            workflow = runpy.run_path(str(PROPOSAL_WORKFLOW))
        construct = workflow["command_construct"]
        write_atomic = construct.__globals__["_write_json_atomic"]

        def failed_candidate_write(path, value):
            if path.parent.name == "iterations":
                raise OSError("simulated candidate write failure")
            return write_atomic(path, value)

        with mock.patch.dict(construct.__globals__, {"_write_json_atomic": failed_candidate_write}):
            with pytest.raises(workflow["ProposalWorkflowError"], match="recover pending state") as failure:
                construct(spec_path)
        recovery_state = recovery_root / "proposal-state.json"
        assert str(recovery_state) in str(failure.value)
        assert (recovery_root / "proposal-request.json").is_file()
        assert (recovery_root / "proposal-original.json").is_file()
        assert target.read_bytes() == target_before_prepare
        recovery_pending = json.loads(recovery_state.read_text(encoding="utf-8"))["pending"]
        recovery_candidate = pathlib.Path(recovery_pending["candidate"])
        value = json.loads(recovery_candidate.read_text(encoding="utf-8"))
        value["targets"][0]["replacements"][0]["replacement"] = "Recovered replacement."
        recovery_candidate.write_text(json.dumps(value) + "\n", encoding="utf-8")
        pathlib.Path(recovery_pending["assessment"]).write_text("Preserved scope\n", encoding="utf-8")
        result = json.loads(workflow["command_advance"](recovery_state, "improved", "passed"))
        assert result["complete"] is True
        assert workflow["command_finalize"](recovery_state) == "OK"
        assert set(recovery_root.iterdir()) == {recovery_root / "validated-champion.json"}
        assert spec_path.is_file() and target.read_bytes() == target_before_prepare


def test_iteration_controller_direct_commands_record_validated_candidate(
    tmp_path: pathlib.Path,
) -> None:
    original = tmp_path / "original.md"
    state = tmp_path / "state.json"
    repository = tmp_path / "repository"
    repository.mkdir()
    target = repository / "AGENTS.md"
    target.write_text("Old target.\n", encoding="utf-8", newline="\n")
    validation_context = tmp_path / "validation-context.json"
    validation_context.write_text(
        json.dumps(
            {
                "schema": "ceratops-rule-candidate-context.v1",
                "rule_stack": [str(target.resolve())],
                "targets": [
                    {
                        "rules": str(target.resolve()),
                        "history": None,
                        "source_sha256": hashlib.sha256(
                            target.read_bytes()
                        ).hexdigest(),
                        "markdown_policy": None,
                        "expected_old": ["Old target."],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    original.write_text("Original\n", encoding="utf-8", newline="\n")
    initialized = subprocess.run(
        [
            sys.executable,
            str(ITERATION_CONTROLLER),
            "init",
            "--state",
            str(state),
            "--original",
            str(original),
            "--validation-context",
            str(validation_context),
            "--max-iterations",
            "1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert initialized.returncode == 0, initialized.stderr
    assert initialized.stdout.strip() == "OK"
    opened = subprocess.run(
        [sys.executable, str(ITERATION_CONTROLLER), "next", "--state", str(state)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert opened.returncode == 0, opened.stderr
    pending = json.loads(opened.stdout)
    candidate_path = pathlib.Path(pending["candidate"])
    candidate_value = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate_value["targets"][0]["replacements"][0]["replacement"] = (
        "Controller submit automatically wraps and validates this candidate "
        "before hashing it."
    )
    candidate_path.write_text(
        json.dumps(candidate_value, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    pathlib.Path(pending["assessment"]).write_text(
        "Assessment\n", encoding="utf-8", newline="\n"
    )
    submitted = subprocess.run(
        [
            sys.executable,
            str(ITERATION_CONTROLLER),
            "submit",
            "--state",
            str(state),
            "--iteration",
            str(pending["iteration"]),
            "--token",
            pending["token"],
            "--outcome",
            "improved",
            "--regressions",
            "passed",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert submitted.returncode == 0, submitted.stderr
    assert json.loads(submitted.stdout)["complete"] is True
    recorded_state = json.loads(state.read_text(encoding="utf-8"))
    assert recorded_state["records"][0]["candidate_sha256"] == hashlib.sha256(
        candidate_path.read_bytes()
    ).hexdigest()
    assert pathlib.Path(
        recorded_state["records"][0]["validation_evidence"]
    ).is_file()
    status = subprocess.run(
        [sys.executable, str(ITERATION_CONTROLLER), "status", "--state", str(state)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["champion_iteration"] == 1
    finalized = subprocess.run(
        [
            sys.executable,
            str(ITERATION_CONTROLLER),
            "finalize",
            "--state",
            str(state),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert finalized.returncode == 0, finalized.stderr
    assert finalized.stdout.strip() == "OK"
    assert original.is_file() and validation_context.is_file() and not state.exists()
