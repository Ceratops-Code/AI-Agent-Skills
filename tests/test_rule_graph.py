import json
import pathlib
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
from rule_graph import parse_rule_text, rule_source_summary  # noqa: E402


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
        global_rules.parent.mkdir()
        local_rules.parent.mkdir()
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
            "version": 1,
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

    def test_rules_update_can_repair_an_invalid_current_stack(self):
        current = (
            "- [LOCAL-01] Use the selected mechanism unless the user "
            "explicitly asks otherwise.\n"
        )
        replacement = "- [LOCAL-01] Use the selected mechanism.\n"
        with tempfile.TemporaryDirectory() as directory:
            request, local_rules = self.rules_update_request(
                pathlib.Path(directory), current, replacement
            )

            update = prepare(request)

        self.assertEqual(
            update.candidates[local_rules.resolve()],
            replacement.encode(),
        )

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
