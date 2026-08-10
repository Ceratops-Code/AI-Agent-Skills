import base64
import contextlib
import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "hooks" / "windows-shell-sanity.py"
SPEC = importlib.util.spec_from_file_location("windows_shell_sanity", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
SANITY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SANITY
SPEC.loader.exec_module(SANITY)


class WindowsShellSanityTests(unittest.TestCase):
    @staticmethod
    def hook_result(command: str) -> dict[str, Any] | None:
        event = {"tool_name": "Bash", "tool_input": {"command": command}}
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(event))):
            with contextlib.redirect_stdout(stdout):
                returncode = SANITY.run_hook()
        if returncode != 0:
            raise AssertionError(f"hook returned {returncode}")
        output = stdout.getvalue().strip()
        return json.loads(output) if output else None

    @staticmethod
    def rewritten_command(payload: dict[str, Any]) -> str:
        hook_output = payload["hookSpecificOutput"]
        assert isinstance(hook_output, dict)
        updated_input = hook_output["updatedInput"]
        assert isinstance(updated_input, dict)
        wrapper = updated_input["command"]
        assert isinstance(wrapper, str)
        encoded = wrapper.rsplit("'", 2)[1]
        return base64.b64decode(encoded, validate=True).decode("utf-8")

    def test_valid_inline_pipeline_routes_instead_of_denying(self):
        command = 'powershell -Command "Get-Date | Select-Object DateTime"'

        payload = self.hook_result(command)

        self.assertIsNotNone(payload)
        assert payload is not None
        output = payload["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "allow")
        self.assertEqual(self.rewritten_command(payload), command)

    def test_structured_loop_aggregation_remains_blocked(self):
        command = (
            "foreach ($item in $items) { "
            "$item | ConvertTo-Json -Compress }"
        )

        payload = self.hook_result(command)

        self.assertIsNotNone(payload)
        assert payload is not None
        output = payload["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("Structured PowerShell", output["permissionDecisionReason"])

    def test_keywords_inside_quoted_data_do_not_block(self):
        command = "Write-Output 'foreach ($x in $xs) { ConvertFrom-Json }'"

        self.assertEqual(SANITY.lint_command(command), [])
        self.assertIsNone(self.hook_result(command))

    def test_numeric_bare_range_is_rewritten_once(self):
        command = "Get-Content -LiteralPath 'x' | Select-Object -Index 2..5"

        payload = self.hook_result(command)

        self.assertIsNotNone(payload)
        assert payload is not None
        rewritten = self.rewritten_command(payload)
        self.assertEqual(
            rewritten,
            "Get-Content -LiteralPath 'x' | Select-Object -Index (2..5)",
        )
        self.assertEqual(SANITY.analyze_command(rewritten).rewrites, ())

    def test_combined_ranges_remain_blocked(self):
        command = "Get-Content x | Select-Object -Index (0..2, 8..10)"

        payload = self.hook_result(command)

        self.assertIsNotNone(payload)
        assert payload is not None
        output = payload["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("Combined Select-Object", output["permissionDecisionReason"])

    def test_inline_python_stdin_gets_utf8_mode(self):
        command = "@'\nprint('é')\n'@ | python -"

        analysis = SANITY.analyze_command(command)

        self.assertEqual(analysis.rewrites, ("python_non_ascii_output",))
        self.assertIn("| python -X utf8 -", analysis.command)
        self.assertNotIn(
            "python_non_ascii_output",
            {item["kind"] for item in analysis.findings},
        )

    def test_new_item_rewrites_only_wildcard_free_static_paths(self):
        safe = "New-Item -ItemType Directory -LiteralPath 'C:\\safe'"
        ambiguous = "New-Item -ItemType Directory -LiteralPath 'C:\\[name]'"

        safe_analysis = SANITY.analyze_command(safe)
        ambiguous_analysis = SANITY.analyze_command(ambiguous)

        self.assertEqual(
            safe_analysis.command,
            "New-Item -ItemType Directory -Path 'C:\\safe'",
        )
        self.assertEqual(safe_analysis.rewrites, ("new_item_literalpath",))
        self.assertIn(
            "new_item_literalpath",
            {item["kind"] for item in ambiguous_analysis.findings},
        )
        self.assertEqual(
            {item["disposition"] for item in ambiguous_analysis.findings},
            {SANITY.ANNOTATE},
        )

    def test_ignored_existence_check_routes_with_failure_annotation(self):
        command = (
            "Test-Path -LiteralPath 'missing.txt'; "
            "Get-Content -LiteralPath 'missing.txt'"
        )

        analysis = SANITY.analyze_command(command)
        payload = self.hook_result(command)

        self.assertIn(
            "ignored_existence_check_before_read",
            {item["kind"] for item in analysis.findings},
        )
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(
            payload["hookSpecificOutput"]["permissionDecision"],
            "allow",
        )

    def test_failed_annotated_execution_appends_compact_hint(self):
        annotation = SANITY.finding(
            "ignored_existence_check_before_read",
            SANITY.ANNOTATE,
            "Choose optional or required handling.",
        )
        stderr = io.StringIO()
        completed = SimpleNamespace(returncode=1)

        with mock.patch.object(subprocess, "run", return_value=completed) as run:
            with contextlib.redirect_stderr(stderr):
                returncode = SANITY.execute_powershell(
                    "Get-Content missing.txt",
                    None,
                    "powershell",
                    [annotation],
                )

        self.assertEqual(returncode, 1)
        self.assertIn("Windows shell sanity hints:", stderr.getvalue())
        self.assertIn("ignored_existence_check_before_read", stderr.getvalue())
        encoded = run.call_args.args[0][-1]
        instrumented = base64.b64decode(encoded).decode("utf-16le")
        self.assertIn("Get-Content missing.txt", instrumented)
        self.assertIn("$Error.Count", instrumented)

    def test_successful_annotated_execution_is_silent(self):
        annotation = SANITY.finding(
            "complex_inline_script",
            SANITY.ANNOTATE,
            "Use a named helper after failure.",
        )
        stderr = io.StringIO()
        completed = SimpleNamespace(returncode=0)

        with mock.patch.object(subprocess, "run", return_value=completed):
            with contextlib.redirect_stderr(stderr):
                returncode = SANITY.execute_powershell(
                    "Write-Output ok",
                    None,
                    "powershell",
                    [annotation],
                )

        self.assertEqual(returncode, 0)
        self.assertEqual(stderr.getvalue(), "")

    def test_invalid_hook_input_is_denied(self):
        stdout = io.StringIO()
        event = {"tool_name": "Bash", "tool_input": {}}

        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(event))):
            with contextlib.redirect_stdout(stdout):
                returncode = SANITY.run_hook()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(returncode, 0)
        self.assertEqual(
            payload["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )

    def test_missing_powershell_retains_structured_error(self):
        stderr = io.StringIO()

        with mock.patch.object(subprocess, "run", side_effect=FileNotFoundError):
            with contextlib.redirect_stderr(stderr):
                returncode = SANITY.execute_powershell(
                    "Write-Output ok",
                    None,
                    "missing-powershell",
                )

        payload = json.loads(stderr.getvalue())
        self.assertEqual(returncode, 127)
        self.assertEqual(payload["findings"][0]["kind"], "powershell_not_found")


if __name__ == "__main__":
    unittest.main()
