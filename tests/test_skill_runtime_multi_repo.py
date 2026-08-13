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
RULE_CANDIDATE_VALIDATOR = (
    GOVERNANCE_SOURCE / "scripts" / "validate_rule_candidate.py"
)
DEPLOY_OPERATION = REPOSITORY_LIFECYCLE_SOURCE / "scripts" / "run-deploy-operation.py"
RELEASE_OPERATION = REPOSITORY_LIFECYCLE_SOURCE / "scripts" / "run-release-operation.py"
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
INSTALLER_VERSION = 11


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
    oversized_user_message_chars: int = 0,
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
            + (
                " OVERSIZED_USER_EVIDENCE_SENTINEL"
                + " semantic context" * oversized_user_message_chars
                if oversized_user_message_chars
                else ""
            )
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
    oversized_user_message_chars: int = 0,
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """Create one request with caller-selected controller and evidence paths."""

    session = tmp_path / "session.jsonl"
    credit_analysis_session(
        session,
        extra_completed_turns=extra_completed_turns,
        extra_calls_per_turn=extra_calls_per_turn,
        oversized_user_message_chars=oversized_user_message_chars,
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
            "expected_surface_contract_version": 5,
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
            "expected_surface_contract_version": 5,
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
    assert plan["projected_luna_calls"] == 1
    assert plan["projected_sol_calls"] == 1
    assert plan["projected_semantic_calls"] == 2
    assert plan["shared_candidate_count"] > 8
    assert len(json.dumps(plan)) < 20_000

    state_path = pathlib.Path(plan["state_path"])
    manifest = json.loads(
        pathlib.Path(plan["manifest_path"]).read_text(encoding="utf-8")
    )
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
    state["execution"][task["task_id"]]["attempts"].append(
        {
            **attempt,
            "outcome": "validation-error",
            "error": "simulated older packet-local evidence rejection",
        }
    )
    state["model_attempts"]["luna"] = 1
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
    assert recovered_state["model_attempts"] == {"luna": 1, "sol": 0}
    assert recovered_state["model_calls"] == {"luna": 1, "sol": 0}
    assert len(recovered_state["child_lineage"]) == 1
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
        def _sol(
            self,
            task: Mapping[str, Any],
            packet: Mapping[str, Any],
            digest: str,
        ) -> dict[str, Any]:
            result = super()._sol(task, packet, digest)
            call_order = [row[1] for row in packet["call_inventory"]["rows"]]
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
    flattened = [
        call_id
        for group in final["call_classifications"]
        for call_id in group["call_ids"]
    ]
    manifest = json.loads(
        pathlib.Path(final["manifest"]["path"]).read_text(encoding="utf-8")
    )
    assert flattened == manifest["call_ids"]
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


def _attach_prior_analysis_state(
    session: pathlib.Path,
    state_path: pathlib.Path,
) -> None:
    rows = [
        json.loads(line)
        for line in session.read_text(encoding="utf-8").splitlines()
    ]
    attached = 0
    quoted_marker = False
    for row in rows:
        payload = row.get("payload", {})
        if (
            payload.get("type") == "function_call_output"
            and payload.get("call_id") in {"read-1", "read-2"}
        ):
            output = json.loads(payload["output"])
            output["state_path"] = str(state_path)
            payload["output"] = json.dumps(output)
            attached += 1
        if (
            not quoted_marker
            and payload.get("type") == "message"
            and payload.get("role") == "user"
        ):
            payload["content"][0]["text"] += (
                " Quoted diagnostic text: CERATOPS_CREDIT_ANALYSIS_CHILD v1."
            )
            quoted_marker = True
    assert attached == 2 and quoted_marker
    session.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def test_credit_analysis_lineage_allows_later_meta_analysis_without_recursion(
    tmp_path: pathlib.Path,
) -> None:
    workflow = load_credit_analysis_workflow_module()
    a_root = tmp_path / "a"
    b_root = tmp_path / "b"
    a_root.mkdir()
    b_root.mkdir()
    request_a, _, _ = credit_analysis_request(
        a_root,
        extra_completed_turns=1,
        extra_calls_per_turn=2,
    )
    runner_a = FakeCreditModelRunner(temporary_controls=False)
    plan_a = workflow.command_plan_orchestration(
        request_a,
        available_models=runner_a.available_models,
    )
    complete_a = workflow.command_execute_orchestration(
        pathlib.Path(plan_a["state_path"]),
        runner=runner_a,
        available_models=runner_a.available_models,
    )
    assert complete_a["complete"] is True

    request_b, session_b, _ = credit_analysis_request(
        b_root,
        extra_completed_turns=1,
        extra_calls_per_turn=2,
    )
    prior_state_path = pathlib.Path(plan_a["state_path"])
    _attach_prior_analysis_state(session_b, prior_state_path)
    raw_rows = [
        json.loads(line)
        for line in session_b.read_text(encoding="utf-8").splitlines()
    ]
    raw_state_paths = workflow.command_plan_orchestration.__globals__[
        "_holistic_raw_state_paths_by_call"
    ](raw_rows)
    assert raw_state_paths["read-1"] == [prior_state_path]
    assert raw_state_paths["read-2"] == [prior_state_path]
    runner_b = FakeCreditModelRunner(temporary_controls=False)
    plan_b = workflow.command_plan_orchestration(
        request_b,
        available_models=runner_b.available_models,
    )
    evidence_b = json.loads(
        pathlib.Path(plan_b["evidence_path"]).read_text(encoding="utf-8")
    )
    assert evidence_b["analysis_lineage"]["included_prior_analysis_ids"] == [
        plan_a["analysis_id"]
    ]
    assert evidence_b["analysis_lineage"]["source_selection_uses_prompt_markers"] is False
    assert evidence_b["analysis_generated_activity"][0]["analysis_id"] == plan_a[
        "analysis_id"
    ]
    assert any(
        attempt["prompt"] is not None
        and attempt["event_summary"]["usage"] is not None
        for task in evidence_b["analysis_generated_activity"][0]["tasks"]
        for attempt in task["attempts"]
    )
    manifest_b = json.loads(
        pathlib.Path(plan_b["manifest_path"]).read_text(encoding="utf-8")
    )
    compact_b = json.loads(
        pathlib.Path(manifest_b["compact_evidence"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    analysis_records = [
        record
        for record in compact_b["records"]
        if record["workstream"] == "analysis-overhead"
    ]
    assert len(analysis_records) >= 2
    assert all(
        record["candidate_id"] in manifest_b["candidate_ids"]
        for record in analysis_records
    )

    complete_b = workflow.command_execute_orchestration(
        pathlib.Path(plan_b["state_path"]),
        runner=runner_b,
        available_models=runner_b.available_models,
    )
    final_b = json.loads(
        pathlib.Path(complete_b["final_result_path"]).read_text(encoding="utf-8")
    )
    assert final_b["lineage"]["included_prior_analysis_ids"] == [
        plan_a["analysis_id"]
    ]
    assert all(
        child["analysis_id"] == plan_b["analysis_id"]
        for child in final_b["lineage"]["created_child_tasks"]
    )
    assert final_b["lineage"]["excluded_own_descendant_task_ids"] == [
        child["task_id"] for child in final_b["lineage"]["created_child_tasks"]
    ]
    analysis_totals = final_b["workstream_classification_totals"][
        "analysis-overhead"
    ]
    assert sum(analysis_totals.values()) == len(analysis_records)


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
            task_root = tmp_path / f"batch-{name}"
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
    ledger = load_credit_analysis_workflow_module()._load_ledger()
    assert (
        ledger.bounded_command_label("rg sentinel <user-home><local-path>")
        == "rg sentinel <local-path>"
    )
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
                "input": (
                    "const result = await tools.exec_command({cmd: "
                    + json.dumps(f"rg sentinel {local_path}")
                    + "}); text(result.output);"
                ),
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
                                "error": "PreToolUse rejected the nested command",
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
        "enumerated_child_calls": 1,
        "dynamic_or_unparsed_outer_actions": 0,
        "outer_actions_with_emitted_process_results": 1,
    }
    assert "functions_exec_dynamic_child_calls_not_enumerated" not in summary[
        "telemetry"
    ]["limitations"]

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
    nested_exec = first["tool_action_results"][-1]
    assert nested_exec["nested_calls"] == [
        {
            "tool": "exec_command",
            "command_label": "rg sentinel <local-path>",
            "command_chars": len(f"rg sentinel {local_path}"),
            "fingerprint": nested_exec["nested_calls"][0]["fingerprint"],
        }
    ]
    assert nested_exec["failure_provenance"] == {
        "category": "pre_tool_use_rejection",
        "semantic_failure": True,
        "reason_label": nested_exec["failure_provenance"]["reason_label"],
        "originating_nested_call": nested_exec["nested_calls"][0],
        "candidate_nested_calls": [],
    }
    assert "PreToolUse rejected" in nested_exec["failure_provenance"][
        "reason_label"
    ]
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
    """Write and run one fast-change request in its canonical task-temp root."""

    task_temp_root = (
        repo.parent / "tmp" / repo.name / f"request-{time.time_ns()}"
    )
    task_temp_root.mkdir(parents=True)
    request_path = task_temp_root / "request.json"
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


def test_skill_update_workflow_accepts_new_shared_section_source(
    tmp_path: pathlib.Path,
) -> None:
    worktree, _scope, task_temp_root = prepare_skill_update_workflow_worktree(
        tmp_path
    )
    shared_source = (
        worktree / "skills" / "sections" / "scripts" / "shared-helper.py"
    )
    shared_source.parent.mkdir(parents=True)
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
            "skills/sections/scripts/shared-helper.py",
        ],
        "change_groups": [
            {
                "name": "shared-helper",
                "paths": [
                    "skills/alpha-tool/scripts/tool.py",
                    "skills/sections/scripts/shared-helper.py",
                ],
            }
        ],
        "checks": [
            {
                "kind": "search",
                "pattern": "SHARED_PAYLOAD",
                "paths": ["skills/sections/scripts/shared-helper.py"],
                "expected_matches": 1,
            }
        ],
    }
    request_path.write_text(
        json.dumps(request) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    prepared = run_skill_update_workflow(
        "prepare",
        "--request",
        str(request_path),
        "--state",
        str(state_path),
    )
    assert prepared.returncode == 0, prepared.stderr
    shared_source.write_text(
        "SHARED_PAYLOAD = True\n",
        encoding="utf-8",
        newline="\n",
    )
    verified = run_skill_update_workflow(
        "verify",
        "--state",
        str(state_path),
        "--evidence-output",
        str(evidence_path),
    )
    assert verified.returncode == 0, verified.stderr
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["changed_paths"] == [
        "skills/sections/scripts/shared-helper.py"
    ]
    finalized = run_skill_update_workflow(
        "finalize",
        "--state",
        str(state_path),
    )
    assert finalized.returncode == 0, finalized.stderr
    assert not task_temp_root.exists()


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
        "import sys\n"
        "path = pathlib.Path(__file__).with_name('check.log')\n"
        "prior = path.read_text(encoding='utf-8') if path.exists() else ''\n"
        "path.write_text(prior + 'run\\n', encoding='utf-8')\n"
        "sys.stdout.buffer.write('מלא\\n'.encode('utf-8'))\n",
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
    assert evidence["checks"][1]["stdout"] == "מלא\n"
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

    empty_task_temp_root = task_temp_root.parent / "empty-finalization"
    empty_task_temp_root.mkdir()
    empty_request_path = empty_task_temp_root / "request.json"
    empty_state_path = empty_task_temp_root / "state.json"
    empty_evidence_path = empty_task_temp_root / "evidence.json"
    empty_request = json.loads(json.dumps(request))
    empty_request["task_temp_root"] = str(empty_task_temp_root)
    empty_request["evidence_output"] = str(empty_evidence_path)
    empty_request_path.write_text(
        json.dumps(empty_request) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    prepared_empty = run_skill_update_workflow(
        "prepare",
        "--request",
        str(empty_request_path),
        "--state",
        str(empty_state_path),
    )
    assert prepared_empty.returncode == 0, prepared_empty.stderr
    helper.write_text(
        "VALUE = 2\n# second verified change\n",
        encoding="utf-8",
        newline="\n",
    )
    verified_empty = run_skill_update_workflow(
        "verify",
        "--state",
        str(empty_state_path),
        "--evidence-output",
        str(empty_evidence_path),
    )
    assert verified_empty.returncode == 0, verified_empty.stderr
    finalized_empty = run_skill_update_workflow(
        "finalize",
        "--state",
        str(empty_state_path),
    )
    assert finalized_empty.returncode == 0, finalized_empty.stderr
    assert finalized_empty.stdout.strip() == "OK"
    assert not empty_task_temp_root.exists()

    removed_task_temp_root = task_temp_root.parent / "removed-worktree-finalization"
    removed_task_temp_root.mkdir()
    removed_request_path = removed_task_temp_root / "request.json"
    removed_state_path = removed_task_temp_root / "state.json"
    removed_evidence_path = removed_task_temp_root / "evidence.json"
    removed_request = json.loads(json.dumps(request))
    removed_request["task_temp_root"] = str(removed_task_temp_root)
    removed_request["evidence_output"] = str(removed_evidence_path)
    removed_request["checks"] = [
        {
            "kind": "search",
            "pattern": "FORBIDDEN",
            "paths": ["skills/alpha-tool/scripts/tool.py"],
            "expected_matches": 0,
        }
    ]
    removed_request_path.write_text(
        json.dumps(removed_request) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    prepared = run_skill_update_workflow(
        "prepare",
        "--request",
        str(removed_request_path),
        "--state",
        str(removed_state_path),
    )
    assert prepared.returncode == 0, prepared.stderr
    helper.write_text(
        "VALUE = 2\n# third verified change\n",
        encoding="utf-8",
        newline="\n",
    )
    verified = run_skill_update_workflow(
        "verify",
        "--state",
        str(removed_state_path),
        "--evidence-output",
        str(removed_evidence_path),
    )
    assert verified.returncode == 0, verified.stderr

    source = scope / task_temp_root.parent.name
    removed = run_git(source, "worktree", "remove", "--force", str(worktree))
    assert removed.returncode == 0, removed.stderr
    finalized = run_skill_update_workflow(
        "finalize", "--state", str(removed_state_path)
    )

    assert finalized.returncode == 0, finalized.stderr
    assert finalized.stdout.strip() == "OK"
    assert not removed_task_temp_root.exists()


def target_repository_markdown_policy(
    repository: pathlib.Path,
) -> dict[str, object]:
    """Build a decoy target policy that the governance skill must reject."""

    configuration = repository / ".markdownlint.json"
    configuration.write_text(
        json.dumps({"default": False}) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "repository_root": str(repository.resolve()),
        "configuration": str(configuration.resolve()),
        "configuration_sha256": hashlib.sha256(
            configuration.read_bytes()
        ).hexdigest(),
        "validate_command": [sys.executable, "-c", "pass", "{file}"],
        "fix_command": None,
    }


def write_rule_candidate(
    path: pathlib.Path,
    *,
    rule_stack: list[pathlib.Path],
    targets: list[dict[str, object]],
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "ceratops-rule-candidate.v1",
                "rule_stack": [str(item.resolve()) for item in rule_stack],
                "targets": targets,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def run_rule_candidate_validator(
    candidate: pathlib.Path,
    evidence: pathlib.Path,
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(RULE_CANDIDATE_VALIDATOR),
            "--candidate",
            str(candidate),
            "--evidence",
            str(evidence),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_rule_candidate_repairs_multiple_targets_and_is_idempotent(
    tmp_path: pathlib.Path,
) -> None:
    first_repo = tmp_path / "first-repo"
    second_repo = tmp_path / "second-repo"
    first_repo.mkdir()
    second_repo.mkdir()
    first = first_repo / "contract.md"
    second = second_repo / "contract.md"
    first_text = (
        "# First\n\n"
        "Old prose.\n\n"
        "- Old nested item.\n\n"
        "> > - Old quoted item.\n\n"
        "````text\n"
        "```\n"
        "protected code line that is intentionally much longer than the limit\n"
        "````\n\n"
        "A [sample link][sample].\n\n"
        "[sample]: https://example.test/reference\n"
        "  \"Old reference title.\"\n"
    )
    second_text = "# Second\n\nOld alpha.\n\nOld beta.\n"
    first.write_text(first_text, encoding="utf-8", newline="\n")
    second.write_text(second_text, encoding="utf-8", newline="\r\n")
    candidate = tmp_path / "candidate.json"
    evidence = tmp_path / "evidence.json"
    first_replacements = [
        {
            "expected_old": "Old prose.",
            "replacement": (
                "Safe ordinary prose wraps deterministically while preserving "
                "every original non-whitespace content character."
            ),
        },
        {
            "expected_old": "- Old nested item.",
            "replacement": (
                "- Nested list continuation wrapping preserves its exact "
                "nesting and marker structure."
            ),
        },
        {
            "expected_old": "> > - Old quoted item.",
            "replacement": (
                "> > - Nested blockquote continuation wrapping preserves "
                "both quote depths and list nesting."
            ),
        },
        {
            "expected_old": (
                "````text\n"
                "```\n"
                "protected code line that is intentionally much longer than the limit\n"
                "````"
            ),
            "replacement": (
                "````text\n"
                "```\n"
                "protected code line that is intentionally much longer than the limit\n"
                "````"
            ),
        },
        {
            "expected_old": '  "Old reference title."',
            "replacement": (
                '  "A reference definition continuation remains byte-for-byte '
                'unwrapped under its surrounding Markdown context."'
            ),
        },
    ]
    second_replacements = [
        {
            "expected_old": "Old alpha.",
            "replacement": "Alpha stays on one line under its wider configured policy.",
        },
        {
            "expected_old": "Old beta.",
            "replacement": (
                "Beta remains independently replaceable and wraps with the "
                "second target's CRLF convention when it exceeds that policy."
            ),
        },
    ]
    write_rule_candidate(
        candidate,
        rule_stack=[first, second],
        targets=[
            {
                "rules": str(first.resolve()),
                "history": None,
                "source_sha256": hashlib.sha256(first.read_bytes()).hexdigest(),
                "markdown_policy": None,
                "replacements": first_replacements,
            },
            {
                "rules": str(second.resolve()),
                "history": None,
                "source_sha256": hashlib.sha256(second.read_bytes()).hexdigest(),
                "markdown_policy": None,
                "replacements": second_replacements,
            },
        ],
    )
    original_sources = (first.read_bytes(), second.read_bytes())
    validated = run_rule_candidate_validator(candidate, evidence)
    assert validated.returncode == 0, validated.stderr
    assert validated.stdout.strip() == "OK"
    fixed = json.loads(candidate.read_text(encoding="utf-8"))
    fixed_first = fixed["targets"][0]["replacements"]
    fixed_second = fixed["targets"][1]["replacements"]
    assert "\n" in fixed_first[0]["replacement"]
    assert "\n  " in fixed_first[1]["replacement"]
    assert "\n> >   " in fixed_first[2]["replacement"]
    assert fixed_first[3]["replacement"] == first_replacements[3]["replacement"]
    assert fixed_first[4]["replacement"] == first_replacements[4]["replacement"]
    assert "\n" not in fixed_second[0]["replacement"]
    assert "\r\n" in fixed_second[1]["replacement"]
    assert "\n" not in fixed_second[1]["replacement"].replace("\r\n", "")
    assert (first.read_bytes(), second.read_bytes()) == original_sources
    detail = json.loads(evidence.read_text(encoding="utf-8"))
    assert detail["status"] == "passed" and detail["idempotent"] is True
    first_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
    second_evidence = tmp_path / "second-evidence.json"
    repeated = run_rule_candidate_validator(candidate, second_evidence)
    assert repeated.returncode == 0, repeated.stderr
    assert hashlib.sha256(candidate.read_bytes()).hexdigest() == first_hash
    assert json.loads(second_evidence.read_text(encoding="utf-8"))["changed"] is False


def test_rule_candidate_failures_are_atomic_and_actionable(
    tmp_path: pathlib.Path,
) -> None:
    safe_repo = tmp_path / "safe-repo"
    blocked_repo = tmp_path / "blocked-repo"
    safe_repo.mkdir()
    blocked_repo.mkdir()
    safe = safe_repo / "contract.md"
    blocked = blocked_repo / "contract.md"
    safe.write_text("Old safe.\n", encoding="utf-8", newline="\n")
    blocked.write_text("Old blocked.\n", encoding="utf-8", newline="\n")
    candidate = tmp_path / "atomic-candidate.json"
    evidence = tmp_path / "atomic-evidence.json"
    token = "https://example.test/" + "x" * 70
    write_rule_candidate(
        candidate,
        rule_stack=[safe, blocked],
        targets=[
            {
                "rules": str(safe.resolve()),
                "history": None,
                "source_sha256": hashlib.sha256(safe.read_bytes()).hexdigest(),
                "markdown_policy": None,
                "replacements": [
                    {
                        "expected_old": "Old safe.",
                        "replacement": (
                            "Safe prose would wrap if every target completed "
                            "mechanical validation."
                        ),
                    }
                ],
            },
            {
                "rules": str(blocked.resolve()),
                "history": None,
                "source_sha256": hashlib.sha256(blocked.read_bytes()).hexdigest(),
                "markdown_policy": None,
                "replacements": [
                    {"expected_old": "Old blocked.", "replacement": token}
                ],
            },
        ],
    )
    before = candidate.read_bytes()
    failed = run_rule_candidate_validator(candidate, evidence)
    assert failed.returncode == 1
    assert str(blocked.resolve()) in failed.stderr
    assert "replacement=0" in failed.stderr
    assert "configured limit 80" in failed.stderr
    assert "indivisible token" in failed.stderr
    assert candidate.read_bytes() == before
    assert json.loads(evidence.read_text(encoding="utf-8"))["status"] == "failed"

    target_policy = target_repository_markdown_policy(safe_repo)
    write_rule_candidate(
        candidate,
        rule_stack=[safe],
        targets=[
            {
                "rules": str(safe.resolve()),
                "history": None,
                "source_sha256": hashlib.sha256(safe.read_bytes()).hexdigest(),
                "markdown_policy": target_policy,
                "replacements": [
                    {"expected_old": "Old safe.", "replacement": "safe value"}
                ],
            }
        ],
    )
    before_mutation = candidate.read_bytes()
    mutated = run_rule_candidate_validator(candidate, tmp_path / "mutation.json")
    assert mutated.returncode == 1
    assert "skill-owned policy" in mutated.stderr
    assert candidate.read_bytes() == before_mutation


def test_rule_candidate_rejects_stale_and_duplicate_expected_old(
    tmp_path: pathlib.Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    target = repository / "contract.md"
    target.write_text("Old value.\n", encoding="utf-8", newline="\n")
    candidate = tmp_path / "candidate.json"
    target_entry: dict[str, object] = {
        "rules": str(target.resolve()),
        "history": None,
        "source_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "markdown_policy": None,
        "replacements": [
            {"expected_old": "Old value.", "replacement": "New value."},
            {"expected_old": "Old value.", "replacement": "Other value."},
        ],
    }
    write_rule_candidate(
        candidate,
        rule_stack=[target],
        targets=[target_entry],
    )
    duplicate = run_rule_candidate_validator(candidate, tmp_path / "duplicate.json")
    assert duplicate.returncode == 1
    assert "duplicates expected_old" in duplicate.stderr

    target_entry["replacements"] = [
        {"expected_old": "Old value.", "replacement": "New value."}
    ]
    write_rule_candidate(candidate, rule_stack=[target], targets=[target_entry])
    target.write_text("Changed value.\n", encoding="utf-8", newline="\n")
    stale = run_rule_candidate_validator(candidate, tmp_path / "stale.json")
    assert stale.returncode == 1
    assert "source-hash" in stale.stderr and "source is stale" in stale.stderr


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
    champion_output = task_temp_root / "validated-champion.json"
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
    target_source: dict[str, object] = {
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
    assert context["schema"] == "ceratops-governance-proposal-context.v3"
    assert context["history_lookup"]["unknown"] == []
    assert context["sources"][1]["history"] is None
    assert context["candidate_validation"]["targets"][0]["rules"] == str(
        target.resolve()
    )
    policy = context["candidate_validation"]["targets"][0]["markdown_policy"]
    assert pathlib.Path(policy["configuration"]) == (
        ROOT
        / "skills"
        / "ceratops-governance-lifecycle"
        / "references"
        / ".markdownlint.json"
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
    candidate_value["targets"][0]["replacements"][0]["replacement"] = (
        "https://example.test/" + "x" * 80
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
    assert "indivisible token" in mechanical_failure.stderr
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
    assert "\n" in fixed_candidate["targets"][0]["replacements"][0]["replacement"]
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
    assert payload["request_cleanup"] == {
        "request": "removed",
        "task_temp_root": "removed",
    }
    canonical_requests = repo.parent / "tmp" / repo.name
    assert list(canonical_requests.rglob("request.json")) == []
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
    preserved_requests = list(canonical_requests.rglob("request.json"))
    assert len(preserved_requests) == 1

    if os.name != "nt":
        symlink_task = canonical_requests / "symlink-request"
        symlink_task.mkdir()
        symlink_request = symlink_task / "request.json"
        symlink_request.symlink_to(preserved_requests[0])
        rejected_symlink = subprocess.run(
            [sys.executable, str(FAST_CHANGE), "--request", str(symlink_request)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert rejected_symlink.returncode == 2
        assert json.loads(rejected_symlink.stderr)["reason"] == (
            "request must be a regular file"
        )
        assert symlink_request.is_symlink() and preserved_requests[0].is_file()

    outside_request = repo.parent / "outside-fast-change-request.json"
    outside_request.write_text(
        json.dumps(
            fast_change_request(
                repo,
                fast_change_edits(
                    {
                        "skills/alpha-tool/notes.txt": (
                            "Updated notes",
                            "Rejected notes",
                        )
                    }
                ),
                selected=["alpha-tool"],
            )
        ),
        encoding="utf-8",
        newline="\n",
    )
    noncanonical = subprocess.run(
        [sys.executable, str(FAST_CHANGE), "--request", str(outside_request)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert noncanonical.returncode == 2
    assert "<repo-parent>/tmp/<repo-name>/<task>/" in noncanonical.stderr
    assert outside_request.is_file()


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

    queries: list[str] = []

    def branch_rules(
        query: str,
        variables: dict[str, Any],
        cwd: pathlib.Path,
    ) -> dict[str, Any]:
        queries.append(query)
        assert variables["qualifiedName"] == "refs/heads/main"
        assert cwd == tmp_path
        return {
            "data": {
                "repository": {
                    "ref": {
                        "name": "main",
                        "branchProtectionRule": {
                            "requiresApprovingReviews": False,
                            "requiredApprovingReviewCount": 0,
                            "requiresConversationResolution": False,
                            "requiresStatusChecks": True,
                            "requiredStatusChecks": [{"context": "classic-ci"}],
                        },
                        "rules": {
                            "nodes": [
                                {
                                    "type": "REQUIRED_STATUS_CHECKS",
                                    "parameters": {
                                        "__typename": (
                                            "RequiredStatusChecksParameters"
                                        ),
                                        "requiredStatusChecks": [
                                            {"context": "ruleset-ci"}
                                        ],
                                    },
                                }
                            ],
                            "pageInfo": {
                                "hasNextPage": False,
                                "endCursor": None,
                            },
                        },
                    }
                }
            }
        }

    monkeypatch.setattr(readiness, "current_repository", lambda cwd: ("acme", "repo"))
    monkeypatch.setattr(readiness, "gh_graphql", branch_rules)
    policy = readiness.branch_rule_policy("main", tmp_path)
    assert policy == {
        "required_approving_review_count": 0,
        "required_review_thread_resolution": False,
        "required_status_checks": ["classic-ci", "ruleset-ci"],
    }
    assert "RequiredStatusChecksParameters" in queries[0]
    assert "requiredStatusChecks" in queries[0]

    pr_data = {
        "number": 24,
        "url": "https://example.invalid/pull/24",
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "reviewDecision": "APPROVED",
        "statusCheckRollup": [],
        "headRefName": "release/local",
        "headRefOid": head,
        "baseRefName": "main",
        "autoMergeRequest": None,
    }
    monkeypatch.setattr(readiness, "gh_pr_view", lambda *args: pr_data)
    monkeypatch.setattr(readiness, "branch_rule_policy", lambda *args: policy)
    _, findings = readiness.pr_readiness("24", tmp_path)
    status_finding = next(
        finding for finding in findings if finding.check == "pr.status_checks"
    )
    assert status_finding.message == readiness.REQUIRED_STATUS_CHECKS_MISSING_MESSAGE
    assert status_finding.actual == ["classic-ci", "ruleset-ci"]

    pr_data["statusCheckRollup"] = [
        {
            "name": "classic-ci",
            "status": "COMPLETED",
            "conclusion": "SUCCESS",
        }
    ]
    _, findings = readiness.pr_readiness("24", tmp_path)
    status_finding = next(
        finding for finding in findings if finding.check == "pr.status_checks"
    )
    assert status_finding.message == readiness.REQUIRED_STATUS_CHECKS_MISSING_MESSAGE
    assert status_finding.actual == ["ruleset-ci"]

    no_ci_policy = {**policy, "required_status_checks": []}
    pr_data["statusCheckRollup"] = []
    monkeypatch.setattr(
        readiness,
        "branch_rule_policy",
        lambda *args: no_ci_policy,
    )
    _, findings = readiness.pr_readiness("24", tmp_path)
    status_finding = next(
        finding for finding in findings if finding.check == "pr.status_checks"
    )
    assert status_finding.message == readiness.NO_STATUS_CHECKS_MESSAGE
    assert status_finding.actual is None

    findings = []
    readiness.status_rollup_findings(
        {
            "statusCheckRollup": [
                {"name": "future-ci", "status": "FUTURE_STATE"}
            ]
        },
        findings,
    )
    assert findings[0].message == readiness.UNKNOWN_STATUS_CHECK_MESSAGE
    assert findings[0].actual == {
        "index": 0,
        "name": "future-ci",
        "conclusion": None,
        "status": "FUTURE_STATE",
        "state": None,
    }


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

    review_task_root = tmp_path / "tmp" / repo.name / "review-fix"
    review_task_root.mkdir(parents=True)
    review_request = review_task_root / "replies.json"
    review_request.write_text("{}\n", encoding="utf-8", newline="\n")
    review_state: dict[str, Any] = {
        "phase": "pr_ready",
        "pr": 24,
        "url": "https://example.invalid/pull/24",
        "commit": head,
    }
    address_calls: list[pathlib.Path] = []

    def address_request(
        request_path: pathlib.Path,
        *,
        cwd: pathlib.Path | None = None,
    ) -> dict[str, Any]:
        address_calls.append(request_path)
        assert cwd == repo
        return {
            "status": "addressed",
            "repo": "example/repository",
            "pr": 24,
            "head_oid": head,
            "reply_count": 1,
            "posted": 1,
            "resolved": 1,
            "already_addressed": 0,
        }

    monkeypatch.setattr(ship.codex_review, "address_request", address_request)
    review_args = argparse.Namespace(review_replies_request=review_request)
    addressed = ship._address_review_replies(
        review_args,
        state=review_state,
        checkpoint_path=checkpoint,
        repo_root=repo,
        repository="example/repository",
        pr="24",
        commit=head,
    )
    assert addressed == {
        "status": "addressed",
        "reply_count": 1,
        "posted": 1,
        "resolved": 1,
        "already_addressed": 0,
        "cleanup": "removed",
    }
    assert not review_request.exists() and not review_task_root.exists()
    assert review_state["review_replies"]["cleanup"] == "removed"
    assert ship._address_review_replies(
        review_args,
        state=review_state,
        checkpoint_path=checkpoint,
        repo_root=repo,
        repository="example/repository",
        pr="24",
        commit=head,
    ) == addressed
    assert address_calls == [review_request.resolve()]

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

    clock = {"now": 0.0}
    validation_times: list[float] = []
    ambiguous = ship.readiness.Finding(
        level="ERROR",
        check="pr.status_checks",
        message=ship.readiness.UNKNOWN_STATUS_CHECK_MESSAGE,
        actual={
            "index": 0,
            "name": "validate",
            "conclusion": None,
            "status": "FUTURE_STATE",
            "state": None,
        },
    )

    def ambiguous_readiness(
        *args: Any, **kwargs: Any
    ) -> tuple[dict[str, Any], list[Any]]:
        validation_times.append(clock["now"])
        return (
            {
                "number": 24,
                "url": "https://example.invalid/pull/24",
                "head_oid": head,
            },
            [ambiguous],
        )

    def uncertainty_json(
        command: list[str],
        *args: Any,
        **kwargs: Any,
    ) -> argparse.Namespace:
        if command[1:3] == ["pr", "checks"]:
            return argparse.Namespace(
                ok=True,
                data=[
                    {
                        "name": "validate",
                        "state": "FUTURE_STATE",
                        "bucket": "pending",
                        "workflow": "CI",
                        "link": (
                            "https://github.com/example/repository/"
                            "actions/runs/42/job/84"
                        ),
                    }
                ],
                message=None,
            )
        if command[1:3] == ["run", "view"]:
            return argparse.Namespace(
                ok=True,
                data={
                    "status": "in_progress",
                    "conclusion": None,
                    "headSha": head,
                    "url": (
                        "https://github.com/example/repository/actions/runs/42"
                    ),
                    "name": "CI",
                    "workflowName": "CI",
                },
                message=None,
            )
        raise AssertionError(command)

    monkeypatch.setattr(ship.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        ship.time,
        "sleep",
        lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
    )
    monkeypatch.setattr(ship.readiness, "validate_readiness", ambiguous_readiness)
    monkeypatch.setattr(ship, "run_json_command", uncertainty_json)
    with pytest.raises(ship.ShipBlocked) as ambiguous_blocked:
        ship.wait_for_ci_gate(
            "24",
            repo,
            head,
            repository="example/repository",
            wait_seconds=900,
            interval_seconds=10,
        )
    ambiguous_payload = ambiguous_blocked.value.payload["blocker"]
    assert ambiguous_payload["kind"] == "ci_ambiguous"
    assert ambiguous_payload["head_oid"] == head
    assert ambiguous_payload["grace_seconds"] == 60
    assert ambiguous_payload["diagnostic"]["finding"]["actual"] == ambiguous.actual
    assert ambiguous_payload["diagnostic"]["normalized_checks"][0]["bucket"] == (
        "pending"
    )
    assert ambiguous_payload["diagnostic"]["action_run"]["head_matches"] is True
    assert validation_times[:2] == [0.0, 0.0]
    assert validation_times[-1] == 60.0

    clock["now"] = 0.0
    pending_times: list[float] = []
    explicit_pending = ship.readiness.Finding(
        level="WARN",
        check="pr.status_checks",
        message="Status checks are still pending.",
        actual=["validate"],
    )

    def pending_then_pass(*args: Any, **kwargs: Any) -> tuple[dict[str, Any], list[Any]]:
        pending_times.append(clock["now"])
        findings = [explicit_pending] if clock["now"] < 70 else []
        return (
            {
                "number": 24,
                "url": "https://example.invalid/pull/24",
                "head_oid": head,
            },
            findings,
        )

    monkeypatch.setattr(ship.readiness, "validate_readiness", pending_then_pass)
    monkeypatch.setattr(
        ship,
        "run_json_command",
        lambda *args, **kwargs: pytest.fail(
            "explicit pending checks must not use uncertainty diagnostics"
        ),
    )
    completed = ship.wait_for_ci_gate(
        "24",
        repo,
        head,
        repository="example/repository",
        wait_seconds=900,
        interval_seconds=10,
    )
    assert completed["pending"] == 0
    assert 60.0 in pending_times
    assert pending_times[-1] == 70.0

    clock["now"] = 0.0
    missing = ship.readiness.Finding(
        level="WARN",
        check="pr.status_checks",
        message=ship.readiness.REQUIRED_STATUS_CHECKS_MISSING_MESSAGE,
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
            [missing],
        ),
    )
    monkeypatch.setattr(
        ship,
        "run_json_command",
        lambda *args, **kwargs: argparse.Namespace(
            ok=False,
            data=None,
            message="no checks reported on the release/local branch",
        ),
    )
    with pytest.raises(ship.ShipBlocked) as missing_blocked:
        ship.wait_for_ci_gate(
            "24",
            repo,
            head,
            repository="example/repository",
            wait_seconds=900,
            interval_seconds=10,
        )
    missing_payload = missing_blocked.value.payload["blocker"]
    assert missing_payload["kind"] == "checks_missing"
    assert missing_payload["grace_seconds"] == 60
    assert missing_payload["diagnostic"]["checks_diagnostic"].startswith(
        "no checks reported"
    )


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


def write_release_contract(
    repo: pathlib.Path,
    operations: dict[str, object],
) -> pathlib.Path:
    """Write one JSON-compatible YAML release-publication contract."""

    contract = repo / "release" / "release.yml"
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text(
        json.dumps(
            {
                "version": 1,
                "kind": "ceratops-release",
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


def run_release_operation(
    repo: pathlib.Path,
    operation: str,
    *,
    contract: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one isolated release-publication operation."""

    command = [
        sys.executable,
        str(RELEASE_OPERATION),
        "--repo-root",
        str(repo),
        "--operation",
        operation,
    ]
    if contract is not None:
        command.extend(("--contract", str(contract)))
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

    write_release_contract(
        repo,
        {
            "publish": {
                "steps": [
                    {
                        "id": "argv",
                        "run": [
                            sys.executable,
                            "argv-probe.py",
                            str(output),
                            "release value",
                            literal,
                        ],
                    }
                ]
            }
        },
    )
    published = run_release_operation(repo, "publish")

    assert published.returncode == 0, published.stderr
    assert json.loads(published.stdout) == {
        "status": "published",
        "operation": "publish",
        "steps": ["argv"],
    }
    assert json.loads(output.read_text(encoding="utf-8")) == [
        "release value",
        literal,
    ]
    wrong_contract = run_release_operation(
        repo,
        "verify",
        contract=repo / "deploy" / "deploy.yml",
    )
    assert wrong_contract.returncode == 1
    assert json.loads(wrong_contract.stderr)["message"].startswith(
        "Invalid release contract:"
    )
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


def prepare_divergent_promotion_repo(
    root: pathlib.Path,
    *,
    conflict: bool = False,
    published: bool = False,
    nonlinear: bool = False,
) -> tuple[pathlib.Path, pathlib.Path, str, str, dict[str, str]]:
    """Create a release/source divergence with a dedicated source worktree."""

    root.mkdir()
    repo, _, _, environment = prepare_repository_lifecycle_repo(root)
    if published:
        assert run_git(repo, "push", "-u", "origin", "approved").returncode == 0
    assert run_git(repo, "switch", "main").returncode == 0
    source_worktree = root / "approved-worktree"
    assert (
        run_git(repo, "worktree", "add", str(source_worktree), "approved").returncode
        == 0
    )
    if nonlinear:
        assert (
            run_git(source_worktree, "switch", "-c", "approved-side", "main").returncode
            == 0
        )
        (source_worktree / "side.txt").write_text(
            "side\n",
            encoding="utf-8",
            newline="\n",
        )
        assert run_git(source_worktree, "add", "side.txt").returncode == 0
        assert run_git(source_worktree, "commit", "-m", "side change").returncode == 0
        assert run_git(source_worktree, "switch", "approved").returncode == 0
        assert (
            run_git(
                source_worktree,
                "merge",
                "--no-ff",
                "approved-side",
                "-m",
                "merge side",
            ).returncode
            == 0
        )
    source_head = run_git(source_worktree, "rev-parse", "HEAD").stdout.strip()

    assert run_git(repo, "switch", "-c", "release/local", "main").returncode == 0
    if conflict:
        (repo / "README.md").write_text(
            "base\nrelease\n",
            encoding="utf-8",
            newline="\n",
        )
        assert run_git(repo, "add", "README.md").returncode == 0
    else:
        (repo / "release.txt").write_text(
            "release\n",
            encoding="utf-8",
            newline="\n",
        )
        assert run_git(repo, "add", "release.txt").returncode == 0
    assert run_git(repo, "commit", "-m", "release change").returncode == 0
    release_head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    return repo, source_worktree, source_head, release_head, environment


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
        "sources": [
            {
                "branch": "approved",
                "commit": approved_head,
                "state": "retained",
            }
        ],
        "target_branch": "release/local",
        "target_commit": approved_head,
        "version": 2,
    }
    assert run_git(repo, "branch", "--show-current").stdout.strip() == "release/local"
    assert run_git(repo, "status", "--porcelain").stdout == ""
    if expects_base_revision is None:
        assert not log.exists()
    elif expects_base_revision:
        assert log.read_text(encoding="utf-8") == f"{release_start}\n"
    else:
        assert log.read_text(encoding="utf-8") == "no-base\n"


def test_promote_repository_ship_after_promotion_composes_terminal_workflow(
    tmp_path: pathlib.Path,
) -> None:
    repo, approved_head, log, _ = prepare_repository_lifecycle_repo(tmp_path)
    loaded = runpy.run_path(str(PROMOTE_REPOSITORY))
    parser = loaded["build_parser"]()
    arguments = [
        "--repo-root",
        str(repo),
        "--source-branch",
        "approved",
        "--main-branch",
        "main",
        "--release-branch",
        "release/local",
        "--remote-name",
        "origin",
        "--ship-after-promotion",
    ]
    parsed = parser.parse_args(arguments)
    assert parsed.ship_after_promotion is True
    assert parsed.run_operation is None
    assert parsed.no_run_operation is False
    for conflicting in (
        ["--run-operation", "deploy"],
        ["--no-run-operation"],
    ):
        with pytest.raises(SystemExit):
            parser.parse_args([*arguments, *conflicting])

    shipped = {
        "status": "shipped",
        "repository": "example/repository",
        "commit": approved_head,
        "pr": 31,
        "url": "https://example.invalid/pull/31",
        "merge_commit": "c" * 40,
        "synchronized_head": "b" * 40,
        "release_publication": {
            "status": "published",
            "operation": "publish",
            "steps": ["publish"],
        },
        "deployment": {
            "status": "deployed",
            "operation": "deploy",
            "steps": ["install"],
        },
        "finalization": {"status": "finalized"},
    }
    original_run_json = loaded["_run_json"]
    original_ship_after_promotion = loaded["_ship_after_promotion"]
    commands: list[list[str]] = []
    recorded: dict[str, object] = {}
    captured_handoff: dict[str, object] = {}

    def run_json(
        command: list[str], cwd: pathlib.Path
    ) -> tuple[int, dict[str, Any]]:
        commands.append(command)
        if pathlib.Path(command[1]) == MANAGE_PENDING_WORK:
            code, result = original_run_json(command, cwd)
            recorded.update(result)
            return code, result
        assert pathlib.Path(command[1]) == SHIP_REPOSITORY
        assert recorded["target_commit"] == approved_head
        assert pathlib.Path(str(recorded["pending_work_scope"])).is_file()
        assert run_git(repo, "rev-parse", "release/local").stdout.strip() == (
            approved_head
        )
        return 0, shipped

    def ship_after_promotion(
        args: argparse.Namespace,
        repo_root: pathlib.Path,
        *,
        target_commit: str,
        pending_work_scope: object,
    ) -> dict[str, object]:
        captured_handoff.update(
            {
                "target_commit": target_commit,
                "pending_work_scope": pending_work_scope,
            }
        )
        return original_ship_after_promotion(
            args,
            repo_root,
            target_commit=target_commit,
            pending_work_scope=pending_work_scope,
        )

    promote = loaded["promote"]
    promote.__globals__["_run_json"] = run_json
    promote.__globals__["_ship_after_promotion"] = ship_after_promotion
    result = promote(parsed)

    assert result == shipped
    assert len(commands) == 2
    assert pathlib.Path(commands[0][1]) == MANAGE_PENDING_WORK
    ship_command = commands[1]
    assert pathlib.Path(ship_command[1]) == SHIP_REPOSITORY
    assert ship_command[ship_command.index("--repo-root") + 1] == str(repo.resolve())
    assert ship_command[ship_command.index("--head-branch") + 1] == "release/local"
    assert ship_command[ship_command.index("--base-branch") + 1] == "main"
    assert ship_command[ship_command.index("--remote-name") + 1] == "origin"
    assert ship_command[ship_command.index("--commit") + 1] == approved_head
    assert pathlib.Path(
        ship_command[ship_command.index("--release-contract") + 1]
    ) == pathlib.Path("release/release.yml")
    assert ship_command[
        ship_command.index("--release-preflight-operation") + 1
    ] == "preflight"
    assert ship_command[ship_command.index("--release-operation") + 1] == "publish"
    assert ship_command[ship_command.index("--deploy-operation") + 1] == "deploy"
    assert "--reusable-head" in ship_command
    assert str(PROMOTE_REPOSITORY.parent / "run-deploy-operation.py") not in (
        command[1] for command in commands
    )
    assert captured_handoff == {
        "target_commit": approved_head,
        "pending_work_scope": recorded["pending_work_scope"],
    }
    assert not log.exists()


def test_promote_repository_ship_after_promotion_preserves_blocked_state(
    tmp_path: pathlib.Path,
) -> None:
    (
        repo,
        source_worktree,
        _,
        release_head,
        _,
    ) = prepare_divergent_promotion_repo(tmp_path / "shipping-blocker")
    loaded = runpy.run_path(str(PROMOTE_REPOSITORY))
    original_run_json = loaded["_run_json"]
    commands: list[list[str]] = []
    retained: dict[str, pathlib.Path] = {}
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

    def run_json(
        command: list[str], cwd: pathlib.Path
    ) -> tuple[int, dict[str, Any]]:
        commands.append(command)
        if pathlib.Path(command[1]) == MANAGE_PENDING_WORK:
            code, result = original_run_json(command, cwd)
            scope = pathlib.Path(str(result["pending_work_scope"]))
            checkpoint = scope.with_suffix(".release-publication.json")
            retained.update({"scope": scope, "checkpoint": checkpoint})
            return code, result
        assert pathlib.Path(command[1]) == SHIP_REPOSITORY
        retained["checkpoint"].write_text(
            "{}\n",
            encoding="utf-8",
            newline="\n",
        )
        return 1, blocker

    promote = loaded["promote"]
    promote.__globals__["_run_json"] = run_json
    args = loaded["build_parser"]().parse_args(
        [
            "--repo-root",
            str(repo),
            "--source-branch",
            "approved",
            "--ship-after-promotion",
        ]
    )
    with pytest.raises(loaded["PromotionError"]) as captured:
        promote(args)

    assert captured.value.payload == blocker
    assert len(commands) == 2
    assert retained["scope"].is_file()
    assert retained["checkpoint"].is_file()
    assert source_worktree.is_dir()
    assert run_git(source_worktree, "status", "--porcelain").stdout == ""
    assert run_git(repo, "show-ref", "--verify", "refs/heads/approved").returncode == 0
    assert run_git(repo, "status", "--porcelain").stdout == ""

    original_ship_after_promotion = loaded["_ship_after_promotion"]
    original_ship_after_promotion.__globals__["_run_json"] = (
        lambda command, cwd: (0, {"status": "ready"})
    )
    with pytest.raises(
        loaded["PromotionError"],
        match="incomplete terminal result",
    ):
        original_ship_after_promotion(
            args,
            repo.resolve(),
            target_commit=run_git(repo, "rev-parse", "release/local").stdout.strip(),
            pending_work_scope=str(retained["scope"]),
        )

    conflict_root = tmp_path / "promotion-blocker"
    (
        conflict_repo,
        _,
        _,
        conflict_release_head,
        _,
    ) = prepare_divergent_promotion_repo(conflict_root, conflict=True)
    conflict_loaded = runpy.run_path(str(PROMOTE_REPOSITORY))
    conflict_promote = conflict_loaded["promote"]

    def unexpected_run_json(
        command: list[str], cwd: pathlib.Path
    ) -> tuple[int, dict[str, Any]]:
        pytest.fail(f"promotion blocker invoked lifecycle child: {command}")

    conflict_promote.__globals__["_run_json"] = unexpected_run_json
    conflict_args = conflict_loaded["build_parser"]().parse_args(
        [
            "--repo-root",
            str(conflict_repo),
            "--source-branch",
            "approved",
            "--ship-after-promotion",
        ]
    )
    with pytest.raises(conflict_loaded["PromotionError"]):
        conflict_promote(conflict_args)
    assert run_git(conflict_repo, "rev-parse", "release/local").stdout.strip() == (
        conflict_release_head
    )


def test_promote_repository_prepare_only_mode_remains_unchanged(
    tmp_path: pathlib.Path,
) -> None:
    repo, _, log, _ = prepare_repository_lifecycle_repo(tmp_path)
    assert run_git(repo, "switch", "main").returncode == 0
    main_head = run_git(repo, "rev-parse", "main").stdout.strip()
    loaded = runpy.run_path(str(PROMOTE_REPOSITORY))
    promote = loaded["promote"]

    def unexpected_run_json(
        command: list[str], cwd: pathlib.Path
    ) -> tuple[int, dict[str, Any]]:
        pytest.fail(f"prepare-only invoked lifecycle child: {command}")

    promote.__globals__["_run_json"] = unexpected_run_json
    result = promote(
        loaded["build_parser"]().parse_args(
            [
                "--repo-root",
                str(repo),
                "--prepare-release-only",
            ]
        )
    )

    assert result == {
        "status": "prepared",
        "release_branch": "release/local",
        "head": main_head,
    }
    assert run_git(repo, "branch", "--show-current").stdout.strip() == "release/local"
    assert run_git(repo, "status", "--porcelain").stdout == ""
    assert not log.exists()


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

    divergent = tmp_path / "automatic-rebase-success"
    (
        rebase_repo,
        source_worktree,
        source_head,
        release_head,
        rebase_environment,
    ) = prepare_divergent_promotion_repo(divergent)
    rebased = subprocess.run(
        [
            sys.executable,
            str(PROMOTE_REPOSITORY),
            "--repo-root",
            str(rebase_repo),
            "--source-branch",
            "approved",
            "--no-run-operation",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=rebase_environment,
    )

    assert rebased.returncode == 0, rebased.stderr
    rebase_result = json.loads(rebased.stdout)
    new_source_head = run_git(source_worktree, "rev-parse", "HEAD").stdout.strip()
    assert new_source_head != source_head
    assert rebase_result["head"] == new_source_head
    assert rebase_result["rebased_branches"] == [
        {
            "branch": "approved",
            "old_head": source_head,
            "new_head": new_source_head,
            "onto": release_head,
        }
    ]
    assert (
        run_git(
            rebase_repo,
            "merge-base",
            "--is-ancestor",
            release_head,
            "approved",
        ).returncode
        == 0
    )
    assert run_git(source_worktree, "status", "--porcelain").stdout == ""
    assert (source_worktree / "release.txt").read_text(encoding="utf-8") == (
        "release\n"
    )
    assert "approved" in (source_worktree / "README.md").read_text(
        encoding="utf-8"
    )


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

    conflict_root = tmp_path / "automatic-rebase-conflict"
    (
        conflict_repo,
        conflict_worktree,
        conflict_source_head,
        conflict_release_head,
        conflict_environment,
    ) = prepare_divergent_promotion_repo(conflict_root, conflict=True)
    conflicted = subprocess.run(
        [
            sys.executable,
            str(PROMOTE_REPOSITORY),
            "--repo-root",
            str(conflict_repo),
            "--source-branch",
            "approved",
            "--no-run-operation",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=conflict_environment,
    )

    assert conflicted.returncode == 1
    conflict_message = json.loads(conflicted.stderr)["message"]
    assert "original head" in conflict_message
    assert "conflicting paths: README.md" in conflict_message
    assert run_git(conflict_worktree, "rev-parse", "HEAD").stdout.strip() == (
        conflict_source_head
    )
    assert run_git(conflict_worktree, "status", "--porcelain").stdout == ""
    assert run_git(conflict_repo, "rev-parse", "release/local").stdout.strip() == (
        conflict_release_head
    )

    published_root = tmp_path / "automatic-rebase-published"
    (
        published_repo,
        published_worktree,
        published_source_head,
        _,
        published_environment,
    ) = prepare_divergent_promotion_repo(published_root, published=True)
    published = subprocess.run(
        [
            sys.executable,
            str(PROMOTE_REPOSITORY),
            "--repo-root",
            str(published_repo),
            "--source-branch",
            "approved",
            "--no-run-operation",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=published_environment,
    )

    assert published.returncode == 1
    assert json.loads(published.stderr)["message"] == (
        "Automatic rebase refuses published branch: approved"
    )
    assert run_git(published_worktree, "rev-parse", "HEAD").stdout.strip() == (
        published_source_head
    )
    assert run_git(published_worktree, "status", "--porcelain").stdout == ""

    nonlinear_root = tmp_path / "automatic-rebase-nonlinear"
    (
        nonlinear_repo,
        nonlinear_worktree,
        nonlinear_source_head,
        _,
        nonlinear_environment,
    ) = prepare_divergent_promotion_repo(nonlinear_root, nonlinear=True)
    nonlinear = subprocess.run(
        [
            sys.executable,
            str(PROMOTE_REPOSITORY),
            "--repo-root",
            str(nonlinear_repo),
            "--source-branch",
            "approved",
            "--no-run-operation",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=nonlinear_environment,
    )

    assert nonlinear.returncode == 1
    assert json.loads(nonlinear.stderr)["message"] == (
        "Automatic rebase requires linear source history: approved"
    )
    assert run_git(nonlinear_worktree, "rev-parse", "HEAD").stdout.strip() == (
        nonlinear_source_head
    )
    assert run_git(nonlinear_worktree, "status", "--porcelain").stdout == ""


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
        json.dumps(
            {
                "version": 2,
                "target_branch": "release/local",
                "target_commit": "a" * 40,
                "sources": [
                    {
                        "branch": "selected",
                        "commit": "a" * 40,
                        "state": "retained",
                    }
                ],
            }
        ),
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
        **({"target_commit": "a" * 40} if scope_present else {}),
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
    review_request = tmp_path / "review-replies.json"
    parsed = loaded["build_parser"]().parse_args(
        [
            "--head-branch",
            "release/local",
            "--review-replies-request",
            str(review_request),
        ]
    )
    assert not hasattr(parsed, "pending_work_scope")
    assert not hasattr(parsed, "no_pending_work_check")
    assert parsed.review_replies_request == review_request
    ship_repository = loaded["ship_repository"]
    ship_repository.__globals__["_run_json"] = run_json
    ship_repository.__globals__["_branch_worktree"] = (
        lambda repo_root, branch: None
    )
    result = ship_repository(
        argparse.Namespace(
            repo_root=repo,
            repo="example/repository",
            head_branch="release/local",
            base_branch="main",
            remote_name="origin",
            commit=None if scope_present else "a" * 40,
            title=None,
            body=None,
            merge_method="merge",
            delete_branch=False,
            reusable_head=True,
            release_contract=pathlib.Path("release/release.yml"),
            release_preflight_operation="preflight",
            release_operation="publish",
            deploy_contract=pathlib.Path("deploy/deploy.yml"),
            deploy_operation="deploy",
            ci_wait_seconds=1,
            review_wait_seconds=1,
            review_replies_request=review_request,
            interval_seconds=1,
        )
    )

    assert result["release_publication"] == {
        "status": "no_op",
        "operation": "publish",
        "steps": [],
        "reason": "release_contract_absent",
    }
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
    if scope_present:
        assert "--target-commit" not in commands[0]
    else:
        assert commands[0][-2:] == ["--target-commit", "a" * 40]
    assert commands[1][commands[1].index("--commit") + 1] == "a" * 40
    assert commands[1][commands[1].index("--review-replies-request") + 1] == str(
        review_request
    )
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
                release_contract=pathlib.Path("release/release.yml"),
                release_preflight_operation="preflight",
                release_operation="publish",
                deploy_contract=pathlib.Path("deploy/deploy.yml"),
                deploy_operation="deploy",
                ci_wait_seconds=1,
                review_wait_seconds=1,
                review_replies_request=None,
                interval_seconds=1,
            )
        )
    assert captured.value.payload == blocker


@pytest.mark.parametrize("contract_kind", ["release", "deploy"])
def test_repository_ship_missing_custom_contract_blocks_before_remote_mutation(
    tmp_path: pathlib.Path,
    contract_kind: str,
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
                release_contract=pathlib.Path(
                    "release/custom.yml"
                    if contract_kind == "release"
                    else "release/release.yml"
                ),
                release_preflight_operation="preflight",
                release_operation="publish",
                deploy_contract=pathlib.Path(
                    "deploy/custom.yml"
                    if contract_kind == "deploy"
                    else "deploy/deploy.yml"
                ),
                deploy_operation="deploy",
                ci_wait_seconds=1,
                review_wait_seconds=1,
                interval_seconds=1,
            )
        )

    assert commands == []


def test_repository_ship_release_failure_blocks_deployment_and_cleanup(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert run_git(repo, "init").returncode == 0
    write_release_contract(
        repo,
        {
            "preflight": {
                "steps": [{"id": "check", "run": ["python", "check.py"]}]
            },
            "publish": {
                "steps": [{"id": "publish", "run": ["python", "publish.py"]}]
            },
        },
    )
    write_deploy_contract(
        repo,
        {
            "deploy": {
                "steps": [
                    {"id": "deploy", "run": ["python", "deploy.py"]}
                ]
            }
        },
    )
    prepared = {
        "status": "ready",
        "source_branches": [],
        "pending_work_scope": "",
    }
    shipped = {
        "status": "shipped",
        "repository": "example/repository",
        "commit": "a" * 40,
        "pr": 17,
        "url": "https://example.invalid/pull/17",
        "merge_commit": "c" * 40,
        "synchronized_head": "b" * 40,
    }
    release_error = {"status": "error", "message": "workflow failed"}
    responses: list[tuple[int, dict[str, Any]]] = [
        (
            0,
            {
                "status": "checked",
                "operation": "preflight",
                "steps": ["check"],
            },
        ),
        (0, prepared),
        (0, shipped),
        (1, release_error),
    ]
    commands: list[list[str]] = []

    def run_json(command: list[str]) -> tuple[int, dict[str, Any]]:
        commands.append(command)
        return responses[len(commands) - 1]

    loaded = runpy.run_path(str(SHIP_REPOSITORY))
    ship_repository = loaded["ship_repository"]
    ship_repository.__globals__["_run_json"] = run_json
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
        release_contract=pathlib.Path("release/release.yml"),
        release_preflight_operation="preflight",
        release_operation="publish",
        deploy_contract=pathlib.Path("deploy/deploy.yml"),
        deploy_operation="deploy",
        ci_wait_seconds=1,
        review_wait_seconds=1,
        review_replies_request=None,
        interval_seconds=1,
    )
    with pytest.raises(loaded["RepositoryShipError"]) as captured:
        ship_repository(args)

    assert captured.value.payload["phase"] == "release_publication"
    assert captured.value.payload["remote_mutation"] is True
    assert len(commands) == 4
    assert str(RELEASE_OPERATION) in commands[-1]
    assert "publish" in commands[-1]
    assert all(str(DEPLOY_OPERATION) not in command for command in commands)

    published = {"status": "published", "operation": "publish", "steps": []}
    deploy_error = {"status": "error", "message": "deployment failed"}
    preflight = {"status": "checked", "operation": "preflight", "steps": []}
    responses = [
        (0, preflight),
        (0, prepared),
        (0, shipped),
        (0, published),
        (1, deploy_error),
    ]
    commands.clear()
    with pytest.raises(loaded["RepositoryShipError"]) as captured:
        ship_repository(args)

    assert captured.value.payload["phase"] == "deployment"
    release_checkpoint = loaded["_operation_checkpoint_path"](
        repo, "a" * 40, "release_publication"
    )
    assert release_checkpoint.is_file()

    deployed = {"status": "deployed", "operation": "deploy", "steps": []}
    responses = [
        (0, preflight),
        (0, prepared),
        (0, {**shipped, "status": "already_shipped"}),
        (0, deployed),
    ]
    commands.clear()
    resumed = ship_repository(args)

    assert resumed["release_publication"] == published
    assert resumed["deployment"] == deployed
    assert all("publish" not in command for command in commands)
    assert not release_checkpoint.exists()


@pytest.mark.parametrize("late_phase", ["post_sync", "post_finalize"])
@pytest.mark.parametrize("relative_scope", [False, True])
def test_repository_ship_late_pending_work_reports_remote_mutation(
    tmp_path: pathlib.Path,
    late_phase: str,
    relative_scope: bool,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert run_git(repo, "init").returncode == 0
    (repo / "deploy").mkdir()
    (repo / "deploy" / "deploy.yml").write_text(
        "version: 1\noperations: {}\n",
        encoding="utf-8",
        newline="\n",
    )
    write_release_contract(
        repo,
        {
            "preflight": {
                "steps": [{"id": "check", "run": ["python", "check.py"]}]
            },
            "publish": {
                "steps": [{"id": "publish", "run": ["python", "publish.py"]}]
            },
        },
    )
    scope = repo / "scope.json" if relative_scope else tmp_path / "scope.json"
    scope.write_text(
        json.dumps(
            {
                "version": 2,
                "target_branch": "release/local",
                "target_commit": "a" * 40,
                "sources": [
                    {
                        "branch": "selected",
                        "commit": "a" * 40,
                        "state": "retained",
                    }
                ],
            }
        ),
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
    preflight = {
        "status": "checked",
        "operation": "preflight",
        "steps": ["check"],
    }
    published = {
        "status": "published",
        "operation": "publish",
        "steps": ["publish"],
    }
    prepared = {
        "status": "ready",
        "source_branches": ["selected"],
        "pending_work_scope": str(scope.resolve()),
    }
    responses: list[tuple[int, dict[str, Any]]] = (
        [(0, preflight), (0, prepared), (0, shipped), (2, pending)]
        if late_phase == "post_sync"
        else [
            (0, preflight),
            (0, prepared),
            (0, shipped),
            (0, prepared),
            (0, published),
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
        release_contract=pathlib.Path("release/release.yml"),
        release_preflight_operation="preflight",
        release_operation="publish",
        deploy_contract=pathlib.Path("deploy/deploy.yml"),
        deploy_operation="deploy",
        ci_wait_seconds=1,
        review_wait_seconds=1,
        interval_seconds=1,
    )
    if late_phase == "post_finalize":
        stale_identity = loaded["_operation_identity"](
            repo,
            phase="deployment",
            target_branch="release/local",
            target_commit="d" * 40,
            synchronized_commit="b" * 40,
            contract=args.deploy_contract,
            operation="deploy",
        )
        loaded["_write_operation_checkpoint"](
            loaded["_operation_checkpoint_path"](
                repo, "a" * 40, "deployment"
            ),
            stale_identity,
            {"status": "deployed", "operation": "deploy", "steps": ["old"]},
        )

    result = ship_repository(args)

    assert result["status"] == "pending_work"
    assert result["remote_mutation"] is True
    assert result["repository"] == "example/repository"
    assert result["commit"] == "a" * 40
    release_runner = str(SHIP_REPOSITORY.parent / "run-release-operation.py")
    deploy_runner = str(SHIP_REPOSITORY.parent / "run-deploy-operation.py")
    assert release_runner in commands[0]
    assert "preflight" in commands[0]
    assert "prepare" in commands[1]
    assert "check" in commands[3]
    if late_phase == "post_sync":
        assert len(commands) == 4
        assert "deployment" not in result
    else:
        assert len(commands) == 7
        assert release_runner in commands[4]
        assert "publish" in commands[4]
        assert deploy_runner in commands[5]
        assert "finalize" in commands[6]
        assert result["release_publication"] == published
        assert result["deployment"] == deployed
        release_checkpoint = loaded["_operation_checkpoint_path"](
            repo, "a" * 40, "release_publication"
        )
        deployment_checkpoint = loaded["_operation_checkpoint_path"](
            repo, "a" * 40, "deployment"
        )
        assert release_checkpoint.is_file()
        assert deployment_checkpoint.is_file()
        release_temporary = release_checkpoint.with_suffix(
            release_checkpoint.suffix + ".tmp"
        )
        deployment_temporary = deployment_checkpoint.with_suffix(
            deployment_checkpoint.suffix + ".tmp"
        )
        release_temporary.write_text("stale", encoding="utf-8", newline="\n")
        deployment_temporary.write_text("stale", encoding="utf-8", newline="\n")
        unrelated_temporary = scope.with_name("unrelated.tmp")
        unrelated_temporary.write_text("retained", encoding="utf-8", newline="\n")
        responses.extend(
            [
                (0, preflight),
                (0, prepared),
                (0, {**shipped, "status": "already_shipped"}),
                (0, prepared),
                (0, {"status": "finalized"}),
            ]
        )

        resumed = ship_repository(args)

        assert resumed["status"] == "already_shipped"
        assert resumed["release_publication"] == published
        assert resumed["deployment"] == deployed
        assert len(commands) == 12
        assert all(release_runner not in command for command in commands[8:])
        assert all(deploy_runner not in command for command in commands[7:])
        assert not release_checkpoint.exists()
        assert not deployment_checkpoint.exists()
        assert not release_temporary.exists()
        assert not deployment_temporary.exists()
        assert unrelated_temporary.is_file()


def test_repository_ship_rejects_malformed_deployment_checkpoint(
    tmp_path: pathlib.Path,
) -> None:
    loaded = runpy.run_path(str(SHIP_REPOSITORY))
    checkpoint = tmp_path / "scope.deployment.json"
    checkpoint.write_text("{}", encoding="utf-8", newline="\n")
    identity = {
        "version": 1,
        "phase": "deployment",
        "target_branch": "release/local",
        "target_commit": "a" * 40,
        "synchronized_commit": "b" * 40,
        "contract": str(tmp_path / "deploy.yml"),
        "operation": "deploy",
    }

    with pytest.raises(
        loaded["RepositoryShipError"],
        match="invalid structure",
    ):
        loaded["_read_operation_checkpoint"](checkpoint, identity)


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
                "version": 2,
                "target_branch": "release/local",
                "target_commit": "a" * 40,
                "sources": [
                    {
                        "branch": "selected",
                        "commit": "a" * 40,
                        "state": "retained",
                    }
                ],
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
                release_contract=pathlib.Path("release/release.yml"),
                release_preflight_operation="preflight",
                release_operation="publish",
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
        "sources": [
            {
                "branch": "selected",
                "commit": target_commit,
                "state": "retained",
            }
        ],
        "target_branch": "release/local",
        "target_commit": target_commit,
        "version": 2,
    }

    lifecycle_scripts = str(MANAGE_PENDING_WORK.parent)
    sys.path.insert(0, lifecycle_scripts)
    try:
        loaded = runpy.run_path(str(MANAGE_PENDING_WORK))
    finally:
        sys.path.remove(lifecycle_scripts)
    ship_module = loaded["ship"]
    unrelated_commit = run_git(repo, "rev-parse", "refs/heads/unrelated").stdout.strip()
    identity_scope = tmp_path / "identity-scope.json"
    identity_scope.write_text(
        json.dumps(
            {
                "version": 2,
                "target_branch": "release/local",
                "target_commit": target_commit,
                "sources": [
                    {
                        "branch": "unrelated",
                        "commit": unrelated_commit,
                        "state": "retained",
                    },
                    {
                        "branch": "selected",
                        "commit": target_commit,
                        "state": "retained",
                    },
                ],
            }
        ),
        encoding="utf-8",
        newline="\n",
    )
    identity, normalized = ship_module._load_pending_work_scope(
        argparse.Namespace(
            pending_work_check=True,
            pending_work_scope=identity_scope,
            head_branch="release/local",
        ),
        repo,
        target_commit,
    )
    expected_normalized = {
        "version": 2,
        "target_branch": "release/local",
        "target_commit": target_commit,
        "sources": [
            {
                "branch": "selected",
                "commit": target_commit,
                "state": "retained",
            },
            {
                "branch": "unrelated",
                "commit": unrelated_commit,
                "state": "retained",
            },
        ],
    }
    assert normalized == expected_normalized
    serialized_scope = json.dumps(
        expected_normalized, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    assert identity == {
        "enabled": True,
        "scope_sha256": hashlib.sha256(serialized_scope).hexdigest(),
    }

    scope_value = json.loads(scope_path.read_text(encoding="utf-8"))
    scope_value["sources"][0]["state"] = "deleting"
    scope_path.write_text(
        json.dumps(scope_value), encoding="utf-8", newline="\n"
    )
    incomplete = run_pending_work(
        repo,
        "record",
        "--target-branch",
        "release/local",
        "--target-commit",
        target_commit,
        "--source-branch",
        "selected",
    )
    assert incomplete.returncode == 2, incomplete.stderr
    incomplete_payload = json.loads(incomplete.stdout)
    assert [item["kind"] for item in incomplete_payload["findings"]] == [
        "incomplete_cleanup"
    ]
    assert run_git(repo, "show-ref", "--verify", "refs/heads/selected").returncode == 0
    assert json.loads(scope_path.read_text(encoding="utf-8"))["sources"][0][
        "state"
    ] == "deleting"

    scope_value["sources"][0]["state"] = "retained"
    scope_value["sources"].insert(
        0,
        {
            "branch": "missing",
            "commit": target_commit,
            "state": "retained",
        },
    )
    scope_path.write_text(
        json.dumps(scope_value),
        encoding="utf-8",
        newline="\n",
    )
    missing_retained = run_pending_work(
        repo,
        "prepare",
        "--target-branch",
        "release/local",
    )
    assert missing_retained.returncode == 2, missing_retained.stderr
    missing_payload = json.loads(missing_retained.stdout)
    assert missing_payload["findings"] == [
        {
            "kind": "missing_branch",
            "subject": "missing",
            "detail": "selected source branch is missing",
        }
    ]
    assert [source["branch"] for source in json.loads(
        scope_path.read_text(encoding="utf-8")
    )["sources"]] == ["missing", "selected"]
    scope_value["sources"] = [scope_value["sources"][1]]
    scope_path.write_text(
        json.dumps(scope_value), encoding="utf-8", newline="\n"
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
    assert checked_payload["target_commit"] == target_commit
    assert [(item["kind"], item["subject"]) for item in checked_payload["findings"]] == [
        ("dirty_worktree", "selected"),
        ("unmerged_branch_commits", "selected"),
    ]
    assert json.loads(scope_path.read_text(encoding="utf-8"))["sources"] == [
        {
            "branch": "selected",
            "commit": target_commit,
            "state": "retained",
        }
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
    assert run_git(repo, "branch", "next-selected", advanced_commit).returncode == 0
    diverged = run_pending_work(
        repo,
        "record",
        "--target-branch",
        "release/local",
        "--target-commit",
        advanced_commit,
        "--source-branch",
        "next-selected",
    )
    assert diverged.returncode == 2, diverged.stderr
    assert json.loads(diverged.stdout)["findings"] == [
        {
            "kind": "target_history_diverged",
            "subject": "release/local",
            "detail": "recorded target is not an ancestor of new target",
        }
    ]
    assert json.loads(scope_path.read_text(encoding="utf-8"))[
        "target_commit"
    ] == target_commit
    resumed = run_pending_work(
        repo,
        "prepare",
        "--target-branch",
        "release/local",
    )
    assert resumed.returncode == 2, resumed.stderr
    resumed_payload = json.loads(resumed.stdout)
    assert resumed_payload["target_commit"] == target_commit
    assert resumed_payload["findings"] == checked_payload["findings"]
    mismatched = run_pending_work(
        repo,
        "prepare",
        "--target-branch",
        "release/local",
        "--target-commit",
        advanced_commit,
    )
    assert mismatched.returncode == 1
    assert "does not match" in json.loads(mismatched.stderr)["message"]
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

    assert run_git(repo, "branch", "recover-old", target_commit).returncode == 0
    recover_recorded = run_pending_work(
        repo,
        "record",
        "--target-branch",
        "release/local",
        "--target-commit",
        target_commit,
        "--source-branch",
        "recover-old",
    )
    assert recover_recorded.returncode == 0, recover_recorded.stderr
    recovery_scope = json.loads(scope_path.read_text(encoding="utf-8"))
    recovery_scope["sources"][0]["state"] = "deleting"
    scope_path.write_text(
        json.dumps(recovery_scope), encoding="utf-8", newline="\n"
    )
    assert run_git(repo, "branch", "-d", "recover-old").returncode == 0
    target_tree = run_git(repo, "rev-parse", f"{target_commit}^{{tree}}").stdout.strip()
    descendant = run_git(
        repo,
        "commit-tree",
        target_tree,
        "-p",
        target_commit,
        "-m",
        "advance reusable release",
    )
    assert descendant.returncode == 0, descendant.stderr
    descendant_target = descendant.stdout.strip()
    assert run_git(
        repo,
        "update-ref",
        "refs/heads/release/local",
        descendant_target,
        target_commit,
    ).returncode == 0
    assert run_git(repo, "branch", "next-source", descendant_target).returncode == 0
    advanced_record = run_pending_work(
        repo,
        "record",
        "--target-branch",
        "release/local",
        "--target-commit",
        descendant_target,
        "--source-branch",
        "next-source",
    )
    assert advanced_record.returncode == 0, advanced_record.stderr
    assert json.loads(scope_path.read_text(encoding="utf-8")) == {
        "version": 2,
        "target_branch": "release/local",
        "target_commit": descendant_target,
        "sources": [
            {
                "branch": "next-source",
                "commit": descendant_target,
                "state": "retained",
            }
        ],
    }
    assert run_git(repo, "merge", "--ff-only", "release/local").returncode == 0
    descendant_main = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    finalized_advanced = run_pending_work(
        repo,
        "finalize",
        "--scope",
        str(scope_path),
        "--target-branch",
        "release/local",
        "--target-commit",
        descendant_target,
        "--current-branch",
        "main",
        "--current-commit",
        descendant_main,
    )
    assert finalized_advanced.returncode == 0, finalized_advanced.stderr
    assert not scope_path.exists()

    scope_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "branch": "already-gone",
                        "commit": advanced_commit,
                        "state": "deleting",
                    }
                ],
                "target_branch": "release/local",
                "target_commit": descendant_target,
                "version": 2,
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
        descendant_target,
    )

    assert prepared.returncode == 2, prepared.stderr
    assert json.loads(prepared.stdout)["findings"] == [
        {
            "kind": "recorded_source_not_in_target",
            "subject": "already-gone",
            "detail": "recorded source commit is not in target commit",
        }
    ]
    assert scope_path.is_file()

    scope_path.write_text(
        json.dumps(
            {
                "source_branches": ["old-format"],
                "target_branch": "release/local",
                "target_commit": descendant_target,
                "version": 1,
            }
        ),
        encoding="utf-8",
        newline="\n",
    )
    old_format = run_pending_work(
        repo,
        "prepare",
        "--target-branch",
        "release/local",
        "--target-commit",
        descendant_target,
    )
    assert old_format.returncode == 1
    assert "sources" in json.loads(old_format.stderr)["message"]
    assert scope_path.is_file()
    scope_path.unlink()

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
    monkeypatch: pytest.MonkeyPatch,
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
    selected_a_commit = run_git(repo, "rev-parse", "HEAD").stdout.strip()
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
    original_run_command = finalize_scope.__globals__["run_command"]
    original_residual_cleanup = finalize_scope.__globals__[
        "_finish_recorded_residual_cleanup"
    ]
    pending_error = loaded["PendingWorkError"]

    def leave_unregistered_residual(
        command: list[str],
        *,
        cwd: pathlib.Path,
    ) -> subprocess.CompletedProcess[str]:
        if command[-3:] == ["worktree", "remove", str(selected_a.resolve())]:
            removed = original_run_command(command, cwd=cwd)
            assert removed.returncode == 0, removed.stderr
            selected_a.mkdir(parents=True)
            (selected_a / ".pytest_cache").mkdir()
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="simulated failure after Git unregistered the worktree",
            )
        return original_run_command(command, cwd=cwd)

    def interrupt_residual_cleanup(
        repo_root: pathlib.Path,
        record_path: pathlib.Path,
    ) -> None:
        raise pending_error("simulated residual cleanup interruption")

    finalize_scope.__globals__["run_command"] = leave_unregistered_residual
    finalize_scope.__globals__["_finish_recorded_residual_cleanup"] = (
        interrupt_residual_cleanup
    )
    with pytest.raises(pending_error, match="residual cleanup interruption"):
        finalize_scope(
            repo,
            scope_path,
            target_branch="release/local",
            target_commit=target_commit,
            current_branch="main",
            current_commit=current_commit,
        )

    residual_cleanup_record = loaded["_residual_cleanup_record_path"](
        scope_path, "selected-a"
    )
    assert residual_cleanup_record.is_file()
    residual_temporary = residual_cleanup_record.with_suffix(".tmp")
    residual_temporary.write_text("stale", encoding="utf-8", newline="\n")
    unrelated_temporary = residual_cleanup_record.with_name("unrelated.tmp")
    unrelated_temporary.write_text("retained", encoding="utf-8", newline="\n")
    assert selected_a.is_dir()
    assert (
        run_git(
            repo,
            "for-each-ref",
            "--format=%(worktreepath)",
            "refs/heads/selected-a",
        ).stdout.strip()
        == ""
    )
    assert json.loads(scope_path.read_text(encoding="utf-8"))["sources"] == [
        {
            "branch": "selected-a",
            "commit": selected_a_commit,
            "state": "deleting",
        },
        {
            "branch": "selected-b",
            "commit": target_commit,
            "state": "retained",
        },
    ]

    finalize_scope.__globals__["run_command"] = original_run_command
    finalize_scope.__globals__["_finish_recorded_residual_cleanup"] = (
        original_residual_cleanup
    )

    def fail_second_branch(
        command: list[str],
        *,
        cwd: pathlib.Path,
    ) -> subprocess.CompletedProcess[str]:
        if command[-3:] == ["branch", "-d", "selected-b"]:
            raise pending_error("simulated second-branch cleanup failure")
        return original_require_success(command, cwd=cwd)

    original_rmtree = shutil.rmtree
    residual_cleanup_steps: list[str] = []

    def deny_first_residual(path: pathlib.Path, *args: Any, **kwargs: Any) -> None:
        if pathlib.Path(path) == selected_a and not residual_cleanup_steps:
            residual_cleanup_steps.append("permission_denied")
            raise PermissionError("simulated inaccessible cache")
        original_rmtree(path, *args, **kwargs)

    def ownership_cleanup(
        repo_root: pathlib.Path,
        record_path: pathlib.Path,
    ) -> None:
        _, _, worktree, _ = loaded["_read_residual_cleanup_record"](
            repo_root, record_path
        )
        residual_cleanup_steps.append("ownership")
        original_rmtree(worktree)

    monkeypatch.setattr(shutil, "rmtree", deny_first_residual)
    finalize_scope.__globals__["_run_recorded_residual_cleanup"] = (
        ownership_cleanup
    )
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

    assert residual_cleanup_steps == ["permission_denied", "ownership"]
    assert not selected_a.exists()
    assert not residual_cleanup_record.exists()
    assert not residual_temporary.exists()
    assert unrelated_temporary.is_file()
    assert json.loads(scope_path.read_text(encoding="utf-8"))["sources"] == [
        {
            "branch": "selected-b",
            "commit": target_commit,
            "state": "deleting",
        }
    ]
    assert run_git(repo, "show-ref", "--verify", "refs/heads/selected-a").returncode != 0
    assert run_git(repo, "show-ref", "--verify", "refs/heads/selected-b").returncode == 0
    monkeypatch.setattr(shutil, "rmtree", original_rmtree)
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

    assert run_git(repo, "branch", "crash-delete", target_commit).returncode == 0
    crash_recorded = run_pending_work(
        repo,
        "record",
        "--target-branch",
        "release/local",
        "--target-commit",
        target_commit,
        "--source-branch",
        "crash-delete",
    )
    assert crash_recorded.returncode == 0, crash_recorded.stderr
    crash_scope = pathlib.Path(
        json.loads(crash_recorded.stdout)["pending_work_scope"]
    )
    original_remove_source = finalize_scope.__globals__["_remove_source_record"]

    def interrupt_after_branch_deletion(
        path: pathlib.Path,
        scope: dict[str, Any],
        branch: str,
    ) -> None:
        assert branch == "crash-delete"
        raise pending_error("simulated interruption after branch deletion")

    finalize_scope.__globals__["_remove_source_record"] = (
        interrupt_after_branch_deletion
    )
    with pytest.raises(pending_error, match="after branch deletion"):
        finalize_scope(
            repo,
            crash_scope,
            target_branch="release/local",
            target_commit=target_commit,
            current_branch="main",
            current_commit=current_commit,
        )

    assert run_git(
        repo, "show-ref", "--verify", "refs/heads/crash-delete"
    ).returncode != 0
    assert json.loads(crash_scope.read_text(encoding="utf-8"))["sources"] == [
        {
            "branch": "crash-delete",
            "commit": target_commit,
            "state": "deleting",
        }
    ]
    crash_temporary = crash_scope.with_suffix(".tmp")
    crash_temporary.write_text("stale", encoding="utf-8", newline="\n")
    finalize_scope.__globals__["_remove_source_record"] = original_remove_source
    recovered = finalize_scope(
        repo,
        crash_scope,
        target_branch="release/local",
        target_commit=target_commit,
        current_branch="main",
        current_commit=current_commit,
    )
    assert recovered == {
        "status": "finalized",
        "removed": [],
        "pending_work_scope": "",
    }
    assert not crash_scope.exists()
    assert not crash_temporary.exists()
    assert unrelated_temporary.is_file()

    ownership_target = worktree_root / "ownership-target"
    ownership_target.mkdir(parents=True)
    ownership_commands: list[list[str]] = []
    removed_targets: list[pathlib.Path] = []
    take_ownership_and_remove = loaded["_take_ownership_and_remove"]
    original_ownership_require = take_ownership_and_remove.__globals__["require_success"]

    def capture_ownership_command(
        command: list[str],
        *,
        cwd: pathlib.Path,
    ) -> None:
        assert cwd == worktree_root
        ownership_commands.append(command)

    def capture_ownership_removal(path: pathlib.Path) -> None:
        removed_targets.append(pathlib.Path(path))
        original_rmtree(path)

    take_ownership_and_remove.__globals__["require_success"] = capture_ownership_command
    monkeypatch.setattr(shutil, "rmtree", capture_ownership_removal)
    take_ownership_and_remove(repo, ownership_target, worktree_root.resolve())
    take_ownership_and_remove.__globals__["require_success"] = (
        original_ownership_require
    )

    assert ownership_commands == [
        [
            "takeown.exe",
            "/F",
            str(ownership_target),
            "/A",
            "/R",
            "/D",
            "Y",
            "/SKIPSL",
        ],
        [
            "icacls.exe",
            str(ownership_target),
            "/grant",
            "*S-1-5-32-544:(OI)(CI)F",
            "/T",
            "/C",
            "/L",
            "/Q",
        ],
    ]
    assert removed_targets == [ownership_target]
    assert not ownership_target.exists()


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
    assert 'python-version: "3.12"' in pnpm_workflow

    uv_repo = empty_repository("uv-compatible")
    (uv_repo / "uv.lock").write_text("version = 1\n", encoding="utf-8", newline="\n")
    (uv_repo / "pyproject.toml").write_text(
        '[project]\nname = "uv-compatible"\nversion = "1.0.0"\n'
        'requires-python = ">=3.13"\n'
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
    assert 'python-version-file: "pyproject.toml"' in uv_workflow
    assert 'python-version: "3.12"' not in uv_workflow
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
    manifest["runtime_payloads"] = {
        "alpha-tool": [
            {
                "source": "runtime-note.md",
                "target": "references/runtime-note.md",
            }
        ]
    }
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
    payload = payload_repo / "skills" / "sections" / "scripts" / "payload-alpha.py"
    payload.parent.mkdir()
    payload.write_text("one\n", encoding="utf-8", newline="\n")
    manifest_path = payload_repo / "skills" / "skill-sections.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mapped_payload = {
        "source": "skills/sections/scripts/payload-alpha.py",
        "target": "scripts/payload-alpha.py",
    }
    manifest["runtime_payloads"] = {"alpha-tool": [mapped_payload]}
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
    assert (
        run_git(
            payload_repo,
            "add",
            "skills/sections/scripts/payload-alpha.py",
        ).returncode
        == 0
    )
    assert run_git(payload_repo, "commit", "-m", "payload").returncode == 0

    payload_affected = installer["affected_from_base"](
        payload_repo, payload_base
    )
    assert payload_affected.deploy == ("alpha-tool",)
    assert payload_affected.remove == ()
    assert payload_affected.all_managed is False
    wildcard_base = run_git(payload_repo, "rev-parse", "HEAD").stdout.strip()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtime_payloads"] = {"*": [mapped_payload]}
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
    create_compatible_repo(
        repo,
        "example/compatible",
        ["alpha-tool", "beta-tool"],
    )
    shared = repo / "skills" / "sections" / "scripts" / "shared.py"
    shared.parent.mkdir()
    shared.write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
    manifest_path = repo / "skills" / "skill-sections.json"
    manifest_source = json.loads(manifest_path.read_text(encoding="utf-8"))
    mapped_payload = {
        "source": "skills/sections/scripts/shared.py",
        "target": "scripts/shared.py",
    }
    manifest_source["runtime_payloads"] = {
        "alpha-tool": [mapped_payload],
        "beta-tool": [mapped_payload],
    }
    manifest_path.write_text(
        json.dumps(manifest_source, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    result = run_builder(repo, install_root, "--skill", "alpha-tool")

    assert result.returncode == 0, result.stderr
    manifest = json.loads((install_root / "alpha-tool" / RUNTIME_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["schema"] == RUNTIME_MANIFEST_SCHEMA
    assert manifest["skill"] == "alpha-tool"
    assert manifest["runtime_source_id"] == "example/compatible"
    assert manifest["source_path"] == "skills/alpha-tool"
    assert manifest["source_repository_root"] == str(repo.resolve())
    assert manifest["validation_profile"] == "ceratops-compatible"
    assert manifest["payload_patterns"] == [mapped_payload]
    assert "installer_version" not in manifest
    assert (install_root / "alpha-tool" / "scripts" / "shared.py").read_text(
        encoding="utf-8"
    ) == "VALUE = 1\n"
    assert not (
        install_root
        / "alpha-tool"
        / "skills"
        / "sections"
        / "scripts"
        / "shared.py"
    ).exists()

    bootstrap_root = tmp_path / "bootstrap-installed"
    bootstrap = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "install-skills-bootstrap.py"),
            "--repo-root",
            str(repo),
            "--install-root",
            str(bootstrap_root),
            "--skill",
            "alpha-tool",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(tmp_path / "empty-codex-home")},
    )
    assert bootstrap.returncode == 0, bootstrap.stderr
    assert (
        bootstrap_root / "alpha-tool" / "scripts" / "shared.py"
    ).is_file()


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
