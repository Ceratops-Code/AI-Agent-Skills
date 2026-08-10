#!/usr/bin/env python3
"""Bound source-search output before it reaches the model.

Direct mode runs ripgrep in two deterministic phases: count and rank matching
files without emitting them, then extract contextual snippets from only the
selected files. Hook mode handles oversized ripgrep results from Codex
``PostToolUse`` by replacing them with a compact per-file projection.

The helper never searches binary files, writes temporary state, or calls a
model. Direct output is closed ``bounded-source-search.v1`` JSON. Hook output
uses Codex's supported ``continue: false`` feedback contract only when the
original successful ripgrep output exceeds the configured byte ceiling.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence, TypedDict

SCHEMA = "bounded-source-search.v1"
DEFAULT_MAX_FILES = 8
DEFAULT_MATCHES_PER_FILE = 3
DEFAULT_CONTEXT = 3
DEFAULT_MAX_BYTES = 8_000
MAX_DISCOVERY_MATCHES = 50_000
MAX_LINE_BYTES = 500
RG_COMMAND = re.compile(r"(?i)(?:^|[\s;&|])(?:&\s*)?rg(?:\.exe)?(?=\s|$)")
RG_OUTPUT_LINE = re.compile(
    r"^(?P<path>.*)(?P<separator>[:-])(?P<line>\d+)(?P=separator)(?P<text>.*)$"
)


class SearchError(RuntimeError):
    """One concise ripgrep, input, or hook-contract failure."""


class Snippet(TypedDict):
    """One bounded source line with its match role."""

    line: int
    kind: str
    text: str


def _field_text(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    text = value.get("text")
    return text if isinstance(text, str) else None


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _utf8_size(value: object) -> int:
    return len(_compact_json(value).encode("utf-8"))


def _truncate_utf8(value: str, maximum: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= maximum:
        return value
    if maximum <= 3:
        return "." * maximum
    return encoded[: maximum - 3].decode("utf-8", errors="ignore") + "..."


def _search_location(root: Path) -> tuple[Path, str]:
    resolved = root.expanduser().resolve()
    if resolved.is_dir():
        return resolved, "."
    if resolved.is_file():
        return resolved.parent, resolved.name
    raise SearchError(f"search root does not exist: {resolved}")


def _rg_base(globs: Sequence[str]) -> list[str]:
    command = ["rg", "--json", "--color", "never", "--no-messages"]
    for pattern in globs:
        command.extend(("--glob", pattern))
    return command


def _stop_process(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _discover(
    cwd: Path,
    target: str,
    query: str,
    globs: Sequence[str],
) -> tuple[Counter[str], int, bool]:
    command = [*_rg_base(globs), "--", query, target]
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise SearchError("ripgrep executable 'rg' is unavailable") from exc
    assert process.stdout is not None
    assert process.stderr is not None

    counts: Counter[str] = Counter()
    total = 0
    truncated = False
    for raw_line in process.stdout:
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            _stop_process(process)
            raise SearchError(f"ripgrep returned invalid JSON: {exc}") from exc
        if not isinstance(event, dict) or event.get("type") != "match":
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        path = _field_text(data.get("path"))
        if path is None:
            continue
        submatches = data.get("submatches")
        count = len(submatches) if isinstance(submatches, list) else 1
        counts[path] += max(1, count)
        total += max(1, count)
        if total >= MAX_DISCOVERY_MATCHES:
            truncated = True
            _stop_process(process)
            break

    stderr = process.stderr.read().strip()
    returncode = process.poll()
    if returncode is None:
        returncode = process.wait()
    if not truncated and returncode not in (0, 1):
        raise SearchError(stderr or f"ripgrep discovery failed with exit {returncode}")
    return counts, total, truncated


def _event_lines(data: dict[str, Any], kind: str) -> list[Snippet]:
    line_number = data.get("line_number")
    text = _field_text(data.get("lines"))
    if not isinstance(line_number, int) or text is None:
        return []
    result: list[Snippet] = []
    for offset, line in enumerate(text.splitlines() or [""]):
        result.append(
            {
                "line": line_number + offset,
                "kind": kind,
                "text": _truncate_utf8(line, MAX_LINE_BYTES),
            }
        )
    return result


def _extract(
    cwd: Path,
    path: str,
    query: str,
    globs: Sequence[str],
    matches_per_file: int,
    context: int,
) -> list[Snippet]:
    command = [
        *_rg_base(globs),
        "--line-number",
        "--context",
        str(context),
        "--max-count",
        str(matches_per_file),
        "--",
        query,
        path,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        raise SearchError("ripgrep executable 'rg' is unavailable") from exc
    if completed.returncode not in (0, 1):
        message = completed.stderr.strip()
        raise SearchError(message or f"ripgrep extraction failed with exit {completed.returncode}")

    records: list[Snippet] = []
    seen: set[tuple[int, str, str]] = set()
    for raw_line in completed.stdout.splitlines():
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise SearchError(f"ripgrep returned invalid JSON: {exc}") from exc
        if not isinstance(event, dict) or event.get("type") not in {"match", "context"}:
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        kind = "match" if event["type"] == "match" else "context"
        for record in _event_lines(data, kind):
            identity = (
                record["line"],
                record["kind"],
                record["text"],
            )
            if identity not in seen:
                seen.add(identity)
                records.append(record)
    records.sort(key=lambda item: (item["line"], item["kind"] != "match"))
    return records


def _bounded_payload(
    ranked: Sequence[tuple[str, int, list[Snippet]]],
    total_matches: int,
    maximum_bytes: int,
    truncated: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": SCHEMA,
        "status": "ok",
        "total_matches": total_matches,
        "files": [],
        "truncated": truncated,
    }
    files = payload["files"]
    assert isinstance(files, list)
    for path, count, snippets in ranked:
        display_path = path.replace("\\", "/")
        if display_path.startswith("./"):
            display_path = display_path[2:]
        entry: dict[str, object] = {
            "path": display_path,
            "match_count": count,
            "snippets": [],
        }
        files.append(entry)
        if _utf8_size(payload) > maximum_bytes:
            files.pop()
            payload["truncated"] = True
            break
        selected = entry["snippets"]
        assert isinstance(selected, list)
        for snippet in snippets:
            selected.append(snippet)
            if _utf8_size(payload) > maximum_bytes:
                selected.pop()
                payload["truncated"] = True
                break
    if _utf8_size(payload) > maximum_bytes:
        raise SearchError("max-bytes is too small for the result envelope")
    return payload


def search(
    root: Path,
    query: str,
    *,
    globs: Sequence[str] = (),
    max_files: int = DEFAULT_MAX_FILES,
    matches_per_file: int = DEFAULT_MATCHES_PER_FILE,
    context: int = DEFAULT_CONTEXT,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, object]:
    """Return one bounded, ranked source-search result."""

    if not query:
        raise SearchError("query must be nonempty")
    if min(max_files, matches_per_file, max_bytes) < 1 or context < 0:
        raise SearchError("search limits must be positive and context nonnegative")
    if max_bytes < 512:
        raise SearchError("max-bytes must be at least 512")

    cwd, target = _search_location(root)
    counts, total, discovery_truncated = _discover(cwd, target, query, globs)
    selected = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))[
        :max_files
    ]
    ranked = [
        (
            path,
            count,
            _extract(cwd, path, query, globs, matches_per_file, context),
        )
        for path, count in selected
    ]
    truncated = discovery_truncated or len(counts) > len(selected)
    return _bounded_payload(ranked, total, max_bytes, truncated)


def _tool_response_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return None
    exit_code = value.get("exit_code")
    if isinstance(exit_code, int) and exit_code != 0:
        return None
    for key in ("output", "stdout", "text"):
        candidate = value.get(key)
        if isinstance(candidate, str):
            return candidate
    return None


def _bound_existing_output(value: str, maximum_bytes: int) -> str:
    grouped: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    match_counts: Counter[str] = Counter()
    for line in value.splitlines():
        match = RG_OUTPUT_LINE.match(line)
        if match is None:
            continue
        path = match.group("path")
        separator = match.group("separator")
        grouped[path].append(
            (int(match.group("line")), separator, match.group("text"))
        )
        if separator == ":":
            match_counts[path] += 1

    header = f"Bounded source-search output; original_bytes={len(value.encode('utf-8'))}."
    if not grouped:
        head_budget = max(1, int((maximum_bytes - len(header) - 10) * 0.7))
        tail_budget = max(1, maximum_bytes - len(header) - head_budget - 10)
        projected = f"{header}\n{_truncate_utf8(value, head_budget)}\n...\n{_truncate_utf8(value[-tail_budget:], tail_budget)}"
        return _truncate_utf8(projected, maximum_bytes)

    parts = [header]
    ranked_paths = sorted(
        grouped,
        key=lambda path: (-match_counts[path], path.casefold()),
    )[:DEFAULT_MAX_FILES]
    for path in ranked_paths:
        parts.append(f"[{path}]")
        retained_matches = 0
        line_budget = DEFAULT_MATCHES_PER_FILE * (2 * DEFAULT_CONTEXT + 1)
        for line_number, separator, text_value in grouped[path][:line_budget]:
            if separator == ":":
                retained_matches += 1
                if retained_matches > DEFAULT_MATCHES_PER_FILE:
                    continue
            parts.append(
                f"{line_number}{separator}{_truncate_utf8(text_value, MAX_LINE_BYTES)}"
            )
    return _truncate_utf8("\n".join(parts), maximum_bytes)


def run_hook(max_bytes: int = DEFAULT_MAX_BYTES) -> int:
    """Replace only oversized successful ripgrep output."""

    try:
        value = json.load(sys.stdin)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SearchError(f"hook stdin is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SearchError("hook stdin must be a JSON object")
    if value.get("hook_event_name") != "PostToolUse" or value.get("tool_name") != "Bash":
        return 0
    tool_input = value.get("tool_input")
    if not isinstance(tool_input, dict):
        raise SearchError("PostToolUse input needs tool_input")
    command = tool_input.get("command")
    if not isinstance(command, str):
        raise SearchError("PostToolUse tool_input.command must be text")
    if "bounded-source-search.py" in command or RG_COMMAND.search(command) is None:
        return 0
    output = _tool_response_text(value.get("tool_response"))
    if output is None or len(output.encode("utf-8")) <= max_bytes:
        return 0
    print(
        _compact_json(
            {
                "continue": False,
                "stopReason": _bound_existing_output(output, max_bytes),
            }
        )
    )
    return 0


def _positive(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hook", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--query")
    parser.add_argument("--glob", action="append", default=[])
    parser.add_argument("--max-files", type=_positive, default=DEFAULT_MAX_FILES)
    parser.add_argument(
        "--matches-per-file",
        type=_positive,
        default=DEFAULT_MATCHES_PER_FILE,
    )
    parser.add_argument("--context", type=int, default=DEFAULT_CONTEXT)
    parser.add_argument("--max-bytes", type=_positive, default=DEFAULT_MAX_BYTES)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.hook:
            if args.root is not None or args.query is not None:
                raise SearchError("--hook does not accept search inputs")
            return run_hook(args.max_bytes)
        if args.root is None or args.query is None:
            raise SearchError("direct mode requires --root and --query")
        if args.context < 0:
            raise SearchError("--context must be nonnegative")
        payload = search(
            args.root,
            args.query,
            globs=args.glob,
            max_files=args.max_files,
            matches_per_file=args.matches_per_file,
            context=args.context,
            max_bytes=args.max_bytes,
        )
    except (SearchError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(_compact_json(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
