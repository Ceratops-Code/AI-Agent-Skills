import contextlib
import importlib.util
import io
import json
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "hooks" / "bounded-source-search.py"
SPEC = importlib.util.spec_from_file_location("bounded_source_search", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
BOUNDED = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BOUNDED
SPEC.loader.exec_module(BOUNDED)


@unittest.skipUnless(shutil.which("rg"), "ripgrep is required")
class BoundedSourceSearchTests(unittest.TestCase):
    def test_search_ranks_files_and_bounds_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "one.py").write_text(
                "needle one\nneedle two\nneedle three\n",
                encoding="utf-8",
            )
            (root / "two.py").write_text("needle once\n", encoding="utf-8")
            (root / "three.py").write_text(
                "needle first\nplain\nneedle second\n",
                encoding="utf-8",
            )

            payload = BOUNDED.search(
                root,
                "needle",
                max_files=2,
                matches_per_file=2,
                context=0,
                max_bytes=4_000,
            )

        self.assertEqual(payload["schema"], "bounded-source-search.v1")
        self.assertTrue(payload["truncated"])
        files = payload["files"]
        self.assertEqual([item["path"] for item in files], ["one.py", "three.py"])
        for item in files:
            matches = [
                snippet
                for snippet in item["snippets"]
                if snippet["kind"] == "match"
            ]
            self.assertLessEqual(len(matches), 2)

    def test_search_enforces_total_output_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            for index in range(5):
                (root / f"file-{index}.txt").write_text(
                    ("needle " + "x" * 300 + "\n") * 4,
                    encoding="utf-8",
                )

            payload = BOUNDED.search(root, "needle", max_bytes=700)

        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertLessEqual(len(encoded), 700)
        self.assertTrue(payload["truncated"])

    @staticmethod
    def hook_result(event, *, max_bytes=600):
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(event))):
            with contextlib.redirect_stdout(stdout):
                returncode = BOUNDED.run_hook(max_bytes)
        if returncode != 0:
            raise AssertionError(f"hook returned {returncode}")
        output = stdout.getvalue().strip()
        return json.loads(output) if output else None

    def test_hook_replaces_only_oversized_successful_rg_output(self):
        lines = [f"src/a.py:{index}:needle {'x' * 100}" for index in range(20)]
        event = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "rg -n needle src"},
            "tool_response": {"exit_code": 0, "output": "\n".join(lines)},
        }

        payload = self.hook_result(event)

        self.assertIsNotNone(payload)
        self.assertFalse(payload["continue"])
        self.assertIn("Bounded source-search output", payload["stopReason"])
        self.assertLessEqual(len(payload["stopReason"].encode("utf-8")), 600)

    def test_hook_bounds_successful_command_probe_rg_output(self):
        lines = [f"src/a.py:{index}:needle {'x' * 100}" for index in range(20)]
        probe_output = json.dumps(
            {
                "schema": "ceratops-command-probe-result.v1",
                "ok": True,
                "mode": "search",
                "matched": True,
                "tool_returncode": 0,
                "stdout": "\n".join(lines),
                "stderr": "",
            }
        )
        event = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {
                "command": "python C:\\hooks\\command-probe.py --encoded-request x"
            },
            "tool_response": {"exit_code": 0, "output": probe_output},
        }

        payload = self.hook_result(event)

        self.assertIsNotNone(payload)
        self.assertIn("Bounded source-search output", payload["stopReason"])
        self.assertLessEqual(len(payload["stopReason"].encode("utf-8")), 600)

    def test_hook_leaves_small_non_search_and_failed_output_unchanged(self):
        base = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "rg -n needle src"},
            "tool_response": {"exit_code": 0, "output": "src/a.py:1:needle"},
        }
        self.assertIsNone(self.hook_result(base))

        non_search = dict(base)
        non_search["tool_input"] = {"command": "git status"}
        non_search["tool_response"] = {"exit_code": 0, "output": "x" * 1_000}
        self.assertIsNone(self.hook_result(non_search))

        failed = dict(base)
        failed["tool_response"] = {"exit_code": 2, "output": "x" * 1_000}
        self.assertIsNone(self.hook_result(failed))
