#!/usr/bin/env python3
"""Persist and validate proposal-iteration state.

The controller makes no model calls and makes no semantic quality judgment. It
owns numbering, source hashes, pending submissions, artifact records, and stop
conditions so the agent cannot legitimately claim unrecorded work. State is
written atomically and existing state is never overwritten by `init`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path
from typing import Any


VERSION = 1
NO_IMPROVEMENT_LIMIT = 10


def file_hash(path: Path) -> str:
    """Return a SHA-256 hash for an existing file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_nonempty(path: Path, label: str) -> str:
    """Read a required non-empty UTF-8 artifact."""
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError(f"{label} is empty: {path}")
    return content


def load_state(path: Path) -> dict[str, Any]:
    """Load controller state and check its version."""
    if not path.is_file():
        raise ValueError(f"state does not exist: {path}")
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("version") != VERSION:
        raise ValueError("unsupported state version")
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Atomically replace state without exposing partial JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def verify_sources(state: dict[str, Any]) -> None:
    """Reject iteration when original or regression inputs changed."""
    for key in ("original", "regressions"):
        source = state.get(key)
        if source and file_hash(Path(source["path"])) != source["sha256"]:
            raise ValueError(f"{key} changed after initialization")


def public_status(state: dict[str, Any]) -> dict[str, Any]:
    """Return compact controller-owned progress."""
    champion = state.get("champion")
    return {
        "complete": state["complete"],
        "stop_reason": state["stop_reason"],
        "completed_iterations": len(state["records"]),
        "next_iteration": state["next_iteration"],
        "no_improvement_streak": state["no_improvement_streak"],
        "champion_iteration": champion["iteration"] if champion else None,
    }


def command_init(args: argparse.Namespace) -> None:
    """Create state bound to immutable original and regression inputs."""
    state_path = args.state.resolve()
    if state_path.exists():
        raise ValueError(f"refusing to overwrite existing state: {state_path}")
    original = args.original.resolve()
    read_nonempty(original, "original")
    regressions = args.regressions.resolve() if args.regressions else None
    if regressions:
        read_nonempty(regressions, "regressions")
    state = {
        "version": VERSION,
        "original": {"path": str(original), "sha256": file_hash(original)},
        "regressions": (
            {"path": str(regressions), "sha256": file_hash(regressions)}
            if regressions
            else None
        ),
        "max_iterations": args.max_iterations,
        "patience": NO_IMPROVEMENT_LIMIT,
        "next_iteration": 1,
        "no_improvement_streak": 0,
        "pending": None,
        "champion": None,
        "records": [],
        "complete": False,
        "stop_reason": None,
    }
    save_state(state_path, state)
    print("OK")


def command_next(args: argparse.Namespace) -> None:
    """Open exactly one pending iteration and return its artifact paths."""
    state_path = args.state.resolve()
    state = load_state(state_path)
    verify_sources(state)
    if state["complete"]:
        print(json.dumps(public_status(state), separators=(",", ":")))
        return
    if state["pending"]:
        raise ValueError("an iteration is already pending")
    iteration = state["next_iteration"]
    token = secrets.token_hex(12)
    artifact_dir = state_path.parent / "iterations"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    candidate = artifact_dir / f"{iteration:03d}-candidate.md"
    assessment = artifact_dir / f"{iteration:03d}-assessment.md"
    state["pending"] = {
        "iteration": iteration,
        "token": token,
        "candidate": str(candidate.resolve()),
        "assessment": str(assessment.resolve()),
    }
    save_state(state_path, state)
    print(json.dumps(state["pending"], separators=(",", ":")))


def command_submit(args: argparse.Namespace) -> None:
    """Record one iteration and update deterministic stop state."""
    state_path = args.state.resolve()
    state = load_state(state_path)
    verify_sources(state)
    pending = state.get("pending")
    if not pending:
        raise ValueError("no iteration is pending")
    if pending["iteration"] != args.iteration or pending["token"] != args.token:
        raise ValueError("iteration or token does not match pending state")
    candidate = Path(pending["candidate"])
    assessment = Path(pending["assessment"])
    read_nonempty(candidate, "candidate")
    read_nonempty(assessment, "assessment")
    if args.outcome == "improved" and args.regressions != "passed":
        raise ValueError("an improved candidate must pass regressions")
    record = {
        "iteration": args.iteration,
        "outcome": args.outcome,
        "regressions": args.regressions,
        "candidate": str(candidate),
        "candidate_sha256": file_hash(candidate),
        "assessment": str(assessment),
        "assessment_sha256": file_hash(assessment),
    }
    state["records"].append(record)
    if args.outcome == "improved":
        state["champion"] = record
        state["no_improvement_streak"] = 0
    else:
        state["no_improvement_streak"] += 1
    state["pending"] = None
    state["next_iteration"] += 1
    if state["no_improvement_streak"] >= state["patience"]:
        state["complete"] = True
        state["stop_reason"] = "patience"
    elif len(state["records"]) >= state["max_iterations"]:
        state["complete"] = True
        state["stop_reason"] = "max_iterations"
    save_state(state_path, state)
    print(json.dumps(public_status(state), separators=(",", ":")))


def command_status(args: argparse.Namespace) -> None:
    """Print controller-owned progress without modifying state."""
    state = load_state(args.state.resolve())
    verify_sources(state)
    print(json.dumps(public_status(state), separators=(",", ":")))


def positive_int(value: str) -> int:
    """Parse a strictly positive command-line integer."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Build the command interface used by the skill."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="initialize immutable run state")
    init.add_argument("--state", type=Path, required=True)
    init.add_argument("--original", type=Path, required=True)
    init.add_argument("--regressions", type=Path)
    init.add_argument("--max-iterations", type=positive_int, default=200)
    init.set_defaults(handler=command_init)

    next_iteration = commands.add_parser("next", help="open one iteration")
    next_iteration.add_argument("--state", type=Path, required=True)
    next_iteration.set_defaults(handler=command_next)

    submit = commands.add_parser("submit", help="record one iteration")
    submit.add_argument("--state", type=Path, required=True)
    submit.add_argument("--iteration", type=positive_int, required=True)
    submit.add_argument("--token", required=True)
    submit.add_argument(
        "--outcome", choices=("improved", "no-improvement"), required=True
    )
    submit.add_argument(
        "--regressions", choices=("passed", "failed"), required=True
    )
    submit.set_defaults(handler=command_submit)

    status = commands.add_parser("status", help="report recorded progress")
    status.add_argument("--state", type=Path, required=True)
    status.set_defaults(handler=command_status)
    return parser


def main() -> int:
    """Run one command with compact, actionable errors."""
    try:
        args = build_parser().parse_args()
        args.handler(args)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
