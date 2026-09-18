"""Stable command-line dispatch for every credit-analysis workflow."""
# ruff: noqa: I001

from __future__ import annotations

from .thread_review_orchestration import *
from .single_surface_analysis import *
from .single_surface_analysis import _exclusive_json, _load_evidence_collector


def command_select_recent(
    days: int, as_of_text: str | None, output_path: pathlib.Path
) -> dict[str, Any]:
    """Freeze recent thread identities for a read-only, non-controller scan."""

    if days < 1:
        raise CreditAnalysisError("days must be positive")
    collector = _load_evidence_collector()
    try:
        as_of = (
            collector.parse_utc_timestamp(as_of_text, "as_of")
            if as_of_text is not None
            else dt.datetime.now(dt.timezone.utc)
        )
    except RuntimeError as exc:
        raise CreditAnalysisError(str(exc)) from exc
    if as_of > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5):
        raise CreditAnalysisError("as_of cannot be in the future")
    index = collector.load_thread_index()
    start = as_of - dt.timedelta(days=days)
    candidates: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    for entry in index["entries"]:
        updated_at = collector.parse_utc_timestamp(
            entry["updated_at"], "thread index updated_at"
        )
        if updated_at < start or updated_at > as_of:
            continue
        thread_id = entry["thread_id"]
        try:
            session = collector.resolve_thread_session(thread_id)
            metadata = collector.read_session_source_metadata(
                session, expected_thread_id=thread_id
            )
        except (OSError, RuntimeError, ValueError):
            exclusions.append(
                {"thread_id": thread_id, "reason": "unresolvable-session-or-metadata"}
            )
            continue
        candidates.append(
            {
                "thread_id": thread_id,
                "thread_name": entry["thread_name"],
                "updated_at": entry["updated_at"],
                "session": str(session),
                "project": {
                    "key": metadata["project_key"],
                    "cwd": metadata["cwd"],
                    "repository_url": metadata["repository_url"],
                },
            }
        )
    if not candidates:
        raise CreditAnalysisError("recent selector matched no resolvable threads")
    target = output_path.expanduser().absolute()
    if not target.parent.is_dir():
        raise CreditAnalysisError("selection output directory does not exist")
    _exclusive_json(
        target,
        {
            "schema": "ceratops-credit-quick-selection.v1",
            "as_of": as_of.isoformat().replace("+00:00", "Z"),
            "days": days,
            "thread_index_fingerprint": index["fingerprint"],
            "threads": candidates,
            "exclusions": exclusions,
        },
        "quick selection",
    )
    return {
        "selected": len(candidates),
        "excluded": len(exclusions),
        "output": str(target),
    }


def command_quick_window(
    days: int, as_of_text: str, usage_path: pathlib.Path
) -> dict[str, Any]:
    """Count the completed-run suffix inside a frozen recent-days window."""

    if days < 1:
        raise CreditAnalysisError("days must be positive")
    collector = _load_evidence_collector()
    try:
        as_of = collector.parse_utc_timestamp(as_of_text, "as_of")
    except RuntimeError as exc:
        raise CreditAnalysisError(str(exc)) from exc
    if as_of > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5):
        raise CreditAnalysisError("as_of cannot be in the future")
    evidence = json.loads(usage_path.expanduser().read_text(encoding="utf-8"))
    if (
        not isinstance(evidence, dict)
        or evidence.get("schema") != collector.USAGE_EVIDENCE_SCHEMA
    ):
        raise CreditAnalysisError("quick window requires collector usage evidence")
    window = evidence.get("window")
    if not isinstance(window, dict) or window.get("mode") != "full_thread":
        raise CreditAnalysisError("quick window requires full-thread usage evidence")
    runs = evidence.get("runs")
    if not isinstance(runs, list):
        raise CreditAnalysisError("usage evidence runs are invalid")
    start = as_of - dt.timedelta(days=days)
    selected: list[str] = []
    for index, run in enumerate(runs):
        if (
            not isinstance(run, dict)
            or not isinstance(run.get("turn_id"), str)
            or not run["turn_id"]
        ):
            raise CreditAnalysisError(f"usage evidence run {index + 1} is invalid")
        try:
            started_at = collector.parse_utc_timestamp(
                run.get("started_at"), f"usage evidence run {index + 1} started_at"
            )
        except RuntimeError as exc:
            raise CreditAnalysisError(str(exc)) from exc
        if start < started_at <= as_of:
            selected.append(run["turn_id"])
    suffix = [run["turn_id"] for run in runs[-len(selected):]] if selected else []
    if selected != suffix:
        raise CreditAnalysisError("quick window runs are not a completed-run suffix")
    return {
        "last_runs": len(selected),
        "first_run": selected[0] if selected else None,
        "last_run": selected[-1] if selected else None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--request", required=True, type=pathlib.Path)
    plan = commands.add_parser("plan")
    plan.add_argument("--request", required=True, type=pathlib.Path)
    execute = commands.add_parser("execute")
    execute.add_argument("--state", required=True, type=pathlib.Path)
    orchestration_status = commands.add_parser("orchestration-status")
    orchestration_status.add_argument("--state", required=True, type=pathlib.Path)
    select_recent = commands.add_parser("select-recent")
    select_recent.add_argument("--days", required=True, type=int)
    select_recent.add_argument("--as-of")
    select_recent.add_argument("--output", required=True, type=pathlib.Path)
    quick_window = commands.add_parser("quick-window")
    quick_window.add_argument("--days", required=True, type=int)
    quick_window.add_argument("--as-of", required=True)
    quick_window.add_argument("--usage-evidence", required=True, type=pathlib.Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output: Any
    try:
        if args.command == "run":
            output = command_run_orchestration(
                args.request.expanduser().resolve(strict=True)
            )
        elif args.command == "plan":
            output = command_plan_orchestration(
                args.request.expanduser().resolve(strict=True)
            )
        elif args.command == "execute":
            output = command_execute_orchestration(args.state)
        elif args.command == "orchestration-status":
            output = command_orchestration_status(args.state)
        elif args.command == "select-recent":
            output = command_select_recent(args.days, args.as_of, args.output)
        elif args.command == "quick-window":
            output = command_quick_window(args.days, args.as_of, args.usage_evidence)
        else:
            raise CreditAnalysisError("unsupported command")
    except (CreditAnalysisError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if output == "OK":
        print("OK")
    else:
        print(json.dumps(output, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = (
    "build_parser",
    "main",
)
