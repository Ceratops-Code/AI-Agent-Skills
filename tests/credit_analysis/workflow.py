from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from typing import Any, Mapping

from tests.credit_analysis.paths import (
    CREDIT_ANALYSIS_CONTRACT,
    CREDIT_ANALYSIS_WORKFLOW,
    ROOT,
)
from tests.credit_analysis.sessions import (
    finding_record,
    surface_result_record,
    write_json_file,
)


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
