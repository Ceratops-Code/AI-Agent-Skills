import argparse
import copy
import hashlib
import json
import pathlib
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = (
    ROOT
    / "skills"
    / "ceratops-governance-lifecycle"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

from apply_rules_update import ApplicationError, commit, prepare  # noqa: E402
from rule_graph import (  # noqa: E402
    parse_rule_text,
    rule_source_summary,
    validate_rule_stack,
)
from validate_rule_candidate import resolve_markdown_policy  # noqa: E402

GOVERNANCE_SNAPSHOT = runpy.run_path(str(SCRIPTS / "governance-snapshot.py"))
agents_rule_graph_inventory = GOVERNANCE_SNAPSHOT["agents_rule_graph_inventory"]
build_snapshot = GOVERNANCE_SNAPSHOT["build_snapshot"]


class RuleGraphTests(unittest.TestCase):
    @staticmethod
    def write_automation(
        root: pathlib.Path,
        automation_id: str,
        reasoning_effort: str,
        prompt: str = "Audit deterministically.",
    ) -> None:
        automation = root / automation_id
        automation.mkdir(parents=True)
        (automation / "automation.toml").write_text(
            f'id = "{automation_id}"\n'
            f'name = "{automation_id}"\n'
            f'prompt = "{prompt}"\n'
            'status = "ACTIVE"\n'
            'rrule = "FREQ=DAILY"\n'
            'model = "gpt-5.6-sol"\n'
            f'reasoning_effort = "{reasoning_effort}"\n',
            encoding="utf-8",
            newline="\n",
        )

    def test_governance_snapshot_uses_source_repo_and_checks_both_effort_scopes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            projects_root = root / "projects"
            source_repo = projects_root / "Codex-Automations"
            source_root = source_repo / "automations"
            runtime_root = root / "runtime" / "automations"
            codex_home = root / "codex-home"
            codex_home.mkdir(parents=True)

            self.write_automation(source_root, "diskfinventorycheck", "max")
            self.write_automation(source_root, "routine-audit", "max")
            self.write_automation(runtime_root, "diskfinventorycheck", "medium")
            self.write_automation(runtime_root, "routine-audit", "medium")
            (source_repo / ".gitignore").write_text(
                "automations/*/memory.md\n",
                encoding="utf-8",
                newline="\n",
            )

            snapshot = build_snapshot(
                argparse.Namespace(
                    automation_root=runtime_root,
                    automation_source_repo=None,
                    projects_root=projects_root,
                    codex_home=codex_home,
                )
            )

            self.assertEqual(snapshot["automations"]["root"], str(runtime_root))
            self.assertEqual(
                snapshot["automation_source"]["root"],
                str(source_root),
            )
            self.assertEqual(
                snapshot["automation_gitignore"]["path"],
                str(source_repo / ".gitignore"),
            )
            mismatches = snapshot["automation_reasoning_effort"]["mismatches"]
            self.assertEqual(
                {(item["scope"], item["id"]) for item in mismatches},
                {("source", "diskfinventorycheck"), ("runtime", "routine-audit")},
            )
            self.assertEqual(
                snapshot["d_rule_brevity"]["sources_checked"],
                2,
            )

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
        candidate_path = task_temp_root / "validated-candidate.json"
        evidence_path = task_temp_root / "application-validation.json"
        candidate = {
            "schema": "ceratops-rule-candidate.v1",
            "rule_stack": [str(global_rules.resolve()), str(local_rules.resolve())],
            "targets": [
                {
                    "rules": str(local_rules.resolve()),
                    "history": str(history.resolve()),
                    "source_sha256": hashlib.sha256(
                        local_rules.read_bytes()
                    ).hexdigest(),
                    "markdown_policy": resolve_markdown_policy(None),
                    "replacements": [
                        {
                            "expected_old": current_rule,
                            "replacement": replacement_rule,
                        }
                    ],
                }
            ],
        }
        candidate_path.write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        request = {
            "version": 4,
            "task_temp_root": str(task_temp_root),
            "request_disposable": True,
            "rule_stack": [str(global_rules), str(local_rules)],
            "rule_stack_sha256": {
                str(global_rules): hashlib.sha256(
                    global_rules.read_bytes()
                ).hexdigest(),
                str(local_rules): hashlib.sha256(
                    local_rules.read_bytes()
                ).hexdigest(),
            },
            "validated_candidate": str(candidate_path),
            "validated_candidate_sha256": hashlib.sha256(
                candidate_path.read_bytes()
            ).hexdigest(),
            "candidate_disposable": True,
            "validation_evidence": str(evidence_path),
            "validation_evidence_disposable": True,
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

    def history_only_update_request(self, root: pathlib.Path):
        rules = root / "AGENTS.md"
        history = root / "AGENTS.history.json"
        task_temp_root = root / "task-temp"
        root.mkdir(parents=True)
        task_temp_root.mkdir()
        rules.write_text(
            "- [CODE-03] Preserve the persistent-test confirmation gate.\n"
            "- [CODE-04] Use behavioral evidence.\n"
            "- [CODE-05] Run the narrowest covering test.\n",
            encoding="utf-8",
            newline="",
        )
        rename_decision = (
            "Rename TEST-01, TEST-02, and TEST-03 to the next unused Coding "
            "IDs CODE-03, CODE-04, and CODE-05 and place them after CODE-01 "
            "and CODE-02 without changing their behavior."
        )
        history.write_text(
            json.dumps(
                {
                    "version": 2,
                    "entries": [
                        {
                            "rules": ["TEST-01"],
                            "decision": "Preserve TEST-01 behavior.",
                            "reason": "Keep the original gate.",
                            "regression": "Preserve TEST-01's confirmation gate.",
                        },
                        {
                            "rules": [
                                "TEST-01",
                                "TEST-02",
                                "TEST-03",
                                "CODE-03",
                                "CODE-04",
                                "CODE-05",
                            ],
                            "decision": rename_decision,
                            "reason": "Consolidate coding governance.",
                            "regression": "Keep all three behaviors unchanged.",
                        },
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="",
        )
        request = {
            "version": 4,
            "task_temp_root": str(task_temp_root),
            "request_disposable": True,
            "rule_stack": [str(rules)],
            "rule_stack_sha256": {
                str(rules): hashlib.sha256(rules.read_bytes()).hexdigest(),
            },
            "validated_candidate": None,
            "validated_candidate_sha256": None,
            "candidate_disposable": False,
            "validation_evidence": str(task_temp_root / "evidence.json"),
            "validation_evidence_disposable": True,
            "history_operations": [
                {
                    "history": str(history),
                    "operation": "rename",
                    "renames": [
                        {"old": "TEST-01", "new": "CODE-03"},
                        {"old": "TEST-02", "new": "CODE-04"},
                        {"old": "TEST-03", "new": "CODE-05"},
                    ],
                    "semantic_replacements": [
                        {
                            "expected_old": rename_decision,
                            "replacement": (
                                "Consolidate the test-governance rules under "
                                "Coding IDs CODE-03, CODE-04, and CODE-05 and "
                                "place them after CODE-01 and CODE-02 without "
                                "changing their behavior."
                            ),
                        }
                    ],
                }
            ],
        }
        return request, rules, history

    @staticmethod
    def run_rules_update(request: dict, request_path: pathlib.Path):
        request_path.write_text(
            json.dumps(request) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return subprocess.run(
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
            failed_candidate = pathlib.Path(failed_request["validated_candidate"])
            failed_value = json.loads(failed_candidate.read_text(encoding="utf-8"))
            failed_value["targets"][0]["replacements"][0]["expected_old"] = "missing"
            failed_candidate.write_text(
                json.dumps(failed_value, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            failed_request["validated_candidate_sha256"] = hashlib.sha256(
                failed_candidate.read_bytes()
            ).hexdigest()
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
            self.assertFalse(
                pathlib.Path(request["validated_candidate"]).exists()
            )
            self.assertFalse(
                pathlib.Path(request["validation_evidence"]).exists()
            )
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

            coupled_root = root / "coupled"
            coupled_root.mkdir()
            coupled_request, coupled_rules = self.rules_update_request(
                coupled_root,
                "- [LOCAL-01] Preserve the old identity.\n",
                "- [LOCAL-02] Preserve the new identity.\n",
            )
            coupled_history = coupled_rules.with_name("AGENTS.history.json")
            coupled_request["history_operations"] = [
                {
                    "history": str(coupled_history),
                    "operation": "rename",
                    "renames": [{"old": "LOCAL-01", "new": "LOCAL-02"}],
                    "semantic_replacements": [],
                },
                {
                    "history": str(coupled_history),
                    "operation": "append",
                    "entry": {
                        "rules": ["LOCAL-02"],
                        "decision": "Use the new local rule identity.",
                        "reason": "The rule was renamed.",
                        "regression": "Keep its behavior unchanged.",
                    },
                },
            ]
            coupled_path = coupled_root / "task-temp" / "request.json"
            coupled = self.run_rules_update(coupled_request, coupled_path)
            self.assertEqual(coupled.returncode, 0, coupled.stderr)
            self.assertNotIn(
                "LOCAL-01",
                coupled_history.read_text(encoding="utf-8"),
            )
            self.assertIn(
                "LOCAL-02",
                coupled_rules.read_text(encoding="utf-8"),
            )

            migration_root = root / "history-only"
            migration_request, _, migration_history = (
                self.history_only_update_request(migration_root)
            )
            migration_path = migration_root / "task-temp" / "request.json"
            migrated = self.run_rules_update(migration_request, migration_path)
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            migrated_text = migration_history.read_text(encoding="utf-8")
            self.assertNotRegex(migrated_text, r"TEST-0[123]")
            migrated_entries = json.loads(migrated_text)["entries"]
            self.assertEqual(migrated_entries[0]["rules"], ["CODE-03"])
            self.assertEqual(
                migrated_entries[1]["rules"],
                ["CODE-03", "CODE-04", "CODE-05"],
            )
            self.assertEqual(
                migrated_entries[1]["decision"],
                "Consolidate the test-governance rules under Coding IDs "
                "CODE-03, CODE-04, and CODE-05 and place them after CODE-01 "
                "and CODE-02 without changing their behavior.",
            )
            self.assertFalse(migration_path.exists())
            self.assertFalse(
                pathlib.Path(migration_request["validation_evidence"]).exists()
            )

            semantic_root = root / "missing-semantic"
            semantic_request, _, _ = self.history_only_update_request(
                semantic_root
            )
            semantic_request["history_operations"][0][
                "semantic_replacements"
            ] = []
            with self.assertRaisesRegex(
                ApplicationError,
                "requires an exact semantic replacement",
            ):
                prepare(semantic_request)

            duplicate_root = root / "duplicate-target"
            duplicate_request, _, _ = self.history_only_update_request(
                duplicate_root
            )
            duplicate_request["history_operations"][0]["renames"][1][
                "new"
            ] = "CODE-03"
            with self.assertRaisesRegex(
                ApplicationError,
                "new IDs must be unique",
            ):
                prepare(duplicate_request)

            cascade_root = root / "cascading-map"
            cascade_request, _, _ = self.history_only_update_request(cascade_root)
            cascade_request["history_operations"][0]["renames"][0][
                "new"
            ] = "TEST-02"
            with self.assertRaisesRegex(
                ApplicationError,
                "must not cascade",
            ):
                prepare(cascade_request)

            ambiguous_root = root / "ambiguous-semantic"
            ambiguous_request, _, ambiguous_history = (
                self.history_only_update_request(ambiguous_root)
            )
            ambiguous_value = json.loads(
                ambiguous_history.read_text(encoding="utf-8")
            )
            ambiguous_value["entries"].append(
                copy.deepcopy(ambiguous_value["entries"][1])
            )
            ambiguous_history.write_text(
                json.dumps(ambiguous_value, indent=2) + "\n",
                encoding="utf-8",
                newline="",
            )
            with self.assertRaisesRegex(
                ApplicationError,
                "semantic expected_old match count is 2",
            ):
                prepare(ambiguous_request)

            old_present_root = root / "old-present"
            old_present_request, old_present_rules, _ = (
                self.history_only_update_request(old_present_root)
            )
            old_present_rules.write_text(
                old_present_rules.read_text(encoding="utf-8")
                + "- [TEST-01] Keep the stale identity.\n",
                encoding="utf-8",
                newline="",
            )
            old_present_request["rule_stack_sha256"][str(old_present_rules)] = (
                hashlib.sha256(old_present_rules.read_bytes()).hexdigest()
            )
            with self.assertRaisesRegex(
                ApplicationError,
                "old ID remains in current rules",
            ):
                prepare(old_present_request)

            new_absent_root = root / "new-absent"
            new_absent_request, new_absent_rules, _ = (
                self.history_only_update_request(new_absent_root)
            )
            new_absent_rules.write_text(
                new_absent_rules.read_text(encoding="utf-8").replace(
                    "- [CODE-05] Run the narrowest covering test.\n",
                    "- [CODE-06] Run the narrowest covering test.\n",
                ),
                encoding="utf-8",
                newline="",
            )
            new_absent_request["rule_stack_sha256"][str(new_absent_rules)] = (
                hashlib.sha256(new_absent_rules.read_bytes()).hexdigest()
            )
            with self.assertRaisesRegex(
                ApplicationError,
                "new ID is absent from current rules",
            ):
                prepare(new_absent_request)

            rollback_root = root / "rollback"
            rollback_request, _, rollback_history = (
                self.history_only_update_request(rollback_root)
            )
            rollback_before = rollback_history.read_bytes()
            rollback_update = prepare(rollback_request)
            with mock.patch(
                "apply_rules_update.revalidate",
                side_effect=ApplicationError("forced revalidation failure"),
            ):
                with self.assertRaisesRegex(ApplicationError, "update rolled back"):
                    commit(rollback_update)
            self.assertEqual(rollback_history.read_bytes(), rollback_before)

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
