#!/usr/bin/env python3
"""Validate and orchestrate one governance proposal iteration run.

``prepare`` validates a closed request against exact current rule text and the
existing structured history lookup, writes detailed context evidence, and
opens iteration one through ``iteration_controller.py``. ``advance`` delegates
the controller's atomic submit-and-open operation; ``finalize`` delegates its
ownership-checked cleanup. This helper never edits a governed rule source or
makes semantic judgments, and stdout contains only the pending/status payload
needed for the next decision or ``OK``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence


REQUEST_SCHEMA = "ceratops-governance-proposal-request.v1"
CONTEXT_SCHEMA = "ceratops-governance-proposal-context.v1"
REQUEST_FIELDS = {
    "schema",
    "state",
    "original",
    "regressions",
    "evidence_output",
    "max_iterations",
    "mutation_authorized",
    "expected_side_effects",
    "sources",
}
SOURCE_FIELDS = {
    "rules",
    "history",
    "rule_ids",
    "expected_text",
}


class ProposalWorkflowError(RuntimeError):
    """One compact request, evidence, or delegated-controller failure."""


def _read_json(path: pathlib.Path, label: str) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProposalWorkflowError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ProposalWorkflowError(f"{label} must be a JSON object")
    return value


def _closed_fields(
    value: Mapping[str, object],
    expected: set[str],
    label: str,
) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append("missing " + ", ".join(missing))
    if extra:
        details.append("unknown " + ", ".join(extra))
    raise ProposalWorkflowError(f"{label} fields are invalid: {'; '.join(details)}")


def _strings(
    value: object,
    label: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or (not value and not allow_empty)
        or not all(isinstance(item, str) and item for item in value)
    ):
        qualifier = "string list" if allow_empty else "nonempty string list"
        raise ProposalWorkflowError(f"{label} must be a {qualifier}")
    result = list(value)
    if len(result) != len(set(result)):
        raise ProposalWorkflowError(f"{label} values must be unique")
    return result


def _input_path(value: object, label: str) -> pathlib.Path:
    if not isinstance(value, str) or not value:
        raise ProposalWorkflowError(f"{label} must be nonempty text")
    try:
        path = pathlib.Path(value).expanduser().resolve(strict=True)
    except OSError as exc:
        raise ProposalWorkflowError(f"{label} does not exist: {value}") from exc
    if not path.is_file() or path.is_symlink():
        raise ProposalWorkflowError(f"{label} must be a regular file: {path}")
    return path


def _output_path(value: object, label: str) -> pathlib.Path:
    if not isinstance(value, str) or not value:
        raise ProposalWorkflowError(f"{label} must be nonempty text")
    path = pathlib.Path(value).expanduser().resolve()
    if not path.parent.is_dir():
        raise ProposalWorkflowError(f"{label} directory does not exist: {path.parent}")
    if path.is_symlink() or path.exists():
        raise ProposalWorkflowError(f"refusing to overwrite {label}: {path}")
    return path


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _run_helper(script: str, arguments: Sequence[str]) -> str:
    path = pathlib.Path(__file__).with_name(script)
    if not path.is_file():
        raise ProposalWorkflowError(f"required helper is missing: {script}")
    try:
        result = subprocess.run(
            [sys.executable, str(path), *arguments],
            cwd=path.parent,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise ProposalWorkflowError(f"could not run {script}: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        if detail.startswith("ERROR: "):
            detail = detail[7:]
        raise ProposalWorkflowError(
            f"{script} failed: {detail}" if detail else f"{script} failed"
        )
    return result.stdout.strip()


def _write_json_atomic(path: pathlib.Path, value: Mapping[str, object]) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, separators=(",", ":"))
            handle.write("\n")
        os.replace(temp_name, path)
    except OSError as exc:
        raise ProposalWorkflowError(f"could not write context evidence: {exc}") from exc
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _validated_request(path: pathlib.Path) -> dict[str, object]:
    request = _read_json(path, "request")
    _closed_fields(request, REQUEST_FIELDS, "request")
    if request.get("schema") != REQUEST_SCHEMA:
        raise ProposalWorkflowError(f"request schema must be {REQUEST_SCHEMA}")
    state = _output_path(request["state"], "state output")
    evidence = _output_path(request["evidence_output"], "evidence output")
    original = _input_path(request["original"], "original")
    regression_value = request["regressions"]
    regressions = (
        None
        if regression_value is None
        else _input_path(regression_value, "regressions")
    )
    max_iterations = request["max_iterations"]
    if (
        not isinstance(max_iterations, int)
        or isinstance(max_iterations, bool)
        or max_iterations < 1
    ):
        raise ProposalWorkflowError("max_iterations must be a positive integer")
    mutation_authorized = request["mutation_authorized"]
    if not isinstance(mutation_authorized, bool):
        raise ProposalWorkflowError("mutation_authorized must be boolean")
    side_effects = _strings(request["expected_side_effects"], "expected_side_effects")
    collisions = [state, evidence, original]
    if regressions is not None:
        collisions.append(regressions)
    if len(collisions) != len(set(collisions)):
        raise ProposalWorkflowError("state, evidence, and input paths must differ")

    raw_sources = request["sources"]
    if (
        not isinstance(raw_sources, Sequence)
        or isinstance(raw_sources, (str, bytes))
        or not raw_sources
    ):
        raise ProposalWorkflowError("sources must be a nonempty list")
    sources: list[dict[str, object]] = []
    seen_rules: set[pathlib.Path] = set()
    history_backed = 0
    for index, raw in enumerate(raw_sources, start=1):
        if not isinstance(raw, Mapping):
            raise ProposalWorkflowError(f"source {index} must be an object")
        _closed_fields(raw, SOURCE_FIELDS, f"source {index}")
        rules = _input_path(raw["rules"], f"source {index} rules")
        history_value = raw["history"]
        if history_value is None:
            history = None
            rule_ids = _strings(
                raw["rule_ids"],
                f"source {index} rule_ids",
                allow_empty=True,
            )
            if rule_ids:
                raise ProposalWorkflowError(
                    f"source {index} without history must not declare rule_ids"
                )
        else:
            history = _input_path(history_value, f"source {index} history")
            rule_ids = _strings(raw["rule_ids"], f"source {index} rule_ids")
            history_backed += 1
        if rules in seen_rules:
            raise ProposalWorkflowError(f"duplicate rules source: {rules}")
        seen_rules.add(rules)
        expected_text = _strings(
            raw["expected_text"],
            f"source {index} expected_text",
        )
        try:
            current = rules.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ProposalWorkflowError(
                f"source {index} rules are unreadable: {exc}"
            ) from exc
        text_records: list[dict[str, object]] = []
        for text in expected_text:
            count = current.count(text)
            if count != 1:
                raise ProposalWorkflowError(
                    f"source {index} expected_text must occur exactly once; found {count}"
                )
            text_records.append(
                {
                    "sha256": _hash_text(text),
                    "characters": len(text),
                }
            )
        sources.append(
            {
                "rules": str(rules),
                "history": str(history) if history is not None else None,
                "rule_ids": rule_ids,
                "expected_text": expected_text,
                "text_records": text_records,
            }
        )
    if history_backed == 0:
        raise ProposalWorkflowError(
            "at least one applicable source must include structured history"
        )
    all_inputs = {original}
    all_inputs.update(pathlib.Path(str(source["rules"])) for source in sources)
    all_inputs.update(
        pathlib.Path(str(source["history"]))
        for source in sources
        if source["history"] is not None
    )
    if regressions is not None:
        all_inputs.add(regressions)
    if state in all_inputs or evidence in all_inputs:
        raise ProposalWorkflowError("outputs must not overwrite proposal inputs")
    for source in sources:
        rules_parent = pathlib.Path(str(source["rules"])).parent
        for output in (state, evidence):
            try:
                output.relative_to(rules_parent)
            except ValueError:
                continue
            raise ProposalWorkflowError(
                "state and evidence outputs must stay outside governed source trees"
            )
    return {
        "state": state,
        "evidence": evidence,
        "original": original,
        "regressions": regressions,
        "max_iterations": max_iterations,
        "mutation_authorized": mutation_authorized,
        "expected_side_effects": side_effects,
        "sources": sources,
    }


def command_prepare(request_path: pathlib.Path) -> str:
    request = _validated_request(request_path)
    sources = request["sources"]
    assert isinstance(sources, list)
    lookup_arguments = ["lookup"]
    rule_ids: list[str] = []
    for source in sources:
        assert isinstance(source, Mapping)
        if source["history"] is None:
            continue
        lookup_arguments.extend(("--history", str(source["history"])))
        lookup_arguments.extend(("--rules", str(source["rules"])))
        source_ids = source["rule_ids"]
        assert isinstance(source_ids, list)
        rule_ids.extend(source_ids)
    lookup_arguments.extend(dict.fromkeys(rule_ids))
    lookup_raw = _run_helper("rule_history.py", lookup_arguments)
    try:
        lookup = json.loads(lookup_raw)
    except json.JSONDecodeError as exc:
        raise ProposalWorkflowError("rule_history.py returned invalid JSON") from exc
    if not isinstance(lookup, Mapping) or not isinstance(lookup.get("unknown"), list):
        raise ProposalWorkflowError("rule_history.py returned invalid lookup evidence")
    if lookup["unknown"]:
        raise ProposalWorkflowError(
            f"unknown target rule ID: {lookup['unknown'][0]}"
        )
    evidence = {
        "schema": CONTEXT_SCHEMA,
        "request_schema": REQUEST_SCHEMA,
        "mutation_authorized": request["mutation_authorized"],
        "expected_side_effects": request["expected_side_effects"],
        "sources": [
            {
                "rules": source["rules"],
                "history": source["history"],
                "rule_ids": source["rule_ids"],
                "expected_text": source["text_records"],
            }
            for source in sources
        ],
        "history_lookup": lookup,
    }
    evidence_path = request["evidence"]
    state_path = request["state"]
    original = request["original"]
    regressions = request["regressions"]
    assert isinstance(evidence_path, pathlib.Path)
    assert isinstance(state_path, pathlib.Path)
    assert isinstance(original, pathlib.Path)
    assert regressions is None or isinstance(regressions, pathlib.Path)
    _write_json_atomic(evidence_path, evidence)
    arguments = [
        "init",
        "--state",
        str(state_path),
        "--original",
        str(original),
        "--max-iterations",
        str(request["max_iterations"]),
        "--open-first",
    ]
    if regressions is not None:
        arguments.extend(("--regressions", str(regressions)))
    try:
        payload = _run_helper("iteration_controller.py", arguments)
    except ProposalWorkflowError:
        evidence_path.unlink(missing_ok=True)
        raise
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ProposalWorkflowError(
            "iteration_controller.py returned invalid pending JSON"
        ) from exc
    if not isinstance(parsed, Mapping):
        raise ProposalWorkflowError("iteration controller pending payload is invalid")
    return json.dumps(parsed, separators=(",", ":"))


def command_advance(
    state: pathlib.Path,
    outcome: str,
    regressions: str,
) -> str:
    payload = _run_helper(
        "iteration_controller.py",
        [
            "advance",
            "--state",
            str(state.resolve(strict=True)),
            "--outcome",
            outcome,
            "--regressions",
            regressions,
        ],
    )
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ProposalWorkflowError(
            "iteration_controller.py returned invalid status JSON"
        ) from exc
    if not isinstance(parsed, Mapping):
        raise ProposalWorkflowError("iteration controller status payload is invalid")
    return json.dumps(parsed, separators=(",", ":"))


def command_finalize(state: pathlib.Path) -> str:
    payload = _run_helper(
        "iteration_controller.py",
        ["finalize", "--state", str(state.resolve(strict=True))],
    )
    if payload != "OK":
        raise ProposalWorkflowError("iteration_controller.py returned invalid finalization")
    return "OK"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--request", required=True, type=pathlib.Path)
    advance = commands.add_parser("advance")
    advance.add_argument("--state", required=True, type=pathlib.Path)
    advance.add_argument(
        "--outcome",
        required=True,
        choices=("improved", "no-improvement"),
    )
    advance.add_argument(
        "--regressions",
        required=True,
        choices=("passed", "failed"),
    )
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--state", required=True, type=pathlib.Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            output = command_prepare(args.request.expanduser().resolve(strict=True))
        elif args.command == "advance":
            output = command_advance(args.state, args.outcome, args.regressions)
        else:
            output = command_finalize(args.state)
    except (ProposalWorkflowError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
