"""Behavior coverage for the community-profile contract and report summary."""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "ceratops-repo-lifecycle" / "scripts"
REFERENCES = SCRIPTS.parent / "references" / "contracts"
sys.path.insert(0, str(SCRIPTS))

from github_contract_engine.compare_states import compare_states  # noqa: E402
from github_contract_engine.format_report import build_report, build_summary_report  # noqa: E402
from github_contract_engine.github_api import load_json  # noqa: E402


class CommunityProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = {
            "repo": load_json(REFERENCES / "github-repo-deterministic-contract.json")
        }

    def test_community_profile_requires_and_reports_one_hundred_percent(self):
        rule = next(
            item
            for item in self.contracts["repo"]["checks"]
            if item["id"] == "content.community_profile_public"
        )
        score_assertion = next(
            item
            for item in rule["assertions"]
            if item["path"] == "/repository/content/community_profile/health_percentage"
        )
        self.assertEqual(score_assertion["expected"], 100)

        desired_state = {
            "parameters": {"owner": "owner", "repo": "repo"},
            "contract_paths": {},
            "selected_ids": {"repo": [rule["id"]]},
            "rules": [rule],
        }
        observed = {
            "repository": {"content": {"community_profile": {"health_percentage": 87}}},
            "local": {"available": True, "root": ".", "errors": []},
        }
        report = build_report(
            desired_state,
            observed,
            {"findings": [], "approved_drift": []},
        )
        summary = build_summary_report(
            report, ["ERROR", "WARN", "NEEDS_AI_AGENT_REVIEW"]
        )
        self.assertEqual(
            summary["community_profile"],
            {"health_percentage": 87, "target_percentage": 100},
        )

    def test_profile_applicability_and_health_failures(self):
        rule = next(
            item for item in self.contracts["repo"]["checks"]
            if item["id"] == "content.community_profile_public"
        )
        desired = {
            "rules": [rule], "contracts": [self.contracts["repo"]],
            "parameters": {"owner": "owner", "repo": "repo"},
        }
        # Forks cannot expose this API. Non-fork collection and health failures
        # must still fail, and the existing private/archive policy must survive.
        cases = [
            ("public-fork", True, False, "public", False, None, "User", False, ["SKIP"]),
            ("private-fork", True, False, "private", False, None, "User", False, ["SKIP"]),
            ("missing-profile", False, False, "public", False, None, "User", False, ["WARN", "ERROR"]),
            ("healthy-profile", False, False, "public", True, 100, "User", False, ["PASS"]),
            ("incomplete-profile", False, False, "public", True, 87, "User", False, ["ERROR"]),
            ("archived-source", False, True, "public", False, None, "User", False, ["SKIP"]),
            ("private-source", False, False, "private", True, 100, "User", False, ["PASS"]),
            ("organization-reports", False, False, "public", True, 100, "Organization", True, ["PASS"]),
            ("missing-content-reports", False, False, "public", True, 100, "Organization", False, ["ERROR"]),
        ]
        for name, fork, archived, visibility, available, score, owner_type, reports, expected in cases:
            with self.subTest(name=name):
                profile = {"content_reports_enabled": reports}
                if score is not None:
                    profile["health_percentage"] = score
                observed = {
                    "repo": {
                        "fork": fork, "archived": archived,
                        "visibility": visibility, "owner": {"type": owner_type},
                    },
                    "repository": {"content": {
                        "community_profile_available": available,
                        "community_profile": profile,
                    }},
                    "api": {},
                }
                if not available:
                    observed["api"][rule["id"]] = {
                        "ok": False, "status": 404, "message": "Not Found",
                    }
                result = compare_states(observed, desired)
                self.assertEqual([item["level"] for item in result["findings"]], expected)
