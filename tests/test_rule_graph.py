import json
import pathlib
import runpy
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = (
    ROOT
    / "skills"
    / "ceratops-governance-lifecycle"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

from apply_rules_update import ApplicationError, prepare  # noqa: E402
from rule_graph import (  # noqa: E402
    parse_rule_text,
    rule_source_summary,
    validate_rule_stack,
)

GOVERNANCE_SNAPSHOT = runpy.run_path(str(SCRIPTS / "governance-snapshot.py"))
agents_rule_graph_inventory = GOVERNANCE_SNAPSHOT["agents_rule_graph_inventory"]


class RuleGraphTests(unittest.TestCase):
    def rules_update_request(
        self,
        root: pathlib.Path,
        current_rule: str,
        replacement_rule: str,
    ):
        global_rules = root / "global" / "AGENTS.md"
        local_rules = root / "local" / "AGENTS.md"
        history = local_rules.with_name("AGENTS.history.json")
        task_temp_root = root / "task-temp"
        global_rules.parent.mkdir()
        local_rules.parent.mkdir()
        task_temp_root.mkdir()
        global_rules.write_text(
            "- [AUTH-10] An explicit current user instruction overrides "
            "default behavior.\n",
            encoding="utf-8",
            newline="",
        )
        local_rules.write_text(current_rule, encoding="utf-8", newline="")
        history.write_text(
            json.dumps(
                {
                    "version": 2,
                    "entries": [
                        {
                            "rules": ["LOCAL-01"],
                            "decision": "Record the original local rule.",
                            "reason": "Keep decision history available.",
                            "regression": "Preserve the intended local behavior.",
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="",
        )
        request = {
            "version": 2,
            "task_temp_root": str(task_temp_root),
            "request_disposable": True,
            "rule_stack": [str(global_rules), str(local_rules)],
            "rule_replacements": [
                {
                    "rules": str(local_rules),
                    "history": str(history),
                    "expected_old": current_rule,
                    "replacement": replacement_rule,
                }
            ],
            "history_operations": [
                {
                    "history": str(history),
                    "operation": "append",
                    "entry": {
                        "rules": ["LOCAL-01"],
                        "decision": "Remove the rule-local user override.",
                        "reason": "The broad authorization rule owns overrides.",
                        "regression": "Keep the local invariant enforceable.",
                    },
                }
            ],
        }
        return request, local_rules

    def test_rule_local_user_override_is_rejected_case_insensitively(self):
        parsed = parse_rule_text(
            "- [FRAME-01] Use the selected mechanism unless the user\n"
            "  Explicitly requires another.\n",
            "AGENTS.md",
        )

        self.assertEqual(
            [finding["code"] for finding in parsed.findings],
            ["rule_local_user_override"],
        )

    def test_broad_user_override_policy_remains_valid(self):
        parsed = parse_rule_text(
            "- [AUTH-10] An explicit current user instruction overrides "
            "default behavior.\n",
            "AGENTS.md",
        )

        self.assertEqual(parsed.findings, [])

    def test_list_heavy_approved_is_metadata_not_debt_or_review(self):
        parsed = parse_rule_text(
            "- [LOCAL-01] Preserve the approved exact enumeration.\n"
            "  - self: list-heavy approved\n",
            "AGENTS.md",
        )

        self.assertEqual(parsed.findings, [])
        self.assertEqual(parsed.debts, [])
        self.assertEqual(parsed.semantic_reviews, [])

    def test_plain_list_heavy_is_review_not_debt(self):
        parsed = parse_rule_text(
            "- [LOCAL-01] Review the exact enumeration.\n"
            "  - self: list-heavy\n",
            "AGENTS.md",
        )

        self.assertEqual(parsed.findings, [])
        self.assertEqual(parsed.debts, [])
        self.assertEqual(
            [review["code"] for review in parsed.semantic_reviews],
            ["list-heavy"],
        )

    def test_plain_and_approved_list_heavy_statuses_conflict(self):
        parsed = parse_rule_text(
            "- [LOCAL-01] Reject conflicting enumeration statuses.\n"
            "  - self: list-heavy, list-heavy approved\n",
            "AGENTS.md",
        )

        self.assertEqual(
            [finding["code"] for finding in parsed.findings],
            ["conflicting_self_statuses"],
        )
        self.assertEqual(parsed.debts, [])
        self.assertEqual(parsed.semantic_reviews, [])

    def test_list_heavy_approved_is_in_summary_inventory_not_counts(self):
        parsed = parse_rule_text(
            "- [LOCAL-01] Preserve the approved exact enumeration.\n"
            "  - self: list-heavy approved\n",
            "AGENTS.md",
        )

        summary = rule_source_summary(parsed)

        self.assertEqual(
            summary["approved_statuses"],
            {"list-heavy approved": ["LOCAL-01"]},
        )
        self.assertEqual(summary["approved_debt"]["count"], 0)
        self.assertEqual(summary["semantic_reviews"]["count"], 0)

    def test_relations_within_global_scope_are_valid(self):
        source = parse_rule_text(
            "- [GLOBAL-01] Apply the narrower global rule.\n"
            "  - limits: GLOBAL-02\n"
            "- [GLOBAL-02] Apply the global baseline.\n",
            "global/AGENTS.md",
        )

        validation = validate_rule_stack(
            [source],
            scope_by_source={source.source: "global"},
        )

        self.assertEqual(validation["findings"], [])

    def test_relations_cannot_cross_global_and_project_scopes(self):
        cases = (
            (
                "- [GLOBAL-01] Apply the global rule.\n"
                "  - limits: LOCAL-01\n",
                "- [LOCAL-01] Apply the local rule.\n",
            ),
            (
                "- [GLOBAL-01] Apply the global rule.\n",
                "- [LOCAL-01] Apply the local rule.\n"
                "  - limits: GLOBAL-01\n",
            ),
        )
        for global_text, local_text in cases:
            with self.subTest(global_text=global_text, local_text=local_text):
                global_source = parse_rule_text(
                    global_text,
                    "global/AGENTS.md",
                )
                local_source = parse_rule_text(
                    local_text,
                    "project/AGENTS.md",
                )

                validation = validate_rule_stack(
                    [global_source, local_source],
                    scope_by_source={
                        global_source.source: "global",
                        local_source.source: "project:one",
                    },
                )

                self.assertEqual(
                    [finding["code"] for finding in validation["findings"]],
                    ["relation_targets_other_scope"],
                )

    def test_relation_between_local_files_in_one_project_is_valid(self):
        parent = parse_rule_text(
            "- [LOCAL-01] Apply the project rule.\n"
            "  - limits: NESTED-01\n",
            "project/AGENTS.md",
        )
        nested = parse_rule_text(
            "- [NESTED-01] Apply the nested project rule.\n",
            "project/component/AGENTS.md",
        )

        validation = validate_rule_stack(
            [parent, nested],
            scope_by_source={
                parent.source: "project:one",
                nested.source: "project:one",
            },
        )

        self.assertEqual(validation["findings"], [])

    def test_non_git_project_root_and_nested_agents_share_stack(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            projects_root = root / "project"
            codex_home = root / "codex"
            nested = projects_root / "component" / "AGENTS.md"
            projects_root.mkdir()
            codex_home.mkdir()
            nested.parent.mkdir()
            (projects_root / "AGENTS.md").write_text(
                "- [ROOT-01] Apply the project rule.\n",
                encoding="utf-8",
                newline="",
            )
            nested.write_text(
                "- [NESTED-01] Apply the nested rule.\n"
                "  - limits: ROOT-01\n",
                encoding="utf-8",
                newline="",
            )

            inventory = agents_rule_graph_inventory(projects_root, codex_home)

        nested_stack = next(
            stack for stack in inventory["stacks"] if stack["path"] == str(nested)
        )
        self.assertEqual(nested_stack["findings"], [])
        self.assertEqual(
            nested_stack["stack_paths"],
            [
                str(projects_root / "AGENTS.md"),
                str(nested),
            ],
        )

    def test_relations_cannot_cross_project_scopes(self):
        first = parse_rule_text(
            "- [FIRST-01] Apply the first project rule.\n"
            "  - limits: SECOND-01\n",
            "first/AGENTS.md",
        )
        second = parse_rule_text(
            "- [SECOND-01] Apply the second project rule.\n",
            "second/AGENTS.md",
        )

        validation = validate_rule_stack(
            [first, second],
            scope_by_source={
                first.source: "project:first",
                second.source: "project:second",
            },
        )

        self.assertEqual(
            [finding["code"] for finding in validation["findings"]],
            ["relation_targets_other_scope"],
        )

    def test_skill_relations_require_one_skill_scope(self):
        owner = parse_rule_text(
            "- [SKILL-01] Apply the owning skill rule.\n"
            "  - limits: ACTION-01\n",
            "skill/SKILL.md",
        )
        action = parse_rule_text(
            "- [ACTION-01] Apply the skill action rule.\n",
            "skill/references/action.md",
        )

        same_skill = validate_rule_stack(
            [owner, action],
            scope_by_source={
                owner.source: "skill:one",
                action.source: "skill:one",
            },
        )
        different_skills = validate_rule_stack(
            [owner, action],
            scope_by_source={
                owner.source: "skill:one",
                action.source: "skill:two",
            },
        )

        self.assertEqual(same_skill["findings"], [])
        self.assertEqual(
            [finding["code"] for finding in different_skills["findings"]],
            ["relation_targets_other_scope"],
        )

    def test_rules_update_can_repair_an_invalid_current_stack(self):
        current = (
            "- [LOCAL-01] Use the selected mechanism unless the user "
            "explicitly asks otherwise.\n"
        )
        replacement = "- [LOCAL-01] Use the selected mechanism.\n"
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            request, local_rules = self.rules_update_request(root, current, replacement)

            update = prepare(request)

            request_path = root / "task-temp" / "request.json"
            request_path.write_text(
                json.dumps(request) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            applied = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "apply_rules_update.py"),
                    "--request",
                    str(request_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            failed_root = root / "failed"
            failed_root.mkdir()
            failed_request, failed_rules = self.rules_update_request(
                failed_root, current, replacement
            )
            failed_request["rule_replacements"][0]["expected_old"] = "missing"
            failed_path = failed_root / "task-temp" / "request.json"
            failed_path.write_text(
                json.dumps(failed_request) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            failed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "apply_rules_update.py"),
                    "--request",
                    str(failed_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            escaped_root = root / "escaped"
            escaped_root.mkdir()
            escaped_request, escaped_rules = self.rules_update_request(
                escaped_root, current, replacement
            )
            escaped_path = escaped_root / "outside-request.json"
            escaped_path.write_text(
                json.dumps(escaped_request) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            escaped = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "apply_rules_update.py"),
                    "--request",
                    str(escaped_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            user_root = root / "user-owned"
            user_root.mkdir()
            user_request, user_rules = self.rules_update_request(
                user_root, current, replacement
            )
            user_request["request_disposable"] = False
            user_path = user_root / "user-request.json"
            user_path.write_text(
                json.dumps(user_request) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            user_applied = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "apply_rules_update.py"),
                    "--request",
                    str(user_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(
                update.candidates[local_rules.resolve()],
                replacement.encode(),
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertEqual(applied.stdout.strip(), "OK")
            self.assertFalse(request_path.exists())
            self.assertEqual(local_rules.read_text(encoding="utf-8"), replacement)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("occurrence count", failed.stderr)
            self.assertTrue(failed_path.is_file())
            self.assertEqual(failed_rules.read_text(encoding="utf-8"), current)
            self.assertNotEqual(escaped.returncode, 0)
            self.assertIn("escapes task_temp_root", escaped.stderr)
            self.assertTrue(escaped_path.is_file())
            self.assertEqual(escaped_rules.read_text(encoding="utf-8"), current)
            self.assertEqual(user_applied.returncode, 0, user_applied.stderr)
            self.assertTrue(user_path.is_file())
            self.assertEqual(user_rules.read_text(encoding="utf-8"), replacement)

    def test_rules_update_accepts_list_heavy_approved_metadata(self):
        current = "- [LOCAL-01] Preserve the exact enumeration.\n"
        replacement = (
            "- [LOCAL-01] Preserve the exact enumeration.\n"
            "  - self: list-heavy approved\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            request, local_rules = self.rules_update_request(
                pathlib.Path(directory), current, replacement
            )

            update = prepare(request)

        self.assertEqual(
            update.candidates[local_rules.resolve()],
            replacement.encode(),
        )

    def test_rules_update_rejects_an_invalid_repair_candidate(self):
        current = (
            "- [LOCAL-01] Use the selected mechanism unless the user "
            "explicitly asks otherwise.\n"
        )
        replacement = (
            "- [LOCAL-01] Use another mechanism unless the user explicitly "
            "asks otherwise.\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            request, _ = self.rules_update_request(
                pathlib.Path(directory), current, replacement
            )

            with self.assertRaisesRegex(
                ApplicationError, "invalid candidate rule stack"
            ):
                prepare(request)


if __name__ == "__main__":
    unittest.main()
