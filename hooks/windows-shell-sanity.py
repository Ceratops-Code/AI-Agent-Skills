#!/usr/bin/env python3
"""Route, repair, or annotate PowerShell commands for Codex shell execution.

The helper is both a Codex ``PreToolUse`` hook and a direct command wrapper.
It applies only closed, semantics-preserving rewrites. Findings that describe
ordinary parse or binding failures are attached only after execution fails;
findings for silent-result uncertainty or explicit policy remain pre-dispatch
blocks. Successful annotated commands produce no additional output.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Sequence

ANNOTATE = "annotate-on-failure"
BLOCK = "block"

BASH_HEREDOC_RE = re.compile(r"<<\s*['\"]?[A-Za-z_][A-Za-z0-9_'-]*")
POWERSHELL_INLINE_PYTHON_RE = re.compile(
    r"@(?P<quote>['\"])[\s\S]*?(?P=quote)@\s*\|\s*"
    r"(?P<python>(?:python|py)(?:\.exe)?)\s+"
    r"(?P<stdin>-(?=\s|$))",
    re.IGNORECASE,
)
PYTHON_UTF8_OUTPUT_GUARD_RE = re.compile(
    r"\b(?:PYTHONIOENCODING|PYTHONUTF8)\b|"
    r"\s-X\s*utf8\b|"
    r"sys\.(?:stdout|stderr)\.reconfigure\([^)]*encoding\s*=",
    re.IGNORECASE,
)
FOREACH_PIPE_RE = re.compile(
    r"\bforeach\s*\([^)]*\)[\s\S]{0,2000}?\}\s*\|",
    re.IGNORECASE,
)
LOOP_RE = re.compile(
    r"\b(?:foreach|for)\s*\(|\bForEach-Object\b",
    re.IGNORECASE,
)
STRUCTURED_TOKEN_RE = re.compile(
    r"\b(?:ConvertFrom-Json|ConvertTo-Json|Where-Object|Select-Object|"
    r"Group-Object|Sort-Object|Measure-Object|Out-String)\b|--json\b",
    re.IGNORECASE,
)
NEW_ITEM_LITERALPATH_RE = re.compile(
    r"\bNew-Item\b[^\r\n;|]*\s-LiteralPath\b",
    re.IGNORECASE,
)
PS_PATH_TOKEN = (
    r"(?:'(?:''|[^'])*'|\"(?:`\"|[^\"])*\"|"
    r"\$[A-Za-z_][\w:]*|[^\s;|)]+)"
)
NEW_ITEM_LITERALPATH_VALUE_RE = re.compile(
    rf"\bNew-Item\b[^\r\n;|]*?\s(?P<parameter>-LiteralPath)\s+"
    rf"(?P<path>{PS_PATH_TOKEN})",
    re.IGNORECASE,
)
SELECT_INDEX_BARE_RANGE_RE = re.compile(
    r"\bSelect-Object\b[^\r\n;|]*?\s-Index\s+"
    r"(?P<range>[0-9]+\s*\.\.\s*[0-9]+)",
    re.IGNORECASE,
)
SELECT_INDEX_COMBINED_RANGES_RE = re.compile(
    r"\bSelect-Object\b[^\r\n;|]*\s-Index\s*"
    r"\((?=[^)]*,)(?=[^)]*\.\.)[^)]*\)",
    re.IGNORECASE,
)
POWERSHELL_RANGE_LIST_RE = re.compile(
    r"\([0-9]+\s*\.\.\s*[0-9]+\s*,\s*[0-9]+\s*\.\.\s*[0-9]+"
)
UNGUARDED_TEST_PATH_READ_RE = re.compile(
    rf"\bTest-Path\b[^\r\n;|]*\s-LiteralPath\s+"
    rf"(?P<path>{PS_PATH_TOKEN})[^\r\n;|]*"
    rf"(?:;|\r?\n)\s*\bGet-Content\b[^\r\n;|]*"
    rf"\s-LiteralPath\s+(?P=path)(?:\s|;|\||$)",
    re.IGNORECASE,
)
INLINE_SCRIPT_RE = re.compile(
    r"\b(?:node|powershell|pwsh|py|python)(?:\.exe)?\b"
    r"[^\r\n]{0,120}?\s-(?:c|command)\b",
    re.IGNORECASE,
)
HERE_STRING_RE = re.compile(
    r"(?ms)@(?P<quote>['\"])[ \t]*\r?\n.*?^(?P=quote)@[ \t]*(?:\r?$)"
)


@dataclass(frozen=True)
class Rewrite:
    """One non-overlapping command replacement planned against original text."""

    kind: str
    start: int
    end: int
    replacement: str


@dataclass(frozen=True)
class Analysis:
    """The executable command plus applied rewrites and remaining findings."""

    command: str
    rewrites: tuple[str, ...]
    findings: tuple[dict[str, str], ...]


def finding(kind: str, disposition: str, message: str) -> dict[str, str]:
    """Create the stable model-facing finding record."""

    severity = "error" if disposition == BLOCK else "warning"
    return {
        "kind": kind,
        "severity": severity,
        "disposition": disposition,
        "message": message,
    }


def _mask_span(characters: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if characters[index] not in "\r\n":
            characters[index] = " "


def mask_non_code(command: str) -> str:
    """Mask PowerShell strings and comments while preserving source offsets.

    This is intentionally a lexical filter rather than a PowerShell parser. It
    prevents rule keywords embedded in quoted data, here-strings, and comments
    from becoming findings. Unrecognized quoting remains conservative because
    run-and-annotate findings do not block successful commands.
    """

    characters = list(command)
    occupied = [False] * len(command)
    for match in HERE_STRING_RE.finditer(command):
        _mask_span(characters, match.start(), match.end())
        for index in range(match.start(), match.end()):
            occupied[index] = True

    index = 0
    while index < len(command):
        if occupied[index]:
            index += 1
            continue
        if command.startswith("<#", index):
            end = command.find("#>", index + 2)
            end = len(command) if end < 0 else end + 2
            _mask_span(characters, index, end)
            index = end
            continue
        character = command[index]
        if character == "#":
            end = command.find("\n", index + 1)
            end = len(command) if end < 0 else end
            _mask_span(characters, index, end)
            index = end
            continue
        if character not in {"'", '"'}:
            index += 1
            continue

        quote = character
        end = index + 1
        while end < len(command):
            if quote == "'" and command.startswith("''", end):
                end += 2
                continue
            if quote == '"' and command[end] == "`" and end + 1 < len(command):
                end += 2
                continue
            if command[end] == quote:
                end += 1
                break
            end += 1
        _mask_span(characters, index, end)
        index = end
    return "".join(characters)


def _is_code_match(masked: str, match: re.Match[str]) -> bool:
    return bool(masked[match.start() : match.end()].strip())


def _safe_static_path(token: str) -> bool:
    if token.startswith("'") and token.endswith("'"):
        value = token[1:-1].replace("''", "'")
    elif token.startswith(('"', "$")) or "`" in token:
        return False
    else:
        value = token
    return not any(character in value for character in "*?[]")


def plan_rewrites(command: str) -> list[Rewrite]:
    """Return only closed rewrites whose replacement semantics are known."""

    masked = mask_non_code(command)
    rewrites: list[Rewrite] = []

    for match in SELECT_INDEX_BARE_RANGE_RE.finditer(masked):
        start, end = match.span("range")
        rewrites.append(
            Rewrite(
                "select_object_bare_range",
                start,
                end,
                f"({command[start:end]})",
            )
        )

    for match in POWERSHELL_INLINE_PYTHON_RE.finditer(command):
        if PYTHON_UTF8_OUTPUT_GUARD_RE.search(match.group(0)):
            continue
        start, end = match.span("stdin")
        rewrites.append(
            Rewrite("python_non_ascii_output", start, end, "-X utf8 -")
        )

    for match in NEW_ITEM_LITERALPATH_VALUE_RE.finditer(command):
        if not _is_code_match(masked, match):
            continue
        if not _safe_static_path(match.group("path")):
            continue
        start, end = match.span("parameter")
        rewrites.append(Rewrite("new_item_literalpath", start, end, "-Path"))

    return rewrites


def apply_rewrites(command: str, rewrites: Sequence[Rewrite]) -> str:
    """Apply validated non-overlapping replacements from right to left."""

    ordered = sorted(rewrites, key=lambda item: (item.start, item.end))
    previous_end = -1
    for item in ordered:
        if item.start < previous_end:
            raise ValueError("Planned command rewrites overlap.")
        previous_end = item.end
    rewritten = command
    for item in reversed(ordered):
        rewritten = rewritten[: item.start] + item.replacement + rewritten[item.end :]
    return rewritten


def lint_command(command: str) -> list[dict[str, str]]:
    """Classify residual findings after deterministic rewrites."""

    masked = mask_non_code(command)
    findings: list[dict[str, str]] = []

    if INLINE_SCRIPT_RE.search(masked) and any(
        token in command for token in ("\n", ";", "|")
    ):
        findings.append(
            finding(
                "complex_inline_script",
                ANNOTATE,
                "The failed command contains a compound inline interpreter payload; move it to a named helper when quoting or control flow caused the failure.",
            )
        )

    if LOOP_RE.search(masked) and STRUCTURED_TOKEN_RE.search(masked):
        findings.append(
            finding(
                "structured_powershell_oneliner",
                BLOCK,
                "Structured PowerShell loop, parsing, filtering, or aggregation logic must use producer output or a named helper.",
            )
        )

    if BASH_HEREDOC_RE.search(masked):
        findings.append(
            finding(
                "bash_heredoc",
                ANNOTATE,
                "PowerShell does not support Bash heredocs; use a PowerShell here-string piped to the command.",
            )
        )

    if (
        POWERSHELL_INLINE_PYTHON_RE.search(command)
        and not PYTHON_UTF8_OUTPUT_GUARD_RE.search(command)
    ):
        findings.append(
            finding(
                "python_non_ascii_output",
                BLOCK,
                "Inline Python that may print Windows session text must enable UTF-8 output.",
            )
        )

    if FOREACH_PIPE_RE.search(masked):
        findings.append(
            finding(
                "foreach_pipeline",
                ANNOTATE,
                "PowerShell cannot pipe directly from this foreach statement; assign or group its results before piping.",
            )
        )

    if NEW_ITEM_LITERALPATH_RE.search(masked):
        findings.append(
            finding(
                "new_item_literalpath",
                ANNOTATE,
                "New-Item does not accept -LiteralPath in Windows PowerShell; use -Path only after accounting for wildcard expansion.",
            )
        )

    for match in UNGUARDED_TEST_PATH_READ_RE.finditer(command):
        if not _is_code_match(masked, match):
            continue
        findings.append(
            finding(
                "ignored_existence_check_before_read",
                ANNOTATE,
                "Test-Path was evaluated but ignored; guard Get-Content when absence is acceptable, or report a required missing file explicitly.",
            )
        )
        break

    if SELECT_INDEX_BARE_RANGE_RE.search(masked):
        findings.append(
            finding(
                "select_object_bare_range",
                BLOCK,
                "Wrap a Select-Object -Index range in parentheses, or use -Skip/-First.",
            )
        )

    if (
        SELECT_INDEX_COMBINED_RANGES_RE.search(masked)
        or POWERSHELL_RANGE_LIST_RE.search(masked)
    ):
        findings.append(
            finding(
                "select_object_combined_ranges",
                BLOCK,
                "Combined Select-Object -Index range behavior is not approved; use -Skip/-First or separate reads.",
            )
        )

    return findings


def analyze_command(command: str) -> Analysis:
    """Rewrite once, prove idempotence, and classify the executable command."""

    rewrites = plan_rewrites(command)
    rewritten = apply_rewrites(command, rewrites)
    residual_rewrites = plan_rewrites(rewritten)
    findings = lint_command(rewritten)
    if residual_rewrites:
        findings.append(
            finding(
                "non_idempotent_rewrite",
                BLOCK,
                "The deterministic rewrite did not converge in one pass.",
            )
        )
    return Analysis(
        command=rewritten,
        rewrites=tuple(item.kind for item in rewrites),
        findings=tuple(findings),
    )


def read_command(args: argparse.Namespace) -> str:
    """Read direct command text while preserving stdin compatibility."""

    if args.encoded_command is not None:
        try:
            return base64.b64decode(args.encoded_command, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError("Invalid UTF-8 base64 command payload.") from exc
    if args.command is not None:
        return args.command
    return sys.stdin.read()


def hook_payload(decision: str, **fields: object) -> dict[str, object]:
    """Build the documented Codex PreToolUse response envelope."""

    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            **fields,
        }
    }


def should_route_through_helper(command: str) -> bool:
    """Return whether quoting or structure warrants encoded helper execution."""

    masked = mask_non_code(command)
    return bool(
        "\n" in command
        or "$(" in command
        or "`" in command
        or STRUCTURED_TOKEN_RE.search(masked)
        or INLINE_SCRIPT_RE.search(masked)
        or masked.count("|") > 1
    )


def powershell_quote(value: str) -> str:
    """Quote one literal PowerShell argument without evaluating its contents."""

    return "'" + value.replace("'", "''") + "'"


def wrapped_command(command: str) -> str:
    """Encode a command so the hook rewrite cannot execute its syntax."""

    encoded = base64.b64encode(command.encode("utf-8")).decode("ascii")
    script = str(pathlib.Path(__file__).resolve())
    return (
        f"& {powershell_quote(sys.executable)} {powershell_quote(script)} "
        f"--encoded-command {powershell_quote(encoded)}"
    )


def is_wrapped_command(command: str) -> bool:
    """Prevent the rewritten helper invocation from recursively triggering itself."""

    script = str(pathlib.Path(__file__).resolve())
    prefix = (
        f"& {powershell_quote(sys.executable)} {powershell_quote(script)} "
        "--encoded-command "
    )
    if not command.startswith(prefix):
        return False
    encoded = command[len(prefix) :]
    if len(encoded) < 3 or not encoded.startswith("'") or not encoded.endswith("'"):
        return False
    try:
        base64.b64decode(encoded[1:-1], validate=True)
    except binascii.Error:
        return False
    return True


def _blocking(findings: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    return [item for item in findings if item["disposition"] == BLOCK]


def _annotations(findings: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    return [item for item in findings if item["disposition"] == ANNOTATE]


def run_hook() -> int:
    """Validate one Codex PreToolUse event without executing the requested command."""

    try:
        event = json.loads(sys.stdin.read())
        tool_input = event.get("tool_input")
        if event.get("tool_name") != "Bash" or not isinstance(tool_input, dict):
            raise ValueError("Expected a Bash tool call with tool_input.command.")
        command = tool_input.get("command")
        if not isinstance(command, str):
            raise ValueError("Expected a Bash tool call with tool_input.command.")
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                hook_payload(
                    "deny",
                    permissionDecisionReason=(
                        f"Windows shell preflight could not validate the tool input: {exc}"
                    ),
                ),
                sort_keys=True,
            )
        )
        return 0

    if is_wrapped_command(command):
        return 0

    analysis = analyze_command(command)
    blockers = _blocking(analysis.findings)
    if blockers:
        reason = " ".join(item["message"] for item in blockers)
        print(
            json.dumps(
                hook_payload("deny", permissionDecisionReason=reason),
                sort_keys=True,
            )
        )
        return 0

    if (
        analysis.command != command
        or _annotations(analysis.findings)
        or should_route_through_helper(analysis.command)
    ):
        updated_input = dict(tool_input)
        updated_input["command"] = wrapped_command(analysis.command)
        print(
            json.dumps(
                hook_payload("allow", updatedInput=updated_input),
                sort_keys=True,
            )
        )
    return 0


def _instrument_for_error_detection(command: str) -> str:
    """Make new PowerShell error records produce a failing process result.

    The trailer does not change ``$ErrorActionPreference`` or stop execution
    early. A hash-derived variable prefix avoids collisions with the command.
    It is used only when a finding must be attached after failure.
    """

    digest = hashlib.sha256(command.encode("utf-8")).hexdigest()
    length = 12
    while True:
        prefix = f"__codex_shell_sanity_{digest[:length]}"
        if prefix.casefold() not in command.casefold():
            break
        length += 4
    before = f"${prefix}_errors_before"
    succeeded = f"${prefix}_succeeded"
    return (
        f"{before} = $Error.Count\n"
        f"{command}\n"
        f"{succeeded} = $?\n"
        f"if ((-not {succeeded}) -or ($Error.Count -gt {before})) {{ exit 1 }}"
    )


def _print_failure_hints(findings: Sequence[dict[str, str]]) -> None:
    if not findings:
        return
    print("Windows shell sanity hints:", file=sys.stderr)
    seen: set[str] = set()
    for item in findings:
        kind = item["kind"]
        if kind in seen:
            continue
        seen.add(kind)
        print(f"- [{kind}] {item['message']}", file=sys.stderr)


def execute_powershell(
    command: str,
    cwd: str | None,
    powershell: str,
    annotations: Sequence[dict[str, str]] = (),
) -> int:
    """Execute one command and append matched guidance only after failure."""

    executable = _instrument_for_error_detection(command) if annotations else command
    encoded = base64.b64encode(executable.encode("utf-16le")).decode("ascii")
    args = [
        powershell,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        encoded,
    ]
    try:
        completed = subprocess.run(args, cwd=cwd or None, check=False)
    except FileNotFoundError:
        payload = {
            "ok": False,
            "blocking_count": 1,
            "findings": [
                finding(
                    "powershell_not_found",
                    BLOCK,
                    f"Could not find PowerShell executable: {powershell}",
                )
            ],
        }
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        return 127
    if completed.returncode:
        _print_failure_hints(annotations)
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    command_source = parser.add_mutually_exclusive_group()
    command_source.add_argument(
        "--command",
        help="Command text to analyze and execute. Defaults to stdin.",
    )
    command_source.add_argument(
        "--encoded-command",
        help="Base64-encoded UTF-8 command supplied by the Codex hook.",
    )
    command_source.add_argument(
        "--hook",
        action="store_true",
        help="Process one Codex PreToolUse JSON event from stdin.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON errors.")
    parser.add_argument("--cwd", help="Working directory for command execution.")
    parser.add_argument(
        "--powershell",
        default="powershell",
        help="PowerShell executable to use.",
    )
    args = parser.parse_args(argv)

    if args.hook:
        return run_hook()

    try:
        command = read_command(args)
    except ValueError as exc:
        error_payload = {
            "ok": False,
            "blocking_count": 1,
            "findings": [finding("invalid_encoded_command", BLOCK, str(exc))],
        }
        print(json.dumps(error_payload, sort_keys=True), file=sys.stderr)
        return 2

    analysis = analyze_command(command)
    blockers = _blocking(analysis.findings)
    if blockers:
        block_payload: dict[str, object] = {
            "ok": False,
            "blocking_count": len(blockers),
            "findings": blockers,
        }
        print(
            json.dumps(
                block_payload,
                indent=2 if args.pretty else None,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    return execute_powershell(
        analysis.command,
        args.cwd,
        args.powershell,
        _annotations(analysis.findings),
    )


if __name__ == "__main__":
    raise SystemExit(main())
