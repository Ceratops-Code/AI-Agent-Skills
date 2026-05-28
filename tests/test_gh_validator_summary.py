import contextlib
import importlib.util
import io
import json
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "ceratops-gh-repo-lifecycle" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import validator_levels  # noqa: E402


def load_script_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


repo_validator = load_script_module("repo_validator", "github-validate-repo-artifact-contract.py")
pr_validator = load_script_module("pr_validator", "github-validate-pr-readiness-contract.py")
org_validator = load_script_module("org_validator", "github-validate-org-contract.py")


class GHValidatorSummaryTests(unittest.TestCase):
    def test_parse_levels_rejects_retired_names(self):
        self.assertEqual(
            validator_levels.parse_levels("ERROR,WARN,NEEDS_REVIEW"),
            ["ERROR", "WARN", "NEEDS_REVIEW"],
        )
        with self.assertRaises(ValueError):
            validator_levels.parse_levels("FA" + "IL")
        with self.assertRaises(ValueError):
            validator_levels.parse_levels("MAN" + "UAL")

    def test_count_by_level_uses_canonical_levels(self):
        counts = validator_levels.count_by_level(
            [
                {"level": "ERROR"},
                {"level": "WARN"},
                {"level": "NEEDS_REVIEW"},
                {"level": "PASS"},
            ]
        )
        self.assertEqual(counts["ERROR"], 1)
        self.assertEqual(counts["WARN"], 1)
        self.assertEqual(counts["NEEDS_REVIEW"], 1)
        self.assertEqual(counts["PASS"], 1)

    def test_summary_filters_findings_and_keeps_inventory_separate(self):
        releases = [
            {"tag_name": f"v1.{index}", "name": f"v1.{index}", "draft": False, "prerelease": False, "assets": []}
            for index in range(6)
        ]
        findings = [
            {
                "level": "ERROR",
                "check_id": "stale_state.local_path_references",
                "path": "$",
                "message": "Forbidden local pattern found.",
                "actual": [
                    {"path": "a.md", "pattern": "Users"},
                    {"path": "b.md", "pattern": "Users"},
                ],
            },
            {
                "level": "PASS",
                "check_id": "stale_state.pull_requests",
                "path": "$",
                "message": "No stale open PR candidates found.",
                "actual": [],
                "inventory": [],
            },
            {
                "level": "PASS",
                "check_id": "stale_state.releases",
                "path": "$",
                "message": "No stale release candidates found; published release history is retained.",
                "actual": releases,
                "inventory": releases,
            },
            {
                "level": "NEEDS_REVIEW",
                "check_id": "stale_state.tags",
                "path": "$",
                "message": "Tags without matching releases need review-owner classification.",
                "actual": [{"name": "v0.0.1", "stale_reason": "tag has no matching GitHub release"}],
                "inventory": [{"name": "v0.0.1"}, {"name": "v1.0.0"}],
            },
            {"level": "PASS", "check_id": "repo.identity", "path": "$", "message": "ok"},
        ]
        report = {
            "repo": "owner/repo",
            "selection_mode": "single",
            "surface": "all",
            "subset": "health",
            "selections": None,
            "result_counts": validator_levels.count_by_level(findings),
            "github_check_count": 2,
            "code_check_count": 1,
            "artifact_check_count": 0,
            "fetched_endpoints": 3,
            "types": {"artifact_surface": ["no_artifact"]},
            "findings": findings,
            "approved_drift": [],
            "local_scan": {"available": True, "root": ".", "errors": []},
        }

        summary = repo_validator.build_summary_report(report, ["ERROR", "WARN", "NEEDS_REVIEW"])

        self.assertEqual([item["check_id"] for item in summary["findings"]], ["stale_state.local_path_references", "stale_state.tags"])
        self.assertNotIn("stale_state.releases", [item["check_id"] for item in summary["findings"]])
        self.assertEqual(summary["stale_state_inventory"]["pull_requests"]["count"], 0)
        self.assertEqual(summary["stale_state_inventory"]["local_path_references"]["count"], 2)
        self.assertEqual(summary["stale_state_inventory"]["releases"]["count"], 6)
        self.assertEqual(len(summary["stale_state_inventory"]["releases"]["sample"]), 5)
        self.assertEqual(summary["findings"][1]["actual"]["sample"][0]["stale_reason"], "tag has no matching GitHub release")

    def test_stale_candidate_helpers_do_not_flag_empty_or_retained_history(self):
        self.assertEqual(repo_validator.stale_pull_request_candidates([], {"report_open_prs_older_than_days": 30}), [])

        retained_releases = [
            {"tag_name": "v1.0.0", "name": "v1.0.0", "draft": False, "prerelease": False, "published_at": "2026-01-01T00:00:00Z"}
        ]
        tags = [{"name": "v1.0.0"}]
        self.assertEqual(repo_validator.stale_release_candidates(retained_releases, tags, {}), [])

        stale_releases = [
            {"tag_name": "v2.0.0-rc1", "name": "v2.0.0-rc1", "draft": False, "prerelease": True, "published_at": "2000-01-01T00:00:00Z"}
        ]
        candidates = repo_validator.stale_release_candidates(stale_releases, [{"name": "v2.0.0-rc1"}], {})
        self.assertEqual(len(candidates), 1)
        self.assertIn("prerelease older than 30 days", candidates[0]["stale_reason"])

    def test_pr_readiness_emit_errors_on_error_level(self):
        finding = pr_validator.Finding(level="ERROR", check="pr.state_open", message="PR is not open.")
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            status = pr_validator.emit({}, [finding], as_json=True, contract_path=pathlib.Path("contract.json"))

        payload = json.loads(stream.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(payload["counts"]["ERROR"], 1)

    def test_org_remediation_summary_uses_needs_review_bucket(self):
        summary = org_validator.remediation_summary(
            [{"check_id": "org.identity", "path": "$.login"}],
            {"remediation_policy": {"auto_apply_check_ids": []}},
        )

        self.assertEqual(summary["needs_review_or_report_only"], [{"check_id": "org.identity", "path": "$.login"}])
        self.assertNotIn("manual" + "_or_report_only", summary)


if __name__ == "__main__":
    unittest.main()
