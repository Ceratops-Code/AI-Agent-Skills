"""Parse repository test requests without running tests or mutating files.

Only explicit ``--auto`` requests inspect GitHub context: pull requests retain
the repository's base/head impact selection; local runs and pushes run all tests.
Malformed or unsupported CI context fails closed before collection.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
from collections.abc import Sequence


def parse_request(argv: Sequence[str] | None) -> tuple[argparse.Namespace, str | None]:
    parser = argparse.ArgumentParser()
    parser.add_argument("targets", nargs="*", help="Repository test paths or pytest node IDs.")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--auto", action="store_true", help="PR impact tests in GitHub; all tests locally or on push.")
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--diagnostic-output", type=pathlib.Path)
    parser.add_argument("--select-only", action="store_true",
                        help="Validate diff/worktree selection without collecting or running tests.")
    parser.add_argument("--node-map", type=pathlib.Path)
    parser.add_argument("--reconcile-collection", type=pathlib.Path)
    parser.add_argument("--validate-manifest", action="store_true")
    parser.add_argument("--worktree", action="store_true")
    parser.add_argument("--write-collection", type=pathlib.Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    modes = sum((bool(args.targets), args.all, args.auto, args.validate_manifest,
                 args.worktree, args.write_collection is not None,
                 args.reconcile_collection is not None,
                 args.base is not None or args.head is not None))
    if (modes != 1 or ((args.base is None) != (args.head is None))
            or (args.node_map is not None and args.reconcile_collection is None)
            or (args.select_only and not (args.worktree or args.base is not None))):
        return args, (
            "choose exactly one of test targets, --all, --auto, --validate-manifest, --worktree, "
            "--write-collection, --reconcile-collection, or --base with --head; "
            "--node-map is valid only with --reconcile-collection; "
            "--select-only requires --worktree or --base with --head"
        )
    if any(target.startswith("-") for target in args.targets):
        return args, "test targets must be paths or node IDs, not pytest options"
    if args.auto:
        try:
            if os.environ.get("GITHUB_ACTIONS") != "true":
                args.all = True
            elif os.environ.get("GITHUB_EVENT_NAME") == "push":
                args.all = True
            elif os.environ.get("GITHUB_EVENT_NAME") == "pull_request":
                event = json.loads(pathlib.Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
                args.base = event["pull_request"]["base"]["sha"]
                args.head = event["pull_request"]["head"]["sha"]
                if not all(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha)
                           for sha in (args.base, args.head)):
                    raise ValueError("pull-request base and head must be full commit SHAs")
            else:
                raise ValueError("--auto supports GitHub pull_request and push events")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return args, f"cannot select CI tests: {exc}"
    return args, None
