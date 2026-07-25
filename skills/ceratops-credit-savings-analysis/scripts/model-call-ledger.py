#!/usr/bin/env python3
"""Emit a compact, judgment-free model-call ledger from one Codex session.

The ledger groups automatic continuations by turn ID, includes only completed
runs, and fingerprints tool arguments instead of reproducing potentially
sensitive command text. It is evidence for credit analysis; the model remains
responsible for deciding whether a call was necessary or avoidable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from collections import Counter
from typing import Any


SCHEMA = "ceratops-model-call-ledger.v1"
SUMMARY_SCHEMA = "ceratops-model-call-ledger-summary.v1"
TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


class LedgerError(RuntimeError):
    """Report invalid session evidence without exposing raw record contents."""


def positive_int(value: str) -> int:
    """Parse a positive count for the optional completed-run window."""

    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def load_rows(path: pathlib.Path) -> list[dict[str, Any]]:
    """Load JSONL records while identifying malformed line numbers."""

    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as session:
            for line_number, line in enumerate(session, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise LedgerError(
                        f"invalid JSON on session line {line_number}"
                    ) from exc
                if not isinstance(row, dict):
                    raise LedgerError(
                        f"session line {line_number} is not a JSON object"
                    )
                rows.append(row)
    except OSError as exc:
        raise LedgerError(f"could not read session: {exc}") from exc
    return rows


def stable_payload(value: Any) -> str:
    """Serialize tool arguments deterministically for duplicate detection."""

    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value
        return json.dumps(decoded, sort_keys=True, separators=(",", ":"))
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def payload_fingerprint(value: Any) -> str:
    """Hash tool arguments so the ledger does not echo commands or secrets."""

    return hashlib.sha256(stable_payload(value).encode("utf-8")).hexdigest()[:16]


def action_from_item(payload: dict[str, Any]) -> dict[str, str] | None:
    """Reduce one response item to a compact message or tool action."""

    item_type = payload.get("type")
    if item_type == "message" and payload.get("role") != "user":
        phase = payload.get("phase")
        return {
            "kind": "message",
            "name": phase if isinstance(phase, str) else "assistant",
        }
    if item_type == "function_call":
        name = payload.get("name")
        arguments = payload.get("arguments")
    elif item_type == "custom_tool_call":
        name = payload.get("name")
        arguments = payload.get("input")
    elif item_type == "tool_search_call":
        name = "tool_search"
        arguments = payload.get("arguments")
    else:
        return None
    return {
        "kind": "tool",
        "name": name if isinstance(name, str) else "unknown",
        "fingerprint": payload_fingerprint(arguments),
    }


def token_usage(payload: dict[str, Any]) -> dict[str, int]:
    """Select non-negative integer usage fields from one token-count event."""

    info = payload.get("info")
    last = info.get("last_token_usage") if isinstance(info, dict) else None
    usage: dict[str, int] = {}
    if not isinstance(last, dict):
        return usage
    for field in TOKEN_FIELDS:
        value = last.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            usage[field] = value
    return usage


def build_ledger(
    rows: list[dict[str, Any]],
    *,
    session: pathlib.Path,
    last_runs: int | None,
) -> dict[str, Any]:
    """Group completed runs and enumerate every non-empty model response."""

    ordered_turns: list[str] = []
    runs: dict[str, dict[str, Any]] = {}
    active_turn: str | None = None
    pending_actions: list[dict[str, str]] = []

    for row in rows:
        row_type = row.get("type")
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue

        if row_type == "turn_context":
            turn_id = payload.get("turn_id")
            active_turn = turn_id if isinstance(turn_id, str) else None
            pending_actions = []
            if active_turn is not None and active_turn not in runs:
                ordered_turns.append(active_turn)
                runs[active_turn] = {
                    "turn_id": active_turn,
                    "started_at": row.get("timestamp"),
                    "completed": False,
                    "calls": [],
                }
            continue

        if active_turn is None or active_turn not in runs:
            continue

        if row_type == "response_item":
            action = action_from_item(payload)
            if action is not None:
                pending_actions.append(action)
            if (
                payload.get("type") == "message"
                and payload.get("role") != "user"
                and payload.get("phase") == "final_answer"
            ):
                runs[active_turn]["completed"] = True
            continue

        if row_type != "event_msg" or payload.get("type") != "token_count":
            continue
        usage = token_usage(payload)
        if sum(usage.values()) == 0:
            pending_actions = []
            continue
        calls = runs[active_turn]["calls"]
        calls.append(
            {
                "index": len(calls) + 1,
                "timestamp": row.get("timestamp"),
                "actions": pending_actions,
                "tokens": usage,
            }
        )
        pending_actions = []

    selected = [
        runs[turn_id]
        for turn_id in ordered_turns
        if runs[turn_id]["completed"]
    ]
    if last_runs is not None:
        selected = selected[-last_runs:]

    selected_fingerprints = Counter(
        (action["name"], action["fingerprint"])
        for run in selected
        for call in run["calls"]
        for action in call["actions"]
        if action["kind"] == "tool"
    )
    totals = {field: 0 for field in TOKEN_FIELDS}
    for run in selected:
        run_totals = {field: 0 for field in TOKEN_FIELDS}
        for call in run["calls"]:
            for field, value in call["tokens"].items():
                run_totals[field] += value
                totals[field] += value
        run["model_calls"] = len(run["calls"])
        run["tokens"] = run_totals
        del run["completed"]

    repeated = [
        {"name": name, "fingerprint": fingerprint, "count": count}
        for (name, fingerprint), count in selected_fingerprints.items()
        if count > 1
    ]
    repeated.sort(
        key=lambda item: (-item["count"], item["name"], item["fingerprint"])
    )

    return {
        "schema": SCHEMA,
        "session": str(session),
        "window": {
            "mode": "last_runs" if last_runs is not None else "full_thread",
            "requested_runs": last_runs,
            "completed_runs": len(selected),
        },
        "totals": {
            "runs": len(selected),
            "model_calls": sum(run["model_calls"] for run in selected),
            **totals,
        },
        "repeated_tool_calls": repeated,
        "runs": selected,
    }


def build_summary(
    ledger: dict[str, Any],
    *,
    evidence_output: pathlib.Path,
    include_runs: list[str],
) -> dict[str, Any]:
    """Keep stdout small while exposing explicitly requested run details."""

    runs = ledger["runs"]
    runs_by_id = {run["turn_id"]: run for run in runs}
    unknown = sorted(set(include_runs) - runs_by_id.keys())
    if unknown:
        raise LedgerError(f"requested run is outside the completed window: {unknown[0]}")
    return {
        "schema": SUMMARY_SCHEMA,
        "evidence_schema": ledger["schema"],
        "evidence_output": str(evidence_output),
        "window": ledger["window"],
        "totals": ledger["totals"],
        "repeated_tool_calls": ledger["repeated_tool_calls"],
        "runs": [
            {
                "turn_id": run["turn_id"],
                "started_at": run["started_at"],
                "model_calls": run["model_calls"],
                "tokens": run["tokens"],
            }
            for run in runs
        ],
        "selected_runs": [runs_by_id[turn_id] for turn_id in include_runs],
    }


def write_evidence(path: pathlib.Path, ledger: dict[str, Any]) -> None:
    """Write sanitized call evidence only to the caller-authorized path."""

    if not path.parent.is_dir():
        raise LedgerError(f"evidence output directory does not exist: {path.parent}")
    try:
        path.write_text(
            json.dumps(ledger, separators=(",", ":")) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as exc:
        raise LedgerError(f"could not write evidence output: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    """Build the public deterministic evidence and summary command."""

    parser = argparse.ArgumentParser(
        description="Write full model-call evidence and emit a compact summary."
    )
    parser.add_argument("--session", required=True, type=pathlib.Path)
    parser.add_argument("--evidence-output", required=True, type=pathlib.Path)
    parser.add_argument("--last-runs", type=positive_int)
    parser.add_argument("--include-run", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    """Write full sanitized evidence while keeping stdout decision-sized."""

    args = build_parser().parse_args(argv)
    try:
        session = args.session.expanduser().resolve(strict=True)
        evidence_output = args.evidence_output.expanduser().resolve()
        if evidence_output == session:
            raise LedgerError("evidence output must not overwrite the session")
        ledger = build_ledger(
            load_rows(session),
            session=session,
            last_runs=args.last_runs,
        )
        summary = build_summary(
            ledger,
            evidence_output=evidence_output,
            include_runs=args.include_run,
        )
        write_evidence(evidence_output, ledger)
    except (LedgerError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
