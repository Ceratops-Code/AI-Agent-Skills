"""Stable command-line dispatch for every credit-analysis workflow."""
# ruff: noqa: F401,F403,F405,I001

from __future__ import annotations

from .batch import *
from .core import *
from .holistic import *

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--request", required=True, type=pathlib.Path)
    execute = commands.add_parser("execute")
    execute.add_argument("--state", required=True, type=pathlib.Path)
    orchestration_status = commands.add_parser("orchestration-status")
    orchestration_status.add_argument("--state", required=True, type=pathlib.Path)
    start = commands.add_parser("start")
    start.add_argument("--request", required=True, type=pathlib.Path)
    submit = commands.add_parser("submit")
    submit.add_argument("--state", required=True, type=pathlib.Path)
    submit.add_argument("--decision", required=True, type=pathlib.Path)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--request", required=True, type=pathlib.Path)
    advance = commands.add_parser("advance")
    advance.add_argument("--state", required=True, type=pathlib.Path)
    advance.add_argument("--result", required=True, type=pathlib.Path)
    status = commands.add_parser("status")
    status.add_argument("--state", required=True, type=pathlib.Path)
    status.add_argument("--packet", action="store_true")
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--state", required=True, type=pathlib.Path)
    finalize.add_argument("--result", required=True, type=pathlib.Path)
    prepare_batch = commands.add_parser("prepare-batch")
    prepare_batch.add_argument("--request", required=True, type=pathlib.Path)
    advance_batch = commands.add_parser("advance-batch")
    advance_batch.add_argument("--state", required=True, type=pathlib.Path)
    advance_batch.add_argument("--result", required=True, type=pathlib.Path)
    status_batch = commands.add_parser("status-batch")
    status_batch.add_argument("--state", required=True, type=pathlib.Path)
    finalize_batch = commands.add_parser("finalize-batch")
    finalize_batch.add_argument("--state", required=True, type=pathlib.Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output: Any
    try:
        if args.command == "plan":
            output = command_plan_orchestration(
                args.request.expanduser().resolve(strict=True)
            )
        elif args.command == "execute":
            output = command_execute_orchestration(args.state)
        elif args.command == "orchestration-status":
            output = command_orchestration_status(args.state)
        elif args.command == "start":
            output = command_start(args.request.expanduser().resolve(strict=True))
        elif args.command == "submit":
            output = command_submit(args.state, args.decision)
        elif args.command == "prepare":
            output = command_prepare(args.request.expanduser().resolve(strict=True))
        elif args.command == "advance":
            output = command_advance(args.state, args.result)
        elif args.command == "status":
            output = _pass_packet(args.state) if args.packet else command_status(args.state)
        elif args.command == "finalize":
            command_finalize(args.state, args.result)
            output = "OK"
        elif args.command == "prepare-batch":
            output = command_prepare_batch(
                args.request.expanduser().resolve(strict=True)
            )
        elif args.command == "advance-batch":
            output = command_advance_batch(args.state, args.result)
        elif args.command == "status-batch":
            output = command_status_batch(args.state)
        else:
            command_finalize_batch(args.state)
            output = "OK"
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
