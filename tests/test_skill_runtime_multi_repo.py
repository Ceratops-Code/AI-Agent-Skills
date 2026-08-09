from __future__ import annotations

import argparse
import errno
import hashlib
import importlib
import json
import os
import pathlib
import runpy
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Mapping

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
LIFECYCLE_SOURCE = ROOT / "skills" / "ceratops-skill-lifecycle"
REPOSITORY_LIFECYCLE_SOURCE = ROOT / "skills" / "ceratops-repo-lifecycle"
REPOSITORY_LIFECYCLE_SCRIPTS = REPOSITORY_LIFECYCLE_SOURCE / "scripts"
sys.path.insert(0, str(REPOSITORY_LIFECYCLE_SCRIPTS))
VALIDATOR = LIFECYCLE_SOURCE / "scripts" / "skills-consistency-source-validator.py"
BUILDER = LIFECYCLE_SOURCE / "scripts" / "runtime" / "managed_runtime_builder.py"
BOOTSTRAP = ROOT / "scripts" / "install-skills-bootstrap.py"
LIVE_SECTION_MANIFEST = ROOT / "skills" / "skill-sections.json"
SECTION_MANIFEST_TEMPLATE = (
    REPOSITORY_LIFECYCLE_SOURCE
    / "references"
    / "templates"
    / "skill-sections-template.json"
)
DEPLOY_CONTRACT_TEMPLATE = (
    REPOSITORY_LIFECYCLE_SOURCE
    / "references"
    / "templates"
    / "deploy-template.yml"
)
INSTALLER_TEMPLATE = (
    REPOSITORY_LIFECYCLE_SOURCE
    / "references"
    / "templates"
    / "install-skills-bootstrap-template.py"
)
COMPATIBILITY_ENGINE = "ceratops_repo_compatibility_engine"
RUNTIME_INSTALLER = LIFECYCLE_SOURCE / "scripts" / "runtime" / "install-managed-skills.py"
FAST_CHANGE = LIFECYCLE_SOURCE / "scripts" / "fast-change.py"
SKILL_UPDATE_WORKFLOW = LIFECYCLE_SOURCE / "scripts" / "skill-update-workflow.py"
GOVERNANCE_SOURCE = ROOT / "skills" / "ceratops-governance-lifecycle"
PROPOSAL_WORKFLOW = GOVERNANCE_SOURCE / "scripts" / "proposal-workflow.py"
ITERATION_CONTROLLER = GOVERNANCE_SOURCE / "scripts" / "iteration_controller.py"
DEPLOY_OPERATION = REPOSITORY_LIFECYCLE_SOURCE / "scripts" / "run-deploy-operation.py"
PROMOTE_REPOSITORY = REPOSITORY_LIFECYCLE_SOURCE / "scripts" / "promote-repository.py"
MANAGE_PENDING_WORK = REPOSITORY_LIFECYCLE_SOURCE / "scripts" / "manage-pending-work.py"
SHIP_REPOSITORY = REPOSITORY_LIFECYCLE_SOURCE / "scripts" / "ship-repository.py"
PR_WORKFLOW_SCRIPTS = REPOSITORY_LIFECYCLE_SOURCE / "scripts"
PR_WORKFLOW_ENTRYPOINT = PR_WORKFLOW_SCRIPTS / "github_pr_workflow" / "__main__.py"
MODEL_CALL_LEDGER = ROOT / "skills" / "ceratops-credit-savings-analysis" / "scripts" / "model-call-ledger.py"
CREDIT_ANALYSIS_WORKFLOW = (
    ROOT
    / "skills"
    / "ceratops-credit-savings-analysis"
    / "scripts"
    / "credit-analysis-workflow.py"
)
CREDIT_ANALYSIS_CONTRACT = (
    ROOT
    / "skills"
    / "ceratops-credit-savings-analysis"
    / "scripts"
    / "credit-analysis-contract.json"
)
CLOSURE_SNAPSHOT = ROOT / "skills" / "ceratops-task-lifecycle" / "scripts" / "closure_snapshot.py"
RUNTIME_MANIFEST = ".runtime-manifest.json"
RUNTIME_MANIFEST_SCHEMA = "ceratops-runtime-skill.v3"
INSTALLER_VERSION = 10


def run_credit_analysis_workflow(
    command: str,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    """Run the credit-analysis controller through its public CLI."""

    return subprocess.run(
        [sys.executable, str(CREDIT_ANALYSIS_WORKFLOW), command, *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def write_json_file(path: pathlib.Path, value: Any) -> None:
    """Write one deterministic JSON test artifact."""

    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def credit_analysis_session(
    path: pathlib.Path,
    *,
    thread_id: str | None = None,
    cwd: pathlib.Path | None = None,
    repository_url: str | None = None,
    extra_completed_turns: int = 0,
    extra_calls_per_turn: int = 1,
) -> None:
    """Create completed synthetic runs and one active tail."""

    rows: list[dict[str, Any]] = [
        {
            "timestamp": "2026-08-01T00:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": thread_id or "synthetic-credit-analysis-thread",
                "cwd": str(cwd or path.parent),
                "git": (
                    {"repository_url": repository_url}
                    if repository_url is not None
                    else None
                ),
                "base_instructions": "BASE_CONTROL_SENTINEL analyze exact evidence",
                "dynamic_tools": [
                    {
                        "name": "read_file",
                        "description": "Read one exact file",
                        "input_schema": {"path": "string"},
                    }
                ],
                "model_provider": "synthetic",
                "context_window": 100000,
            },
        },
        {
            "timestamp": "2026-08-01T00:00:00.100Z",
            "type": "world_state",
            "payload": {
                "full": True,
                "state": {
                    "agents_md": "WORLD_STATE_CONTROL_SENTINEL",
                    "permissions": {"mode": "synthetic"},
                },
            },
        },
        {
            "timestamp": "2026-08-01T00:00:00.200Z",
            "type": "compacted",
            "payload": {
                "first_window_id": "window-1",
                "previous_window_id": "window-0",
                "window_id": "window-2",
                "window_number": 2,
                "message": "COMPACTION_CONTEXT_SENTINEL",
                "replacement_history": ["inactive history must not be copied"],
            },
        },
        {
            "timestamp": "2026-08-01T00:00:00.300Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "developer",
                "content": [
                    {
                        "type": "input_text",
                        "text": "DEVELOPER_CONTROL_SENTINEL preserve causality",
                    }
                ],
            },
        },
    ]

    def add_call(
        timestamp: str,
        turn_id: str,
        *,
        name: str | None = None,
        call_id: str | None = None,
        arguments: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        final: bool = False,
    ) -> None:
        if name is not None:
            rows.append(
                {
                    "timestamp": timestamp,
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": name,
                        "call_id": call_id,
                        "arguments": json.dumps(arguments or {}),
                    },
                }
            )
            if output is not None:
                rows.append(
                    {
                        "timestamp": timestamp + ".100",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": json.dumps(output),
                        },
                    }
                )
        if final:
            rows.append(
                {
                    "timestamp": timestamp,
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "phase": "final_answer",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    f"done {turn_id} ASSISTANT_ANSWER_SENTINEL "
                                    + ("answer detail " * 220)
                                ),
                            }
                        ],
                    },
                }
            )
        rows.append(
            {
                "timestamp": timestamp + ".900",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "last_token_usage": {
                            "input_tokens": 10,
                            "cached_input_tokens": 2,
                            "output_tokens": 2,
                            "reasoning_output_tokens": 1,
                            "total_tokens": 12,
                        }
                    },
                },
            }
        )

    def add_user_message(timestamp: str, text: str) -> None:
        rows.append(
            {
                "timestamp": timestamp,
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            }
        )

    rows.append(
        {
            "timestamp": "2026-08-01T00:00:00Z",
            "type": "turn_context",
            "payload": {
                "turn_id": "turn-1",
                "cwd": str(cwd or path.parent),
                "model": "synthetic-model",
                "effort": "high",
                "approval_policy": "never",
                "workspace_roots": [str(cwd or path.parent)],
            },
        }
    )
    rows.append(
        {
            "timestamp": "2026-08-01T00:00:00.600Z",
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "turn_id": "turn-1",
                "started_at": "2026-08-01T00:00:00.600Z",
                "model_context_window": 100000,
            },
        }
    )
    rows.append(
        {
            "timestamp": "2026-08-01T00:00:00.700Z",
            "type": "response_item",
            "payload": {
                "type": "reasoning",
                "summary": ["PRIVATE_REASONING_SENTINEL"],
                "encrypted_content": "PRIVATE_REASONING_SENTINEL",
            },
        }
    )
    add_user_message(
        "2026-08-01T00:00:00.500Z",
        (
            "Fix the failed read, correct the earlier plan, apply my approval, "
            "and use token=synthetic-user-secret. Explain the cause at "
            f"{path.parent / 'private' / 'input.txt'}"
        ),
    )
    add_call(
        "2026-08-01T00:00:01Z",
        "turn-1",
        name="read_file",
        call_id="read-1",
        arguments={"path": str(path.parent / "private" / "input.txt")},
        output={
            "success": False,
            "error": "synthetic failure",
            "stdout": ("tool result detail " * 700) + "TOOL_RESULT_TAIL_SENTINEL",
        },
    )
    add_call(
        "2026-08-01T00:00:02Z",
        "turn-1",
        name="read_file",
        call_id="read-2",
        arguments={"path": str(path.parent / "private" / "input.txt")},
        output={"success": True},
    )
    add_call("2026-08-01T00:00:03Z", "turn-1", final=True)

    rows.append(
        {
            "timestamp": "2026-08-01T00:01:00Z",
            "type": "turn_context",
            "payload": {"turn_id": "turn-2"},
        }
    )
    add_user_message(
        "2026-08-01T00:01:00.500Z",
        "Wait for the agent and clarify whether the result needs another check.",
    )
    add_call(
        "2026-08-01T00:01:01Z",
        "turn-2",
        name="wait_agent",
        call_id="wait-1",
        output={"timed_out": False},
    )
    add_call("2026-08-01T00:01:02Z", "turn-2", final=True)

    rows.append(
        {
            "timestamp": "2026-08-01T00:02:00Z",
            "type": "turn_context",
            "payload": {"turn_id": "turn-3"},
        }
    )
    add_user_message(
        "2026-08-01T00:02:00.500Z",
        "Give the final result for this completed run.",
    )
    add_call("2026-08-01T00:02:01Z", "turn-3", final=True)
    for index in range(extra_completed_turns):
        minute = 3 + index
        turn_id = f"turn-extra-{index + 1}"
        prefix = f"2026-08-01T00:{minute:02d}"
        rows.append(
            {
                "timestamp": f"{prefix}:00Z",
                "type": "turn_context",
                "payload": {"turn_id": turn_id},
            }
        )
        add_user_message(
            f"{prefix}:00.500Z",
            f"Review synthetic overflow candidate {index + 1}.",
        )
        for call_index in range(extra_calls_per_turn):
            candidate = index * extra_calls_per_turn + call_index + 1
            add_call(
                f"{prefix}:01Z",
                turn_id,
                name="inspect_candidate",
                call_id=f"overflow-{index + 1}-{call_index + 1}",
                arguments={"candidate": candidate},
                output={"reviewed": True, "candidate": candidate},
            )
        add_call(f"{prefix}:02Z", turn_id, final=True)
    active_minute = 3 + extra_completed_turns
    active_prefix = f"2026-08-01T00:{active_minute:02d}"
    rows.append(
        {
            "timestamp": f"{active_prefix}:00Z",
            "type": "turn_context",
            "payload": {"turn_id": "turn-3"},
        }
    )
    add_user_message(
        f"{active_prefix}:00.500Z",
        "ACTIVE_TAIL_MUST_NOT_BE_COLLECTED",
    )
    add_call(
        f"{active_prefix}:01Z",
        "turn-3",
        name="active_tail_tool",
        call_id="active-tail-1",
        output={"status": "still-running"},
    )
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def credit_analysis_request(
    tmp_path: pathlib.Path,
    *,
    action: str = "full-analysis",
    extra_completed_turns: int = 0,
    extra_calls_per_turn: int = 1,
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """Create one request with caller-selected controller and evidence paths."""

    session = tmp_path / "session.jsonl"
    credit_analysis_session(
        session,
        extra_completed_turns=extra_completed_turns,
        extra_calls_per_turn=extra_calls_per_turn,
    )
    task_root = tmp_path / f"analysis-{action}"
    task_root.mkdir()
    evidence = tmp_path / f"evidence-{action}.json"
    request = tmp_path / f"request-{action}.json"
    write_json_file(
        request,
        {
            "schema": "ceratops-credit-analysis-request.v1",
            "action": action,
            "mode": "full-analysis" if action == "full-analysis" else "standalone",
            "source": {"thread_id": None, "session": str(session)},
            "window": {"mode": "full_thread", "last_runs": None, "turn_ids": []},
            "task_temp_root": str(task_root),
            "evidence_output": str(evidence),
            "pricing_profile": None,
            "expected_surface_contract_version": 1,
            "mutation_authority": False,
        },
    )
    return request, session, task_root


def indexed_credit_analysis_session(
    codex_home: pathlib.Path,
    *,
    thread_id: str,
    thread_name: str,
    updated_at: str,
    project_name: str,
    repository_owner: str = "example",
) -> pathlib.Path:
    """Create one indexed Codex session with deterministic project metadata."""

    session_root = codex_home / "sessions" / "2026" / "08" / "01"
    session_root.mkdir(parents=True, exist_ok=True)
    session = session_root / f"rollout-2026-08-01T00-00-00-{thread_id}.jsonl"
    project = codex_home / "projects" / project_name
    credit_analysis_session(
        session,
        thread_id=thread_id,
        cwd=project,
        repository_url=f"https://example.test/{repository_owner}/{project_name}.git",
    )
    index = codex_home / "session_index.jsonl"
    with index.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                {
                    "id": thread_id,
                    "thread_name": thread_name,
                    "updated_at": updated_at,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
    return session


def credit_analysis_batch_request(
    tmp_path: pathlib.Path,
    *,
    selector: dict[str, Any],
    name: str,
    as_of: str = "2026-08-07T18:00:00Z",
) -> pathlib.Path:
    """Create one caller-bounded per-thread batch request."""

    task_root = tmp_path / f"batch-{name}"
    task_root.mkdir()
    request = tmp_path / f"batch-request-{name}.json"
    write_json_file(
        request,
        {
            "schema": "ceratops-credit-analysis-batch-request.v1",
            "action": "full-analysis",
            "mode": "per-thread-batch",
            "selector": selector,
            "as_of": as_of,
            "task_temp_root": str(task_root),
            "manifest_output": str(tmp_path / f"batch-manifest-{name}.json"),
            "pricing_profile": None,
            "expected_surface_contract_version": 1,
            "expected_source_selection_contract_version": 1,
            "mutation_authority": False,
        },
    )
    return request


def finding_record(
    finding_id: str,
    calls: list[str],
    *,
    producer_type: str,
    owner: str,
    status: str = "unimplemented",
    waste_kind: str = "model-calls",
    complexity: str = "Low",
    helper_categories: list[str] | None = None,
) -> dict[str, Any]:
    """Build one valid surface finding with deterministic ROI arithmetic."""

    return {
        "id": finding_id,
        "title": finding_id.replace("-", " "),
        "problem_summary": (
            f"Synthetic episode for {finding_id} caused avoidable work at {owner}."
        ),
        "waste_kind": waste_kind,
        "affected_call_ids": calls,
        "evidence_refs": [f"evidence://calls/{call_id}" for call_id in calls],
        "evidence_narrative": (
            f"The synthetic episode for {finding_id} repeated work already visible "
            "in the retained evidence."
        ),
        "producer_type": producer_type,
        "producer_owner": owner,
        "proposed_durable_control": f"Prevent {finding_id} at {owner}",
        "implementation_status": status,
        "targeted_verification": [f"verify-{finding_id}"],
        "observed_avoidable_call_count": (
            0 if waste_kind == "context-volume" else len(calls)
        ),
        "recurrence": {
            "calls_saved_per_affected_run": (
                0.0 if waste_kind == "context-volume" else float(len(calls))
            ),
            "additional_recurring_calls_per_affected_run": 0.0,
            "affected_similar_run_frequency": 0.5,
            "affected_similar_run_frequency_range": [0.25, 0.75],
            "estimated_calls_saved_per_similar_run": (
                0.0 if waste_kind == "context-volume" else float(len(calls)) * 0.5
            ),
            "assumptions": ["synthetic recurrence"],
        },
        "confidence": 0.8,
        "complexity": complexity,
        "one_time_implementation_cost": {
            "estimated_model_calls": 1.0,
            "description": "one focused implementation pass",
        },
        "helper_categories": helper_categories or [],
    }


def surface_result_record(
    status: Mapping[str, Any],
    context: Mapping[str, Any],
    evidence_fingerprint: str,
    *,
    findings: list[dict[str, Any]] | None = None,
    risks: list[dict[str, Any]] | None = None,
    exclusions: list[dict[str, Any]] | None = None,
    helper_reviews: list[dict[str, Any]] | None = None,
    remediation_groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a fully covered surface result for the pending controller pass."""

    findings = findings or []
    risks = risks or []
    exclusions = exclusions or []
    candidates = list(context["candidate_call_ids"])
    covered = {
        call_id
        for finding in findings
        for call_id in finding["affected_call_ids"]
    }
    covered.update(
        call_id for risk in risks for call_id in risk["affected_call_ids"]
    )
    covered.update(item["call_id"] for item in exclusions)
    dismissals = [
        {"call_id": call_id, "reason": "candidate did not support a finding"}
        for call_id in candidates
        if call_id not in covered
    ]
    referenced_calls = list(
        dict.fromkeys(
            [*candidates]
            + [
                call_id
                for item in [*findings, *risks]
                for call_id in item["affected_call_ids"]
            ]
        )
    )
    return {
        "schema": "ceratops-credit-analysis-surface-result.v1",
        "analysis_id": status["analysis_id"],
        "pass_id": status["pass_id"],
        "surface_id": status["pending_surface"],
        "evidence_fingerprint": evidence_fingerprint,
        "artifact_paths": {
            "state": status["state_path"],
            "evidence": status["evidence_path"],
            "context": status["context_path"],
            "result": status["required_result_path"],
        },
        "reviewed_candidate_call_ids": candidates,
        "confirmed_findings": findings,
        "plausible_risks": risks,
        "dismissed_candidates": dismissals,
        "necessary_call_exclusions": exclusions,
        "evidence_references": [
            f"evidence://calls/{call_id}" for call_id in referenced_calls
        ],
        "helper_category_reviews": helper_reviews or [],
        "remediation_groups": remediation_groups or [],
    }


def surface_decision_record(
    packet: Mapping[str, Any],
    *,
    finding_id: str | None = None,
    implementation_status: str = "unimplemented",
    waste_kind: str = "model-calls",
    risks: list[dict[str, Any]] | None = None,
    exclusions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one compact model judgment for the end-to-end controller."""

    findings: list[dict[str, Any]] = []
    if finding_id is not None:
        selected_cluster = packet["evidence"]["candidate_clusters"][0]
        cluster_selectors = [
            {
                "cluster_ids": [
                    selected_cluster["cluster_id"]
                ]
            }
        ]
        helper_categories = (
            ["noisy-or-incomplete-result-contract"]
            if packet["surface_id"] == "helper-contracts"
            else []
        )
        findings.append(
            {
                "id": finding_id,
                "title": finding_id.replace("-", " "),
                "problem_summary": (
                    f"The synthetic {packet['surface_id']} episode used an avoidable "
                    "model call because its producer lacked a complete control."
                ),
                "waste_kind": waste_kind,
                "affected_selectors": cluster_selectors,
                "additional_evidence_selectors": [],
                "evidence_narrative": (
                        (
                            "Aggregate evidence records "
                            f"{selected_cluster.get('input_tokens', 0)} input, "
                            f"{selected_cluster.get('cached_input_tokens', 0)} "
                            "cached-input, "
                            f"{selected_cluster.get('output_tokens', 0)} output "
                            "tokens, "
                            f"{selected_cluster.get('tool_argument_chars', 0)} "
                            "tool-argument "
                            "characters, and "
                            f"{selected_cluster.get('tool_result_chars', 0)} tool-result "
                            "characters beyond the bounded decision payload."
                    )
                    if waste_kind == "context-volume"
                    else (
                        f"The {packet['surface_id']} evidence shows a repeated semantic "
                        "decision after the producer had enough deterministic state "
                        "to finish."
                    )
                ),
                "producer_type": "script",
                "producer_owner": f"scripts/{packet['surface_id']}.py",
                "proposed_durable_control": (
                    f"Complete {packet['surface_id']} deterministically in its producer."
                ),
                "implementation_status": implementation_status,
                "targeted_verification": [
                    f"verify {packet['surface_id']} completes without the call"
                ],
                "recurrence": {
                    "additional_recurring_calls_per_affected_run": 0.0,
                    "affected_similar_run_frequency": 0.5,
                    "affected_similar_run_frequency_range": [0.25, 0.75],
                    "assumptions": ["synthetic recurrence"],
                },
                "confidence": 0.8,
                "complexity": "Minimal",
                "one_time_implementation_cost": {
                    "estimated_model_calls": 1.0,
                    "description": "one focused implementation pass",
                },
                "helper_categories": helper_categories,
            }
        )
    return {
        "schema": "ceratops-credit-analysis-surface-decision.v1",
        "findings": findings,
        "risks": risks or [],
        "exclusions": exclusions or [],
        "dismissal_reason": "No additional candidate confirmed avoidable work.",
    }


def complete_credit_analysis_with_instruction_finding(
    child_status: Mapping[str, Any],
) -> pathlib.Path:
    """Finalize one prepared full analysis with one preserved synthetic finding."""

    status = dict(child_status)
    evidence = json.loads(
        pathlib.Path(status["evidence_path"]).read_text(encoding="utf-8")
    )
    categories = json.loads(CREDIT_ANALYSIS_CONTRACT.read_text(encoding="utf-8"))[
        "helper_categories"
    ]
    finding: dict[str, Any] | None = None
    while status["pending_surface"] != "synthesis":
        context = json.loads(
            pathlib.Path(status["context_path"]).read_text(encoding="utf-8")
        )
        findings: list[dict[str, Any]] = []
        exclusions: list[dict[str, Any]] = []
        helper_reviews: list[dict[str, Any]] = []
        if status["pending_surface"] == "helper-contracts":
            helper_reviews = [
                {
                    "category": category,
                    "status": "not-applicable",
                    "finding_ids": [],
                    "reason": "synthetic evidence confirms no helper gap",
                }
                for category in categories
            ]
        if status["pending_surface"] == "instruction-reasoning":
            finding = finding_record(
                "instruction-gap",
                [context["candidate_call_ids"][0]],
                producer_type="prompt",
                owner="synthetic request",
            )
            findings = [finding]
            exclusions = [
                {
                    "call_id": call_id,
                    "reason_code": "required-workflow",
                    "reason": "synthetic required workflow calls",
                }
                for call_id in context["candidate_call_ids"]
                if call_id not in finding["affected_call_ids"]
            ]
        result = surface_result_record(
            status,
            context,
            evidence["evidence_fingerprint"],
            findings=findings,
            exclusions=exclusions,
            helper_reviews=helper_reviews,
        )
        result_path = pathlib.Path(status["required_result_path"])
        write_json_file(result_path, result)
        advanced = run_credit_analysis_workflow(
            "advance",
            "--state",
            status["state_path"],
            "--result",
            str(result_path),
        )
        assert advanced.returncode == 0, advanced.stderr
        status = json.loads(advanced.stdout)
    assert finding is not None
    context = json.loads(
        pathlib.Path(status["context_path"]).read_text(encoding="utf-8")
    )
    primary_call = finding["affected_call_ids"][0]
    primary_position = evidence["call_inventory"].index(primary_call) + 1
    necessary_positions = [
        position
        for position in range(1, len(evidence["call_inventory"]) + 1)
        if position != primary_position
    ]
    synthesis = {
        "schema": "ceratops-credit-analysis-synthesis-result.v1",
        "analysis_id": status["analysis_id"],
        "pass_id": status["pass_id"],
        "surface_id": "synthesis",
        "evidence_fingerprint": evidence["evidence_fingerprint"],
        "artifact_paths": {
            "state": status["state_path"],
            "evidence": status["evidence_path"],
            "context": status["context_path"],
            "result": status["required_result_path"],
        },
        "finding_order": [finding["id"]],
        "risk_order": [],
        "finding_dispositions": [
            {
                "finding_id": finding["id"],
                "primary_call_ids": [primary_call],
                "secondary_call_ids": [],
            }
        ],
        "classification_groups": [
            {
                "classification": "avoidable_unimplemented",
                "inventory_positions": [primary_position],
                "primary_finding_id": finding["id"],
                "reason_code": None,
                "reason": "synthetic avoidable instruction call",
            },
            {
                "classification": "necessary",
                "inventory_positions": necessary_positions,
                "primary_finding_id": None,
                "reason_code": "required-workflow",
                "reason": "synthetic required workflow calls",
            },
        ],
        "secondary_call_mappings": [],
        "producer_groups": [
            {
                "id": "synthetic-prompt-group",
                "producer_type": finding["producer_type"],
                "owner": finding["producer_owner"],
                "finding_ids": [finding["id"]],
                "recommended_control": finding["proposed_durable_control"],
                "targeted_verification": finding["targeted_verification"],
            }
        ],
    }
    synthesis_path = pathlib.Path(status["required_result_path"])
    write_json_file(synthesis_path, synthesis)
    finalized = run_credit_analysis_workflow(
        "finalize",
        "--state",
        status["state_path"],
        "--result",
        str(synthesis_path),
    )
    assert finalized.returncode == 0, finalized.stderr
    final_state = json.loads(
        pathlib.Path(status["state_path"]).read_text(encoding="utf-8")
    )
    return pathlib.Path(final_state["final_result"]["path"])


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
    assert "<workspace>" in json.dumps(tool_call_record["content"])
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
    assert evidence["focused_semantic_context"]["run_ids"] == ["turn-1", "turn-2"]
    assert evidence["focused_semantic_context"]["covered_percent"] == 83.33
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


def test_credit_analysis_workflow_end_to_end_uses_six_semantic_packets(
    tmp_path: pathlib.Path,
) -> None:
    loaded = runpy.run_path(str(CREDIT_ANALYSIS_WORKFLOW))
    calls: list[dict[str, Any]] = []
    for index, (summary, tools) in enumerate(
        (
            ("first semantic path", ["exec", "wait"]),
            ("second semantic path", ["exec", "wait"]),
            ("second semantic path", ["wait", "exec"]),
            ("terminal semantic path", ["exec", "wait"]),
        ),
        start=1,
    ):
        turn_id = "cluster-turn-a" if index <= 2 else "cluster-turn-b"
        calls.append(
            {
                "call_id": f"{turn_id}:{index}",
                "turn_id": turn_id,
                "index": index,
                "semantic_actions": [
                    {"kind": "analysis", "name": "inspect", "summary": summary}
                ],
                "tool_results": [
                    {
                        "name": name,
                        "argument_chars": 10,
                        "result_chars": 20,
                        "outcomes": {},
                    }
                    for name in tools
                ],
                "tokens": {"total_tokens": 200_000 if index == 1 else 100},
                "user_message_ids": ["user-1"] if index == 1 else [],
            }
        )
    semantic_clusters = loaded["_candidate_clusters"](
        [call["call_id"] for call in calls],
        {
            "runs": [
                {"turn_id": "cluster-turn-a", "calls": calls[:2]},
                {"turn_id": "cluster-turn-b", "calls": calls[2:]},
            ]
        },
        {"cluster-turn-a"},
    )
    assert len(semantic_clusters) == 1
    assert semantic_clusters[0]["call_count"] == 4
    assert semantic_clusters[0]["volume"]["input_tokens"] == 0
    assert semantic_clusters[0]["volume"]["tool_result_chars"] == 160
    assert loaded["_budgeted_values"](
        [{"text": "x" * 100}], text_limit=200, character_budget=10
    ) == []

    request, session, _ = credit_analysis_request(
        tmp_path,
        extra_completed_turns=50,
        extra_calls_per_turn=30,
    )
    task_root = tmp_path / "analysis-full-analysis"
    task_root.rmdir()
    started = run_credit_analysis_workflow("start", "--request", str(request))
    assert started.returncode == 0, started.stderr
    assert task_root.is_dir()
    packet = json.loads(started.stdout)
    assert packet["schema"] == "ceratops-credit-analysis-pass-packet.v1"
    assert packet["surface_id"] == "helper-contracts"
    assert "prompt" in packet["decision_contract"]["producer_types"]
    assert "tool-choice" in packet["decision_contract"]["producer_types"]
    assert len(packet["decision_contract"]["producer_types"]) == len(
        set(packet["decision_contract"]["producer_types"])
    )
    assert packet["protocol_budget"] == {
        "target_total_model_calls": 8,
        "preparation_model_calls": 1,
        "semantic_model_calls": 6,
        "semantic_call_number": 1,
        "delivery_model_calls": 1,
        "bookkeeping_model_calls": 0,
    }
    assert len(started.stdout.encode("utf-8")) < 30_000
    shapes = packet["decision_contract"]["field_shapes"]
    assert shapes["risk"]["competing_explanations"] == "string list; min 2"
    assert shapes["risk"]["verification_needed"] == "string list; min 1"
    assert shapes["exclusion"]["reason_code"] == [
        "protocol-overhead",
        "required-freshness",
        "required-safety",
        "required-verification",
        "required-workflow",
        "ordinary-model-error",
        "controlled-iteration",
    ]
    assert packet["evidence"]["candidate_call_count"] > 30
    clusters = packet["evidence"]["candidate_clusters"]
    assert packet["evidence"]["candidate_cluster_count"] == len(clusters)
    assert len(clusters) * 10 < packet["evidence"]["candidate_call_count"]
    state_path = pathlib.Path(packet["submit_argv"][4])
    pending_candidates = json.loads(state_path.read_text(encoding="utf-8"))[
        "pending"
    ]["candidate_call_ids"]
    evidence_path = pathlib.Path(packet["retained_evidence_path"])
    evidence_text = evidence_path.read_text(encoding="utf-8")
    evidence = json.loads(evidence_text)
    partitions = loaded["_candidate_cluster_partition"](
        pending_candidates,
        evidence,
        set(evidence["focused_semantic_context"]["run_ids"]),
    )
    cluster_calls = {
        partition["cluster_id"]: partition["call_ids"] for partition in partitions
    }
    clustered_calls: list[str] = []
    for cluster in clusters:
        assert "selectors" not in cluster
        mapped_calls = cluster_calls[cluster["cluster_id"]]
        assert cluster["call_count"] == len(mapped_calls)
        assert cluster["representative_summary"]
        clustered_calls.extend(mapped_calls)
    assert len(clustered_calls) == len(set(clustered_calls))
    assert set(clustered_calls) == set(pending_candidates)
    expanded = loaded["_expand_decision_selectors"](
        [{"cluster_ids": [clusters[0]["cluster_id"]]}],
        set(pending_candidates),
        "test clusters",
        cluster_calls=cluster_calls,
    )
    assert expanded == cluster_calls[clusters[0]["cluster_id"]]
    assert packet["evidence"]["detailed_call_count"] == len(
        packet["evidence"]["detailed_calls"]
    )
    assert 0 < packet["evidence"]["detailed_call_count"] < packet["evidence"][
        "candidate_call_count"
    ]
    assert {
        call["call_id"] for call in packet["evidence"]["detailed_calls"]
    }.issubset(pending_candidates)
    detailed_message_ids = {
        message_id
        for call in packet["evidence"]["detailed_calls"]
        for message_id in call.get("user_message_ids", [])
    }
    assert packet["evidence"]["candidate_user_message_count"] > 16
    assert len(packet["evidence"]["candidate_user_messages"]) == packet[
        "evidence"
    ]["included_user_message_count"]
    assert packet["evidence"]["included_user_message_count"] < packet[
        "evidence"
    ]["candidate_user_message_count"]
    if detailed_message_ids and packet["evidence"]["candidate_user_messages"]:
        assert (
            packet["evidence"]["candidate_user_messages"][0]["message_id"]
            in detailed_message_ids
        )
    assert packet["evidence"]["included_model_review_record_count"] < packet[
        "evidence"
    ]["relevant_model_review_record_count"]
    assert packet["evidence"]["relevant_model_review_record_count"] > 30
    assert packet["evidence"]["complete_evidence_retained_on_disk"] is True
    assert packet["evidence"]["included_run_outcome_count"] == len(
        packet["evidence"]["run_outcomes"]
    )
    assert packet["evidence"]["included_run_outcome_count"] <= packet[
        "evidence"
    ]["run_outcome_count"]
    assert packet["evidence"]["run_outcome_purpose"].startswith(
        "Check later run outcomes"
    )
    assert "ACTIVE_TAIL_MUST_NOT_BE_COLLECTED" not in evidence_text
    assert "active_tail_tool" not in evidence_text
    assert evidence["collection"]["session_reads"] == 1
    session.rename(tmp_path / "session-collected-once-end-to-end.jsonl")

    expected_surfaces = [
        "helper-contracts",
        "context-evidence",
        "rework-validation",
        "tool-flow",
        "instruction-reasoning",
    ]
    implemented_finding_id = "e2e-context-evidence"
    finding_ids: list[str] = []
    claimed_call_ids: set[str] = set()
    for semantic_number, surface_id in enumerate(expected_surfaces, start=1):
        assert len(json.dumps(packet, separators=(",", ":")).encode("utf-8")) < 30_000
        assert packet["surface_id"] == surface_id
        assert packet["protocol_budget"]["semantic_call_number"] == semantic_number
        assert packet["action_reference"]["path"] == f"references/{surface_id}.md"
        assert packet["action_reference"]["content"]
        assert packet["evidence"]["candidate_clusters"]
        assert packet["evidence"]["detailed_calls"]
        if surface_id != "context-evidence":
            assert all(
                cluster["representative_summary"]
                for cluster in packet["evidence"]["candidate_clusters"]
            )
            assert all(
                isinstance(cluster["representative_call_id"], str)
                for cluster in packet["evidence"]["candidate_clusters"]
            )
        if surface_id == "context-evidence":
            assert all(
                "input_tokens" in cluster and "tool_result_chars" not in cluster
                for cluster in packet["evidence"]["candidate_clusters"]
            )
        elif surface_id == "tool-flow":
            assert all(
                "tool_result_chars" in cluster and "input_tokens" not in cluster
                for cluster in packet["evidence"]["candidate_clusters"]
            )
        else:
            assert all(
                "input_tokens" not in cluster and "tool_result_chars" not in cluster
                for cluster in packet["evidence"]["candidate_clusters"]
            )
        assert all(
            "model_call_id" in record
            for record in packet["evidence"]["included_model_review_records"]
        )
        pending = json.loads(state_path.read_text(encoding="utf-8"))["pending"]
        partitions = loaded["_candidate_cluster_partition"](
            pending["candidate_call_ids"],
            evidence,
            set(evidence["focused_semantic_context"]["run_ids"]),
        )
        selected_cluster_id = packet["evidence"]["candidate_clusters"][0][
            "cluster_id"
        ]
        selected_calls = set(
            next(
                partition["call_ids"]
                for partition in partitions
                if partition["cluster_id"] == selected_cluster_id
            )
        )
        if surface_id == "context-evidence":
            assert packet["evidence"]["candidate_call_count"] == evidence["totals"][
                "model_calls"
            ]
            assert packet["evidence"]["input_volume_hotspots"]
            hotspot_ids = set(packet["evidence"]["input_volume_hotspots"])
            assert all(
                cluster.get("representative_summary")
                for cluster in packet["evidence"]["candidate_clusters"]
                if cluster["cluster_id"] in hotspot_ids
            )
            assert all(
                isinstance(cluster_id, str)
                for cluster_id in packet["evidence"]["input_volume_hotspots"]
            )
        if surface_id == "tool-flow":
            assert packet["evidence"]["output_volume_hotspots"]
            assert set(packet["evidence"]["output_volume_hotspots"]).issubset(
                {cluster["cluster_id"] for cluster in packet["evidence"]["candidate_clusters"]}
            )
        finding_id = f"e2e-{surface_id}"
        finding_ids.append(finding_id)
        risks: list[dict[str, Any]] = []
        exclusions: list[dict[str, Any]] = []
        if surface_id == "tool-flow":
            risks.append(
                {
                    "id": "e2e-tool-risk",
                    "description": "synthetic wait timing is ambiguous",
                    "observed_sequence": (
                        "The synthetic tool call was followed by a wait."
                    ),
                    "competing_explanations": [
                        "The wait repeated an already complete check.",
                        "The wait observed a still-running external operation.",
                    ],
                    "missing_fact": (
                        "The exact external completion timestamp was not retained"
                    ),
                    "affected_selectors": [
                        {
                            "call_ids": [
                                packet["evidence"]["detailed_calls"][-1]["call_id"]
                            ]
                        }
                    ],
                    "additional_evidence_selectors": [],
                    "verification_needed": [
                        "retain the external completion timestamp"
                    ],
                }
            )
        if surface_id == "instruction-reasoning":
            retained_partition = min(
                (
                    partition
                    for partition in partitions
                    if partition["cluster_id"] != selected_cluster_id
                    and set(partition["call_ids"]) - claimed_call_ids
                ),
                key=lambda partition: len(
                    set(partition["call_ids"]) - claimed_call_ids
                ),
            )
            retained_calls = set(retained_partition["call_ids"]) - claimed_call_ids
            excluded_calls = [
                call_id
                for call_id in pending["candidate_call_ids"]
                if call_id not in selected_calls and call_id not in retained_calls
            ]
            exclusions = [
                {
                    "selectors": [{"call_ids": excluded_calls}],
                    "reason_code": "required-workflow",
                    "reason": "Synthetic surface evidence proves required workflow work.",
                }
            ]
        if surface_id != "tool-flow":
            claimed_call_ids.update(selected_calls)
        decision_path = pathlib.Path(packet["decision_path"])
        write_json_file(
            decision_path,
            surface_decision_record(
                packet,
                finding_id=finding_id,
                implementation_status=(
                    "implemented"
                    if finding_id == implemented_finding_id
                    else "unimplemented"
                ),
                waste_kind=(
                    "context-volume" if surface_id == "tool-flow" else "model-calls"
                ),
                risks=risks,
                exclusions=exclusions,
            ),
        )
        submitted = run_credit_analysis_workflow(
            "submit",
            "--state",
            str(state_path),
            "--decision",
            str(decision_path),
        )
        assert submitted.returncode == 0, submitted.stderr
        assert len(submitted.stdout.encode("utf-8")) < 30_000
        packet = json.loads(submitted.stdout)

    assert packet["surface_id"] == "synthesis"
    assert packet["internal"] is True
    assert packet["action_reference"] is None
    assert packet["protocol_budget"]["semantic_call_number"] == 6
    assert packet["decision_contract"]["assessment_shape"] == {
        "cluster_ids": "string list; min 1; each cluster at most once",
        "classification": ["unassessed"],
        "reason_code": None,
        "reason": "nonempty string",
    }
    assert "must not invent necessity" in packet["decision_contract"]["rule"]
    assert "Explicitly assess every listed input and output hotspot" in packet[
        "decision_contract"
    ]["rule"]
    assert "more than half" in packet["decision_contract"]["rule"]
    assert [item["id"] for item in packet["accepted_findings"]] == finding_ids
    remaining_clusters = packet["remaining_calls"]["clusters"]
    assert packet["remaining_calls"]["call_count"] > 0
    assert remaining_clusters
    assert all(cluster.get("representative_summary") for cluster in remaining_clusters)
    assert all("observable_signature" not in cluster for cluster in remaining_clusters)
    assert all("volume" not in cluster for cluster in remaining_clusters)
    assert all(cluster["semantic_actions"] for cluster in remaining_clusters)
    assert all("uncached_input_tokens" in cluster for cluster in remaining_clusters)
    assert all("tool_result_chars" in cluster for cluster in remaining_clusters)
    assert packet["remaining_calls"]["input_volume_hotspots"]
    assert packet["remaining_calls"]["output_volume_hotspots"]
    decision_path = pathlib.Path(packet["decision_path"])
    write_json_file(
        decision_path,
        {
            "schema": "ceratops-credit-analysis-synthesis-decision.v1",
            "finding_order": list(reversed(finding_ids)),
            "risk_order": ["e2e-tool-risk"],
            "remaining_call_assessments": [],
        },
    )
    rejected_hotspot = run_credit_analysis_workflow(
        "submit",
        "--state",
        str(state_path),
        "--decision",
        str(decision_path),
    )
    assert rejected_hotspot.returncode == 2
    assert "explicitly assess every input/output hotspot" in rejected_hotspot.stderr
    assert json.loads(state_path.read_text(encoding="utf-8"))["pending"][
        "surface_id"
    ] == "synthesis"

    assert packet["remaining_calls"]["call_count"] * 2 <= evidence["totals"][
        "model_calls"
    ]
    write_json_file(
        decision_path,
        {
            "schema": "ceratops-credit-analysis-synthesis-decision.v1",
            "finding_order": list(reversed(finding_ids)),
            "risk_order": ["e2e-tool-risk"],
            "remaining_call_assessments": [
                {
                    "cluster_ids": [
                        cluster["cluster_id"] for cluster in remaining_clusters
                    ],
                    "classification": "necessary",
                    "reason_code": "required-workflow",
                    "reason": "Synthetic workflow work was required.",
                }
            ],
        },
    )
    rejected_unsupported_necessary = run_credit_analysis_workflow(
        "submit",
        "--state",
        str(state_path),
        "--decision",
        str(decision_path),
    )
    assert rejected_unsupported_necessary.returncode == 2
    assert "necessary calls must come from accepted surface exclusions" in (
        rejected_unsupported_necessary.stderr
    )
    assert json.loads(state_path.read_text(encoding="utf-8"))["pending"][
        "surface_id"
    ] == "synthesis"

    write_json_file(
        decision_path,
        {
            "schema": "ceratops-credit-analysis-synthesis-decision.v1",
            "finding_order": list(reversed(finding_ids)),
            "risk_order": ["e2e-tool-risk"],
            "remaining_call_assessments": [
                {
                    "cluster_ids": [
                        cluster["cluster_id"] for cluster in remaining_clusters
                    ],
                    "classification": "unassessed",
                    "reason_code": None,
                    "reason": "Synthetic evidence omits the required outcome purpose.",
                }
            ],
        },
    )
    submitted = run_credit_analysis_workflow(
        "submit",
        "--state",
        str(state_path),
        "--decision",
        str(decision_path),
    )
    assert submitted.returncode == 0, submitted.stderr
    final_packet = json.loads(submitted.stdout)
    assert final_packet["schema"] == "ceratops-credit-analysis-final-packet.v1"
    assert final_packet["complete"] is True
    assert final_packet["protocol_budget"]["target_total_model_calls"] == 8
    assert final_packet["protocol_budget"]["semantic_model_calls"] == 6
    assert final_packet["protocol_budget"]["bookkeeping_model_calls"] == 0
    report = final_packet["report_markdown"]
    assert "Confirmed: 5; outstanding: 4; already addressed: 1" in report
    assert all(finding_id not in report for finding_id in finding_ids)
    assert all(
        finding_id.replace("-", " ") in report
        for finding_id in finding_ids
        if finding_id != implemented_finding_id
    )
    assert implemented_finding_id.replace("-", " ") not in report
    assert "Evidence: The helper-contracts evidence shows" in report
    assert "## Input/output token reduction" in report
    assert "Recommended control:" in report
    assert "cached-input" in report
    assert all(call_id not in report for call_id in evidence["call_inventory"])
    assert "Unassessed:" in final_packet["report_markdown"]
    assert "Observed: The synthetic tool call was followed by a wait." in report
    assert (
        "Unknown: The wait repeated an already complete check.; The wait observed "
        "a still-running external operation."
        in report
    )
    assert (
        "Why not confirmed: The exact external completion timestamp was not "
        "retained; choosing between the competing explanations would be speculation."
        in report
    )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["finalized"] is True
    assert [item["surface_id"] for item in state["completed"]] == [
        *expected_surfaces,
        "synthesis",
    ]
    assert len(list(pathlib.Path(state["paths"]["findings_dir"]).glob("*.json"))) == 6
    assert not pathlib.Path(state["paths"]["context_dir"]).exists()
    assert not pathlib.Path(state["paths"]["pending_dir"]).exists()
    final_result = json.loads(
        pathlib.Path(final_packet["retained_result_path"]).read_text(encoding="utf-8")
    )
    assert [item["id"] for item in final_result["confirmed_findings"]] == list(
        reversed(finding_ids)
    )
    assert final_result["totals"]["unassessed_calls"] == packet[
        "remaining_calls"
    ]["call_count"]
    assert {
        item["classification"] for item in final_result["primary_call_mappings"]
    } <= {
        "avoidable_unimplemented",
        "avoidable_implemented",
        "necessary",
        "unassessed",
    }

    resumed = run_credit_analysis_workflow(
        "status", "--state", str(state_path), "--packet"
    )
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout) == final_packet


def test_credit_analysis_workflow_rejects_invalid_and_conflicting_passes(
    tmp_path: pathlib.Path,
) -> None:
    request, session, _ = credit_analysis_request(tmp_path)
    prepared = run_credit_analysis_workflow("prepare", "--request", str(request))
    assert prepared.returncode == 0, prepared.stderr
    status = json.loads(prepared.stdout)
    state_path = pathlib.Path(status["state_path"])
    evidence = json.loads(pathlib.Path(status["evidence_path"]).read_text(encoding="utf-8"))
    context = json.loads(pathlib.Path(status["context_path"]).read_text(encoding="utf-8"))
    result_path = pathlib.Path(status["required_result_path"])
    categories = json.loads(CREDIT_ANALYSIS_CONTRACT.read_text(encoding="utf-8"))[
        "helper_categories"
    ]
    reviews = [
        {
            "category": category,
            "status": "not-applicable",
            "finding_ids": [],
            "reason": "no helper defect confirmed",
        }
        for category in categories
    ]
    valid = surface_result_record(
        status,
        context,
        evidence["evidence_fingerprint"],
        helper_reviews=reviews,
    )
    invalid_values = [
        {},
        {**valid, "surface_id": "context-evidence"},
        {**valid, "pass_id": "stale.pass"},
        {**valid, "evidence_fingerprint": "0" * 64},
        {**valid, "reviewed_candidate_call_ids": valid["reviewed_candidate_call_ids"][:-1]},
        {
            **valid,
            "dismissed_candidates": valid["dismissed_candidates"][:-1],
        },
        {
            **valid,
            "plausible_risks": [
                {
                    "id": "incomplete-risk",
                    "description": "risk detail is incomplete",
                    "affected_call_ids": [context["candidate_call_ids"][0]],
                    "evidence_refs": [
                        f"evidence://calls/{context['candidate_call_ids'][0]}"
                    ],
                    "verification_needed": ["inspect the missing evidence"],
                }
            ],
        },
    ]
    for invalid in invalid_values:
        write_json_file(result_path, invalid)
        rejected = run_credit_analysis_workflow(
            "advance",
            "--state",
            str(state_path),
            "--result",
            str(result_path),
        )
        assert rejected.returncode == 2
        current = json.loads(
            run_credit_analysis_workflow("status", "--state", str(state_path)).stdout
        )
        assert current["pass_id"] == status["pass_id"]
        assert not pathlib.Path(json.loads(state_path.read_text(encoding="utf-8"))["paths"]["index"]).exists()

    write_json_file(result_path, valid)
    accepted = run_credit_analysis_workflow(
        "advance",
        "--state",
        str(state_path),
        "--result",
        str(result_path),
    )
    assert accepted.returncode == 0, accepted.stderr
    next_status = json.loads(accepted.stdout)
    assert next_status["pending_surface"] == "context-evidence"
    repeated = run_credit_analysis_workflow(
        "advance",
        "--state",
        str(state_path),
        "--result",
        str(result_path),
    )
    assert repeated.returncode == 0, repeated.stderr
    assert json.loads(repeated.stdout) == next_status
    conflict_path = tmp_path / "conflict.json"
    write_json_file(conflict_path, {**valid, "evidence_references": []})
    conflict = run_credit_analysis_workflow(
        "advance",
        "--state",
        str(state_path),
        "--result",
        str(conflict_path),
    )
    assert conflict.returncode == 2
    assert "conflicting resubmission" in conflict.stderr

    next_context = json.loads(
        pathlib.Path(next_status["context_path"]).read_text(encoding="utf-8")
    )
    valid_context_result = surface_result_record(
        next_status,
        next_context,
        evidence["evidence_fingerprint"],
    )
    reordered = {**valid_context_result, "surface_id": "helper-contracts"}
    write_json_file(pathlib.Path(next_status["required_result_path"]), reordered)
    rejected_repeat = run_credit_analysis_workflow(
        "advance",
        "--state",
        str(state_path),
        "--result",
        next_status["required_result_path"],
    )
    assert rejected_repeat.returncode == 2
    assert "surface_id" in rejected_repeat.stderr

    context_result_path = pathlib.Path(next_status["required_result_path"])
    write_json_file(context_result_path, valid_context_result)
    orphaned_immutable = (
        pathlib.Path(json.loads(state_path.read_text(encoding="utf-8"))["paths"]["findings_dir"])
        / "002-context-evidence.json"
    )
    write_json_file(orphaned_immutable, valid_context_result)
    orphan_hash = hashlib.sha256(orphaned_immutable.read_bytes()).hexdigest()
    index_path = pathlib.Path(
        json.loads(state_path.read_text(encoding="utf-8"))["paths"]["index"]
    )
    with index_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                {
                    "schema": "ceratops-credit-analysis-index-record.v1",
                    "ordinal": 2,
                    "surface_id": "context-evidence",
                    "pass_id": next_status["pass_id"],
                    "path": str(orphaned_immutable.resolve()),
                    "sha256": orphan_hash,
                    "content_hash": orphan_hash,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
    recovered = run_credit_analysis_workflow("status", "--state", str(state_path))
    assert recovered.returncode == 0, recovered.stderr
    assert json.loads(recovered.stdout)["pending_surface"] == "rework-validation"

    state = json.loads(state_path.read_text(encoding="utf-8"))
    accepted_path = pathlib.Path(state["completed"][0]["path"])
    original = accepted_path.read_text(encoding="utf-8")
    accepted_path.write_text(original.replace("helper-contracts", "tool-flow", 1), encoding="utf-8")
    integrity = run_credit_analysis_workflow("status", "--state", str(state_path))
    assert integrity.returncode == 2
    assert "hash mismatch" in integrity.stderr
    accepted_path.write_text(original, encoding="utf-8", newline="\n")
    session.rename(tmp_path / "session-not-reread.jsonl")
    resumed = run_credit_analysis_workflow("status", "--state", str(state_path))
    assert resumed.returncode == 0, resumed.stderr


def test_credit_analysis_workflow_standalone_zero_findings_is_isolated(
    tmp_path: pathlib.Path,
) -> None:
    request, _, task_root = credit_analysis_request(
        tmp_path,
        action="context-evidence",
    )
    pricing = tmp_path / "pricing.json"
    write_json_file(
        pricing,
        {
            "schema": "ceratops-model-call-pricing-profile.v1",
            "input_per_million_tokens": 1.0,
            "cached_input_per_million_tokens": 0.5,
            "output_per_million_tokens": 2.0,
            "mode_multiplier": 1.0,
        },
    )
    request_value = json.loads(request.read_text(encoding="utf-8"))
    request_value["pricing_profile"] = str(pricing)
    write_json_file(request, request_value)
    prepared = run_credit_analysis_workflow("prepare", "--request", str(request))
    assert prepared.returncode == 0, prepared.stderr
    status = json.loads(prepared.stdout)
    assert status["pending_surface"] == "context-evidence"
    evidence = json.loads(pathlib.Path(status["evidence_path"]).read_text(encoding="utf-8"))
    context = json.loads(pathlib.Path(status["context_path"]).read_text(encoding="utf-8"))
    result = surface_result_record(
        status,
        context,
        evidence["evidence_fingerprint"],
    )
    result_path = pathlib.Path(status["required_result_path"])
    incomplete = {**result, "dismissed_candidates": []}
    write_json_file(result_path, incomplete)
    rejected = run_credit_analysis_workflow(
        "advance",
        "--state",
        status["state_path"],
        "--result",
        str(result_path),
    )
    assert rejected.returncode == 2
    assert "zero-finding" in rejected.stderr or "not accounted" in rejected.stderr

    write_json_file(result_path, result)
    write_json_file(task_root / "findings" / "001-context-evidence.json", result)
    advanced = run_credit_analysis_workflow(
        "advance",
        "--state",
        status["state_path"],
        "--result",
        str(result_path),
    )
    assert advanced.returncode == 0, advanced.stderr
    ready = json.loads(advanced.stdout)
    assert ready["pending_surface"] is None
    assert ready["ready_to_finalize"] is True
    state = json.loads(pathlib.Path(status["state_path"]).read_text(encoding="utf-8"))
    assert state["queue"] == ["context-evidence"]
    assert [record["surface_id"] for record in state["completed"]] == [
        "context-evidence"
    ]
    finalized = run_credit_analysis_workflow(
        "finalize",
        "--state",
        status["state_path"],
        "--result",
        ready["required_result_path"],
    )
    assert finalized.returncode == 0, finalized.stderr
    final_state = json.loads(pathlib.Path(status["state_path"]).read_text(encoding="utf-8"))
    final_result = json.loads(
        pathlib.Path(final_state["final_result"]["path"]).read_text(encoding="utf-8")
    )
    assert final_result["mode"] == "standalone"
    assert "not a whole-thread credit reconciliation" in final_result[
        "scope_limitation"
    ]
    assert final_result["confirmed_findings"] == []
    assert final_result["pricing"]["provided"] is True
    assert final_result["priced_cost"] == {
        "total": 7.8e-05,
        "selected_surface_observed_avoidable": 0.0,
    }
    assert not (task_root / "context").exists()
    assert not (task_root / "pending").exists()

    contract = json.loads(CREDIT_ANALYSIS_CONTRACT.read_text(encoding="utf-8"))
    public_actions = [item["id"] for item in contract["public_actions"]]
    assert "synthesis" not in public_actions
    assert "batch-summary" not in public_actions
    assert contract["internal_phases"] == [
        {"id": "synthesis", "public": False},
        {"id": "batch-summary", "public": False},
    ]
    rejected_root = tmp_path / "analysis-synthesis"
    rejected_root.mkdir()
    rejected_request = tmp_path / "request-synthesis.json"
    write_json_file(
        rejected_request,
        {
            **json.loads(request.read_text(encoding="utf-8")),
            "action": "synthesis",
            "mode": "standalone",
            "task_temp_root": str(rejected_root),
            "evidence_output": str(tmp_path / "synthesis-evidence.json"),
        },
    )
    rejected_synthesis = run_credit_analysis_workflow(
        "prepare", "--request", str(rejected_request)
    )
    assert rejected_synthesis.returncode == 2
    assert "action is not public" in rejected_synthesis.stderr

    volume_base = tmp_path / "volume"
    volume_base.mkdir()
    volume_request, _, _ = credit_analysis_request(
        volume_base,
        action="tool-flow",
    )
    volume_prepared = run_credit_analysis_workflow(
        "prepare", "--request", str(volume_request)
    )
    assert volume_prepared.returncode == 0, volume_prepared.stderr
    volume_status = json.loads(volume_prepared.stdout)
    volume_evidence = json.loads(
        pathlib.Path(volume_status["evidence_path"]).read_text(encoding="utf-8")
    )
    volume_context = json.loads(
        pathlib.Path(volume_status["context_path"]).read_text(encoding="utf-8")
    )
    volume_finding = finding_record(
        "oversized-output",
        [volume_evidence["call_inventory"][0]],
        producer_type="tool-choice",
        owner="synthetic command",
        waste_kind="context-volume",
        complexity="Minimal",
    )
    volume_result = surface_result_record(
        volume_status,
        volume_context,
        volume_evidence["evidence_fingerprint"],
        findings=[volume_finding],
    )
    write_json_file(
        pathlib.Path(volume_status["required_result_path"]), volume_result
    )
    volume_advanced = run_credit_analysis_workflow(
        "advance",
        "--state",
        volume_status["state_path"],
        "--result",
        volume_status["required_result_path"],
    )
    assert volume_advanced.returncode == 0, volume_advanced.stderr
    volume_ready = json.loads(volume_advanced.stdout)
    volume_finalized = run_credit_analysis_workflow(
        "finalize",
        "--state",
        volume_status["state_path"],
        "--result",
        volume_ready["required_result_path"],
    )
    assert volume_finalized.returncode == 0, volume_finalized.stderr
    volume_state = json.loads(
        pathlib.Path(volume_status["state_path"]).read_text(encoding="utf-8")
    )
    volume_machine_result = json.loads(
        pathlib.Path(volume_state["final_result"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    assert volume_machine_result["totals"]["surface_observed_avoidable_calls"] == 0
    assert volume_machine_result["confirmed_findings"][0][
        "deduplicated_avoidable_call_count"
    ] == 0


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
    prepared = run_credit_analysis_workflow("prepare", "--request", str(request))
    assert prepared.returncode == 0, prepared.stderr
    status = json.loads(prepared.stdout)
    assert status["pending_surface"] == action
    state = json.loads(pathlib.Path(status["state_path"]).read_text(encoding="utf-8"))
    assert state["mode"] == "standalone"
    assert state["queue"] == [action]


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
        root = tmp_path / f"single-{name}"
        root.mkdir()
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
                "evidence_output": str(tmp_path / f"single-evidence-{name}.json"),
                "pricing_profile": None,
                "expected_surface_contract_version": 1,
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
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    thread_ids = {
        "alpha_new": "00000000-0000-4000-8000-000000000011",
        "alpha_old": "00000000-0000-4000-8000-000000000012",
        "beta_old": "00000000-0000-4000-8000-000000000013",
        "alpha_stale": "00000000-0000-4000-8000-000000000014",
        "beta_new": "00000000-0000-4000-8000-000000000015",
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
                thread_ids["beta_old"],
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
            task_root = tmp_path / f"batch-{name}"
            task_root.rmdir()
        prepared = run_credit_analysis_workflow(
            "prepare-batch", "--request", str(request)
        )
        assert prepared.returncode == 0, prepared.stderr
        if name == "count-overall":
            assert task_root.is_dir()
        status = json.loads(prepared.stdout)
        manifest = json.loads(
            pathlib.Path(status["manifest_path"]).read_text(encoding="utf-8")
        )
        assert [item["thread_id"] for item in manifest["items"]] == expected_ids
        for item in manifest["items"]:
            evidence = json.loads(
                pathlib.Path(item["evidence_path"]).read_text(encoding="utf-8")
            )
            assert evidence["collection"]["session_reads"] == 1
            child_state = json.loads(
                pathlib.Path(item["state_path"]).read_text(encoding="utf-8")
            )
            assert child_state["queue"] == [
                "helper-contracts",
                "context-evidence",
                "rework-validation",
                "tool-flow",
                "instruction-reasoning",
                "synthesis",
            ]
        resumed = run_credit_analysis_workflow(
            "prepare-batch", "--request", str(request)
        )
        assert resumed.returncode == 0, resumed.stderr
        assert json.loads(resumed.stdout) == status

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
    ambiguous = run_credit_analysis_workflow(
        "prepare-batch", "--request", str(ambiguous_request)
    )
    assert ambiguous.returncode == 2
    assert "project name is ambiguous" in ambiguous.stderr


def test_credit_analysis_batch_resumes_and_preserves_every_thread_finding(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    prepared = run_credit_analysis_workflow(
        "prepare-batch", "--request", str(request)
    )
    assert prepared.returncode == 0, prepared.stderr
    status = json.loads(prepared.stdout)
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
    resumed_prepare = run_credit_analysis_workflow(
        "prepare-batch", "--request", str(request)
    )
    assert resumed_prepare.returncode == 0, resumed_prepare.stderr
    status = json.loads(resumed_prepare.stdout)
    resumed_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert resumed_state["items"] == prepared_items

    first_final = complete_credit_analysis_with_instruction_finding(
        status["child_status"]
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

    second_final = complete_credit_analysis_with_instruction_finding(
        second_status["child_status"]
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
        f"{ids[0]}:instruction-gap",
        f"{ids[1]}:instruction-gap",
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
                "id": "shared-instruction-gap",
                "title": "Shared instruction gap",
                "producer_type": "prompt",
                "owner": "synthetic request",
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
    assert [item["thread_id"] for item in final["confirmed_findings"]] == ids
    assert [item["finding"]["id"] for item in final["confirmed_findings"]] == [
        "instruction-gap",
        "instruction-gap",
    ]
    assert [item["thread_id"] for item in final["per_thread_totals"]] == ids
    assert len(final["summary_groups"]) == 1
    group = final["summary_groups"][0]
    assert group["id"] == "shared-instruction-gap"
    assert [item["batch_finding_id"] for item in group["findings"]] == (
        batch_finding_ids
    )
    assert group["threads"] == ids
    assert group["contributing_surfaces"] == ["instruction-reasoning"]
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
        assert not (child_root / "context").exists()
        assert not (child_root / "pending").exists()
        assert pathlib.Path(item["request_path"]).is_file()
        assert pathlib.Path(item["evidence_path"]).is_file()
    complete = run_credit_analysis_workflow(
        "status-batch", "--state", str(state_path)
    )
    assert complete.returncode == 0, complete.stderr
    assert json.loads(complete.stdout)["complete"] is True


def run_compatibility_engine(
    scripts_root: pathlib.Path,
    command: str,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    """Run one package command from its source or installed scripts folder."""

    return subprocess.run(
        [sys.executable, "-m", COMPATIBILITY_ENGINE, command, *arguments],
        cwd=scripts_root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_model_call_ledger_keeps_full_evidence_out_of_stdout(
    tmp_path: pathlib.Path,
) -> None:
    session = tmp_path / "session.jsonl"
    evidence = tmp_path / "ledger.json"
    semantic_evidence = tmp_path / "semantic.json"
    local_path = str(tmp_path / "private" / "command.txt")
    user_message_text = (
        "Please handle token=sentinel-secret, correct the previous answer, "
        f"accept my approval, and clarify the request at {local_path}"
    )
    rows = [
        {
            "timestamp": "2026-07-25T00:00:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": user_message_text}],
            },
        },
        {
            "timestamp": "2026-07-25T00:00:00.500Z",
            "type": "turn_context",
            "payload": {"turn_id": "turn-1"},
        },
        {
            "timestamp": "2026-07-25T00:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "shell_command",
                "arguments": json.dumps(
                    {
                        "credential": "sentinel-secret",
                        "path": local_path,
                    }
                ),
            },
        },
        {
            "timestamp": "2026-07-25T00:00:02Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 10,
                        "output_tokens": 1,
                        "total_tokens": 11,
                    }
                },
            },
        },
        {
            "timestamp": "2026-07-25T00:00:03Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
            },
        },
        {
            "timestamp": "2026-07-25T00:00:04Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 20,
                        "output_tokens": 2,
                        "total_tokens": 22,
                    }
                },
            },
        },
    ]
    session.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )

    compact = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--session",
            str(session),
            "--evidence-output",
            str(evidence),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert compact.returncode == 0, compact.stderr
    summary = json.loads(compact.stdout)
    assert summary["schema"] == "ceratops-model-call-ledger-summary.v1"
    assert summary["totals"]["model_calls"] == 2
    assert summary["runs"][0]["turn_id"] == "turn-1"
    assert summary["selected_runs"] == []
    assert "calls" not in summary["runs"][0]
    ledger = json.loads(evidence.read_text(encoding="utf-8"))
    assert len(ledger["runs"][0]["calls"]) == 2
    assert "sentinel-secret" not in evidence.read_text(encoding="utf-8")

    missing_sidecar = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--session",
            str(session),
            "--evidence-output",
            str(evidence),
            "--include-run",
            "turn-1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_sidecar.returncode == 2
    assert (
        "--include-run requires --semantic-evidence-output"
        in missing_sidecar.stderr
    )
    assert missing_sidecar.stdout == ""

    sidecar = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--session",
            str(session),
            "--evidence-output",
            str(evidence),
            "--semantic-evidence-output",
            str(semantic_evidence),
            "--include-run",
            "turn-1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert sidecar.returncode == 0, sidecar.stderr
    assert "sentinel-secret" not in sidecar.stdout
    assert local_path not in sidecar.stdout
    sidecar_summary = json.loads(sidecar.stdout)
    assert sidecar_summary["schema"] == (
        "ceratops-model-call-semantic-summary.v1"
    )
    assert sidecar_summary["evidence_schemas"] == {
        "ledger": "ceratops-model-call-ledger.v1",
        "semantic": "ceratops-model-call-semantic-evidence.v1",
    }
    assert sidecar_summary["written"] == {"ledger": True, "semantic": True}
    assert sidecar_summary["totals"] == {
        "selected_runs": 1,
        "selected_model_calls": 2,
    }
    assert sidecar_summary["selected_runs"] == [
        {"turn_id": "turn-1", "model_calls": 2}
    ]
    assert "evidence_output" not in sidecar_summary
    assert json.loads(evidence.read_text(encoding="utf-8"))["schema"] == (
        "ceratops-model-call-ledger.v1"
    )
    semantic_detail = json.loads(semantic_evidence.read_text(encoding="utf-8"))
    assert semantic_detail["schema"] == (
        "ceratops-model-call-semantic-evidence.v1"
    )
    serialized_semantics = json.dumps(semantic_detail)
    assert "sentinel-secret" not in serialized_semantics
    assert local_path not in serialized_semantics
    user_message = semantic_detail["selected_runs"][0]["user_messages"][0]
    assert user_message["first_model_call_index"] == 1
    assert "correct the previous answer" in user_message["text"]
    assert "accept my approval" in user_message["text"]
    assert "clarify the request" in user_message["text"]
    assert "<redacted>" in user_message["text"]
    assert "<local-path>" in user_message["text"]
    assert "kind" not in user_message
    assert semantic_detail["redaction"]["semantic_classification"] == "none"
    assert semantic_detail["selected_runs"][0]["calls"][1][
        "user_message_ids"
    ] == [user_message["message_id"]]
    assert semantic_detail["selected_runs"][0]["calls"][0][
        "semantic_actions"
    ][0]["summary"] == (
        '{"credential":"<redacted>","path":"<local-path>"}'
    )

    missing_selection = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--session",
            str(session),
            "--evidence-output",
            str(evidence),
            "--semantic-evidence-output",
            str(semantic_evidence),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_selection.returncode == 2
    assert "requires --include-run" in missing_selection.stderr

    classifications = tmp_path / "classifications.json"
    classifications.write_text(
        json.dumps(
            {
                "schema": "ceratops-model-call-classifications.v1",
                "session": str(session),
                "runs": [
                    {
                        "turn_id": "turn-1",
                        "groups": [
                            {"category": "necessary", "indices": [1, 2]}
                        ],
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    classified = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--session",
            str(session),
            "--classifications",
            str(classifications),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert classified.returncode == 0, classified.stderr
    classified_summary = json.loads(classified.stdout)
    assert classified_summary["schema"] == (
        "ceratops-model-call-classified-summary.v1"
    )
    assert classified_summary["totals"]["model_calls"] == 2
    assert classified_summary["totals"]["necessary"] == 2


def test_model_call_ledger_usage_summary_is_ranked_and_evidence_based(
    tmp_path: pathlib.Path,
) -> None:
    session = tmp_path / "session.jsonl"
    evidence = tmp_path / "usage-evidence.json"
    unpriced_evidence = tmp_path / "unpriced-evidence.json"
    pricing = tmp_path / "pricing.json"
    secret = "summary-sentinel-secret"
    local_path = str(pathlib.Path.home() / "private" / "summary.txt")
    repeated_arguments = json.dumps(
        {"command": "check", "credential": secret},
        sort_keys=True,
    )
    rows = [
        {
            "timestamp": "2026-07-25T00:00:00Z",
            "type": "turn_context",
            "payload": {"turn_id": "turn-1"},
        },
        {
            "timestamp": "2026-07-25T00:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "mcp_process",
                "call_id": "call-1",
                "input": repeated_arguments,
            },
        },
        {
            "timestamp": "2026-07-25T00:00:01.100Z",
            "type": "event_msg",
            "payload": {
                "type": "mcp_tool_call_end",
                "call_id": "call-1",
                "duration": {"secs": 0, "nanos": 100_000_000},
                "result": {
                    "Ok": {
                        "isError": True,
                        "structuredContent": {
                            "exit_code": 7,
                            "timed_out": True,
                            "path": local_path,
                            "secret": secret,
                        },
                    }
                },
            },
        },
        {
            "timestamp": "2026-07-25T00:00:01.200Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "call-1",
                "output": [{"type": "text", "text": f"{local_path} {secret}"}],
            },
        },
        {
            "timestamp": "2026-07-25T00:00:02Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 40,
                        "output_tokens": 20,
                        "reasoning_output_tokens": 5,
                        "total_tokens": 120,
                    }
                },
            },
        },
        {
            "timestamp": "2026-07-25T00:00:03Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "mcp_process",
                "call_id": "call-2",
                "input": repeated_arguments,
            },
        },
        {
            "timestamp": "2026-07-25T00:00:03.100Z",
            "type": "event_msg",
            "payload": {
                "type": "mcp_tool_call_end",
                "call_id": "call-2",
                "duration": {"secs": 0, "nanos": 100_000_000},
                "result": {
                    "Ok": {
                        "isError": False,
                        "structuredContent": {
                            "exit_code": 3,
                            "timed_out": False,
                        },
                    }
                },
            },
        },
        {
            "timestamp": "2026-07-25T00:00:03.200Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "call-2",
                "output": [{"type": "text", "text": "nonzero but handled"}],
            },
        },
        {
            "timestamp": "2026-07-25T00:00:04Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "wait_agent",
                "call_id": "call-3",
                "arguments": "{}",
            },
        },
        {
            "timestamp": "2026-07-25T00:00:04.100Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call-3",
                "output": json.dumps({"timed_out": True, "message": secret}),
            },
        },
        {
            "timestamp": "2026-07-25T00:00:05Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "apply_patch",
                "call_id": "call-4",
                "input": {"patch": local_path, "credential": secret},
            },
        },
        {
            "timestamp": "2026-07-25T00:00:05.100Z",
            "type": "event_msg",
            "payload": {
                "type": "patch_apply_end",
                "call_id": "call-4",
                "success": False,
                "status": "failed",
                "changes": {local_path: {"type": "update"}},
            },
        },
        {
            "timestamp": "2026-07-25T00:00:05.200Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "call-4",
                "output": [{"type": "text", "text": secret}],
            },
        },
        {
            "timestamp": "2026-07-25T00:00:06Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "process_control",
                "call_id": "call-5",
                "arguments": json.dumps({"path": local_path}),
            },
        },
        {
            "timestamp": "2026-07-25T00:00:06.100Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call-5",
                "output": json.dumps(
                    {"terminated": True, "returncode": 0, "message": secret}
                ),
            },
        },
        {
            "timestamp": "2026-07-25T00:00:07Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "call-6",
                "input": f"await tools.shell_command({local_path!r}, {secret!r})",
            },
        },
        {
            "timestamp": "2026-07-25T00:00:07.100Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "call-6",
                "output": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "exit_code": 9,
                                "timed_out": True,
                                "path": local_path,
                                "secret": secret,
                            }
                        ),
                    }
                ],
            },
        },
        {
            "timestamp": "2026-07-25T00:00:08Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": secret}],
            },
        },
        {
            "timestamp": "2026-07-25T00:00:09Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 120,
                        "cached_input_tokens": 60,
                        "output_tokens": 30,
                        "reasoning_output_tokens": 10,
                        "total_tokens": 150,
                    }
                },
            },
        },
        {
            "timestamp": "2026-07-25T00:00:10Z",
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": "turn-1",
                "duration_ms": 2500,
            },
        },
        {
            "timestamp": "2026-07-25T00:01:00Z",
            "type": "turn_context",
            "payload": {"turn_id": "turn-2"},
        },
        {
            "timestamp": "2026-07-25T00:01:01Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
            },
        },
        {
            "timestamp": "2026-07-25T00:01:02Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 1000,
                        "cached_input_tokens": 900,
                        "output_tokens": 100,
                        "reasoning_output_tokens": 80,
                        "total_tokens": 1100,
                    }
                },
            },
        },
        {
            "timestamp": "2026-07-25T00:01:03Z",
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": "turn-2",
                "duration_ms": 1000,
            },
        },
        {
            "timestamp": "2026-07-25T00:01:10Z",
            "type": "turn_context",
            "payload": {"turn_id": "turn-2"},
        },
        {
            "timestamp": "2026-07-25T00:01:11Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "active_tail_tool",
                "call_id": "active-tail-call",
                "arguments": "{}",
            },
        },
        {
            "timestamp": "2026-07-25T00:01:12Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 8000,
                        "cached_input_tokens": 0,
                        "output_tokens": 800,
                        "reasoning_output_tokens": 80,
                        "total_tokens": 8800,
                    }
                },
            },
        },
        {
            "timestamp": "2026-07-25T00:02:00Z",
            "type": "turn_context",
            "payload": {"turn_id": "incomplete-turn"},
        },
        {
            "timestamp": "2026-07-25T00:02:01Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 9000,
                        "cached_input_tokens": 0,
                        "output_tokens": 900,
                        "reasoning_output_tokens": 90,
                        "total_tokens": 9900,
                    }
                },
            },
        },
    ]
    session.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )
    pricing.write_text(
        json.dumps(
            {
                "schema": "ceratops-model-call-pricing-profile.v1",
                "input_per_million_tokens": 2,
                "cached_input_per_million_tokens": 0.5,
                "output_per_million_tokens": 8,
                "mode_multiplier": 1.5,
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--session",
            str(session),
            "--summary",
            "--evidence-output",
            str(evidence),
            "--pricing-profile",
            str(pricing),
            "--top",
            "1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    summary_text = completed.stdout
    evidence_text = evidence.read_text(encoding="utf-8")
    for sensitive in (secret, local_path, str(session), str(evidence)):
        assert sensitive not in summary_text
        assert sensitive not in evidence_text
    summary = json.loads(summary_text)
    assert summary["schema"] == "ceratops-model-call-usage-summary.v1"
    assert summary["evidence_schema"] == "ceratops-model-call-usage-evidence.v1"
    assert summary["top_n"] == 1
    assert summary["totals"] == {
        "model_calls": 3,
        "input_tokens": 1220,
        "cached_input_tokens": 1000,
        "uncached_input_tokens": 220,
        "output_tokens": 150,
        "reasoning_output_tokens": 95,
        "total_tokens": 1370,
        "input_of_total_pct": 89.05,
        "cache_rate_pct": 81.97,
        "output_of_total_pct": 10.95,
        "reasoning_of_output_pct": 63.33,
        "duration_ms": 3500,
        "waits": 1,
        "actions": 8,
        "tool_actions": 6,
        "distinct_calls": 5,
        "repeated_calls": 1,
        "retries": 1,
        "explicit_failures": 5,
        "structured_tool_errors": 2,
        "nonzero_process_results": 3,
        "timeouts": 3,
        "terminations": 1,
        "estimated_credit_cost": 0.00321,
    }
    expected_rankings = {
        "total_tokens": "turn-2",
        "uncached_input_tokens": "turn-1",
        "output_tokens": "turn-2",
        "reasoning_output_tokens": "turn-2",
        "model_calls": "turn-1",
        "explicit_failures": "turn-1",
        "retries": "turn-1",
        "duration_ms": "turn-1",
        "estimated_credit_cost": "turn-2",
    }
    assert {
        metric: ranked[0]["turn_id"]
        for metric, ranked in summary["rankings"].items()
    } == expected_rankings
    assert all(len(ranked) == 1 for ranked in summary["rankings"].values())
    assert summary["telemetry"]["functions_exec"] == {
        "outer_actions": 1,
        "child_calls": "not_enumerated",
        "outer_actions_with_emitted_process_results": 1,
    }
    assert "functions_exec_child_calls_not_enumerated" in summary["telemetry"][
        "limitations"
    ]

    detailed = json.loads(evidence_text)
    assert detailed["schema"] == "ceratops-model-call-usage-evidence.v1"
    assert "active_tail_tool" not in evidence_text
    assert [run["turn_id"] for run in detailed["runs"]] == ["turn-1", "turn-2"]
    first = detailed["runs"][0]
    assert first["totals"]["estimated_credit_cost"] == 0.001035
    assert first["tool_action_results"][1]["retry"] is True
    assert first["tool_action_results"][1]["explicit_failure"] is False
    assert first["tool_action_results"][0]["argument_chars"] == len(
        repeated_arguments
    )
    assert first["tool_action_results"][0]["result_chars"] > 0
    assert first["tool_action_results"][0]["result_chars"] > first[
        "tool_action_results"
    ][1]["result_chars"]
    assert first["tool_action_results"][1]["outcomes"][
        "nonzero_process_result"
    ] is True
    assert first["tool_action_results"][0]["process_exit_codes"] == [7]
    assert first["tool_action_results"][1]["process_exit_codes"] == [3]
    assert first["tool_action_results"][-1]["name"] == "exec"
    assert first["tool_action_results"][-1]["result_telemetry"] == "structured"
    assert first["tool_action_results"][-1]["process_exit_codes"] == [9]
    assert detailed["telemetry"]["structured_process_result_actions"] == 4
    assert detailed["telemetry"][
        "nonzero_process_results_are_semantic_failures"
    ] is False

    unpriced = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--session",
            str(session),
            "--summary",
            "--evidence-output",
            str(unpriced_evidence),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert unpriced.returncode == 0, unpriced.stderr
    unpriced_summary = json.loads(unpriced.stdout)
    assert unpriced_summary["pricing"] == {"provided": False}
    assert unpriced_summary["totals"]["estimated_credit_cost"] is None
    assert unpriced_summary["rankings"]["estimated_credit_cost"] == []
    assert "pricing_profile_not_provided" in unpriced_summary["telemetry"][
        "limitations"
    ]

    invalid = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--session",
            str(session),
            "--summary",
            "--evidence-output",
            str(tmp_path / "invalid.json"),
            "--include-run",
            "turn-1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalid.returncode == 2
    assert "--summary does not accept --include-run" in invalid.stderr
    assert not (tmp_path / "invalid.json").exists()

    invalid_pricing = tmp_path / "invalid-pricing.json"
    invalid_pricing.write_text(
        pricing.read_text(encoding="utf-8").replace(
            "ceratops-model-call-pricing-profile.v1",
            "ceratops-model-call-pricing-profile.v0",
        ),
        encoding="utf-8",
        newline="\n",
    )
    rejected_pricing = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--session",
            str(session),
            "--summary",
            "--evidence-output",
            str(tmp_path / "rejected-pricing-evidence.json"),
            "--pricing-profile",
            str(invalid_pricing),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected_pricing.returncode == 2
    assert "pricing profile schema must be" in rejected_pricing.stderr
    assert not (tmp_path / "rejected-pricing-evidence.json").exists()


def test_model_call_ledger_closure_mode_is_artifact_free(
    tmp_path: pathlib.Path,
) -> None:
    thread_id = "019f9b47-678b-7e93-9fb7-acefa2453eeb"
    codex_home = tmp_path / "codex-home"
    session = (
        codex_home
        / "sessions"
        / "2026"
        / "07"
        / "26"
        / f"rollout-2026-07-26T00-56-15-{thread_id}.jsonl"
    )
    session.parent.mkdir(parents=True)
    command_secret = "command-secret"
    custom_secret = "custom-secret"
    message_secret = "message-secret"
    private_tool = pathlib.Path.home() / "private" / "tool.py"
    search_secret = "search-secret"
    rows = [
        {
            "timestamp": "2026-07-25T00:00:00Z",
            "type": "turn_context",
            "payload": {"turn_id": "turn-1"},
        },
        {
            "timestamp": "2026-07-25T00:00:00.500Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "commentary",
                "content": [
                    {
                        "type": "output_text",
                        "text": (
                            f"Inspect {private_tool} token={message_secret}"
                        ),
                    }
                ],
            },
        },
        {
            "timestamp": "2026-07-25T00:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "shell_command",
                "arguments": json.dumps(
                    {
                        "credential": "sentinel-secret",
                        "command": (
                            f'python "{private_tool}" --token {command_secret}'
                        ),
                        "note": "x" * 500,
                    }
                ),
            },
        },
        {
            "timestamp": "2026-07-25T00:00:01.250Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "custom_tool",
                "input": {"password": custom_secret},
            },
        },
        {
            "timestamp": "2026-07-25T00:00:01.500Z",
            "type": "response_item",
            "payload": {
                "type": "tool_search_call",
                "arguments": {"q": "topic", "apiKey": search_secret},
            },
        },
        {
            "timestamp": "2026-07-25T00:00:02Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 10,
                        "output_tokens": 1,
                        "total_tokens": 11,
                    }
                },
            },
        },
        {
            "timestamp": "2026-07-25T00:00:03Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
            },
        },
        {
            "timestamp": "2026-07-25T00:00:04Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 20,
                        "output_tokens": 2,
                        "total_tokens": 22,
                    }
                },
            },
        },
        {
            "timestamp": "2026-07-25T00:00:05Z",
            "type": "turn_context",
            "payload": {"turn_id": "turn-2"},
        },
        {
            "timestamp": "2026-07-25T00:00:06Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
            },
        },
        {
            "timestamp": "2026-07-25T00:00:07Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 25,
                        "output_tokens": 2,
                        "total_tokens": 27,
                    }
                },
            },
        },
        {
            "timestamp": "2026-07-25T00:00:08Z",
            "type": "turn_context",
            "payload": {"turn_id": "incomplete-turn"},
        },
        {
            "timestamp": "2026-07-25T00:00:09Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 30,
                        "output_tokens": 3,
                        "total_tokens": 33,
                    }
                },
            },
        },
    ]
    session.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )
    before = sorted(path.relative_to(codex_home) for path in codex_home.rglob("*"))
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)

    closure = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--closure",
            "--thread-id",
            thread_id,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert closure.returncode == 0, closure.stderr
    assert "sentinel-secret" not in closure.stdout
    for secret in (
        command_secret,
        custom_secret,
        message_secret,
        search_secret,
    ):
        assert secret not in closure.stdout
    summary = json.loads(closure.stdout)
    assert summary["schema"] == "ceratops-model-call-ledger-closure.v1"
    assert summary["totals"]["runs"] == 2
    assert summary["totals"]["model_calls"] == 3
    assert [run["turn_id"] for run in summary["runs"]] == ["turn-1", "turn-2"]
    assert [call["index"] for call in summary["runs"][0]["calls"]] == [1, 2]
    assert "tokens" not in summary["runs"][0]["calls"][0]
    assert "selected_runs" not in summary

    usage_evidence = tmp_path / "thread-usage.json"
    usage = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--summary",
            "--thread-id",
            thread_id,
            "--evidence-output",
            str(usage_evidence),
            "--top",
            "1",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert usage.returncode == 0, usage.stderr
    usage_summary = json.loads(usage.stdout)
    assert usage_summary["schema"] == "ceratops-model-call-usage-summary.v1"
    assert usage_summary["window"]["completed_runs"] == 2
    assert json.loads(usage_evidence.read_text(encoding="utf-8"))["schema"] == (
        "ceratops-model-call-usage-evidence.v1"
    )

    thread_ledger = tmp_path / "thread-ledger.json"
    thread_semantic_evidence = tmp_path / "thread-semantic.json"
    thread_semantic = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--thread-id",
            thread_id,
            "--evidence-output",
            str(thread_ledger),
            "--semantic-evidence-output",
            str(thread_semantic_evidence),
            "--include-run",
            "turn-1",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert thread_semantic.returncode == 0, thread_semantic.stderr
    thread_semantic_summary = json.loads(thread_semantic.stdout)
    assert thread_semantic_summary["selected_runs"] == [
        {"turn_id": "turn-1", "model_calls": 2}
    ]
    assert pathlib.Path(
        json.loads(thread_ledger.read_text(encoding="utf-8"))["session"]
    ) == session.resolve()
    assert json.loads(
        thread_semantic_evidence.read_text(encoding="utf-8")
    )["selected_runs"][0]["turn_id"] == "turn-1"

    semantic = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--closure",
            "--session",
            str(session),
            "--include-run",
            "turn-1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert semantic.returncode == 0, semantic.stderr
    assert "sentinel-secret" not in semantic.stdout
    for secret in (
        command_secret,
        custom_secret,
        message_secret,
        search_secret,
    ):
        assert secret not in semantic.stdout
    semantic_summary = json.loads(semantic.stdout)
    selected_run = semantic_summary["selected_runs"][0]
    assert selected_run["turn_id"] == "turn-1"
    selected_actions = selected_run["calls"][0]["actions"]
    assert [action["name"] for action in selected_actions] == [
        "commentary",
        "shell_command",
        "custom_tool",
        "tool_search",
    ]
    assert all("<redacted>" in action["summary"] for action in selected_actions)
    selected_action = selected_actions[1]
    assert selected_action["kind"] == "tool"
    assert selected_action["name"] == "shell_command"
    assert "<redacted>" in selected_action["summary"]
    assert "<user-home>" in selected_action["summary"]
    assert str(pathlib.Path.home()) not in selected_action["summary"]
    assert len(selected_action["summary"]) == 240
    assert selected_action["summary"].endswith("...")

    bounded = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--closure",
            "--session",
            str(session),
            "--last-runs",
            "1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert bounded.returncode == 0, bounded.stderr
    bounded_summary = json.loads(bounded.stdout)
    assert bounded_summary["window"] == {
        "mode": "last_runs",
        "requested_runs": 1,
        "completed_runs": 1,
    }
    assert bounded_summary["totals"]["model_calls"] == 1
    assert [run["turn_id"] for run in bounded_summary["runs"]] == ["turn-2"]

    after = sorted(path.relative_to(codex_home) for path in codex_home.rglob("*"))
    assert after == before

    invalid_cases = [
        (
            ["--include-run", "missing-turn"],
            "requested run is outside the completed window: missing-turn",
        ),
        (
            [
                "--classifications",
                str(tmp_path / "unused-classifications.json"),
                "--include-run",
                "turn-1",
            ],
            "--classifications validates every completed run",
        ),
        (
            ["--evidence-output", str(tmp_path / "unexpected.json")],
            "--closure does not accept --evidence-output",
        ),
    ]
    for extra_arguments, expected_error in invalid_cases:
        invalid = subprocess.run(
            [
                sys.executable,
                str(MODEL_CALL_LEDGER),
                "--closure",
                "--session",
                str(session),
                *extra_arguments,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert invalid.returncode == 2
        assert expected_error in invalid.stderr
    assert not (tmp_path / "unexpected.json").exists()

    archived_session = (
        codex_home
        / "archived_sessions"
        / f"rollout-2026-07-26T00-56-15-{thread_id}.jsonl"
    )
    archived_session.parent.mkdir()
    shutil.copy2(session, archived_session)
    ambiguous = subprocess.run(
        [
            sys.executable,
            str(MODEL_CALL_LEDGER),
            "--closure",
            "--thread-id",
            thread_id,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert ambiguous.returncode == 2
    assert "multiple sessions found for thread ID" in ambiguous.stderr


def run_git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one isolated test-repository Git command."""

    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def prepare_fast_change_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create one clean release checkout with a logging runtime installer."""

    repo = tmp_path / "skills-repo"
    repo.mkdir()
    assert run_git(repo, "init", "-b", "release/local").returncode == 0
    assert run_git(repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(repo, "config", "user.name", "Test Agent").returncode == 0
    for skill_name in ("alpha-tool", "beta-tool"):
        skill_root = repo / "skills" / skill_name
        (skill_root / "references").mkdir(parents=True)
        (skill_root / "scripts").mkdir()
        (skill_root / "SKILL.md").write_text(
            f"---\nname: {skill_name}\ndescription: Test skill.\n---\n",
            encoding="utf-8",
            newline="\n",
        )
        (skill_root / "references" / "change.md").write_text(
            "# Change\n",
            encoding="utf-8",
            newline="\n",
        )
        (skill_root / "notes.txt").write_text(
            "Notes\n",
            encoding="utf-8",
            newline="\n",
        )
        (skill_root / "scripts" / "tool.py").write_text(
            "VALUE = 1\n",
            encoding="utf-8",
            newline="\n",
        )
    runtime = (
        repo
        / "skills"
        / "ceratops-skill-lifecycle"
        / "scripts"
        / "runtime"
    )
    runtime.mkdir(parents=True)
    (runtime / "install-managed-skills.py").write_text(
        "import os, pathlib, sys\n"
        "log = pathlib.Path(__file__).resolve().parents[5] / 'install.log'\n"
        "with log.open('a', encoding='utf-8') as stream:\n"
        "    stream.write(' '.join(sys.argv[1:]) + '\\n')\n"
        "raise SystemExit(1 if os.environ.get('FAST_INSTALL_FAIL') else 0)\n",
        encoding="utf-8",
        newline="\n",
    )
    (repo / ".gitignore").write_text(
        "__pycache__/\n.pytest_cache/\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(repo, "add", ".").returncode == 0
    assert run_git(repo, "commit", "-m", "base").returncode == 0
    return repo


def enable_test_markdown_lint(repo: pathlib.Path) -> pathlib.Path:
    """Declare one observable repository Markdown check in an isolated repo."""

    log = repo.parent / "markdown-lint.log"
    (repo / "package.json").write_text(
        json.dumps(
            {
                "private": True,
                "scripts": {"lint:markdown": "python markdown-lint.py"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (repo / "markdown-lint.py").write_text(
        "import pathlib\n"
        "root = pathlib.Path(__file__).resolve().parent\n"
        "log = root.parent / 'markdown-lint.log'\n"
        "with log.open('a', encoding='utf-8') as stream:\n"
        "    stream.write('run\\n')\n"
        "for path in (root / 'skills').rglob('*.md'):\n"
        "    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):\n"
        "        if len(line) > 80:\n"
        "            print(f'{path}:{number}: line too long')\n"
        "            raise SystemExit(1)\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(repo, "add", "package.json", "markdown-lint.py").returncode == 0
    assert run_git(repo, "commit", "-m", "add markdown lint").returncode == 0
    return log


def fast_change_edits(
    replacements: dict[str, tuple[str, str]],
) -> list[dict[str, object]]:
    """Create one version-2 structured edit list from exact replacements."""

    return [
        {
            "path": path,
            "replacements": [{"old": old, "new": new}],
        }
        for path, (old, new) in replacements.items()
    ]


def run_fast_change(
    repo: pathlib.Path,
    request: dict[str, object],
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Write and run one fast-change request outside the target repository."""

    request_path = repo.parent / f"request-{time.time_ns()}.json"
    request_path.write_text(
        json.dumps(request),
        encoding="utf-8",
        newline="\n",
    )
    return subprocess.run(
        [sys.executable, str(FAST_CHANGE), "--request", str(request_path)],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def fast_change_request(
    repo: pathlib.Path,
    edits: list[dict[str, object]],
    *,
    selected: list[str],
    classification: str = "rules-only",
    tests: list[str] | None = None,
) -> dict[str, object]:
    """Return one complete versioned fast-change request."""

    return {
        "version": 2,
        "repo_root": str(repo),
        "release_branch": "release/local",
        "edits": edits,
        "selected_skills": selected,
        "removed_skills": [],
        "classification": classification,
        "tests": tests or [],
        "commit_message": "Apply exact fast change",
    }


def prepare_skill_update_workflow_worktree(
    tmp_path: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """Create one linked task worktree with an existing helper behavior test."""

    scope = tmp_path / "skill-update-workflow"
    scope.mkdir()
    source = prepare_fast_change_repo(scope)
    tests = source / "tests"
    tests.mkdir()
    (tests / "test_helper.py").write_text(
        "import pathlib\n\n"
        "def test_helper_value():\n"
        "    root = pathlib.Path(__file__).resolve().parents[1]\n"
        "    namespace = {}\n"
        "    source = root / 'skills' / 'alpha-tool' / 'scripts' / 'tool.py'\n"
        "    exec(source.read_text(encoding='utf-8'), namespace)\n"
        "    assert namespace['VALUE'] == 2\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(source, "add", "tests/test_helper.py").returncode == 0
    assert run_git(source, "commit", "-m", "add helper behavior test").returncode == 0
    worktree = scope / "task-worktree"
    added = run_git(
        source,
        "worktree",
        "add",
        "-b",
        "codex/skill-update-workflow-test",
        str(worktree),
        "HEAD",
    )
    assert added.returncode == 0, added.stderr
    task_temp_root = scope / "tmp" / source.name / "skill-update-workflow"
    task_temp_root.mkdir(parents=True)
    return worktree, scope, task_temp_root


def run_skill_update_workflow(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run one skill-update workflow command with compact captured output."""

    return subprocess.run(
        [sys.executable, str(SKILL_UPDATE_WORKFLOW), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


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
        "path = pathlib.Path(__file__).with_name('check.log')\n"
        "prior = path.read_text(encoding='utf-8') if path.exists() else ''\n"
        "path.write_text(prior + 'run\\n', encoding='utf-8')\n",
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
    assert check_log.read_text(encoding="utf-8").splitlines() == ["run"]
    assert baseline.read_text(encoding="utf-8") == "keep me\n"

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


def test_proposal_workflow_validates_context_and_owns_iteration_transition(
    tmp_path: pathlib.Path,
) -> None:
    task_temp_root = tmp_path / "task-temp"
    task_temp_root.mkdir()
    original = task_temp_root / "original.md"
    regressions = task_temp_root / "regressions.md"
    target_dir = tmp_path / "governed"
    target_dir.mkdir()
    target = target_dir / "contract.md"
    request_path = task_temp_root / "proposal-request.json"
    state = task_temp_root / "proposal-state.json"
    evidence = task_temp_root / "proposal-context.json"
    iterations = task_temp_root / "iterations"
    undeclared_input = task_temp_root / "user-owned.md"
    original.write_text("Observed failure\n", encoding="utf-8", newline="\n")
    regressions.write_text("Preserve current scope\n", encoding="utf-8", newline="\n")
    undeclared_input.write_text("Preserve me\n", encoding="utf-8", newline="\n")
    target.write_text(
        "# Contract\n\nCurrent exact target.\n",
        encoding="utf-8",
        newline="\n",
    )
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
    }
    target_source: dict[str, object] = {
        "rules": str(target),
        "history": None,
        "rule_ids": [],
        "expected_text": ["Current exact target."],
    }
    request: dict[str, object] = {
        "schema": "ceratops-governance-proposal-request.v2",
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
        "max_iterations": 1,
        "mutation_authorized": False,
        "expected_side_effects": [
            "write context evidence",
            "write controller artifacts",
        ],
        "sources": [history_source, target_source],
    }
    request_path.write_text(
        json.dumps(request) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    prepared = subprocess.run(
        [
            sys.executable,
            str(PROPOSAL_WORKFLOW),
            "prepare",
            "--request",
            str(request_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert prepared.returncode == 0, prepared.stderr
    pending = json.loads(prepared.stdout)
    assert pending["iteration"] == 1
    context = json.loads(evidence.read_text(encoding="utf-8"))
    assert context["schema"] == "ceratops-governance-proposal-context.v2"
    assert context["history_lookup"]["unknown"] == []
    assert context["sources"][1]["history"] is None
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
    pathlib.Path(pending["candidate"]).write_text(
        "Exact candidate\n",
        encoding="utf-8",
        newline="\n",
    )
    pathlib.Path(pending["assessment"]).write_text(
        "Regression assessment\n",
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
    assert not state.exists()
    assert not iterations.exists()
    assert not request_path.exists()
    assert not original.exists() and not regressions.exists() and not evidence.exists()
    assert undeclared_input.is_file() and outside_evidence.is_file()

    invalid_request = dict(request)
    invalid_run = task_temp_root / "invalid-run"
    invalid_run.mkdir()
    invalid_original = invalid_run / "original.md"
    invalid_regressions = invalid_run / "regressions.md"
    invalid_original.write_text("Failure\n", encoding="utf-8", newline="\n")
    invalid_regressions.write_text("Boundary\n", encoding="utf-8", newline="\n")
    invalid_state = invalid_run / "state.json"
    invalid_evidence = invalid_run / "context.json"
    invalid_iterations = invalid_run / "iterations"
    invalid_request["state"] = str(invalid_state)
    invalid_request["original"] = str(invalid_original)
    invalid_request["regressions"] = str(invalid_regressions)
    invalid_request["evidence_output"] = str(invalid_evidence)
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


def test_iteration_controller_preserves_legacy_commands(
    tmp_path: pathlib.Path,
) -> None:
    original = tmp_path / "legacy-original.md"
    state = tmp_path / "legacy-state.json"
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
    pathlib.Path(pending["candidate"]).write_text(
        "Candidate\n", encoding="utf-8", newline="\n"
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
    assert original.is_file() and not state.exists()


def test_fast_change_commits_cohesive_rules_only_multi_skill_scope(
    tmp_path: pathlib.Path,
) -> None:
    repo = prepare_fast_change_repo(tmp_path)
    lint_log = enable_test_markdown_lint(repo)
    paths = {
        "skills/alpha-tool/SKILL.md": ("description: Test", "description: Updated"),
        "skills/alpha-tool/references/change.md": ("# Change", "# Updated"),
        "skills/beta-tool/SKILL.md": ("description: Test", "description: Updated"),
    }
    edits = fast_change_edits(paths)
    edits[0]["replacements"] = [
        {"old": "description: Test", "new": "description: Intermediate"},
        {"old": "description: Intermediate", "new": "description: Updated"},
    ]
    result = run_fast_change(
        repo,
        fast_change_request(
            repo,
            edits,
            selected=["alpha-tool", "beta-tool"],
        ),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "committed"
    assert payload["skills"] == ["alpha-tool", "beta-tool"]
    assert run_git(repo, "status", "--porcelain").stdout == ""
    committed = set(
        run_git(repo, "show", "--pretty=", "--name-only", "HEAD").stdout.splitlines()
    )
    assert committed == set(paths)
    installs = (repo.parent / "install.log").read_text(encoding="utf-8").splitlines()
    assert len(installs) == 1
    assert installs[0].count("--skill") == 2
    assert lint_log.read_text(encoding="utf-8").splitlines() == ["run"]

    plain_text = run_fast_change(
        repo,
        fast_change_request(
            repo,
            fast_change_edits(
                {"skills/alpha-tool/notes.txt": ("Notes\n", "Updated notes")},
            ),
            selected=["alpha-tool"],
        ),
    )
    assert plain_text.returncode == 0, plain_text.stderr
    assert (repo / "skills" / "alpha-tool" / "notes.txt").read_bytes() == b"Updated notes"
    assert lint_log.read_text(encoding="utf-8").splitlines() == ["run"]

    head_before_failure = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    too_long = "description: " + ("x" * 90)
    failed_lint = run_fast_change(
        repo,
        fast_change_request(
            repo,
            fast_change_edits(
                {
                    "skills/alpha-tool/SKILL.md": (
                        "description: Updated skill.",
                        too_long,
                    )
                },
            ),
            selected=["alpha-tool"],
        ),
    )
    assert failed_lint.returncode == 1
    assert run_git(repo, "rev-parse", "HEAD").stdout.strip() == head_before_failure
    assert "description: Updated skill." in (
        repo / "skills" / "alpha-tool" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert run_git(repo, "status", "--porcelain").stdout == ""
    installs = (repo.parent / "install.log").read_text(encoding="utf-8").splitlines()
    assert len(installs) == 2
    assert lint_log.read_text(encoding="utf-8").splitlines() == ["run", "run"]
    detail = json.loads(failed_lint.stderr)["detail"]
    assert detail["phase"] == "markdown_lint"
    assert detail["compensation"] == ["source_restored"]


def test_fast_change_helper_tests_and_compensates_failures(
    tmp_path: pathlib.Path,
) -> None:
    repo = prepare_fast_change_repo(tmp_path)
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_helper.py"
    test_file.write_text(
        "import pathlib\n\n"
        "def test_value():\n"
        "    assert pathlib.Path('skills/alpha-tool/scripts/tool.py')"
        ".read_text(encoding='utf-8') == 'VALUE = 2\\n'\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(repo, "add", "tests/test_helper.py").returncode == 0
    assert run_git(repo, "commit", "-m", "add helper test").returncode == 0
    edits = fast_change_edits(
        {"skills/alpha-tool/scripts/tool.py": ("VALUE = 1", "VALUE = 2")},
    )
    request = fast_change_request(
        repo,
        edits,
        selected=["alpha-tool"],
        classification="helper",
        tests=["tests/test_helper.py::test_value"],
    )

    success = run_fast_change(repo, request)
    assert success.returncode == 0, success.stderr
    assert "VALUE = 2" in (
        repo / "skills" / "alpha-tool" / "scripts" / "tool.py"
    ).read_text(encoding="utf-8")

    failing_edits = fast_change_edits(
        {"skills/alpha-tool/scripts/tool.py": ("VALUE = 2", "VALUE = 3")},
    )
    failing_request = fast_change_request(
        repo,
        failing_edits,
        selected=["alpha-tool"],
        classification="helper",
        tests=["tests/test_helper.py::test_value"],
    )
    failed_test = run_fast_change(repo, failing_request)
    assert failed_test.returncode == 1, failed_test.stderr
    assert "VALUE = 2" in (
        repo / "skills" / "alpha-tool" / "scripts" / "tool.py"
    ).read_text(encoding="utf-8")
    assert run_git(repo, "status", "--porcelain").stdout == ""

    install_failure = run_fast_change(
        repo,
        fast_change_request(
            repo,
            fast_change_edits(
                {"skills/alpha-tool/SKILL.md": ("description: Test", "description: Failed")},
            ),
            selected=["alpha-tool"],
        ),
        environment={**os.environ, "FAST_INSTALL_FAIL": "1"},
    )
    assert install_failure.returncode == 1
    assert "description: Test" in (
        repo / "skills" / "alpha-tool" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert run_git(repo, "status", "--porcelain").stdout == ""


def test_fast_change_commit_failure_restores_source_and_runtime(
    tmp_path: pathlib.Path,
) -> None:
    repo = prepare_fast_change_repo(tmp_path)
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8", newline="\n")
    hook.chmod(0o755)
    original_head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    request = fast_change_request(
        repo,
        fast_change_edits(
            {"skills/alpha-tool/SKILL.md": ("description: Test", "description: Updated")},
        ),
        selected=["alpha-tool"],
    )

    result = run_fast_change(repo, request)

    assert result.returncode == 1
    assert run_git(repo, "rev-parse", "HEAD").stdout.strip() == original_head
    assert "description: Test" in (
        repo / "skills" / "alpha-tool" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert run_git(repo, "status", "--porcelain").stdout == ""
    installs = (repo.parent / "install.log").read_text(encoding="utf-8").splitlines()
    assert len(installs) == 2
    detail = json.loads(result.stderr)["detail"]
    assert detail["compensation"] == ["source_restored", "runtime_restored"]


def test_fast_change_rejects_complete_ineligible_or_dirty_scope_before_mutation(
    tmp_path: pathlib.Path,
) -> None:
    repo = prepare_fast_change_repo(tmp_path)
    edits = fast_change_edits(
        {"skills/alpha-tool/SKILL.md": ("description: Test", "description: Updated")},
    )
    noncanonical_request = fast_change_request(
        repo,
        edits,
        selected=["alpha-tool"],
    )
    noncanonical_request["release_branch"] = "release/task"

    noncanonical = run_fast_change(repo, noncanonical_request)

    assert noncanonical.returncode == 2
    assert json.loads(noncanonical.stderr)["reason"] == (
        "release_branch must be release/local"
    )
    assert run_git(repo, "status", "--porcelain").stdout == ""
    assert not (repo.parent / "install.log").exists()

    request = fast_change_request(repo, edits, selected=["beta-tool"])

    mismatch = run_fast_change(repo, request)

    assert mismatch.returncode == 2
    payload = json.loads(mismatch.stderr)
    assert payload["status"] == "decision_required"
    assert payload["route"] == "update"
    assert payload["affected_files"] == ["skills/alpha-tool/SKILL.md"]
    assert payload["affected_skills"] == ["beta-tool"]
    assert pathlib.Path(payload["change_specification"]).is_file()
    assert run_git(repo, "status", "--porcelain").stdout == ""
    assert not (repo.parent / "install.log").exists()

    raw_request = fast_change_request(repo, edits, selected=["alpha-tool"])
    raw_request["version"] = 1
    raw_request["patch"] = "@@ malformed caller hunk"
    del raw_request["edits"]
    raw = run_fast_change(repo, raw_request)

    assert raw.returncode == 2
    assert json.loads(raw.stderr)["reason"] == (
        "request fields are invalid: missing edits; unknown patch"
    )
    assert run_git(repo, "status", "--porcelain").stdout == ""

    ambiguous = run_fast_change(
        repo,
        fast_change_request(
            repo,
            [
                {
                    "path": "skills/alpha-tool/SKILL.md",
                    "replacements": [{"old": "---", "new": "***"}],
                }
            ],
            selected=["alpha-tool"],
        ),
    )

    assert ambiguous.returncode == 2
    assert "must occur exactly once" in json.loads(ambiguous.stderr)["reason"]
    assert "found 2" in json.loads(ambiguous.stderr)["reason"]
    assert run_git(repo, "status", "--porcelain").stdout == ""

    missing = run_fast_change(
        repo,
        fast_change_request(
            repo,
            [
                {
                    "path": "skills/alpha-tool/SKILL.md",
                    "replacements": [
                        {"old": "not present", "new": "replacement"}
                    ],
                }
            ],
            selected=["alpha-tool"],
        ),
    )

    assert missing.returncode == 2
    assert "found 0" in json.loads(missing.stderr)["reason"]
    assert run_git(repo, "status", "--porcelain").stdout == ""

    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8", newline="\n")
    dirty = run_fast_change(
        repo,
        fast_change_request(repo, edits, selected=["alpha-tool"]),
    )
    assert dirty.returncode == 2
    assert "must be clean" in json.loads(dirty.stderr)["reason"]
    assert "description: Test" in (
        repo / "skills" / "alpha-tool" / "SKILL.md"
    ).read_text(encoding="utf-8")


def load_pr_workflow_module(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> Any:
    """Load one source workflow module without using the installed runtime."""

    monkeypatch.syspath_prepend(str(PR_WORKFLOW_SCRIPTS))
    return importlib.import_module(f"github_pr_workflow.{name}")


def merge_args(
    repo_root: pathlib.Path,
    *,
    admin: bool,
    auto: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        pr="24",
        repo_root=repo_root,
        repo="example/repository",
        merge_method="merge",
        admin=admin,
        auto=auto,
        delete_branch=False,
    )


def merged_pr_state(head: str) -> str:
    return json.dumps(
        {
            "number": 24,
            "url": "https://example.invalid/pull/24",
            "state": "MERGED",
            "headRefOid": head,
            "mergedAt": "2026-08-01T00:00:00Z",
            "mergeCommit": {"oid": "c" * 40},
        }
    )


@pytest.mark.parametrize("enabled", [True, False])
def test_read_admin_enforcement_preserves_boolean_state(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    monkeypatch.setattr(
        merge,
        "require_output",
        lambda command, *, cwd: json.dumps({"enabled": enabled}),
    )

    assert merge._read_admin_enforcement("endpoint", cwd=tmp_path) is enabled


def test_private_free_plan_limit_skips_admin_protection_mutation(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    repo = tmp_path / "repo"
    repo.mkdir()
    head = "a" * 40
    commands: list[tuple[str, ...]] = []

    def require_output(command: list[str], *, cwd: pathlib.Path) -> str:
        commands.append(tuple(command))
        if command[:2] == ["gh", "api"]:
            raise merge.CommandError(
                "gh api failed\n"
                "Upgrade to GitHub Pro or make this repository public "
                "to enable this feature. (HTTP 403)"
            )
        if command[:3] == ["gh", "pr", "view"]:
            return merged_pr_state(head)
        raise AssertionError(command)

    def require_success(command: list[str], *, cwd: pathlib.Path) -> None:
        commands.append(tuple(command))
        if command[:3] != ["gh", "pr", "merge"]:
            raise AssertionError(command)

    monkeypatch.setattr(merge, "require_output", require_output)
    monkeypatch.setattr(merge, "require_success", require_success)

    result = merge.merge_verified_pr(
        merge_args(repo, admin=True),
        expected_head=head,
        readiness_summary={
            "base": "main",
            "head_oid": head,
            "review_required": True,
        },
        recover_checkpoints=False,
    )

    assert result["status"] == "merged"
    assert not any(
        command[:2] == ("gh", "api") and "--method" in command
        for command in commands
    )


def test_read_admin_enforcement_rejects_unrelated_forbidden_error(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")

    def require_output(command: list[str], *, cwd: pathlib.Path) -> str:
        raise merge.CommandError("Resource not accessible by integration (HTTP 403)")

    monkeypatch.setattr(merge, "require_output", require_output)

    with pytest.raises(merge.CommandError, match="Resource not accessible"):
        merge._read_admin_enforcement("endpoint", cwd=tmp_path)


@pytest.mark.parametrize("initial", [True, False])
@pytest.mark.parametrize("merge_fails", [False, True])
def test_admin_enforcement_restores_exact_state_on_every_exit(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    initial: bool,
    merge_fails: bool,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    repo = tmp_path / "repo"
    repo.mkdir()
    checkpoints = tmp_path / "checkpoints"
    head = "a" * 40
    state = {"enabled": initial}
    commands: list[tuple[str, ...]] = []

    def require_output(command: list[str], *, cwd: pathlib.Path) -> str:
        commands.append(tuple(command))
        if command[:2] == ["gh", "api"]:
            return json.dumps({"url": "https://api.invalid", **state})
        if command[:3] == ["gh", "pr", "view"]:
            return merged_pr_state(head)
        raise AssertionError(command)

    def require_success(command: list[str], *, cwd: pathlib.Path) -> None:
        commands.append(tuple(command))
        if command[:4] == ["gh", "api", "--method", "DELETE"]:
            state["enabled"] = False
            return
        if command[:4] == ["gh", "api", "--method", "POST"]:
            state["enabled"] = True
            return
        if command[:3] == ["gh", "pr", "merge"]:
            if merge_fails:
                raise merge.CommandError("merge failed")
            return
        raise AssertionError(command)

    monkeypatch.setattr(merge, "require_output", require_output)
    monkeypatch.setattr(merge, "require_success", require_success)
    monkeypatch.setattr(merge, "_checkpoint_directory", lambda _: checkpoints)
    summary = {
        "base": "main",
        "head_oid": head,
        "review_required": True,
    }

    if merge_fails:
        with pytest.raises(merge.CommandError, match="merge failed"):
            merge.merge_verified_pr(
                merge_args(repo, admin=True),
                expected_head=head,
                readiness_summary=summary,
                recover_checkpoints=False,
            )
    else:
        result = merge.merge_verified_pr(
            merge_args(repo, admin=True),
            expected_head=head,
            readiness_summary=summary,
            recover_checkpoints=False,
        )
        assert result["status"] == "merged"

    labels = []
    for command in commands:
        if command[:2] == ("gh", "api") and "--method" not in command:
            labels.append("read")
        elif command[:4] == ("gh", "api", "--method", "DELETE"):
            labels.append("disable")
        elif command[:4] == ("gh", "api", "--method", "POST"):
            labels.append("restore")
        elif command[:3] == ("gh", "pr", "merge"):
            labels.append("merge")
        elif command[:3] == ("gh", "pr", "view"):
            labels.append("view")
    expected = ["read"]
    if initial:
        expected.append("disable")
    expected.append("merge")
    if not merge_fails:
        expected.append("view")
    if initial:
        expected.append("restore")
    expected.append("read")
    assert labels == expected
    assert state["enabled"] is initial
    assert not list(checkpoints.glob("*.json"))
    protection_calls = [command for command in commands if command[:2] == ("gh", "api")]
    assert protection_calls
    assert all(command[-1].endswith("/protection/enforce_admins") for command in protection_calls)


@pytest.mark.parametrize(
    ("admin", "auto", "review_required"),
    [(False, False, False), (True, True, True)],
)
def test_non_admin_and_auto_merge_never_toggle_protection(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    admin: bool,
    auto: bool,
    review_required: bool,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    repo = tmp_path / "repo"
    repo.mkdir()
    head = "a" * 40
    commands: list[tuple[str, ...]] = []

    def require_success(command: list[str], *, cwd: pathlib.Path) -> None:
        commands.append(tuple(command))

    def require_output(command: list[str], *, cwd: pathlib.Path) -> str:
        commands.append(tuple(command))
        return merged_pr_state(head)

    monkeypatch.setattr(merge, "require_success", require_success)
    monkeypatch.setattr(merge, "require_output", require_output)
    merge.merge_verified_pr(
        merge_args(repo, admin=admin, auto=auto),
        expected_head=head,
        readiness_summary={
            "base": "main",
            "head_oid": head,
            "review_required": review_required,
        },
        recover_checkpoints=False,
    )

    assert not any(command[:2] == ("gh", "api") for command in commands)
    assert [command[:3] for command in commands] == [
        ("gh", "pr", "merge"),
        ("gh", "pr", "view"),
    ]


def test_disable_failure_prevents_merge_and_still_verifies_restore(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    repo = tmp_path / "repo"
    repo.mkdir()
    checkpoints = tmp_path / "checkpoints"
    head = "a" * 40
    state = {"enabled": True}
    commands: list[tuple[str, ...]] = []

    def require_output(command: list[str], *, cwd: pathlib.Path) -> str:
        commands.append(tuple(command))
        return json.dumps(state)

    def require_success(command: list[str], *, cwd: pathlib.Path) -> None:
        commands.append(tuple(command))
        if command[:4] == ["gh", "api", "--method", "DELETE"]:
            state["enabled"] = False
            raise merge.CommandError("disable failed")
        if command[:4] == ["gh", "api", "--method", "POST"]:
            state["enabled"] = True
            return
        raise AssertionError("merge must not be attempted after disable failure")

    monkeypatch.setattr(merge, "require_output", require_output)
    monkeypatch.setattr(merge, "require_success", require_success)
    monkeypatch.setattr(merge, "_checkpoint_directory", lambda _: checkpoints)

    with pytest.raises(merge.CommandError, match="disable failed"):
        merge.merge_verified_pr(
            merge_args(repo, admin=True),
            expected_head=head,
            readiness_summary={
                "base": "main",
                "head_oid": head,
                "review_required": True,
            },
            recover_checkpoints=False,
        )

    assert not any(command[:3] == ("gh", "pr", "merge") for command in commands)
    assert state["enabled"] is True
    assert not list(checkpoints.glob("*.json"))


def test_restore_failure_is_critical_and_retains_checkpoint(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    repo = tmp_path / "repo"
    repo.mkdir()
    checkpoints = tmp_path / "checkpoints"
    head = "a" * 40
    state = {"enabled": True}

    def require_output(command: list[str], *, cwd: pathlib.Path) -> str:
        if command[:2] == ["gh", "api"]:
            return json.dumps(state)
        return merged_pr_state(head)

    def require_success(command: list[str], *, cwd: pathlib.Path) -> None:
        if command[:4] == ["gh", "api", "--method", "DELETE"]:
            state["enabled"] = False
            return
        if command[:4] == ["gh", "api", "--method", "POST"]:
            raise merge.CommandError("restore failed")
        if command[:3] == ["gh", "pr", "merge"]:
            return
        raise AssertionError(command)

    monkeypatch.setattr(merge, "require_output", require_output)
    monkeypatch.setattr(merge, "require_success", require_success)
    monkeypatch.setattr(merge, "_checkpoint_directory", lambda _: checkpoints)

    with pytest.raises(merge.CriticalRestoreError) as raised:
        merge.merge_verified_pr(
            merge_args(repo, admin=True),
            expected_head=head,
            readiness_summary={
                "base": "main",
                "head_oid": head,
                "review_required": True,
            },
            recover_checkpoints=False,
        )

    payload = raised.value.payload
    assert payload["status"] == "critical"
    assert payload["repository"] == "example/repository"
    assert payload["base_branch"] == "main"
    assert payload["pr"] == "24"
    assert payload["head"] == head
    assert payload["merge_state"] == "MERGED"
    assert "--method POST" in payload["recovery"]
    retained = list(checkpoints.glob("*.json"))
    assert len(retained) == 1
    assert set(json.loads(retained[0].read_text(encoding="utf-8"))) == {
        "version",
        "repository",
        "base_branch",
        "pr",
        "expected_head",
        "enforce_admins",
    }


def test_interrupted_checkpoint_recovers_before_later_merge(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    repo = tmp_path / "repo"
    repo.mkdir()
    checkpoints = tmp_path / "checkpoints"
    head = "a" * 40
    checkpoint = merge._checkpoint_document(
        "example/repository", "release/main", "24", head
    )
    monkeypatch.setattr(merge, "_checkpoint_directory", lambda _: checkpoints)
    path = merge._checkpoint_path(repo, "example/repository", "release/main")
    merge._write_restore_checkpoint(path, checkpoint)
    state = {"enabled": False}
    commands: list[tuple[str, ...]] = []

    def require_output(command: list[str], *, cwd: pathlib.Path) -> str:
        commands.append(tuple(command))
        if command[:2] == ["gh", "api"]:
            return json.dumps(state)
        return merged_pr_state(head)

    def require_success(command: list[str], *, cwd: pathlib.Path) -> None:
        commands.append(tuple(command))
        if command[:4] == ["gh", "api", "--method", "POST"]:
            state["enabled"] = True

    monkeypatch.setattr(merge, "require_output", require_output)
    monkeypatch.setattr(merge, "require_success", require_success)

    merge.merge_verified_pr(
        merge_args(repo, admin=False),
        expected_head=head,
    )

    labels = [
        "api" if command[:2] == ("gh", "api") else command[2]
        for command in commands
    ]
    assert labels == ["api", "api", "api", "merge", "view"]
    assert "%2F" in commands[0][-1]
    assert state["enabled"] is True
    assert not path.exists()


def test_admin_restore_checkpoint_is_shared_across_worktrees(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    repo = tmp_path / "repo"
    linked = tmp_path / "linked"
    repo.mkdir()
    assert run_git(repo, "init", "-b", "main").returncode == 0
    assert run_git(repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(repo, "config", "user.name", "Test Agent").returncode == 0
    (repo / "README.md").write_text("base\n", encoding="utf-8", newline="\n")
    assert run_git(repo, "add", "README.md").returncode == 0
    assert run_git(repo, "commit", "-m", "base").returncode == 0
    assert run_git(repo, "branch", "linked").returncode == 0
    assert run_git(repo, "worktree", "add", str(linked), "linked").returncode == 0

    assert merge._checkpoint_directory(repo) == merge._checkpoint_directory(linked)


def test_admin_bypass_accepts_only_review_required_readiness(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    readiness = load_pr_workflow_module(monkeypatch, "readiness")
    head = "a" * 40
    summary = {"base": "main", "head_oid": head}
    review = readiness.Finding(
        "WARN",
        "pr.review_decision",
        "Required review.",
        actual="REVIEW_REQUIRED",
    )
    pending = readiness.Finding(
        "WARN",
        "pr.status_checks",
        "Pending checks.",
        actual=["CI"],
    )
    requested = readiness.Finding(
        "ERROR",
        "pr.review_decision",
        "Changes requested.",
        actual="CHANGES_REQUESTED",
    )

    monkeypatch.setattr(
        merge.readiness,
        "validate_readiness",
        lambda *args, **kwargs: (summary, [review]),
    )
    accepted = merge._validate_readiness(
        "24", tmp_path, allow_admin_review_bypass=True
    )
    assert accepted["review_required"] is True

    for blocker in (pending, requested):
        monkeypatch.setattr(
            merge.readiness,
            "validate_readiness",
            lambda *args, blocker=blocker, **kwargs: (
                summary,
                [review, blocker],
            ),
        )
        with pytest.raises(merge.WorkflowError, match="PR readiness failed"):
            merge._validate_readiness(
                "24", tmp_path, allow_admin_review_bypass=True
            )


def test_merge_pr_runs_all_gates_before_shared_merge(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    repo = tmp_path / "repo"
    repo.mkdir()
    head = "a" * 40
    events: list[str] = []

    monkeypatch.setattr(
        merge,
        "restore_unfinished_checkpoints",
        lambda root: events.append("recover"),
    )

    def validate(*args: Any, **kwargs: Any) -> dict[str, object]:
        events.append("readiness")
        return {
            "base": "main",
            "head_oid": head,
            "review_required": True,
        }

    monkeypatch.setattr(merge, "_validate_readiness", validate)
    def codex_gate(*args: Any, **kwargs: Any) -> dict[str, object]:
        events.append("codex")
        return {
            "head_oid": head,
            "active_codex_thread_count": 0,
            "unresolved_review_thread_count": 0,
        }

    monkeypatch.setattr(
        merge.codex_review,
        "wait_for_codex_threads",
        codex_gate,
    )

    def delegated(*args: Any, **kwargs: Any) -> dict[str, Any]:
        events.append("merge")
        assert kwargs["readiness_summary"]["review_required"] is True
        assert kwargs["recover_checkpoints"] is False
        return {"status": "merged"}

    monkeypatch.setattr(merge, "merge_verified_pr", delegated)
    result = merge.merge_pr(
        argparse.Namespace(
            **vars(merge_args(repo, admin=True)),
            expected_head=head,
            wait_seconds=0,
            interval_seconds=0,
        )
    )

    assert result["status"] == "merged"
    assert events == ["recover", "readiness", "codex", "readiness", "merge"]


def test_unresolved_required_conversation_blocks_before_shared_merge(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    repo = tmp_path / "repo"
    repo.mkdir()
    head = "a" * 40
    monkeypatch.setattr(merge, "restore_unfinished_checkpoints", lambda root: None)
    monkeypatch.setattr(
        merge,
        "_validate_readiness",
        lambda *args, **kwargs: {
            "base": "main",
            "head_oid": head,
            "review_required": True,
        },
    )
    monkeypatch.setattr(
        merge.codex_review,
        "wait_for_codex_threads",
        lambda *args, **kwargs: {
            "head_oid": head,
            "active_codex_thread_count": 0,
            "unresolved_review_thread_count": 1,
        },
    )
    monkeypatch.setattr(
        merge.readiness,
        "review_thread_resolution_required",
        lambda *args: True,
    )
    monkeypatch.setattr(
        merge,
        "merge_verified_pr",
        lambda *args, **kwargs: pytest.fail("merge must remain gated"),
    )

    with pytest.raises(merge.WorkflowError, match="require resolution"):
        merge.merge_pr(
            argparse.Namespace(
                **vars(merge_args(repo, admin=True)),
                expected_head=head,
                wait_seconds=0,
                interval_seconds=0,
            )
        )


def test_merge_cli_emits_compact_critical_json(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    merge = load_pr_workflow_module(monkeypatch, "merge")
    critical = merge.CriticalRestoreError(
        repository="example/repository",
        base_branch="main",
        pr="24",
        head="a" * 40,
        merge_state="MERGED",
        recovery="gh api --method POST endpoint",
    )

    def fail(args: argparse.Namespace) -> dict[str, Any]:
        raise critical

    monkeypatch.setattr(merge, "merge_pr", fail)
    assert merge.main(["--pr", "24"]) == 1
    output = capsys.readouterr().err.strip()
    assert json.loads(output)["status"] == "critical"
    assert '": "' not in output
    assert '", "' not in output

    direct = subprocess.run(
        [sys.executable, str(PR_WORKFLOW_ENTRYPOINT), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert direct.returncode == 0, direct.stderr
    assert "GitHub PR workflows" in direct.stdout

    module = subprocess.run(
        [sys.executable, "-m", "github_pr_workflow", "--help"],
        cwd=PR_WORKFLOW_SCRIPTS,
        capture_output=True,
        text=True,
        check=False,
    )
    assert module.returncode == 0, module.stderr
    assert "GitHub PR workflows" in module.stdout


def test_integrated_ship_delegates_admin_semantics_to_merge_owner(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ship = load_pr_workflow_module(monkeypatch, "ship")
    repo = tmp_path / "repo"
    repo.mkdir()
    head = "a" * 40
    checkpoint = tmp_path / "ship-checkpoint.json"
    events: list[str] = []
    state = {
        "phase": "gates_passed",
        "pr": 24,
        "url": "https://example.invalid/pull/24",
        "commit": head,
        "gate_disposition": "admin_authorized",
    }
    ci = {
        "base": "main",
        "head_oid": head,
        "review_required": True,
    }

    monkeypatch.setattr(
        ship.merge,
        "restore_unfinished_checkpoints",
        lambda root: events.append("recover"),
    )
    monkeypatch.setattr(ship, "_repository_name", lambda *args: "example/repository")
    monkeypatch.setattr(ship, "_resolve_commit", lambda *args: head)
    monkeypatch.setattr(ship, "_load_pending_work_scope", lambda *args: (None, None))
    monkeypatch.setattr(
        ship,
        "_load_or_create_checkpoint",
        lambda *args: (checkpoint, state),
    )
    monkeypatch.setattr(
        ship,
        "_live_pr",
        lambda *args: {"state": "OPEN", "headRefOid": head},
    )
    monkeypatch.setattr(
        ship,
        "run_parallel_gates",
        lambda *args, **kwargs: {
            "disposition": "admin_authorized",
            "ci": ci,
            "codex": {"active_threads": 0, "unresolved_threads": 0},
        },
    )
    monkeypatch.setattr(ship, "_write_checkpoint", lambda *args: None)
    monkeypatch.setattr(ship.sync, "sync_main", lambda args: {"head": "b" * 40})
    monkeypatch.setattr(ship, "_remove_completed_pr_checkpoints", lambda *args: [])

    def delegated(
        args: argparse.Namespace,
        *,
        expected_head: str,
        readiness_summary: dict[str, object],
        recover_checkpoints: bool,
    ) -> dict[str, Any]:
        events.append("merge")
        assert args.admin is True
        assert args.auto is False
        assert expected_head == head
        assert readiness_summary is ci
        assert recover_checkpoints is False
        return {
            "status": "merged",
            "merged_at": "2026-08-01T00:00:00Z",
            "merge_commit": "c" * 40,
        }

    monkeypatch.setattr(ship.merge, "merge_verified_pr", delegated)
    result = ship.ship(
        argparse.Namespace(
            repo_root=repo,
            repo="example/repository",
            commit=head,
            head_branch="release/local",
            base_branch="main",
            remote_name="origin",
            title=None,
            body=None,
            merge_method="merge",
            delete_branch=False,
            reusable_head=False,
            pending_work_check=False,
            pending_work_scope=None,
            ci_wait_seconds=0,
            review_wait_seconds=0,
            interval_seconds=0,
        )
    )

    assert result["status"] == "shipped"
    assert events == ["recover", "merge"]

    review_result = {
        "repo": "example/repository",
        "pr": 24,
        "url": "https://example.invalid/pull/24",
        "head_oid": head,
        "active_codex_thread_count": 1,
        "active_codex_threads": [
            {
                "id": "PRRT_1",
                "thread_id": "PRRT_1",
                "path": "skills/example/SKILL.md",
                "line": 17,
                "body": "Preserve the exact contract.",
                "top_comment_database_id": 91,
                "comment_url": "https://example.invalid/comment/91",
            }
        ],
        "unresolved_review_thread_count": 1,
    }
    with pytest.raises(ship.ShipBlocked) as review_blocked:
        ship._enforce_review_thread_gate(
            argparse.Namespace(repo_root=repo, base_branch="main"),
            review_result,
            head,
            base_branch="main",
        )
    review_payload = review_blocked.value.payload["blocker"]
    assert review_payload["kind"] == "review_threads"
    assert review_payload["threads"][0] == {
        "thread_id": "PRRT_1",
        "path": "skills/example/SKILL.md",
        "line": 17,
        "is_outdated": False,
        "body": "Preserve the exact contract.",
        "top_comment_database_id": 91,
        "comment_url": "https://example.invalid/comment/91",
    }

    failing = ship.readiness.Finding(
        level="ERROR",
        check="pr.status_checks",
        message="One or more status checks are failing.",
        actual=["validate"],
    )
    monkeypatch.setattr(
        ship.readiness,
        "validate_readiness",
        lambda *args, **kwargs: (
            {
                "number": 24,
                "url": "https://example.invalid/pull/24",
                "head_oid": head,
            },
            [failing],
        ),
    )
    monkeypatch.setattr(
        ship,
        "run_json_command",
        lambda *args, **kwargs: argparse.Namespace(
            ok=True,
            data=[
                {
                    "name": "validate",
                    "state": "FAILURE",
                    "bucket": "fail",
                    "workflow": "CI",
                    "link": (
                        "https://github.com/example/repository/"
                        "actions/runs/42/job/84"
                    ),
                }
            ],
            message=None,
        ),
    )
    monkeypatch.setattr(
        ship,
        "run_command",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            stdout=(
                "setup\nFAILED tests/test_example.py::test_contract\n"
                "assert False\n"
            ),
            stderr="",
        ),
    )
    with pytest.raises(ship.ShipBlocked) as ci_blocked:
        ship.wait_for_ci_gate(
            "24",
            repo,
            head,
            repository="example/repository",
            wait_seconds=0,
            interval_seconds=0,
        )
    ci_payload = ci_blocked.value.payload["blocker"]
    assert ci_payload["kind"] == "ci"
    assert ci_payload["head_oid"] == head
    assert ci_payload["check"] == {
        "name": "validate",
        "state": "FAILURE",
        "workflow": "CI",
        "url": "https://github.com/example/repository/actions/runs/42/job/84",
        "run_id": "42",
        "job_id": "84",
        "failed_log_excerpt": (
            "setup\nFAILED tests/test_example.py::test_contract\nassert False"
        ),
        "failing_names": ["validate"],
        "diagnostic": None,
    }


def test_dependency_finalization_delegates_admin_to_shared_merge(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependency = load_pr_workflow_module(monkeypatch, "dependency_finalization")
    commands: list[list[str]] = []

    def run_command(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "merged", "head": "a" * 40}),
            stderr="",
        )

    monkeypatch.setattr(dependency, "run_command", run_command)
    monkeypatch.setattr(dependency, "merge_helper_directory", lambda: tmp_path)
    result, error = dependency.merge_pr(
        "example/repository",
        24,
        tmp_path,
        "merge",
        expected_head="a" * 40,
        admin=True,
        wait_seconds=0,
        interval_seconds=0,
    )

    assert error is None
    assert result == {"status": "merged", "head": "a" * 40}
    command = commands[0]
    assert command[1:4] == ["-m", "github_pr_workflow", "merge"]
    assert "--admin" in command
    assert command[command.index("--expected-head") + 1] == "a" * 40
    assert "enforce_admins" not in " ".join(command)


def write_deploy_contract(
    repo: pathlib.Path,
    operations: dict[str, object],
) -> pathlib.Path:
    """Write one JSON-compatible YAML deployment contract."""

    contract = repo / "deploy" / "deploy.yml"
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text(
        json.dumps(
            {
                "version": 1,
                "kind": "ceratops-deploy",
                "operations": operations,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return contract


def run_deploy_operation(
    repo: pathlib.Path,
    operation: str,
    *,
    contract: pathlib.Path | None = None,
    parameters: tuple[str, ...] = (),
    parameters_if_declared: tuple[str, ...] = (),
    if_declared: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run one isolated deployment operation."""

    command = [
        sys.executable,
        str(DEPLOY_OPERATION),
        "--repo-root",
        str(repo),
        "--operation",
        operation,
    ]
    if contract is not None:
        command.extend(("--contract", str(contract)))
    for parameter in parameters:
        command.extend(("--parameter", parameter))
    for parameter in parameters_if_declared:
        command.extend(("--parameter-if-declared", parameter))
    if if_declared:
        command.append("--if-declared")
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )


def test_deploy_template_is_a_schema_valid_empty_skeleton(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy2(DEPLOY_CONTRACT_TEMPLATE, write_deploy_contract(repo, {}))

    result = run_deploy_operation(repo, "missing")

    assert result.returncode == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert payload["message"] == "Deployment operation is not declared: missing"

    optional = run_deploy_operation(repo, "missing", if_declared=True)
    assert optional.returncode == 0, optional.stderr
    assert json.loads(optional.stdout) == {
        "status": "no_op",
        "operation": "missing",
        "steps": [],
        "reason": "operation_not_declared",
    }


def test_deploy_operation_preserves_argv_without_a_shell(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    probe = repo / "argv-probe.py"
    output = repo / "argv.json"
    injected = repo / "injected.txt"
    literal = f"literal; echo injected > {injected}"
    probe.write_text(
        "import json, pathlib, sys\n"
        "pathlib.Path(sys.argv[1]).write_text("
        "json.dumps(sys.argv[2:]), encoding='utf-8')\n",
        encoding="utf-8",
        newline="\n",
    )
    write_deploy_contract(
        repo,
        {
            "verify": {
                "handoff": "ceratops-skill-lifecycle/deploy",
                "steps": [
                    {
                        "id": "argv",
                        "run": [
                            sys.executable,
                            "argv-probe.py",
                            str(output),
                            "value with spaces",
                            literal,
                        ],
                    }
                ]
            }
        },
    )

    result = run_deploy_operation(repo, "verify")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "status": "deployed",
        "operation": "verify",
        "steps": ["argv"],
        "handoff": "ceratops-skill-lifecycle/deploy",
    }
    assert json.loads(output.read_text(encoding="utf-8")) == [
        "value with spaces",
        literal,
    ]
    assert not injected.exists()


def test_deploy_operation_requires_and_expands_exact_declared_parameters(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    output = repo / "parameter.txt"
    parameterless_output = repo / "parameterless.txt"
    probe = repo / "parameter-probe.py"
    probe.write_text(
        "import pathlib, sys\n"
        "pathlib.Path(sys.argv[1]).write_text(sys.argv[2], encoding='utf-8')\n",
        encoding="utf-8",
        newline="\n",
    )
    write_deploy_contract(
        repo,
        {
            "after_promote": {
                "parameters": ["base_revision"],
                "steps": [
                    {
                        "id": "record",
                        "run": [
                            sys.executable,
                            "parameter-probe.py",
                            str(output),
                            "{base_revision}",
                        ],
                    }
                ],
            },
            "parameterless": {
                "steps": [
                    {
                        "id": "record",
                        "run": [
                            sys.executable,
                            "parameter-probe.py",
                            str(parameterless_output),
                            "literal",
                        ],
                    }
                ]
            },
        },
    )

    missing = run_deploy_operation(repo, "after_promote")
    assert missing.returncode == 1
    assert "missing base_revision" in json.loads(missing.stderr)["message"]
    extra = run_deploy_operation(
        repo,
        "after_promote",
        parameters=("base_revision=abc", "unexpected=value"),
    )
    assert extra.returncode == 1
    assert "unexpected unexpected" in json.loads(extra.stderr)["message"]

    conditional = run_deploy_operation(
        repo,
        "after_promote",
        parameters_if_declared=("base_revision=conditional",),
    )
    assert conditional.returncode == 0, conditional.stderr
    assert output.read_text(encoding="utf-8") == "conditional"

    duplicated = run_deploy_operation(
        repo,
        "after_promote",
        parameters=("base_revision=explicit",),
        parameters_if_declared=("base_revision=conditional",),
    )
    assert duplicated.returncode == 1
    assert "supplied more than once" in json.loads(duplicated.stderr)["message"]

    strict_parameterless = run_deploy_operation(
        repo,
        "parameterless",
        parameters=("base_revision=explicit",),
    )
    assert strict_parameterless.returncode == 1
    assert "unexpected base_revision" in json.loads(strict_parameterless.stderr)[
        "message"
    ]
    conditional_parameterless = run_deploy_operation(
        repo,
        "parameterless",
        parameters_if_declared=("base_revision=conditional",),
    )
    assert (
        conditional_parameterless.returncode == 0
    ), conditional_parameterless.stderr
    assert parameterless_output.read_text(encoding="utf-8") == "literal"

    result = run_deploy_operation(
        repo,
        "after_promote",
        parameters=("base_revision=0123456789abcdef",),
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text(encoding="utf-8") == "0123456789abcdef"


def test_deploy_runs_repository_command_once_from_repository_directory(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "repo"
    installed_skill = tmp_path / "runtime" / "ceratops-repo-lifecycle"
    installed_skill.mkdir(parents=True)
    (repo / "scripts").mkdir(parents=True)
    log = tmp_path / "deploy-invocations.jsonl"
    (repo / "scripts" / "deploy-repository.py").write_text(
        "import json, os, pathlib, sys\n"
        "with pathlib.Path(os.environ['INSTALL_LOG']).open('a', encoding='utf-8') as stream:\n"
        "    stream.write(json.dumps({'cwd': str(pathlib.Path.cwd()), 'argv': sys.argv[1:]}) + '\\n')\n",
        encoding="utf-8",
        newline="\n",
    )
    write_deploy_contract(
        repo,
        {
            "deploy": {
                "steps": [
                    {
                        "id": "deploy-repository",
                        "run": [sys.executable, "scripts/deploy-repository.py"],
                    }
                ]
            }
        },
    )

    result = subprocess.run(
        [
            sys.executable,
            str(DEPLOY_OPERATION),
            "--repo-root",
            str(repo),
            "--operation",
            "deploy",
        ],
        cwd=installed_skill,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "INSTALL_LOG": str(log)},
    )

    assert result.returncode == 0, result.stderr
    invocations = [
        json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
    ]
    assert invocations == [{"cwd": str(repo.resolve()), "argv": []}]


def test_deploy_operation_rejects_invalid_schema(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    contract = write_deploy_contract(
        repo,
        {"invalid": {"steps": [{"id": "invalid", "run": "python -V"}]}},
    )

    result = run_deploy_operation(repo, "invalid", contract=contract)

    assert result.returncode == 1
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert payload["message"].startswith("Invalid deployment contract:")


def test_deploy_operation_enforces_repository_path_boundaries(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    marker = repo / "must-not-run.txt"
    repo.mkdir()
    outside.mkdir()
    write_deploy_contract(
        repo,
        {
            "escape": {
                "steps": [
                    {
                        "id": "would-mutate",
                        "run": [
                            sys.executable,
                            "-c",
                            (
                                "import pathlib; "
                                "pathlib.Path('must-not-run.txt').write_text('ran')"
                            ),
                        ],
                    },
                    {
                        "id": "escape",
                        "cwd": "../outside",
                        "run": [sys.executable, "-c", "raise SystemExit(0)"],
                    }
                ]
            }
        },
    )

    escaped_cwd = run_deploy_operation(repo, "escape")

    assert escaped_cwd.returncode == 1
    assert json.loads(escaped_cwd.stderr)["message"] == (
        "Deployment step cwd must be a directory inside the repository."
    )
    assert not marker.exists()

    outside_contract = outside / "deploy.yml"
    outside_contract.write_text(
        json.dumps({"version": 1, "operations": {}}),
        encoding="utf-8",
        newline="\n",
    )
    escaped_contract = run_deploy_operation(
        repo,
        "escape",
        contract=outside_contract,
    )
    assert escaped_contract.returncode == 1
    assert json.loads(escaped_contract.stderr)["message"] == (
        "Deployment contract must be a file inside the repository."
    )


def test_deploy_operation_reports_a_bounded_failure_tail(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    failure = repo / "fail.py"
    failure.write_text(
        "import sys\n"
        "for index in range(12):\n"
        "    print(f'line-{index}', file=sys.stderr)\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
        newline="\n",
    )
    write_deploy_contract(
        repo,
        {
            "fail": {
                "steps": [
                    {
                        "id": "expected-failure",
                        "run": [sys.executable, "fail.py"],
                    }
                ]
            }
        },
    )

    result = run_deploy_operation(repo, "fail")

    assert result.returncode == 1
    message = json.loads(result.stderr)["message"]
    assert message.startswith("Deployment step failed: expected-failure\nline-4")
    assert "line-11" in message
    assert "line-3" not in message


def test_closure_snapshot_composes_only_named_local_state(
    tmp_path: pathlib.Path,
) -> None:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    task_worktree = tmp_path / "task-worktree"
    temp_root = tmp_path / "retained-temp"
    repo.mkdir()
    temp_root.mkdir()
    (temp_root / "one.txt").write_text("one\n", encoding="utf-8", newline="\n")
    (temp_root / "two.txt").write_text("two\n", encoding="utf-8", newline="\n")

    assert run_git(tmp_path, "init", "--bare", str(remote)).returncode == 0
    assert run_git(repo, "init", "-b", "main").returncode == 0
    assert run_git(repo, "config", "user.name", "Closure Test").returncode == 0
    assert (
        run_git(repo, "config", "user.email", "closure@example.invalid").returncode
        == 0
    )
    (repo / "README.md").write_text("base\n", encoding="utf-8", newline="\n")
    assert run_git(repo, "add", "README.md").returncode == 0
    assert run_git(repo, "commit", "-m", "base").returncode == 0
    assert run_git(repo, "remote", "add", "origin", str(remote)).returncode == 0
    assert run_git(repo, "push", "-u", "origin", "main").returncode == 0
    assert run_git(repo, "branch", "release/local").returncode == 0
    assert run_git(repo, "push", "origin", "release/local").returncode == 0
    (repo / "local.txt").write_text("local\n", encoding="utf-8", newline="\n")
    assert run_git(repo, "add", "local.txt").returncode == 0
    assert run_git(repo, "commit", "-m", "local").returncode == 0
    assert (
        run_git(
            repo,
            "worktree",
            "add",
            "-b",
            "codex/closure-test",
            str(task_worktree),
            "release/local",
        ).returncode
        == 0
    )
    (task_worktree / "task.txt").write_text(
        "task\n", encoding="utf-8", newline="\n"
    )
    assert run_git(task_worktree, "add", "task.txt").returncode == 0
    assert run_git(task_worktree, "commit", "-m", "task").returncode == 0
    assert (
        run_git(repo, "branch", "-f", "release/local", "codex/closure-test").returncode
        == 0
    )

    snapshot = subprocess.run(
        [
            sys.executable,
            str(CLOSURE_SNAPSHOT),
            "--repo",
            str(repo),
            "--fetch-remote",
            "origin",
            "--release-branch",
            "release/local",
            "--release-upstream",
            "origin/release/local",
            "--task-worktree",
            str(task_worktree),
            "--task-branch",
            "codex/closure-test",
            "--temp-root",
            str(temp_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert snapshot.returncode == 0, snapshot.stderr
    result = json.loads(snapshot.stdout)
    assert result["schema"] == "ceratops-closure-snapshot.v1"
    assert result["repo"]["branch"] == "main"
    assert result["repo"]["clean"] is True
    assert result["repo"]["tracking"] == {
        "status": "tracked",
        "ref": "origin/main",
        "ahead": 1,
        "behind": 0,
    }
    assert result["release"]["ahead"] == 1
    assert result["release"]["behind"] == 0
    assert result["task"]["branch"] == "codex/closure-test"
    assert result["task"]["clean"] is True
    assert result["task"]["staged_in_release"] is True
    assert result["temp"]["files"] == 2

    invalid = subprocess.run(
        [
            sys.executable,
            str(CLOSURE_SNAPSHOT),
            "--repo",
            str(repo),
            "--release-branch",
            "release/local",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalid.returncode == 2
    assert "must be provided together" in invalid.stderr


def load_source_validator(skills_dir: pathlib.Path) -> dict[str, Any]:
    """Load the source validator with an isolated skill tree for contract tests."""

    validator = runpy.run_path(str(VALIDATOR))
    check_contract = validator["check_multi_action_skill_contract"]
    check_contract.__globals__["SKILLS_DIR"] = skills_dir
    return validator


def write_multi_action_skill(
    skills_dir: pathlib.Path,
    name: str,
    action_references: list[str],
    action_files: dict[str, str],
) -> None:
    """Write one minimal multi-action index and its declared reference files."""

    skill_dir = skills_dir / name
    references_dir = skill_dir / "references"
    references_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "### Action References\n\n"
        + "\n".join(f"- `{action_reference}`" for action_reference in action_references)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for action_reference, content in action_files.items():
        action_path = skill_dir / pathlib.PurePosixPath(action_reference)
        action_path.write_text(content, encoding="utf-8", newline="\n")


def add_skill(repo: pathlib.Path, name: str) -> None:
    """Add one minimal source skill that satisfies the compatible profile."""

    skill_dir = repo / "skills" / name
    (skill_dir / "agents").mkdir(parents=True)
    (skill_dir / "assets").mkdir()
    (skill_dir / "assets" / "icon.png").write_bytes(b"test-icon")
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: Manage {name.replace('-', ' ')} workflows safely across compatible repositories.",
                "---",
                "",
                f"# {name.replace('-', ' ').title()}",
                "",
                "## Workflow",
                "",
                "### Boundaries",
                "",
                "Stay within the selected repository.",
                "",
                "### Output Contract",
                "",
                "Report the validated result.",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    (skill_dir / "agents" / "openai.yaml").write_text(
        "\n".join(
            [
                "interface:",
                f'  display_name: "{name.replace("-", " ").title()}"',
                f'  short_description: "Manage {name.replace("-", " ")} workflows"',
                '  icon_small: "./assets/icon.png"',
                '  icon_large: "./assets/icon.png"',
                f'  default_prompt: "Use ${name} for this workflow."',
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )


def create_compatible_repo(repo: pathlib.Path, source_id: str, skill_names: list[str]) -> None:
    """Create the smallest complete Ceratops-compatible source repository."""

    (repo / "skills" / "sections").mkdir(parents=True)
    shutil.copy2(
        ROOT / "skills" / "sections" / "core.md",
        repo / "skills" / "sections" / "core.md",
    )
    write_deploy_contract(
        repo,
        {
            "deploy": {
                "handoff": "ceratops-skill-lifecycle/deploy",
            },
            "bootstrap": {
                "steps": [
                    {
                        "id": "bootstrap-skills",
                        "run": [
                            "python",
                            "scripts/install-skills-bootstrap.py",
                        ],
                    }
                ]
            }
        },
    )
    (repo / "scripts").mkdir()
    shutil.copy2(
        INSTALLER_TEMPLATE,
        repo / "scripts" / "install-skills-bootstrap.py",
    )
    for skill_name in skill_names:
        add_skill(repo, skill_name)
    write_manifest(repo, source_id)
    rows = "\n".join(f"| `{name}` | Test skill. |" for name in sorted(skill_names))
    (repo / "README.md").write_text(
        "# Compatible Skills\n\n"
        "| org | repo |\n| --- | --- |\n| `unrelated-row` | value |\n\n"
        "## Skills\n\n| Skill | Purpose |\n| --- | --- |\n"
        f"{rows}\n\n## Notes\n",
        encoding="utf-8",
        newline="\n",
    )
def write_manifest(repo: pathlib.Path, source_id: str) -> None:
    """Rewrite assignments after a test adds or removes source skills."""

    skill_names = sorted(path.parent.name for path in (repo / "skills").glob("*/SKILL.md"))
    manifest = {
        "runtime_source_id": source_id,
        "validation_profile": "ceratops-compatible",
        "sections": {"core": "skills/sections/core.md"},
        "skills": {name: ["core"] for name in skill_names},
    }
    (repo / "skills" / "skill-sections.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def run_builder(
    repo: pathlib.Path,
    install_root: pathlib.Path,
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    """Run the managed runtime builder against one isolated install root."""

    return subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--repo-root",
            str(repo),
            "--install-root",
            str(install_root),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def load_runtime_builder() -> dict[str, Any]:
    """Load one isolated builder module namespace for monkeypatched behavior tests."""

    return runpy.run_path(str(BUILDER))


def load_runtime_installer() -> dict[str, Any]:
    """Load the runtime installer with its sibling builder import available."""

    runtime_dir = str(RUNTIME_INSTALLER.parent)
    sys.modules.pop("managed_runtime_builder", None)
    sys.path.insert(0, runtime_dir)
    try:
        return runpy.run_path(str(RUNTIME_INSTALLER))
    finally:
        sys.path.remove(runtime_dir)


def runtime_skill_text(install_root: pathlib.Path, skill_name: str) -> str:
    """Read one installed runtime skill body."""

    return (install_root / skill_name / "SKILL.md").read_text(encoding="utf-8")


def runtime_owner(install_root: pathlib.Path, skill_name: str) -> str:
    data = json.loads((install_root / skill_name / RUNTIME_MANIFEST).read_text(encoding="utf-8"))
    return str(data["runtime_source_id"])


def prepare_repository_lifecycle_repo(
    tmp_path: pathlib.Path,
    *,
    declares_base_revision: bool = False,
    managed_skills: bool = False,
    handoff: str | None = None,
) -> tuple[pathlib.Path, str, pathlib.Path, dict[str, str]]:
    """Create one isolated repository with a promotable source branch."""

    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    log = tmp_path / "deploy.log"
    assert run_git(tmp_path, "init", "--bare", str(remote)).returncode == 0
    repo.mkdir()
    assert run_git(repo, "init", "-b", "main").returncode == 0
    assert run_git(repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(repo, "config", "user.name", "Test Agent").returncode == 0
    (repo / "README.md").write_text("base\n", encoding="utf-8", newline="\n")
    (repo / "deploy-probe.py").write_text(
        "import os, pathlib, sys\n"
        "pathlib.Path(os.environ['DEPLOY_TEST_LOG']).write_text("
        "(sys.argv[1] if len(sys.argv) > 1 else 'no-base') + '\\n', "
        "encoding='utf-8')\n",
        encoding="utf-8",
        newline="\n",
    )
    operation: dict[str, object] = {
        "steps": [
            {
                "id": "record",
                "run": [
                    sys.executable,
                    "deploy-probe.py",
                    *(["{base_revision}"] if declares_base_revision else []),
                ],
            }
        ]
    }
    if declares_base_revision:
        operation["parameters"] = ["base_revision"]
    if handoff is not None:
        operation["handoff"] = handoff
    write_deploy_contract(
        repo,
        {"deploy": operation},
    )
    if managed_skills:
        (repo / "skills").mkdir()
        (repo / "skills" / "skill-sections.json").write_text(
            json.dumps({"skills": {"sample-skill": []}}),
            encoding="utf-8",
            newline="\n",
        )
    assert run_git(repo, "add", ".").returncode == 0
    assert run_git(repo, "commit", "-m", "base").returncode == 0
    assert run_git(repo, "remote", "add", "origin", str(remote)).returncode == 0
    assert run_git(repo, "push", "-u", "origin", "main").returncode == 0
    assert run_git(repo, "switch", "-c", "approved").returncode == 0
    (repo / "README.md").write_text(
        "base\napproved\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(repo, "add", "README.md").returncode == 0
    assert run_git(repo, "commit", "-m", "approved change").returncode == 0
    approved_head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    environment = {**os.environ, "DEPLOY_TEST_LOG": str(log)}
    return repo, approved_head, log, environment


@pytest.mark.parametrize(
    (
        "operation_arguments",
        "declares_base_revision",
        "managed_skills",
        "declared_handoff",
        "expected_operation",
        "expected_managed_skills",
        "expected_handoff",
        "expects_base_revision",
    ),
    [
        (["--no-run-operation"], False, False, None, None, None, None, None),
        (
            ["--run-operation", "deploy"],
            False,
            False,
            None,
            {
                "status": "deployed",
                "operation": "deploy",
                "steps": ["record"],
            },
            False,
            None,
            False,
        ),
        (
            ["--run-operation", "deploy"],
            False,
            True,
            None,
            {
                "status": "deployed",
                "operation": "deploy",
                "steps": ["record"],
            },
            True,
            None,
            False,
        ),
        (
            ["--run-operation", "deploy"],
            False,
            True,
            "ceratops-skill-lifecycle/deploy",
            {
                "status": "deployed",
                "operation": "deploy",
                "steps": ["record"],
                "handoff": "ceratops-skill-lifecycle/deploy",
            },
            True,
            "ceratops-skill-lifecycle/deploy",
            False,
        ),
    ],
)
def test_promote_repository_requires_an_explicit_deployment_choice(
    tmp_path: pathlib.Path,
    operation_arguments: list[str],
    declares_base_revision: bool,
    managed_skills: bool,
    declared_handoff: str | None,
    expected_operation: dict[str, object] | None,
    expected_managed_skills: bool | None,
    expected_handoff: str | None,
    expects_base_revision: bool | None,
) -> None:
    repo, approved_head, log, environment = prepare_repository_lifecycle_repo(
        tmp_path,
        declares_base_revision=declares_base_revision,
        managed_skills=managed_skills,
        handoff=declared_handoff,
    )
    release_start = run_git(repo, "rev-parse", "main").stdout.strip()

    promoted = subprocess.run(
        [
            sys.executable,
            str(PROMOTE_REPOSITORY),
            "--repo-root",
            str(repo),
            "--source-branch",
            "approved",
            *operation_arguments,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert promoted.returncode == 0, promoted.stderr
    result = json.loads(promoted.stdout)
    assert result["status"] == "ready"
    assert result["release_branch"] == "release/local"
    assert result["merged_branches"] == ["approved"]
    assert result["head"] == approved_head
    assert result["release_start"] == release_start
    assert result["operation"] == expected_operation
    if expected_managed_skills is None:
        assert "managed_skills" not in result
        assert "handoff" not in result
    else:
        assert result["managed_skills"] is expected_managed_skills
        assert result["handoff"] == expected_handoff
    scope_path = pathlib.Path(result["pending_work_scope"])
    assert json.loads(scope_path.read_text(encoding="utf-8")) == {
        "source_branches": ["approved"],
        "target_branch": "release/local",
        "target_commit": approved_head,
        "version": 1,
    }
    assert run_git(repo, "branch", "--show-current").stdout.strip() == "release/local"
    assert run_git(repo, "status", "--porcelain").stdout == ""
    if expects_base_revision is None:
        assert not log.exists()
    elif expects_base_revision:
        assert log.read_text(encoding="utf-8") == f"{release_start}\n"
    else:
        assert log.read_text(encoding="utf-8") == "no-base\n"


def test_promote_and_deploy_does_not_inject_base_revision(
    tmp_path: pathlib.Path,
) -> None:
    repo, approved_head, log, environment = prepare_repository_lifecycle_repo(tmp_path)
    first = subprocess.run(
        [
            sys.executable,
            str(PROMOTE_REPOSITORY),
            "--repo-root",
            str(repo),
            "--source-branch",
            "approved",
            "--no-run-operation",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert first.returncode == 0, first.stderr
    assert not log.exists()

    assert run_git(repo, "switch", "-c", "approved-second", "release/local").returncode == 0
    (repo / "README.md").write_text(
        "base\napproved\napproved second\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(repo, "add", "README.md").returncode == 0
    assert run_git(repo, "commit", "-m", "approved second change").returncode == 0
    second = subprocess.run(
        [
            sys.executable,
            str(PROMOTE_REPOSITORY),
            "--repo-root",
            str(repo),
            "--source-branch",
            "approved-second",
            "--run-operation",
            "deploy",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["release_start"] == approved_head
    assert log.read_text(encoding="utf-8") == "no-base\n"


def test_promote_repository_rejects_noncanonical_release_branch_before_mutation(
    tmp_path: pathlib.Path,
) -> None:
    repo, _, _, environment = prepare_repository_lifecycle_repo(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(PROMOTE_REPOSITORY),
            "--repo-root",
            str(repo),
            "--source-branch",
            "approved",
            "--release-branch",
            "release/task",
            "--no-run-operation",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert result.returncode == 1
    assert json.loads(result.stderr)["message"] == (
        "release_branch must be release/local."
    )
    assert run_git(repo, "branch", "--show-current").stdout.strip() == "approved"
    assert run_git(repo, "branch", "--list", "release/task").stdout == ""


def test_promote_and_deploy_rejects_operation_created_repository_work(
    tmp_path: pathlib.Path,
) -> None:
    repo, _, _, environment = prepare_repository_lifecycle_repo(tmp_path)
    probe = repo / "deploy-probe.py"
    probe.write_text(
        "import pathlib\n"
        "pathlib.Path('generated-by-deploy.txt').write_text("
        "'untracked\\n', encoding='utf-8')\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(repo, "add", "deploy-probe.py").returncode == 0
    assert run_git(repo, "commit", "-m", "create deploy output").returncode == 0

    promoted = subprocess.run(
        [
            sys.executable,
            str(PROMOTE_REPOSITORY),
            "--repo-root",
            str(repo),
            "--source-branch",
            "approved",
            "--run-operation",
            "deploy",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert promoted.returncode == 1
    result = json.loads(promoted.stderr)
    assert result["status"] == "error"
    assert "dirty" in result["message"].lower()
    assert "ready" in result["message"].lower()
    assert (repo / "generated-by-deploy.txt").is_file()


@pytest.mark.parametrize("scope_present", [False, True])
def test_repository_ship_absent_default_contract_is_no_op_and_finalizes(
    tmp_path: pathlib.Path,
    scope_present: bool,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    scope = tmp_path / "scope.json"
    scope.write_text(
        json.dumps({"source_branches": []}),
        encoding="utf-8",
        newline="\n",
    )
    shipped = {
        "status": "shipped",
        "repository": "example/repository",
        "commit": "a" * 40,
        "pr": 24,
        "url": "https://example.invalid/pull/24",
        "merge_commit": "c" * 40,
        "synchronized_head": "b" * 40,
    }
    prepared = {
        "status": "ready",
        "source_branches": [] if not scope_present else ["selected"],
        "pending_work_scope": str(scope) if scope_present else "",
    }
    responses: list[tuple[int, dict[str, Any]]] = [
        (0, prepared),
        (0, shipped),
    ]
    if scope_present:
        responses.extend(
            [
                (0, prepared),
                (0, {"status": "finalized"}),
            ]
        )
    commands: list[list[str]] = []

    def run_json(
        command: list[str], *, cwd: pathlib.Path | None = None
    ) -> tuple[int, dict[str, Any]]:
        if cwd is not None:
            assert cwd == repo
        commands.append(command)
        return responses[len(commands) - 1]

    loaded = runpy.run_path(str(SHIP_REPOSITORY))
    parsed = loaded["build_parser"]().parse_args(
        ["--head-branch", "release/local"]
    )
    assert not hasattr(parsed, "pending_work_scope")
    assert not hasattr(parsed, "no_pending_work_check")
    ship_repository = loaded["ship_repository"]
    ship_repository.__globals__["_run_json"] = run_json
    result = ship_repository(
        argparse.Namespace(
            repo_root=repo,
            repo="example/repository",
            head_branch="release/local",
            base_branch="main",
            remote_name="origin",
            commit="a" * 40,
            title=None,
            body=None,
            merge_method="merge",
            delete_branch=False,
            reusable_head=True,
            deploy_contract=pathlib.Path("deploy/deploy.yml"),
            deploy_operation="deploy",
            ci_wait_seconds=1,
            review_wait_seconds=1,
            interval_seconds=1,
        )
    )

    assert result["deployment"] == {
        "status": "no_op",
        "operation": "deploy",
        "steps": [],
        "reason": "deployment_contract_absent",
    }
    assert result["finalization"] == (
        {"status": "finalized"} if scope_present else None
    )
    assert "prepare" in commands[0]
    assert commands[0][-2:] == ["--target-commit", "a" * 40]
    if scope_present:
        assert len(commands) == 4
        assert "--pending-work-check" in commands[1]
        assert str(scope.resolve()) in commands[1]
        assert "check" in commands[2]
        assert "finalize" in commands[3]
    else:
        assert len(commands) == 2
        assert "--no-pending-work-check" in commands[1]
    deploy_runner = str(SHIP_REPOSITORY.parent / "run-deploy-operation.py")
    assert all(deploy_runner not in command for command in commands)

    blocker = {
        "status": "blocked",
        "message": "Codex review gate found one active thread.",
        "phase": "gates",
        "blocker": {
            "kind": "review_threads",
            "head_oid": "a" * 40,
            "threads": [{"thread_id": "PRRT_1", "body": "Fix this."}],
        },
    }
    blocked_responses: list[tuple[int, dict[str, Any]]] = [
        (
            0,
            {
                "status": "ready",
                "source_branches": [],
                "pending_work_scope": "",
            },
        ),
        (1, blocker),
    ]

    def blocked_run_json(
        command: list[str], *, cwd: pathlib.Path | None = None
    ) -> tuple[int, dict[str, Any]]:
        return blocked_responses.pop(0)

    ship_repository.__globals__["_run_json"] = blocked_run_json
    with pytest.raises(loaded["RepositoryShipError"]) as captured:
        ship_repository(
            argparse.Namespace(
                repo_root=repo,
                repo="example/repository",
                head_branch="release/local",
                base_branch="main",
                remote_name="origin",
                commit="a" * 40,
                title=None,
                body=None,
                merge_method="merge",
                delete_branch=False,
                reusable_head=True,
                deploy_contract=pathlib.Path("deploy/deploy.yml"),
                deploy_operation="deploy",
                ci_wait_seconds=1,
                review_wait_seconds=1,
                interval_seconds=1,
            )
        )
    assert captured.value.payload == blocker


def test_repository_ship_missing_custom_contract_blocks_before_remote_mutation(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    loaded = runpy.run_path(str(SHIP_REPOSITORY))
    ship_repository = loaded["ship_repository"]
    commands: list[list[str]] = []
    def unexpected_run(command: list[str]) -> tuple[int, dict[str, Any]]:
        commands.append(command)
        return 0, {}

    ship_repository.__globals__["_run_json"] = unexpected_run

    with pytest.raises(
        loaded["RepositoryShipError"],
        match="does not exist before shipping",
    ):
        ship_repository(
            argparse.Namespace(
                repo_root=repo,
                repo="example/repository",
                head_branch="release/local",
                base_branch="main",
                remote_name="origin",
                commit="a" * 40,
                title=None,
                body=None,
                merge_method="merge",
                delete_branch=False,
                reusable_head=False,
                deploy_contract=pathlib.Path("deploy/custom.yml"),
                deploy_operation="deploy",
                ci_wait_seconds=1,
                review_wait_seconds=1,
                interval_seconds=1,
            )
        )

    assert commands == []


@pytest.mark.parametrize("late_phase", ["post_sync", "post_finalize"])
@pytest.mark.parametrize("relative_scope", [False, True])
def test_repository_ship_late_pending_work_reports_remote_mutation(
    tmp_path: pathlib.Path,
    late_phase: str,
    relative_scope: bool,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "deploy").mkdir()
    (repo / "deploy" / "deploy.yml").write_text(
        "version: 1\noperations: {}\n",
        encoding="utf-8",
        newline="\n",
    )
    scope = repo / "scope.json" if relative_scope else tmp_path / "scope.json"
    scope.write_text(
        json.dumps({"source_branches": ["selected"]}),
        encoding="utf-8",
        newline="\n",
    )
    shipped = {
        "status": "shipped",
        "repository": "example/repository",
        "commit": "a" * 40,
        "pr": 17,
        "url": "https://example.invalid/pull/17",
        "merge_commit": "c" * 40,
        "synchronized_head": "b" * 40,
    }
    pending = {
        "status": "pending_work",
        "remote_mutation": False,
        "findings": [
            {
                "kind": "dirty_worktree",
                "subject": "selected",
                "detail": "1 status entry",
            }
        ],
    }
    deployed = {
        "status": "deployed",
        "operation": "deploy",
        "steps": ["install"],
    }
    prepared = {
        "status": "ready",
        "source_branches": ["selected"],
        "pending_work_scope": str(scope.resolve()),
    }
    responses: list[tuple[int, dict[str, Any]]] = (
        [(0, prepared), (0, shipped), (2, pending)]
        if late_phase == "post_sync"
        else [
            (0, prepared),
            (0, shipped),
            (0, prepared),
            (0, deployed),
            (2, pending),
        ]
    )
    commands: list[list[str]] = []

    def run_json(
        command: list[str], *, cwd: pathlib.Path | None = None
    ) -> tuple[int, dict[str, Any]]:
        commands.append(command)
        return responses[len(commands) - 1]

    loaded = runpy.run_path(str(SHIP_REPOSITORY))
    ship_repository = loaded["ship_repository"]
    ship_repository.__globals__["_run_json"] = run_json
    ship_repository.__globals__["_branch_worktree"] = (
        lambda repo_root, branch: None
    )
    args = argparse.Namespace(
        repo_root=repo,
        repo="example/repository",
        head_branch="release/local",
        base_branch="main",
        remote_name="origin",
        commit="a" * 40,
        title=None,
        body=None,
        merge_method="merge",
        delete_branch=False,
        reusable_head=True,
        deploy_contract=pathlib.Path("deploy/deploy.yml"),
        deploy_operation="deploy",
        ci_wait_seconds=1,
        review_wait_seconds=1,
        interval_seconds=1,
    )
    if late_phase == "post_finalize":
        stale_identity = loaded["_deployment_identity"](
            repo,
            target_branch="release/local",
            target_commit="d" * 40,
            contract=args.deploy_contract,
            operation="deploy",
        )
        loaded["_write_deployment_checkpoint"](
            scope.with_suffix(".after-ship.json"),
            stale_identity,
            {"status": "deployed", "operation": "deploy", "steps": ["old"]},
        )

    result = ship_repository(args)

    assert result["status"] == "pending_work"
    assert result["remote_mutation"] is True
    assert result["repository"] == "example/repository"
    assert result["commit"] == "a" * 40
    assert "prepare" in commands[0]
    assert "check" in commands[2]
    if late_phase == "post_sync":
        assert len(commands) == 3
        assert "deployment" not in result
    else:
        assert len(commands) == 5
        assert "finalize" in commands[4]
        assert result["deployment"] == deployed
        checkpoint = scope.with_suffix(".after-ship.json")
        assert checkpoint.is_file()
        responses.extend(
            [
                (0, prepared),
                (0, {**shipped, "status": "already_shipped"}),
                (0, prepared),
                (0, {"status": "finalized"}),
            ]
        )

        resumed = ship_repository(args)

        assert resumed["status"] == "already_shipped"
        assert resumed["deployment"] == deployed
        assert len(commands) == 9
        deploy_runner = str(SHIP_REPOSITORY.parent / "run-deploy-operation.py")
        assert all(deploy_runner not in command for command in commands[5:])
        assert not checkpoint.exists()


def test_repository_ship_rejects_malformed_deployment_checkpoint(
    tmp_path: pathlib.Path,
) -> None:
    loaded = runpy.run_path(str(SHIP_REPOSITORY))
    checkpoint = tmp_path / "scope.after-ship.json"
    checkpoint.write_text("{}", encoding="utf-8", newline="\n")
    identity = {
        "version": 1,
        "target_branch": "release/local",
        "target_commit": "a" * 40,
        "contract": str(tmp_path / "deploy.yml"),
        "operation": "deploy",
    }

    with pytest.raises(
        loaded["RepositoryShipError"],
        match="invalid structure",
    ):
        loaded["_read_deployment_checkpoint"](checkpoint, identity)


def test_repository_ship_rejects_noncanonical_release_branch_before_remote_process(
    tmp_path: pathlib.Path,
) -> None:
    loaded = runpy.run_path(str(SHIP_REPOSITORY))
    repo = tmp_path / "repo"
    repo.mkdir()
    child_calls: list[list[str]] = []

    def run_json(command: list[str]) -> tuple[int, dict[str, Any]]:
        child_calls.append(command)
        return 0, {}

    ship_repository = loaded["ship_repository"]
    ship_repository.__globals__["_run_json"] = run_json

    with pytest.raises(
        loaded["RepositoryShipError"],
        match="Head branch must be release/local",
    ):
        ship_repository(
            argparse.Namespace(
                repo_root=repo,
                head_branch="release/task",
            )
        )

    assert child_calls == []


def test_repository_ship_finalization_runs_outside_selected_worktree(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = runpy.run_path(str(SHIP_REPOSITORY))
    repo = tmp_path / "repo"
    repo.mkdir()
    command = ["python", "manage-pending-work.py", "finalize"]
    events: list[tuple[str, object]] = []
    original_directory = pathlib.Path.cwd().resolve()

    def change_directory(path: pathlib.Path) -> None:
        events.append(("chdir", path))

    def run_json(
        child_command: list[str], *, cwd: pathlib.Path
    ) -> tuple[int, dict[str, Any]]:
        events.append(("run", (child_command, cwd)))
        return 0, {"status": "finalized"}

    monkeypatch.setattr(loaded["os"], "chdir", change_directory)
    loaded["_run_finalization"].__globals__["_run_json"] = run_json

    result = loaded["_run_finalization"](command, repo_root=repo)

    assert result == (0, {"status": "finalized"})
    assert events == [
        ("chdir", repo),
        ("run", (command, repo)),
        ("chdir", original_directory),
    ]


def test_repository_ship_blocks_selected_worktree_caller_before_remote_process(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = runpy.run_path(str(SHIP_REPOSITORY))
    repo = tmp_path / "repo"
    selected = tmp_path / "worktrees" / "repo" / "thread"
    selected.mkdir(parents=True)
    repo.mkdir()
    scope = tmp_path / "scope.json"
    scope.write_text(
        json.dumps(
            {
                "version": 1,
                "target_branch": "release/local",
                "target_commit": "a" * 40,
                "source_branches": ["selected"],
            }
        ),
        encoding="utf-8",
        newline="\n",
    )
    child_calls: list[list[str]] = []

    def branch_worktree(repo_root: pathlib.Path, branch: str) -> pathlib.Path:
        assert repo_root == repo
        assert branch == "selected"
        return selected

    def run_json(command: list[str]) -> tuple[int, dict[str, Any]]:
        child_calls.append(command)
        return 0, {
            "status": "ready",
            "source_branches": ["selected"],
            "pending_work_scope": str(scope),
        }

    ship_repository = loaded["ship_repository"]
    ship_repository.__globals__["_branch_worktree"] = branch_worktree
    ship_repository.__globals__["_run_json"] = run_json
    monkeypatch.chdir(selected)

    with pytest.raises(
        loaded["RepositoryShipError"],
        match="outside selected worktree",
    ):
        ship_repository(
            argparse.Namespace(
                repo_root=repo,
                repo="example/repository",
                head_branch="release/local",
                base_branch="main",
                remote_name="origin",
                commit="a" * 40,
                title=None,
                body=None,
                merge_method="merge",
                delete_branch=False,
                reusable_head=True,
                deploy_contract=pathlib.Path("deploy/deploy.yml"),
                deploy_operation="deploy",
                ci_wait_seconds=1,
                review_wait_seconds=1,
                interval_seconds=1,
            )
        )

    assert len(child_calls) == 1
    assert "prepare" in child_calls[0]


def run_pending_work(
    repo: pathlib.Path,
    command: str,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    """Run one generic pending-work operation."""

    return subprocess.run(
        [
            sys.executable,
            str(MANAGE_PENDING_WORK),
            "--repo-root",
            str(repo),
            command,
            *arguments,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_pending_work_scope_is_selected_generic_and_finalized_late(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "Repository"
    repo.mkdir()
    assert run_git(repo, "init", "-b", "main").returncode == 0
    assert run_git(repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(repo, "config", "user.name", "Test Agent").returncode == 0
    (repo / "README.md").write_text("base\n", encoding="utf-8", newline="\n")
    assert run_git(repo, "add", "README.md").returncode == 0
    assert run_git(repo, "commit", "-m", "base").returncode == 0
    assert run_git(repo, "branch", "selected").returncode == 0
    assert run_git(repo, "branch", "unrelated").returncode == 0

    worktree_root = tmp_path / "worktrees" / repo.name
    selected_worktree = worktree_root / "selected"
    unrelated_worktree = worktree_root / "unrelated"
    worktree_root.mkdir(parents=True)
    assert (
        run_git(repo, "worktree", "add", str(selected_worktree), "selected").returncode
        == 0
    )
    assert (
        run_git(repo, "worktree", "add", str(unrelated_worktree), "unrelated").returncode
        == 0
    )
    (selected_worktree / "README.md").write_text(
        "base\nselected\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(selected_worktree, "add", "README.md").returncode == 0
    assert run_git(selected_worktree, "commit", "-m", "selected").returncode == 0
    target_commit = run_git(selected_worktree, "rev-parse", "HEAD").stdout.strip()
    assert run_git(repo, "branch", "release/local", target_commit).returncode == 0

    recorded = run_pending_work(
        repo,
        "record",
        "--target-branch",
        "release/local",
        "--target-commit",
        target_commit,
        "--source-branch",
        "selected",
    )

    assert recorded.returncode == 0, recorded.stderr
    recorded_payload = json.loads(recorded.stdout)
    assert recorded_payload["status"] == "ready"
    scope_path = pathlib.Path(recorded_payload["pending_work_scope"])
    assert json.loads(scope_path.read_text(encoding="utf-8")) == {
        "source_branches": ["selected"],
        "target_branch": "release/local",
        "target_commit": target_commit,
        "version": 1,
    }
    scope_path.write_text(
        json.dumps(
            {
                "source_branches": ["missing", "selected"],
                "target_branch": "release/local",
                "target_commit": target_commit,
                "version": 1,
            }
        ),
        encoding="utf-8",
        newline="\n",
    )

    (selected_worktree / "README.md").write_text(
        "base\nselected\nlater commit\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(selected_worktree, "add", "README.md").returncode == 0
    assert run_git(selected_worktree, "commit", "-m", "later selected").returncode == 0
    (selected_worktree / "README.md").write_text(
        "base\nselected\nlater commit\ndirty\n",
        encoding="utf-8",
        newline="\n",
    )
    (unrelated_worktree / "README.md").write_text(
        "base\nunrelated commit\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(unrelated_worktree, "add", "README.md").returncode == 0
    assert run_git(unrelated_worktree, "commit", "-m", "unrelated").returncode == 0
    (unrelated_worktree / "README.md").write_text(
        "base\nunrelated commit\ndirty\n",
        encoding="utf-8",
        newline="\n",
    )

    checked = run_pending_work(
        repo,
        "prepare",
        "--target-branch",
        "release/local",
    )

    assert checked.returncode == 2, checked.stderr
    checked_payload = json.loads(checked.stdout)
    assert checked_payload["status"] == "pending_work"
    assert checked_payload["remote_mutation"] is False
    assert [(item["kind"], item["subject"]) for item in checked_payload["findings"]] == [
        ("dirty_worktree", "selected"),
        ("unmerged_branch_commits", "selected"),
    ]
    assert json.loads(scope_path.read_text(encoding="utf-8"))["source_branches"] == [
        "selected"
    ]
    assert all(
        item["subject"] != "unrelated" for item in checked_payload["findings"]
    )

    tree = run_git(repo, "rev-parse", f"{target_commit}^{{tree}}").stdout.strip()
    base_commit = run_git(repo, "rev-parse", "main").stdout.strip()
    advanced = run_git(
        repo,
        "commit-tree",
        tree,
        "-p",
        base_commit,
        "-m",
        "realign reusable release after squash",
    )
    assert advanced.returncode == 0, advanced.stderr
    advanced_commit = advanced.stdout.strip()
    assert (
        run_git(
            repo,
            "update-ref",
            "refs/heads/release/local",
            advanced_commit,
            target_commit,
        ).returncode
        == 0
    )
    resumed = run_pending_work(
        repo,
        "prepare",
        "--target-branch",
        "release/local",
        "--target-commit",
        target_commit,
    )
    assert resumed.returncode == 2, resumed.stderr
    assert json.loads(resumed.stdout)["findings"] == checked_payload["findings"]
    assert (
        run_git(
            repo,
            "update-ref",
            "refs/heads/release/local",
            target_commit,
            advanced_commit,
        ).returncode
        == 0
    )

    assert run_git(selected_worktree, "reset", "--hard", target_commit).returncode == 0
    assert run_git(repo, "merge", "--ff-only", "release/local").returncode == 0
    current_commit = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    finalized = run_pending_work(
        repo,
        "finalize",
        "--scope",
        str(scope_path),
        "--target-branch",
        "release/local",
        "--target-commit",
        target_commit,
        "--current-branch",
        "main",
        "--current-commit",
        current_commit,
    )

    assert finalized.returncode == 0, finalized.stderr
    assert json.loads(finalized.stdout) == {
        "status": "finalized",
        "removed": ["selected"],
        "pending_work_scope": "",
    }
    assert not selected_worktree.exists()
    assert run_git(repo, "show-ref", "--verify", "refs/heads/selected").returncode != 0
    assert unrelated_worktree.is_dir()
    assert run_git(repo, "show-ref", "--verify", "refs/heads/unrelated").returncode == 0
    assert not scope_path.exists()

    scope_path.write_text(
        json.dumps(
            {
                "source_branches": ["already-gone"],
                "target_branch": "release/local",
                "target_commit": target_commit,
                "version": 1,
            }
        ),
        encoding="utf-8",
        newline="\n",
    )
    prepared = run_pending_work(
        repo,
        "prepare",
        "--target-branch",
        "release/local",
        "--target-commit",
        target_commit,
    )

    assert prepared.returncode == 0, prepared.stderr
    assert json.loads(prepared.stdout) == {
        "status": "ready",
        "source_branches": [],
        "pending_work_scope": "",
    }
    assert not scope_path.exists()

    absent = run_pending_work(
        repo,
        "prepare",
        "--target-branch",
        "release/local",
    )

    assert absent.returncode == 0, absent.stderr
    assert json.loads(absent.stdout) == {
        "status": "ready",
        "source_branches": [],
        "pending_work_scope": "",
    }


def test_pending_work_finalization_persists_partial_cleanup_progress(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "Repository"
    repo.mkdir()
    assert run_git(repo, "init", "-b", "main").returncode == 0
    assert run_git(repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(repo, "config", "user.name", "Test Agent").returncode == 0
    readme = repo / "README.md"
    readme.write_text("base\n", encoding="utf-8", newline="\n")
    assert run_git(repo, "add", "README.md").returncode == 0
    assert run_git(repo, "commit", "-m", "base").returncode == 0
    assert run_git(repo, "switch", "-c", "selected-a").returncode == 0
    readme.write_text("base\na\n", encoding="utf-8", newline="\n")
    assert run_git(repo, "commit", "-am", "selected a").returncode == 0
    assert run_git(repo, "switch", "-c", "selected-b").returncode == 0
    readme.write_text("base\na\nb\n", encoding="utf-8", newline="\n")
    assert run_git(repo, "commit", "-am", "selected b").returncode == 0
    target_commit = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    assert run_git(repo, "branch", "release/local", target_commit).returncode == 0
    assert run_git(repo, "switch", "main").returncode == 0
    assert run_git(repo, "merge", "--ff-only", "release/local").returncode == 0
    current_commit = run_git(repo, "rev-parse", "HEAD").stdout.strip()

    worktree_root = tmp_path / "worktrees" / repo.name
    selected_a = worktree_root / "selected-a"
    selected_b = worktree_root / "selected-b"
    worktree_root.mkdir(parents=True)
    assert run_git(repo, "worktree", "add", str(selected_a), "selected-a").returncode == 0
    assert run_git(repo, "worktree", "add", str(selected_b), "selected-b").returncode == 0
    recorded = run_pending_work(
        repo,
        "record",
        "--target-branch",
        "release/local",
        "--target-commit",
        target_commit,
        "--source-branch",
        "selected-a",
        "--source-branch",
        "selected-b",
    )
    assert recorded.returncode == 0, recorded.stderr
    scope_path = pathlib.Path(json.loads(recorded.stdout)["pending_work_scope"])

    lifecycle_scripts = str(MANAGE_PENDING_WORK.parent)
    sys.path.insert(0, lifecycle_scripts)
    try:
        loaded = runpy.run_path(str(MANAGE_PENDING_WORK))
    finally:
        sys.path.remove(lifecycle_scripts)
    finalize_scope = loaded["finalize_scope"]
    original_require_success = finalize_scope.__globals__["require_success"]
    pending_error = loaded["PendingWorkError"]

    def fail_second_branch(
        command: list[str],
        *,
        cwd: pathlib.Path,
    ) -> subprocess.CompletedProcess[str]:
        if command[-3:] == ["branch", "-d", "selected-b"]:
            raise pending_error("simulated second-branch cleanup failure")
        return original_require_success(command, cwd=cwd)

    finalize_scope.__globals__["require_success"] = fail_second_branch
    with pytest.raises(pending_error, match="second-branch cleanup failure"):
        finalize_scope(
            repo,
            scope_path,
            target_branch="release/local",
            target_commit=target_commit,
            current_branch="main",
            current_commit=current_commit,
        )

    assert json.loads(scope_path.read_text(encoding="utf-8"))["source_branches"] == [
        "selected-b"
    ]
    assert run_git(repo, "show-ref", "--verify", "refs/heads/selected-a").returncode != 0
    assert run_git(repo, "show-ref", "--verify", "refs/heads/selected-b").returncode == 0
    finalize_scope.__globals__["require_success"] = original_require_success

    resumed = finalize_scope(
        repo,
        scope_path,
        target_branch="release/local",
        target_commit=target_commit,
        current_branch="main",
        current_commit=current_commit,
    )

    assert resumed["status"] == "finalized"
    assert resumed["removed"] == ["selected-b"]
    assert not scope_path.exists()
    assert run_git(repo, "show-ref", "--verify", "refs/heads/selected-b").returncode != 0


def install_bundle_manifest(bundle_root: pathlib.Path) -> None:
    """Mark one copied lifecycle source folder as a supported installed bundle."""

    shutil.copytree(
        ROOT / "skills" / "sections",
        bundle_root / "skills" / "sections",
        dirs_exist_ok=True,
    )
    installed_schema = (
        bundle_root
        / "skills"
        / "ceratops-repo-lifecycle"
        / "references"
        / "schemas"
        / "deploy-contract.schema.json"
    )
    installed_schema.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        ROOT
        / "skills"
        / "ceratops-repo-lifecycle"
        / "references"
        / "schemas"
        / "deploy-contract.schema.json",
        installed_schema,
    )

    (bundle_root / RUNTIME_MANIFEST).write_text(
        json.dumps(
            {
                "schema": RUNTIME_MANIFEST_SCHEMA,
                "skill": "ceratops-skill-lifecycle",
                "validation_profile": "ceratops",
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def test_compatible_full_validation_accepts_arbitrary_skill_names(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok: 1"


def test_source_validator_ignores_shared_sections_directory(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "sections"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok: sections 1"


def test_skill_sections_template_contains_no_live_repository_inventory() -> None:
    template = json.loads(SECTION_MANIFEST_TEMPLATE.read_text(encoding="utf-8"))
    live = json.loads(LIVE_SECTION_MANIFEST.read_text(encoding="utf-8"))

    assert template == {
        "runtime_source_id": "",
        "validation_profile": "ceratops-compatible",
        "sections": {"core": "skills/sections/core.md"},
        "maintenance_workflows": {},
        "runtime_payloads": {},
        "skills": {},
    }
    assert live["runtime_source_id"]
    assert live["skills"]


def test_source_validator_rejects_section_drift_and_empty_source_identity(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    (repo / "skills" / "sections" / "core.md").write_text(
        "# Drifted core\n",
        encoding="utf-8",
        newline="\n",
    )

    drifted = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert drifted.returncode == 1
    assert "canonical materialized section differs" in drifted.stderr

    manifest_path = repo / "skills" / "skill-sections.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtime_source_id"] = ""
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "sections"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "runtime_source_id must be a nonempty string" in result.stderr


def test_compatibility_materializer_supplies_target_identity_and_assignments(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "stale/source", ["alpha-tool", "beta-tool"])
    (repo / ".git").write_text("gitdir: test\n", encoding="utf-8", newline="\n")
    shutil.rmtree(repo / "skills" / "sections")
    (repo / "skills" / "skill-sections.json").unlink()
    beta = repo / "skills" / "beta-tool" / "SKILL.md"
    (beta.parent / "references").mkdir()
    (beta.parent / "references" / "run.md").write_text(
        "# Run Action\n\n## Goal\n\nRun the target workflow.\n",
        encoding="utf-8",
        newline="\n",
    )
    (beta.parent / "references" / "check.md").write_text(
        "# Check Action\n\n## Goal\n\nCheck the target workflow.\n",
        encoding="utf-8",
        newline="\n",
    )
    beta.write_text(
        beta.read_text(encoding="utf-8")
        + "\n### Action References\n\n"
        + "- Run: `references/run.md`\n"
        + "- Check: `references/check.md`\n"
        + "\n"
        + "\n".join(
            [
                "<!-- CERATOPS_SHARED_SECTIONS_START -->",
                "<!-- SECTION SOURCE: skills/sections/core.md -->",
                "## Generated Core",
                "",
                "<!-- SECTION SOURCE: skills/sections/multi-action-skill.md -->",
                "## Generated Multi Action",
                "<!-- CERATOPS_SHARED_SECTIONS_END -->",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )

    result = run_compatibility_engine(
        REPOSITORY_LIFECYCLE_SCRIPTS,
        "materialize",
        "--target-repo-root",
        str(repo),
        "--runtime-source-id",
        "target/skills",
    )

    assert result.returncode == 0, result.stdout
    output = json.loads(result.stdout)
    manifest = json.loads(
        (repo / "skills" / "skill-sections.json").read_text(encoding="utf-8")
    )
    assert output["status"] == "ok"
    assert output["markers_removed"] == ["beta-tool"]
    assert manifest["runtime_source_id"] == "target/skills"
    assert manifest["validation_profile"] == "ceratops-compatible"
    assert manifest["skills"] == {
        "alpha-tool": ["core"],
        "beta-tool": ["core", "multi-action-skill"],
    }
    assert manifest["runtime_source_id"] != json.loads(
        SECTION_MANIFEST_TEMPLATE.read_text(encoding="utf-8")
    )["runtime_source_id"]
    assert (repo / "skills" / "sections" / "core.md").read_bytes() == (
        ROOT / "skills" / "sections" / "core.md"
    ).read_bytes()
    assert "SECTION SOURCE: skills/sections/" not in beta.read_text(encoding="utf-8")
    contract = yaml.safe_load(
        (repo / "deploy" / "deploy.yml").read_text(encoding="utf-8")
    )
    assert contract["kind"] == "ceratops-deploy"
    assert contract["operations"]["deploy"] == {
        "handoff": "ceratops-skill-lifecycle/deploy"
    }
    assert contract["operations"]["bootstrap"] == {
        "steps": [
            {
                "id": "bootstrap-skills",
                "run": ["python", "scripts/install-skills-bootstrap.py"],
            }
        ]
    }
    assert (repo / "scripts" / "install-skills-bootstrap.py").is_file()
    assert (repo / "scripts" / "validate-repository.py").is_file()
    assert (repo / ".github" / "workflows" / "validate.yml").is_file()
    assert output["repository_validation"] == {
        "checks": [],
        "validator": "materialized",
        "workflow": "materialized",
    }


def test_compatibility_materializer_supports_repositories_without_skills(
    tmp_path: pathlib.Path,
) -> None:
    lifecycle_bundle = tmp_path / "lifecycle-bundle"
    shutil.copytree(REPOSITORY_LIFECYCLE_SOURCE, lifecycle_bundle)
    (
        lifecycle_bundle
        / "scripts"
        / COMPATIBILITY_ENGINE
        / "bootstrap_installer_synchronization.py"
    ).write_text(
        "raise SystemExit('bootstrap synchronizer must not run')\n",
        encoding="utf-8",
        newline="\n",
    )
    engine_scripts = lifecycle_bundle / "scripts"
    repo = tmp_path / "empty-compatible"
    repo.mkdir()
    (repo / ".git").write_text(
        "gitdir: test\n", encoding="utf-8", newline="\n"
    )
    (repo / "README.md").write_text(
        "# Empty Compatible Repository\n\n"
        "## Skills\n\n"
        "| Skill | Purpose |\n"
        "| --- | --- |\n",
        encoding="utf-8",
        newline="\n",
    )
    (repo / "package.json").write_text(
        json.dumps({"scripts": {"lint": "echo lint"}}) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    blocked_result = run_compatibility_engine(
        engine_scripts,
        "materialize",
        "--target-repo-root",
        str(repo),
        "--runtime-source-id",
        "example/empty-compatible",
    )

    assert blocked_result.returncode == 1
    assert json.loads(blocked_result.stdout) == {
        "phase": "materialization_planning",
        "reason": (
            "npm validation checks require package-lock.json for "
            "deterministic npm ci setup"
        ),
        "rollback": "not_started",
        "status": "blocked",
    }
    assert not (repo / "skills").exists()
    assert not (repo / "deploy").exists()
    assert not (repo / "scripts").exists()
    assert not (repo / ".github").exists()

    (repo / "package-lock.json").write_text(
        json.dumps({"lockfileVersion": 3, "requires": True, "packages": {}})
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    result = run_compatibility_engine(
        engine_scripts,
        "materialize",
        "--target-repo-root",
        str(repo),
        "--runtime-source-id",
        "example/empty-compatible",
    )

    assert result.returncode == 0, result.stdout
    manifest = json.loads(
        (repo / "skills" / "skill-sections.json").read_text(encoding="utf-8")
    )
    contract = yaml.safe_load(
        (repo / "deploy" / "deploy.yml").read_text(encoding="utf-8")
    )
    assert manifest["skills"] == {}
    assert manifest["sections"] == {}
    assert json.loads(result.stdout)["bootstrap"] == "skipped"
    assert contract == {
        "version": 1,
        "kind": "ceratops-deploy",
        "operations": {},
    }
    assert not (repo / "skills" / "sections").exists()
    assert not (repo / "scripts" / "install-skills-bootstrap.py").exists()
    output = json.loads(result.stdout)
    assert output["repository_validation"] == {
        "checks": ["npm-lint"],
        "validator": "materialized",
        "workflow": "materialized",
    }
    assert (repo / "scripts" / "validate-repository.py").is_file()
    assert (repo / ".github" / "workflows" / "validate.yml").is_file()
    validation_evidence = tmp_path / "zero-skill-validation.log"
    validation_evidence.write_text("stale failure evidence\n", encoding="utf-8")
    validation_temporary = validation_evidence.with_name(
        f".{validation_evidence.name}.tmp"
    )
    validation_temporary.write_text("stale partial evidence\n", encoding="utf-8")
    validation = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "validate-repository.py"),
            "--evidence-file",
            str(validation_evidence),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert validation.returncode == 0, validation.stdout
    assert validation.stdout == "OK\n"
    assert not validation_evidence.exists()
    assert not validation_temporary.exists()

    omitted = tmp_path / "empty-without-deploy"
    shutil.copytree(repo, omitted)
    (omitted / "deploy" / "deploy.yml").unlink()
    omitted_result = run_compatibility_engine(
        engine_scripts,
        "materialize",
        "--target-repo-root",
        str(omitted),
        "--no-deploy-contract",
    )
    assert omitted_result.returncode == 0, omitted_result.stdout
    assert not (omitted / "deploy" / "deploy.yml").exists()
    assert json.loads(omitted_result.stdout)["repository_validation"] == {
        "checks": [],
        "validator": "preserved",
        "workflow": "preserved",
    }

    def empty_repository(name: str) -> pathlib.Path:
        target = tmp_path / name
        target.mkdir()
        (target / ".git").write_text("gitdir: test\n", encoding="utf-8", newline="\n")
        (target / "README.md").write_text(
            f"# {name}\n\n## Skills\n\n| Skill | Purpose |\n| --- | --- |\n",
            encoding="utf-8",
            newline="\n",
        )
        return target

    pnpm_repo = empty_repository("pnpm-compatible")
    (pnpm_repo / "package.json").write_text(
        json.dumps(
            {
                "packageManager": "pnpm@10.33.4",
                "scripts": {"build": "tsc --noEmit"},
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (pnpm_repo / "pnpm-lock.yaml").write_text(
        "lockfileVersion: '9.0'\n", encoding="utf-8", newline="\n"
    )
    (pnpm_repo / "requirements-dev.txt").write_text(
        "pytest==9.1.1\n", encoding="utf-8", newline="\n"
    )
    (pnpm_repo / "pyproject.toml").write_text(
        '[tool.mypy]\npython_version = "3.12"\n',
        encoding="utf-8",
        newline="\n",
    )
    pnpm_result = run_compatibility_engine(
        engine_scripts,
        "materialize",
        "--target-repo-root",
        str(pnpm_repo),
        "--runtime-source-id",
        "example/pnpm-compatible",
    )
    assert pnpm_result.returncode == 0, pnpm_result.stdout
    assert json.loads(pnpm_result.stdout)["repository_validation"]["checks"] == [
        "pnpm-build",
        "pytest",
        "mypy",
    ]
    pnpm_workflow = (
        pnpm_repo / ".github" / "workflows" / "validate.yml"
    ).read_text(encoding="utf-8")
    assert "actions/setup-node@2028fbc5c25fe9cf00d9f06a71cc4710d4507903" in pnpm_workflow
    assert "corepack prepare pnpm@10.33.4 --activate" in pnpm_workflow
    assert "pnpm install --frozen-lockfile" in pnpm_workflow
    assert "python -m pip install -r requirements-dev.txt" in pnpm_workflow
    assert "python -m pip install mypy==2.3.0" in pnpm_workflow

    uv_repo = empty_repository("uv-compatible")
    (uv_repo / "uv.lock").write_text("version = 1\n", encoding="utf-8", newline="\n")
    (uv_repo / "pyproject.toml").write_text(
        '[project]\nname = "uv-compatible"\nversion = "1.0.0"\n'
        '[project.optional-dependencies]\ndev = ["pytest", "ruff", "mypy"]\n'
        "[tool.pytest.ini_options]\n"
        "[tool.ruff]\n"
        '[tool.mypy]\npython_version = "3.12"\n',
        encoding="utf-8",
        newline="\n",
    )
    uv_result = run_compatibility_engine(
        engine_scripts,
        "materialize",
        "--target-repo-root",
        str(uv_repo),
        "--runtime-source-id",
        "example/uv-compatible",
    )
    assert uv_result.returncode == 0, uv_result.stdout
    assert json.loads(uv_result.stdout)["repository_validation"]["checks"] == [
        "pytest",
        "ruff",
        "mypy",
    ]
    uv_workflow = (uv_repo / ".github" / "workflows" / "validate.yml").read_text(
        encoding="utf-8"
    )
    assert "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9" in uv_workflow
    assert "uv sync --extra dev --frozen" in uv_workflow
    assert "uv run --no-sync python scripts/validate-repository.py" in uv_workflow

    powershell_repo = empty_repository("powershell-compatible")
    for relative in (
        "scripts/Test-CodexSourceReadiness.ps1",
        "scripts/Test-CodexRuntimeHealth.ps1",
        "tests/Run-PowerShellQuality.ps1",
        "tests/Run-SmokeTests.ps1",
    ):
        path = powershell_repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("exit 0\n", encoding="utf-8", newline="\n")
    powershell_result = run_compatibility_engine(
        engine_scripts,
        "materialize",
        "--target-repo-root",
        str(powershell_repo),
        "--runtime-source-id",
        "example/powershell-compatible",
    )
    assert powershell_result.returncode == 0, powershell_result.stdout
    assert json.loads(powershell_result.stdout)["repository_validation"]["checks"] == [
        "powershell-source-readiness",
        "powershell-runtime-health",
        "powershell-lint",
        "powershell-smoke",
    ]
    powershell_workflow = (
        powershell_repo / ".github" / "workflows" / "validate.yml"
    ).read_text(encoding="utf-8")
    assert "runs-on: windows-latest" in powershell_workflow
    assert "Install-Module PSScriptAnalyzer" in powershell_workflow

    unittest_repo = empty_repository("unittest-compatible")
    (unittest_repo / "deploy").mkdir()
    (unittest_repo / "deploy" / "validate-automations.py").write_text(
        "print('OK')\n", encoding="utf-8", newline="\n"
    )
    (unittest_repo / "tests").mkdir()
    (unittest_repo / "tests" / "test_example.py").write_text(
        "import unittest\n", encoding="utf-8", newline="\n"
    )
    unittest_result = run_compatibility_engine(
        engine_scripts,
        "materialize",
        "--target-repo-root",
        str(unittest_repo),
        "--runtime-source-id",
        "example/unittest-compatible",
    )
    assert unittest_result.returncode == 0, unittest_result.stdout
    assert json.loads(unittest_result.stdout)["repository_validation"]["checks"] == [
        "automation-source-validation",
        "unittest",
    ]

    docs_repo = empty_repository("docs-compatible")
    (docs_repo / "README.md").write_text(
        "python -m ruff check --select E9,F63,F7,F82 scripts/run_form.py "
        "skills/claims-catalog-invoice/scripts tests/test_claims_tracker.py\n",
        encoding="utf-8",
        newline="\n",
    )
    (docs_repo / "requirements.txt").write_text(
        "python-docx==1.2.0\n", encoding="utf-8", newline="\n"
    )
    (docs_repo / "scripts").mkdir()
    (docs_repo / "scripts" / "run_form.py").write_text(
        "print('OK')\n", encoding="utf-8", newline="\n"
    )
    (docs_repo / "skills" / "claims-catalog-invoice" / "scripts").mkdir(
        parents=True
    )
    (docs_repo / "skills" / "claims-catalog-invoice" / "scripts" / "claim.py").write_text(
        "CLAIM = True\n", encoding="utf-8", newline="\n"
    )
    (docs_repo / "tests").mkdir()
    (docs_repo / "tests" / "test_claims_tracker.py").write_text(
        "import unittest\n", encoding="utf-8", newline="\n"
    )
    docs_result = run_compatibility_engine(
        engine_scripts,
        "materialize",
        "--target-repo-root",
        str(docs_repo),
        "--runtime-source-id",
        "example/docs-compatible",
    )
    assert docs_result.returncode == 0, docs_result.stdout
    assert json.loads(docs_result.stdout)["repository_validation"]["checks"] == [
        "unittest",
        "ruff-critical",
    ]
    docs_workflow = (
        docs_repo / ".github" / "workflows" / "validate.yml"
    ).read_text(encoding="utf-8")
    assert "ruff==0.16.1" in docs_workflow

    authoritative_repo = empty_repository("authoritative-compatible")
    (authoritative_repo / "scripts").mkdir()
    (authoritative_repo / "scripts" / "validate_repository.py").write_text(
        "import argparse\n"
        "import pathlib\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--temp-root')\n"
        "parser.add_argument('--evidence-file', type=pathlib.Path, required=True)\n"
        "args = parser.parse_args()\n"
        "if not pathlib.Path(args.temp_root).is_dir():\n"
        "    args.evidence_file.write_text('temp root missing\\n', encoding='utf-8')\n"
        "    raise SystemExit(2)\n"
        "args.evidence_file.write_text('inner diagnostic\\n', encoding='utf-8')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
        newline="\n",
    )
    (authoritative_repo / "pyproject.toml").write_text(
        '[tool.mypy]\npython_version = "3.12"\n',
        encoding="utf-8",
        newline="\n",
    )
    authoritative_result = run_compatibility_engine(
        engine_scripts,
        "materialize",
        "--target-repo-root",
        str(authoritative_repo),
        "--runtime-source-id",
        "example/authoritative-compatible",
    )
    assert authoritative_result.returncode == 0, authoritative_result.stdout
    assert json.loads(authoritative_result.stdout)["repository_validation"]["checks"] == [
        "hasbaratops-validator"
    ]
    authoritative_validator = (
        authoritative_repo / "scripts" / "validate-repository.py"
    ).read_text(encoding="utf-8")
    assert "{temp}/hasbaratops" in authoritative_validator
    assert max(len(line) for line in authoritative_validator.splitlines()) <= 100
    authoritative_evidence = tmp_path / "authoritative-validation.log"
    authoritative_validation = subprocess.run(
        [
            sys.executable,
            str(authoritative_repo / "scripts" / "validate-repository.py"),
            "--evidence-file",
            str(authoritative_evidence),
        ],
        cwd=authoritative_repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert authoritative_validation.returncode == 1
    retained_evidence = authoritative_evidence.read_text(encoding="utf-8")
    assert "child_evidence: hasbaratops-validation.log" in retained_evidence
    assert "inner diagnostic" in retained_evidence


def test_compatibility_materializer_preserves_existing_validator_and_ci(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "preserved/source", ["alpha-tool"])
    (repo / ".git").write_text("gitdir: test\n", encoding="utf-8", newline="\n")
    validator = repo / "scripts" / "validate-repository.py"
    validator.write_text(
        "#!/usr/bin/env python3\nprint('target-owned')\n",
        encoding="utf-8",
        newline="\n",
    )
    validator.chmod(0o744)
    workflow = repo / ".github" / "workflows" / "validate.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n"
        "  validate:\n"
        "    steps:\n"
        "      - run: python scripts/validate-repository.py "
        "--evidence-file evidence.log\n",
        encoding="utf-8",
        newline="\n",
    )
    before = {
        path: (path.read_bytes(), path.stat().st_mode)
        for path in (validator, workflow)
    }

    result = run_compatibility_engine(
        REPOSITORY_LIFECYCLE_SCRIPTS,
        "materialize",
        "--target-repo-root",
        str(repo),
    )

    assert result.returncode == 0, result.stdout
    assert {
        path: (path.read_bytes(), path.stat().st_mode)
        for path in (validator, workflow)
    } == before
    assert json.loads(result.stdout)["repository_validation"] == {
        "checks": [],
        "validator": "preserved",
        "workflow": "preserved",
    }


def test_compatibility_materializer_preserves_existing_identity_and_custom_sections(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "preserved/source", ["alpha-tool"])
    (repo / ".git").write_text("gitdir: test\n", encoding="utf-8", newline="\n")
    custom = repo / "skills" / "sections" / "custom.md"
    custom.write_text(
        "## Custom Rules\n\nPreserve this target behavior.\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest_path = repo / "skills" / "skill-sections.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sections"]["custom"] = "skills/sections/custom.md"
    manifest["skills"]["alpha-tool"].append("custom")
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    result = run_compatibility_engine(
        REPOSITORY_LIFECYCLE_SCRIPTS,
        "materialize",
        "--target-repo-root",
        str(repo),
    )

    assert result.returncode == 0, result.stdout
    output = json.loads(result.stdout)
    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert output["runtime_source_id"] == "preserved/source"
    assert output["rollback"] == "not_needed"
    assert updated["runtime_source_id"] == "preserved/source"
    assert updated["sections"]["custom"] == "skills/sections/custom.md"
    assert updated["skills"]["alpha-tool"] == ["core", "custom"]
    assert custom.read_text(encoding="utf-8").endswith(
        "Preserve this target behavior.\n"
    )

    overridden = run_compatibility_engine(
        REPOSITORY_LIFECYCLE_SCRIPTS,
        "materialize",
        "--target-repo-root",
        str(repo),
        "--runtime-source-id",
        "explicit/source",
    )
    assert overridden.returncode == 0, overridden.stdout
    assert json.loads(manifest_path.read_text(encoding="utf-8"))[
        "runtime_source_id"
    ] == "explicit/source"


def test_compatibility_materializer_rolls_back_every_target_write_on_blocker(
    tmp_path: pathlib.Path,
) -> None:
    lifecycle_bundle = tmp_path / "lifecycle-bundle"
    shutil.copytree(REPOSITORY_LIFECYCLE_SOURCE, lifecycle_bundle)
    shutil.copytree(
        ROOT / "skills" / "sections",
        lifecycle_bundle / "skills" / "sections",
    )
    workflow_template = (
        lifecycle_bundle / "references" / "templates" / "validate.yml.tmpl"
    )
    workflow_template.write_text(
        workflow_template.read_text(encoding="utf-8").replace(
            "__VALIDATOR_PYTHON__ scripts/validate-repository.py",
            "__VALIDATOR_PYTHON__ scripts/not-the-repository-validator.py",
        ),
        encoding="utf-8",
        newline="\n",
    )
    engine_scripts = lifecycle_bundle / "scripts"
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "preserved/source", ["alpha-tool"])
    (repo / ".git").write_text("gitdir: test\n", encoding="utf-8", newline="\n")
    skill_md = repo / "skills" / "alpha-tool" / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8")
        + "\n<!-- CERATOPS_SHARED_SECTIONS_START -->\n"
        + "<!-- SECTION SOURCE: skills/sections/core.md -->\n"
        + "## Generated Core\n"
        + "<!-- CERATOPS_SHARED_SECTIONS_END -->\n",
        encoding="utf-8",
        newline="\n",
    )
    changed_paths = (
        skill_md,
        repo / "skills" / "sections" / "core.md",
        repo / "skills" / "skill-sections.json",
        repo / "scripts" / "install-skills-bootstrap.py",
        repo / "deploy" / "deploy.yml",
    )
    original = {path: path.read_bytes() for path in changed_paths}

    result = run_compatibility_engine(
        engine_scripts,
        "materialize",
        "--target-repo-root",
        str(repo),
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["status"] == "blocked"
    assert output["phase"] == "compatibility_validation"
    assert output["rollback"] == "completed"
    assert {path: path.read_bytes() for path in changed_paths} == original
    assert not (repo / "scripts" / "validate-repository.py").exists()
    assert not (repo / ".github" / "workflows" / "validate.yml").exists()


def test_compatibility_materializer_blocks_invalid_assignments_before_writes(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "preserved/source", ["alpha-tool"])
    (repo / ".git").write_text("gitdir: test\n", encoding="utf-8", newline="\n")
    manifest_path = repo / "skills" / "skill-sections.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["skills"]["alpha-tool"].append("missing-section")
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    observed_paths = (
        repo / "skills" / "alpha-tool" / "SKILL.md",
        repo / "skills" / "sections" / "core.md",
        manifest_path,
        repo / "scripts" / "install-skills-bootstrap.py",
        repo / "deploy" / "deploy.yml",
    )
    original = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in observed_paths
    }

    result = run_compatibility_engine(
        REPOSITORY_LIFECYCLE_SCRIPTS,
        "materialize",
        "--target-repo-root",
        str(repo),
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["phase"] == "materialization_planning"
    assert output["rollback"] == "not_started"
    assert {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in observed_paths
    } == original


def test_source_validator_rejects_consecutive_name_hyphens(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha--tool"])

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "alpha--tool: invalid directory name" in result.stderr


@pytest.mark.parametrize(
    ("length", "expected_error"),
    [
        (39, "description is too short"),
        (40, None),
        (1024, None),
        (1025, "description exceeds 1024 characters"),
    ],
)
def test_source_validator_enforces_description_boundaries(
    tmp_path: pathlib.Path,
    length: int,
    expected_error: str | None,
) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    skill_md = repo / "skills" / "alpha-tool" / "SKILL.md"
    lines = skill_md.read_text(encoding="utf-8").splitlines()
    seed = "Manage alpha tool workflows safely across compatible repositories. "
    lines[2] = f"description: {(seed * (length // len(seed) + 1))[:length]}"
    skill_md.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )

    if expected_error is None:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode == 1
        assert expected_error in result.stderr


def test_openai_example_comparison_is_not_a_per_skill_check() -> None:
    contract = json.loads(
        (
            ROOT
            / "skills"
            / "ceratops-skill-lifecycle"
            / "references"
            / "contracts"
            / "skill-nondeterministic-contract.json"
        ).read_text(encoding="utf-8")
    )
    check_ids = {check["id"] for check in contract["checks"]}
    assert "ND.skill.openai-example-comparison" not in check_ids

    action_root = (
        ROOT / "skills" / "ceratops-skill-lifecycle" / "references"
    )
    ownership_phrase = "installed OpenAI skill examples"
    assert ownership_phrase in (
        action_root / "skills-contract-review.md"
    ).read_text(encoding="utf-8")
    assert ownership_phrase not in (
        action_root / "skills-consistency-review.md"
    ).read_text(encoding="utf-8")


def test_multi_action_membership_is_owned_by_the_skill_index(
    tmp_path: pathlib.Path,
) -> None:
    skills_dir = tmp_path / "skills"
    write_multi_action_skill(
        skills_dir,
        "ceratops-repo-lifecycle",
        ["references/merge-pr.md", "references/new-command.md"],
        {
            "references/merge-pr.md": "# Merge PR Action\n\nMerge the ready pull request.\n",
            "references/new-command.md": "# New Command Action\n\nRun the new command.\n",
        },
    )
    validator = load_source_validator(skills_dir)
    manifest = {
        "skills": {
            "ceratops-repo-lifecycle": ["multi-action-skill"],
        }
    }

    assert validator["check_multi_action_skill_contract"](manifest) == []


def test_multi_action_contract_rejects_structural_drift(
    tmp_path: pathlib.Path,
) -> None:
    skills_dir = tmp_path / "skills"
    write_multi_action_skill(
        skills_dir,
        "example-lifecycle",
        [
            "references/first.md",
            "references/first.md",
            "references/missing.md",
        ],
        {
            "references/first.md": "---\n# First Action\n",
            "references/orphan.md": "# Orphan Action\n",
        },
    )
    validator = load_source_validator(skills_dir)
    manifest = {"skills": {"example-lifecycle": ["multi-action-skill"]}}

    errors = validator["check_multi_action_skill_contract"](manifest)

    assert "example-lifecycle: duplicate action reference references/first.md" in errors
    assert "example-lifecycle: missing action reference references/missing.md" in errors
    assert (
        "example-lifecycle: references/first.md still looks like a standalone skill"
        in errors
    )
    assert "example-lifecycle: unlisted action reference references/orphan.md" in errors


def test_full_validation_excludes_git_ignored_files(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    subprocess.run(
        ["git", "init", "--quiet", str(repo)],
        capture_output=True,
        text=True,
        check=True,
    )
    (repo / ".gitignore").write_text(
        ".venv/\nignored-output/\n",
        encoding="utf-8",
        newline="\n",
    )
    for ignored_dir in (repo / ".venv", repo / "ignored-output"):
        ignored_dir.mkdir()
        private_path = chr(92).join(("C:", "Users", "fixture", "generated"))
        (ignored_dir / "generated.md").write_text(
            f"{private_path}\nUse $" + "unknown-skill.\n",
            encoding="utf-8",
            newline="\n",
        )
    (repo / "executable.py").write_text(
        "REFERENCE = '$unknown-skill'\n",
        encoding="utf-8",
        newline="\n",
    )

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok: 1"


def test_full_validation_scans_manifest_runtime_inputs_only(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    runtime_input = repo / "runtime-note.md"
    private_path = chr(92).join(("C:", "Users", "fixture", "private-source"))
    runtime_input.write_text(
        f"Generated from {private_path}.\n",
        encoding="utf-8",
        newline="\n",
    )

    unlisted = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert unlisted.returncode == 0, unlisted.stderr

    manifest_path = repo / "skills" / "skill-sections.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtime_payloads"] = {"alpha-tool": ["runtime-note.md"]}
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    listed = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert listed.returncode == 1
    assert "runtime-note.md: high-confidence secret or private path pattern" in listed.stderr


def test_full_install_removes_only_same_source_stale_skills(tmp_path: pathlib.Path) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo_a, "example/source-a", ["alpha-tool", "retired-tool"])
    create_compatible_repo(repo_b, "example/source-b", ["beta-tool"])

    assert run_builder(repo_a, install_root, "--all-managed").returncode == 0
    assert run_builder(repo_b, install_root, "--all-managed").returncode == 0
    shutil.rmtree(repo_a / "skills" / "retired-tool")
    write_manifest(repo_a, "example/source-a")

    result = run_builder(repo_a, install_root, "--all-managed")

    assert result.returncode == 0, result.stderr
    assert not (install_root / "retired-tool").exists()
    assert runtime_owner(install_root, "alpha-tool") == "example/source-a"
    assert runtime_owner(install_root, "beta-tool") == "example/source-b"


def test_targeted_install_keeps_stale_and_rejects_other_source_collision(tmp_path: pathlib.Path) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo_a, "example/source-a", ["alpha-tool", "retired-tool"])
    create_compatible_repo(repo_b, "example/source-b", ["beta-tool"])
    assert run_builder(repo_a, install_root, "--all-managed").returncode == 0
    assert run_builder(repo_b, install_root, "--all-managed").returncode == 0

    shutil.rmtree(repo_a / "skills" / "retired-tool")
    write_manifest(repo_a, "example/source-a")
    targeted = run_builder(repo_a, install_root, "--skill", "alpha-tool")
    assert targeted.returncode == 0, targeted.stderr
    assert (install_root / "retired-tool").is_dir()

    add_skill(repo_b, "alpha-tool")
    write_manifest(repo_b, "example/source-b")
    collision = run_builder(repo_b, install_root, "--skill", "alpha-tool")
    assert collision.returncode == 1
    assert "owned by 'example/source-a'" in collision.stderr
    assert runtime_owner(install_root, "alpha-tool") == "example/source-a"

    unmanaged = install_root / "unmanaged-tool"
    unmanaged.mkdir()
    (unmanaged / "sentinel.txt").write_text("keep\n", encoding="utf-8")
    add_skill(repo_b, "unmanaged-tool")
    write_manifest(repo_b, "example/source-b")
    unmanaged_collision = run_builder(repo_b, install_root, "--skill", "unmanaged-tool")
    assert unmanaged_collision.returncode == 1
    assert "unmanaged runtime skill folder" in unmanaged_collision.stderr
    assert (unmanaged / "sentinel.txt").is_file()

    legacy = install_root / "legacy-tool"
    legacy.mkdir()
    (legacy / RUNTIME_MANIFEST).write_text(
        json.dumps({"schema": "ceratops-runtime-skill.v2", "skill": "legacy-tool"}) + "\n",
        encoding="utf-8",
    )
    add_skill(repo_b, "legacy-tool")
    write_manifest(repo_b, "example/source-b")
    legacy_collision = run_builder(repo_b, install_root, "--skill", "legacy-tool")
    assert legacy_collision.returncode == 1
    assert "unsupported ownership manifest" in legacy_collision.stderr


def test_transaction_stages_complete_batch_before_canonical_mutation(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool", "beta-tool"])
    assert run_builder(repo, install_root, "--all-managed").returncode == 0
    before = {
        name: runtime_skill_text(install_root, name)
        for name in ("alpha-tool", "beta-tool")
    }
    for name in before:
        source = repo / "skills" / name / "SKILL.md"
        source.write_text(
            source.read_text(encoding="utf-8") + f"\nUpdated {name}.\n",
            encoding="utf-8",
            newline="\n",
        )

    builder = load_runtime_builder()
    original_write = builder["write_expected_skill"]
    observed: list[tuple[str, dict[str, str]]] = []

    def traced_write(skill: str, *args: object, **kwargs: object) -> None:
        observed.append(
            (
                skill,
                {
                    name: runtime_skill_text(install_root, name)
                    for name in before
                },
            )
        )
        original_write(skill, *args, **kwargs)

    monkeypatch.setitem(
        builder["install_transaction"].__globals__,
        "write_expected_skill",
        traced_write,
    )
    result = builder["install_transaction"](
        repo,
        install_root,
        selected=("alpha-tool", "beta-tool"),
    )

    assert result.status == "ok"
    assert [skill for skill, _ in observed] == ["alpha-tool", "beta-tool"]
    assert all(snapshot == before for _, snapshot in observed)
    assert all(
        f"Updated {name}." in runtime_skill_text(install_root, name)
        for name in before
    )


def test_transaction_staging_or_activation_failure_restores_prior_batch(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool", "beta-tool"])
    assert run_builder(repo, install_root, "--all-managed").returncode == 0
    before = {
        name: runtime_skill_text(install_root, name)
        for name in ("alpha-tool", "beta-tool")
    }
    for name in before:
        source = repo / "skills" / name / "SKILL.md"
        source.write_text(
            source.read_text(encoding="utf-8") + "\nChanged.\n",
            encoding="utf-8",
            newline="\n",
        )

    staging_builder = load_runtime_builder()
    original_write = staging_builder["write_expected_skill"]

    def fail_second_stage(skill: str, *args: object, **kwargs: object) -> None:
        if skill == "beta-tool":
            raise OSError("staging failed")
        original_write(skill, *args, **kwargs)

    monkeypatch.setitem(
        staging_builder["install_transaction"].__globals__,
        "write_expected_skill",
        fail_second_stage,
    )
    with pytest.raises(staging_builder["TransactionError"]) as staging_error:
        staging_builder["install_transaction"](
            repo,
            install_root,
            selected=("alpha-tool", "beta-tool"),
        )
    assert staging_error.value.phase == "staging"
    assert staging_error.value.rollback_state == "complete"
    assert {
        name: runtime_skill_text(install_root, name)
        for name in before
    } == before
    assert not list(install_root.glob(".*-deployed-*"))

    activation_builder = load_runtime_builder()
    original_rename = activation_builder["rename_with_retry"]

    def fail_second_activation(
        source: pathlib.Path, target: pathlib.Path
    ) -> None:
        if source.name.startswith(".beta-tool-deployed-"):
            raise PermissionError("activation denied")
        original_rename(source, target)

    monkeypatch.setitem(
        activation_builder["install_transaction"].__globals__,
        "rename_with_retry",
        fail_second_activation,
    )
    with pytest.raises(activation_builder["TransactionError"]) as activation_error:
        activation_builder["install_transaction"](
            repo,
            install_root,
            selected=("alpha-tool", "beta-tool"),
        )
    assert activation_error.value.phase == "activation"
    assert activation_error.value.rollback_state == "complete"
    assert {
        name: runtime_skill_text(install_root, name)
        for name in before
    } == before


def test_transaction_retry_policy_and_acl_order(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = load_runtime_builder()

    class RenameError(OSError):
        winerror: int

    class RenameProbe:
        def __init__(self, failures: int, *, transient: bool) -> None:
            self.failures = failures
            self.transient = transient
            self.calls = 0

        def replace(self, _target: object) -> None:
            self.calls += 1
            if self.calls <= self.failures:
                error = RenameError(
                    errno.EBUSY if self.transient else errno.EACCES,
                    "rename failure",
                )
                error.winerror = 32 if self.transient else 5
                raise error

    monkeypatch.setattr(builder["time"], "sleep", lambda _seconds: None)
    transient = RenameProbe(2, transient=True)
    builder["rename_with_retry"](transient, pathlib.Path("unused"))
    assert transient.calls == 3
    permanent = RenameProbe(2, transient=False)
    with pytest.raises(OSError):
        builder["rename_with_retry"](permanent, pathlib.Path("unused"))
    assert permanent.calls == 1

    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    order: list[str] = []
    original_rename = builder["rename_with_retry"]

    def record_acl(path: pathlib.Path) -> None:
        order.append(f"acl:{path.name}")

    def record_rename(source: pathlib.Path, target: pathlib.Path) -> None:
        if "-deployed-" in source.name:
            order.append(f"activate:{source.name}")
        original_rename(source, target)

    monkeypatch.setitem(
        builder["install_transaction"].__globals__,
        "enable_windows_acl_inheritance",
        record_acl,
    )
    monkeypatch.setitem(
        builder["install_transaction"].__globals__,
        "rename_with_retry",
        record_rename,
    )
    builder["install_transaction"](
        repo,
        install_root,
        selected=("alpha-tool",),
    )
    assert order[0].startswith("acl:.alpha-tool-deployed-")
    assert order[1].startswith("activate:.alpha-tool-deployed-")


def test_transaction_recovers_interrupted_and_blocks_ambiguous_remnants(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool", "beta-tool"])
    assert run_builder(repo, install_root, "--all-managed").returncode == 0
    source = repo / "skills" / "alpha-tool" / "SKILL.md"
    source.write_text(
        source.read_text(encoding="utf-8") + "\nRecovered update.\n",
        encoding="utf-8",
        newline="\n",
    )
    builder = load_runtime_builder()
    builder["configure_repo"](repo)
    manifest = builder["load_manifest"]()
    transaction = "a" * 32
    retired = install_root / f".alpha-tool-retired-{transaction}"
    deployed = install_root / f".alpha-tool-deployed-{transaction}"
    (install_root / "alpha-tool").replace(retired)
    builder["write_expected_skill"](
        "alpha-tool",
        deployed,
        manifest,
    )

    recovered = builder["install_transaction"](
        repo,
        install_root,
        selected=("alpha-tool",),
    )

    assert recovered.status == "ok"
    assert "Recovered update." in runtime_skill_text(install_root, "alpha-tool")
    assert not retired.exists()
    assert not deployed.exists()

    ambiguous = install_root / f".alpha-tool-retired-{'b' * 32}"
    (install_root / "alpha-tool").replace(ambiguous)
    with pytest.raises(builder["TransactionError"]) as blocked:
        builder["install_transaction"](
            repo,
            install_root,
            selected=("beta-tool",),
        )
    assert blocked.value.phase == "recovery"
    assert "same affected set" in str(blocked.value)


def test_transaction_rejects_conflicting_remnant_ids(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    assert run_builder(repo, install_root, "--all-managed").returncode == 0
    for transaction in ("c" * 32, "d" * 32):
        shutil.copytree(
            install_root / "alpha-tool",
            install_root / f".alpha-tool-retired-{transaction}",
        )
    builder = load_runtime_builder()

    with pytest.raises(builder["TransactionError"]) as blocked:
        builder["install_transaction"](
            repo,
            install_root,
            selected=("alpha-tool",),
        )

    assert blocked.value.phase == "recovery"
    assert "conflicting transaction IDs" in str(blocked.value)


def test_transaction_supports_explicit_add_remove_and_rename(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool", "old-tool"])
    assert run_builder(repo, install_root, "--all-managed").returncode == 0

    add_skill(repo, "beta-tool")
    write_manifest(repo, "example/compatible")
    added = run_builder(repo, install_root, "--skill", "beta-tool")
    assert added.returncode == 0, added.stderr
    assert (install_root / "beta-tool").is_dir()

    shutil.rmtree(repo / "skills" / "old-tool")
    write_manifest(repo, "example/compatible")
    removed = run_builder(repo, install_root, "--remove-skill", "old-tool")
    assert removed.returncode == 0, removed.stderr
    assert not (install_root / "old-tool").exists()

    (repo / "skills" / "alpha-tool").replace(repo / "skills" / "renamed-tool")
    skill_md = repo / "skills" / "renamed-tool" / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8").replace(
            "name: alpha-tool", "name: renamed-tool"
        ),
        encoding="utf-8",
        newline="\n",
    )
    write_manifest(repo, "example/compatible")
    renamed = run_builder(
        repo,
        install_root,
        "--skill",
        "renamed-tool",
        "--remove-skill",
        "alpha-tool",
    )
    assert renamed.returncode == 0, renamed.stderr
    assert (install_root / "renamed-tool").is_dir()
    assert not (install_root / "alpha-tool").exists()


def test_base_revision_resolves_structured_add_remove_rename_and_sections(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(
        repo,
        "example/compatible",
        ["alpha-tool", "beta-tool", "old-tool"],
    )
    assert run_git(repo, "init", "-b", "main").returncode == 0
    assert run_git(repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(repo, "config", "user.name", "Test Agent").returncode == 0
    assert run_git(repo, "add", ".").returncode == 0
    assert run_git(repo, "commit", "-m", "base").returncode == 0
    base = run_git(repo, "rev-parse", "HEAD").stdout.strip()

    (repo / "skills" / "old-tool").replace(repo / "skills" / "renamed-tool")
    renamed_skill = repo / "skills" / "renamed-tool" / "SKILL.md"
    renamed_skill.write_text(
        renamed_skill.read_text(encoding="utf-8").replace(
            "name: old-tool", "name: renamed-tool"
        ),
        encoding="utf-8",
        newline="\n",
    )
    section = repo / "skills" / "sections" / "core.md"
    section.write_text(
        section.read_text(encoding="utf-8") + "\nUpdated shared rule.\n",
        encoding="utf-8",
        newline="\n",
    )
    write_manifest(repo, "example/compatible")
    assert run_git(repo, "add", "-A").returncode == 0
    assert run_git(repo, "commit", "-m", "rename and section").returncode == 0
    installer = load_runtime_installer()

    affected = installer["affected_from_base"](repo, base)

    assert affected.deploy == ("alpha-tool", "beta-tool", "renamed-tool")
    assert affected.remove == ("old-tool",)
    assert affected.all_managed is False


def test_base_revision_resolves_payload_global_and_ambiguous_changes(
    tmp_path: pathlib.Path,
) -> None:
    installer = load_runtime_installer()

    payload_repo = tmp_path / "payload"
    create_compatible_repo(
        payload_repo,
        "example/payload",
        ["alpha-tool", "beta-tool"],
    )
    payload = payload_repo / "payload-alpha.txt"
    payload.write_text("one\n", encoding="utf-8", newline="\n")
    manifest_path = payload_repo / "skills" / "skill-sections.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtime_payloads"] = {"alpha-tool": ["payload-alpha.txt"]}
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(payload_repo, "init", "-b", "main").returncode == 0
    assert run_git(payload_repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(payload_repo, "config", "user.name", "Test Agent").returncode == 0
    assert run_git(payload_repo, "add", ".").returncode == 0
    assert run_git(payload_repo, "commit", "-m", "base").returncode == 0
    payload_base = run_git(payload_repo, "rev-parse", "HEAD").stdout.strip()
    payload.write_text("two\n", encoding="utf-8", newline="\n")
    with pytest.raises(installer["DecisionRequired"], match="clean checkout"):
        installer["affected_from_base"](payload_repo, payload_base)
    assert run_git(payload_repo, "add", "payload-alpha.txt").returncode == 0
    assert run_git(payload_repo, "commit", "-m", "payload").returncode == 0

    payload_affected = installer["affected_from_base"](
        payload_repo, payload_base
    )
    assert payload_affected.deploy == ("alpha-tool",)
    assert payload_affected.remove == ()
    assert payload_affected.all_managed is False
    wildcard_base = run_git(payload_repo, "rev-parse", "HEAD").stdout.strip()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtime_payloads"] = {"*": ["payload-alpha.txt"]}
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(payload_repo, "add", "skills/skill-sections.json").returncode == 0
    assert run_git(payload_repo, "commit", "-m", "wildcard payload").returncode == 0
    wildcard_affected = installer["affected_from_base"](
        payload_repo, wildcard_base
    )
    assert wildcard_affected.deploy == ("alpha-tool", "beta-tool")
    assert wildcard_affected.all_managed is True

    global_repo = tmp_path / "global"
    create_compatible_repo(
        global_repo,
        "example/global",
        ["alpha-tool", "beta-tool"],
    )
    assert run_git(global_repo, "init", "-b", "main").returncode == 0
    assert run_git(global_repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(global_repo, "config", "user.name", "Test Agent").returncode == 0
    assert run_git(global_repo, "add", ".").returncode == 0
    assert run_git(global_repo, "commit", "-m", "base").returncode == 0
    global_base = run_git(global_repo, "rev-parse", "HEAD").stdout.strip()
    bootstrap = global_repo / "scripts" / "install-skills-bootstrap.py"
    bootstrap.write_text(
        bootstrap.read_text(encoding="utf-8") + "\n# changed generator\n",
        encoding="utf-8",
        newline="\n",
    )
    assert (
        run_git(
            global_repo,
            "add",
            "scripts/install-skills-bootstrap.py",
        ).returncode
        == 0
    )
    assert run_git(global_repo, "commit", "-m", "global").returncode == 0
    global_affected = installer["affected_from_base"](global_repo, global_base)
    assert global_affected.deploy == ("alpha-tool", "beta-tool")
    assert global_affected.all_managed is True
    global_install_root = tmp_path / "global-installed"
    global_install = subprocess.run(
        [
            sys.executable,
            str(RUNTIME_INSTALLER),
            "--repo-root",
            str(global_repo),
            "--install-root",
            str(global_install_root),
            "--base-revision",
            global_base,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert global_install.returncode == 0, global_install.stderr
    assert {
        path.name
        for path in global_install_root.iterdir()
        if not path.name.startswith(".")
    } == {"alpha-tool", "beta-tool"}

    ambiguous_repo = tmp_path / "ambiguous"
    create_compatible_repo(ambiguous_repo, "example/ambiguous", ["alpha-tool"])
    assert run_git(ambiguous_repo, "init", "-b", "main").returncode == 0
    assert run_git(ambiguous_repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(ambiguous_repo, "config", "user.name", "Test Agent").returncode == 0
    assert run_git(ambiguous_repo, "add", ".").returncode == 0
    assert run_git(ambiguous_repo, "commit", "-m", "base").returncode == 0
    ambiguous_base = run_git(ambiguous_repo, "rev-parse", "HEAD").stdout.strip()
    ambiguous_manifest = ambiguous_repo / "skills" / "skill-sections.json"
    value = json.loads(ambiguous_manifest.read_text(encoding="utf-8"))
    value["unowned_effect"] = {"value": True}
    ambiguous_manifest.write_text(
        json.dumps(value, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(ambiguous_repo, "add", "skills/skill-sections.json").returncode == 0
    assert run_git(ambiguous_repo, "commit", "-m", "ambiguous").returncode == 0
    with pytest.raises(installer["DecisionRequired"]):
        installer["affected_from_base"](ambiguous_repo, ambiguous_base)


def test_transaction_hard_crash_converges_only_matching_scope(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool", "beta-tool"])
    assert run_builder(repo, install_root, "--skill", "alpha-tool").returncode == 0
    builder = load_runtime_builder()
    builder["configure_repo"](repo)
    manifest = builder["load_manifest"]()
    builder["write_expected_skill"](
        "beta-tool",
        install_root / "beta-tool",
        manifest,
    )
    source = repo / "skills" / "beta-tool" / "SKILL.md"
    source.write_text(
        source.read_text(encoding="utf-8") + "\nAfter crash.\n",
        encoding="utf-8",
        newline="\n",
    )

    unrelated = run_builder(repo, install_root, "--skill", "alpha-tool")
    assert unrelated.returncode == 0, unrelated.stderr
    assert "After crash." not in runtime_skill_text(install_root, "beta-tool")

    matching = run_builder(repo, install_root, "--skill", "beta-tool")
    assert matching.returncode == 0, matching.stderr
    assert "After crash." in runtime_skill_text(install_root, "beta-tool")


def test_transaction_cleanup_blocker_keeps_new_batch_and_serializes_writers(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    assert run_builder(repo, install_root, "--all-managed").returncode == 0
    source = repo / "skills" / "alpha-tool" / "SKILL.md"
    source.write_text(
        source.read_text(encoding="utf-8") + "\nCommitted update.\n",
        encoding="utf-8",
        newline="\n",
    )
    builder = load_runtime_builder()
    original_remove = builder["_remove_tree"]

    def block_retired(path: pathlib.Path, root: pathlib.Path) -> None:
        if "-retired-" in path.name:
            raise PermissionError("cleanup blocked")
        original_remove(path, root)

    monkeypatch.setitem(
        builder["install_transaction"].__globals__,
        "_remove_tree",
        block_retired,
    )
    result = builder["install_transaction"](
        repo,
        install_root,
        selected=("alpha-tool",),
    )
    assert result.status == "cleanup_blocked"
    assert "Committed update." in runtime_skill_text(install_root, "alpha-tool")
    assert result.retained_retired
    monkeypatch.setitem(
        builder["install_transaction"].__globals__,
        "_remove_tree",
        original_remove,
    )
    recovered = builder["install_transaction"](
        repo,
        install_root,
        selected=("alpha-tool",),
    )
    assert recovered.status == "ok"
    assert not list(install_root.glob(".*-retired-*"))

    lock_builder = load_runtime_builder()
    errors: list[BaseException] = []

    def competing_install() -> None:
        try:
            lock_builder["install_transaction"](
                repo,
                install_root,
                selected=("alpha-tool",),
            )
        except BaseException as exc:
            errors.append(exc)

    with lock_builder["runtime_lock"](install_root):
        thread = threading.Thread(target=competing_install)
        thread.start()
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], lock_builder["InstallBusy"])


def test_external_installer_needs_no_ceratops_bundle(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    codex_home = tmp_path / "codex-home"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/external", ["alpha-tool"])
    env = {**os.environ, "CODEX_HOME": str(codex_home)}

    result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "install-skills-bootstrap.py"),
            "--repo-root",
            str(repo),
            "--install-root",
            str(install_root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert runtime_owner(install_root, "alpha-tool") == "example/external"


def test_external_installer_rejects_unresolved_or_malformed_input_without_fallback(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    codex_home = tmp_path / "codex-home"
    install_root = tmp_path / "installed"
    installed_bundle = codex_home / "skills" / "ceratops-skill-lifecycle"
    create_compatible_repo(repo, "example/external", ["alpha-tool"])
    shutil.copytree(LIFECYCLE_SOURCE, installed_bundle)
    (installed_bundle / "scripts" / "runtime" / "install-managed-skills.py").write_text(
        "raise SystemExit('installed runtime was selected')\n",
        encoding="utf-8",
        newline="\n",
    )
    environment = {**os.environ, "CODEX_HOME": str(codex_home)}
    manifest_path = repo / "skills" / "skill-sections.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["skills"]["alpha-tool"] = ["missing-section"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    unresolved = subprocess.run(
        [sys.executable, str(repo / "scripts" / "install-skills-bootstrap.py"), "--repo-root", str(repo), "--install-root", str(install_root)],
        capture_output=True, text=True, check=False, env=environment,
    )
    assert unresolved.returncode != 0
    assert "unresolved section" in unresolved.stderr
    assert install_root.is_dir()
    assert not list(install_root.iterdir())

    manifest_path.write_text("[]\n", encoding="utf-8", newline="\n")
    malformed = subprocess.run(
        [sys.executable, str(repo / "scripts" / "install-skills-bootstrap.py"), "--repo-root", str(repo), "--install-root", str(install_root)],
        capture_output=True, text=True, check=False, env=environment,
    )
    assert malformed.returncode != 0
    assert "must contain an object" in malformed.stderr
    assert "installed runtime was selected" not in malformed.stderr


def test_bootstrap_never_calls_installed_lifecycle(
    tmp_path: pathlib.Path,
) -> None:
    codex_home = tmp_path / "codex-home"
    install_root = tmp_path / "installed"
    installed_bundle = codex_home / "skills" / "ceratops-skill-lifecycle"
    shutil.copytree(LIFECYCLE_SOURCE, installed_bundle)
    marker = tmp_path / "runtime-selected.txt"
    installed_runtime = (
        installed_bundle / "scripts" / "runtime" / "install-managed-skills.py"
    )
    installed_runtime.write_text(
        "import pathlib\n"
        f"pathlib.Path({str(marker)!r}).write_text(__file__, encoding='utf-8')\n",
        encoding="utf-8",
        newline="\n",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP),
            "--repo-root",
            str(ROOT),
            "--install-root",
            str(install_root),
            "--skill",
            "ceratops-skill-lifecycle",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )

    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert runtime_owner(
        install_root, "ceratops-skill-lifecycle"
    ) == "Ceratops-Code/AI-Agent-Skills"


def test_bootstrap_is_first_install_only_and_cleans_owned_state(
    tmp_path: pathlib.Path,
) -> None:
    codex_home = tmp_path / "codex-home"
    install_root = tmp_path / "installed"
    installed_bundle = codex_home / "skills" / "ceratops-skill-lifecycle"
    shutil.copytree(LIFECYCLE_SOURCE, installed_bundle)
    installed_runtime = (
        installed_bundle / "scripts" / "runtime" / "install-managed-skills.py"
    )
    installed_runtime.write_text(
        "raise SystemExit('installed runtime failed')\n",
        encoding="utf-8",
        newline="\n",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP),
            "--repo-root",
            str(ROOT),
            "--install-root",
            str(install_root),
            "--skill",
            "ceratops-skill-lifecycle",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )

    assert result.returncode == 0, result.stderr
    assert runtime_owner(install_root, "ceratops-skill-lifecycle") == (
        "Ceratops-Code/AI-Agent-Skills"
    )
    repeated = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP),
            "--repo-root",
            str(ROOT),
            "--install-root",
            str(install_root),
            "--skill",
            "ceratops-skill-lifecycle",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )
    assert repeated.returncode == 1
    assert "bootstrap is first-install-only" in repeated.stderr
    assert not list(install_root.glob(".ceratops-bootstrap*"))


def test_bootstrap_rejects_undeclared_selection_without_runtime_fallback(
    tmp_path: pathlib.Path,
) -> None:
    codex_home = tmp_path / "codex-home"
    installed_bundle = codex_home / "skills" / "ceratops-skill-lifecycle"
    shutil.copytree(LIFECYCLE_SOURCE, installed_bundle)
    installed_runtime = (
        installed_bundle / "scripts" / "runtime" / "install-managed-skills.py"
    )
    installed_runtime.write_text(
        "raise SystemExit('installed runtime failed')\n",
        encoding="utf-8",
        newline="\n",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP),
            "--repo-root",
            str(ROOT),
            "--install-root",
            str(tmp_path / "installed"),
            "--skill",
            "undeclared-skill",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )

    assert result.returncode != 0
    assert "undeclared skill" in result.stderr
    assert "installed runtime failed" not in result.stderr


def test_bootstrap_full_install_materializes_self_contained_lifecycle_bundle(
    tmp_path: pathlib.Path,
) -> None:
    codex_home = tmp_path / "empty-codex-home"
    install_root = tmp_path / "installed"
    env = {**os.environ, "CODEX_HOME": str(codex_home)}

    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP),
            "--repo-root",
            str(ROOT),
            "--install-root",
            str(install_root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert runtime_owner(install_root, "ceratops-repo-lifecycle") == "Ceratops-Code/AI-Agent-Skills"
    installed_lifecycle = install_root / "ceratops-repo-lifecycle"
    assert (
        installed_lifecycle
        / "references"
        / "templates"
        / "skill-sections-template.json"
    ).is_file()
    assert (installed_lifecycle / "skills" / "sections" / "core.md").is_file()
    assert (
        installed_lifecycle / "skills" / "sections" / "multi-action-skill.md"
    ).is_file()
    assert (
        installed_lifecycle
        / "references"
        / "schemas"
        / "deploy-contract.schema.json"
    ).is_file()
    assert (
        installed_lifecycle / "scripts" / COMPATIBILITY_ENGINE / "__main__.py"
    ).is_file()
    target_repo = tmp_path / "installed-bundle-target"
    create_compatible_repo(target_repo, "stale/source", ["alpha-tool"])
    (target_repo / ".git").write_text(
        "gitdir: test\n", encoding="utf-8", newline="\n"
    )
    shutil.rmtree(target_repo / "skills" / "sections")
    (target_repo / "skills" / "skill-sections.json").unlink()
    materialized = run_compatibility_engine(
        installed_lifecycle / "scripts",
        "materialize",
        "--target-repo-root",
        str(target_repo),
        "--runtime-source-id",
        "installed/target",
    )
    assert materialized.returncode == 0, materialized.stdout
    assert json.loads(materialized.stdout)["runtime_source_id"] == "installed/target"

    other_checkout = tmp_path / "other-checkout"
    other_checkout.mkdir()
    rejected = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP),
            "--repo-root",
            str(other_checkout),
            "--install-root",
            str(tmp_path / "rejected-install"),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert rejected.returncode != 0
    assert "skill-sections.json" in rejected.stderr
    assert not (tmp_path / "rejected-install").exists()


def test_lifecycle_only_installed_bundle_materializes_compatible_repo(
    tmp_path: pathlib.Path,
) -> None:
    codex_home = tmp_path / "empty-codex-home"
    install_root = tmp_path / "installed"
    target_repo = tmp_path / "target"
    installed = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP),
            "--repo-root",
            str(ROOT),
            "--install-root",
            str(install_root),
            "--skill",
            "ceratops-repo-lifecycle",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )
    assert installed.returncode == 0, installed.stderr
    create_compatible_repo(target_repo, "stale/source", ["alpha-tool"])
    (target_repo / ".git").write_text(
        "gitdir: test\n", encoding="utf-8", newline="\n"
    )
    shutil.rmtree(target_repo / "skills" / "sections")
    (target_repo / "skills" / "skill-sections.json").unlink()

    result = run_compatibility_engine(
        install_root / "ceratops-repo-lifecycle" / "scripts",
        "materialize",
        "--target-repo-root",
        str(target_repo),
        "--runtime-source-id",
        "installed/only",
    )

    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["runtime_source_id"] == "installed/only"


def test_bootstrap_ignores_stale_broken_installed_bundle(
    tmp_path: pathlib.Path,
) -> None:
    codex_home = tmp_path / "codex-home"
    install_root = tmp_path / "installed"
    installed_bundle = codex_home / "skills" / "ceratops-skill-lifecycle"
    repository_bundle = codex_home / "skills" / "ceratops-repo-lifecycle"
    shutil.copytree(LIFECYCLE_SOURCE, installed_bundle)
    shutil.copytree(
        REPOSITORY_LIFECYCLE_SOURCE,
        repository_bundle,
    )
    install_bundle_manifest(installed_bundle)
    installed_runtime = installed_bundle / "scripts" / "runtime" / "install-managed-skills.py"
    installed_runtime.write_text(
        "raise SystemExit('broken installed runtime was selected')\n",
        encoding="utf-8",
        newline="\n",
    )

    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/external", ["alpha-tool"])
    result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "install-skills-bootstrap.py"),
            "--repo-root",
            str(repo),
            "--install-root",
            str(install_root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )

    assert result.returncode == 0, result.stderr
    assert runtime_owner(install_root, "alpha-tool") == "example/external"


def test_runtime_manifest_uses_schema_without_installer_version(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])

    result = run_builder(repo, install_root, "--skill", "alpha-tool")

    assert result.returncode == 0, result.stderr
    manifest = json.loads((install_root / "alpha-tool" / RUNTIME_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["schema"] == RUNTIME_MANIFEST_SCHEMA
    assert manifest["skill"] == "alpha-tool"
    assert manifest["runtime_source_id"] == "example/compatible"
    assert manifest["source_path"] == "skills/alpha-tool"
    assert manifest["source_repository_root"] == str(repo.resolve())
    assert manifest["validation_profile"] == "ceratops-compatible"
    assert "installer_version" not in manifest


def test_full_install_does_not_run_source_validation(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    codex_home = tmp_path / "codex-home"
    install_root = tmp_path / "installed"
    installed_bundle = codex_home / "skills" / "ceratops-skill-lifecycle"
    repository_bundle = codex_home / "skills" / "ceratops-repo-lifecycle"
    create_compatible_repo(repo, "example/external", ["alpha-tool"])
    shutil.copytree(LIFECYCLE_SOURCE, installed_bundle)
    shutil.copytree(
        REPOSITORY_LIFECYCLE_SOURCE,
        repository_bundle,
    )
    install_bundle_manifest(installed_bundle)
    (repo / "README.md").write_text("# Invalid\n", encoding="utf-8", newline="\n")
    (
        installed_bundle / "scripts" / "skills-consistency-source-validator.py"
    ).write_text(
        "raise SystemExit('source validator must not run during installation')\n",
        encoding="utf-8",
        newline="\n",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "install-skills-bootstrap.py"),
            "--repo-root",
            str(repo),
            "--install-root",
            str(install_root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )

    assert result.returncode == 0, result.stderr
    assert (install_root / "alpha-tool" / "SKILL.md").is_file()


def test_targeted_install_checks_only_selected_rendering_inputs(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    codex_home = tmp_path / "codex-home"
    install_root = tmp_path / "installed"
    installed_bundle = codex_home / "skills" / "ceratops-skill-lifecycle"
    create_compatible_repo(repo, "example/external", ["alpha-tool", "broken-tool"])
    shutil.copytree(LIFECYCLE_SOURCE, installed_bundle)
    shutil.copytree(
        REPOSITORY_LIFECYCLE_SOURCE,
        codex_home / "skills" / "ceratops-repo-lifecycle",
    )
    install_bundle_manifest(installed_bundle)
    (repo / "skills" / "broken-tool" / "SKILL.md").write_text("invalid\n", encoding="utf-8", newline="\n")

    result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "install-skills-bootstrap.py"),
            "--repo-root",
            str(repo),
            "--install-root",
            str(install_root),
            "--skill",
            "alpha-tool",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )

    assert result.returncode == 0, result.stderr
    assert (install_root / "alpha-tool" / "SKILL.md").is_file()
    assert not (install_root / "broken-tool").exists()

    (repo / "skills" / "alpha-tool" / "SKILL.md").write_text("invalid\n", encoding="utf-8", newline="\n")
    invalid_selected = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "install-skills-bootstrap.py"),
            "--repo-root",
            str(repo),
            "--install-root",
            str(tmp_path / "invalid-installed"),
            "--skill",
            "alpha-tool",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )

    assert invalid_selected.returncode == 1
    assert "missing frontmatter" in invalid_selected.stderr
    assert (install_root / "alpha-tool" / "SKILL.md").is_file()


def test_bootstrap_synchronization_compares_only_version(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: test\n", encoding="utf-8", newline="\n")
    (repo / "scripts").mkdir()
    target = repo / "scripts" / "install-skills-bootstrap.py"
    shutil.copy2(INSTALLER_TEMPLATE, target)
    custom = target.read_text(encoding="utf-8") + "\n# same-version local difference\n"
    target.write_text(custom, encoding="utf-8", newline="\n")

    retained = run_compatibility_engine(
        REPOSITORY_LIFECYCLE_SCRIPTS,
        "synchronize-bootstrap",
        "--target-repo-root",
        str(repo),
    )

    assert retained.returncode == 0, retained.stderr
    assert json.loads(retained.stdout)["status"] == "retained"
    assert target.read_text(encoding="utf-8") == custom

    target.write_text(
        custom.replace(
            f"INSTALLER_VERSION = {INSTALLER_VERSION}", "INSTALLER_VERSION = 0"
        ),
        encoding="utf-8",
        newline="\n",
    )
    updated = run_compatibility_engine(
        REPOSITORY_LIFECYCLE_SCRIPTS,
        "synchronize-bootstrap",
        "--target-repo-root",
        str(repo),
    )

    assert updated.returncode == 0, updated.stderr
    assert json.loads(updated.stdout)["status"] == "updated"
    assert target.read_bytes() == INSTALLER_TEMPLATE.read_bytes()

    help_result = run_compatibility_engine(
        REPOSITORY_LIFECYCLE_SCRIPTS,
        "synchronize-bootstrap",
        "--help",
    )
    assert help_result.returncode == 0
    assert "--target-repo-root" in help_result.stdout
    assert "--validate-only" not in help_result.stdout


def test_bootstrap_copies_declare_the_same_explicit_version(
    tmp_path: pathlib.Path,
) -> None:
    validator = runpy.run_path(str(VALIDATOR))
    parse_version = validator["installer_version"]
    template = tmp_path / "install-skills-bootstrap-template.py"
    template.write_text(
        "INSTALLER_VERSION = 11\nprint('authoritative')\n",
        encoding="utf-8",
        newline="\n",
    )
    assert parse_version(template) == 11
    assert parse_version(INSTALLER_TEMPLATE) == INSTALLER_VERSION
    assert parse_version(BOOTSTRAP) == INSTALLER_VERSION
    assert INSTALLER_TEMPLATE.read_bytes() == BOOTSTRAP.read_bytes()
    help_result = subprocess.run(
        [sys.executable, str(BOOTSTRAP), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_result.returncode == 0
    for option in ("--repo-root", "--install-root", "--skill"):
        assert option in help_result.stdout
    for removed in (
        "--base-revision",
        "--remove-skill",
        "--installer-version",
    ):
        assert removed not in help_result.stdout

    template.write_text(
        "INSTALLER_VERSION = 11\nINSTALLER_VERSION = 12\n",
        encoding="utf-8",
        newline="\n",
    )
    assert parse_version(template) is None


def test_runtime_inventory_lists_direct_manifests_and_malformed_blockers(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool", "beta-tool"])
    assert run_builder(repo, install_root, "--all-managed").returncode == 0
    malformed = install_root / "broken-tool"
    malformed.mkdir()
    (malformed / RUNTIME_MANIFEST).write_text("{\n", encoding="utf-8", newline="\n")
    nested = install_root / "unmanaged-tool" / "nested-managed"
    nested.mkdir(parents=True)
    (nested / RUNTIME_MANIFEST).write_text("{}\n", encoding="utf-8", newline="\n")
    (install_root / "alpha-tool" / "SKILL.md").write_text(
        "runtime drift is not inventory validation\n",
        encoding="utf-8",
        newline="\n",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(RUNTIME_INSTALLER),
            "--install-root",
            str(install_root),
            "--inventory-output",
            str(tmp_path / "inventory.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"
    inventory = json.loads(
        (tmp_path / "inventory.json").read_text(encoding="utf-8")
    )
    assert inventory["status"] == "inventory"
    assert inventory["managed"] == 2
    assert inventory["blocked"] == 1
    assert [item["skill"] for item in inventory["skills"]] == ["alpha-tool", "beta-tool"]
    assert inventory["blockers"][0]["directory"] == "broken-tool"
    assert "unreadable runtime manifest" in inventory["blockers"][0]["errors"][0]
