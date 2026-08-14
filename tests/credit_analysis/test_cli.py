from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys

from tests.credit_analysis.models import (
    load_credit_analysis_workflow_module,
)
from tests.credit_analysis.paths import (
    MODEL_CALL_LEDGER,
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
