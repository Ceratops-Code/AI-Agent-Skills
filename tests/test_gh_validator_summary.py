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

    def test_classifier_does_not_treat_tool_manifests_as_publish_artifacts(self):
        local = {
            "files": ["pyproject.toml", "package.json", "scripts/check.py", ".github/workflows/validate.yml"],
            "texts": {
                "pyproject.toml": "[tool.mypy]\npython_version = \"3.11\"\n",
                "package.json": "{\"name\":\"dev-tools\",\"private\":true}",
                ".github/workflows/validate.yml": "name: Validate\n",
            },
        }

        types = repo_validator.classify({"visibility": "public"}, local["files"], [], local)

        self.assertEqual(types["artifact_surface"], ["no_artifact"])
        self.assertIn("python", types["language_or_iac"])
        self.assertIn("javascript_or_typescript", types["language_or_iac"])

    def test_classify_keeps_publishable_package_manifests(self):
        local = {
            "files": ["pyproject.toml", "package.json"],
            "texts": {
                "pyproject.toml": "[project]\nname = \"demo\"\nversion = \"1.0.0\"\n",
                "package.json": json.dumps({"name": "demo", "version": "1.0.0", "license": "MIT"}),
            },
        }

        types = repo_validator.classify({}, local["files"], [], local)

        self.assertEqual(types["artifact_surface"], ["npm_package", "pypi_python_package"])

    def test_classify_keeps_private_workspace_publish_surface(self):
        local = {
            "files": ["package.json"],
            "texts": {
                "package.json": json.dumps({"name": "root", "private": True, "workspaces": ["packages/*"]}),
            },
        }

        types = repo_validator.classify({}, local["files"], [], local)

        self.assertEqual(types["artifact_surface"], ["npm_package"])

    def test_github_package_metadata_skips_pypi_release_assets(self):
        check = {
            "id": "github_packages.live_package_metadata",
            "applies_when": "artifact_type category == github_packages || registry host == github.com || registry host == ghcr.io",
        }
        releases = [{"assets": [{"name": "pdf_form_tools-2.1.0.tar.gz"}]}]

        findings = repo_validator.evaluate_artifact_check(
            check,
            {},
            {"files": [], "texts": {}},
            {"artifact_surface": ["pypi_python_package"]},
            {},
            releases,
        )

        self.assertEqual(findings[0]["level"], "SKIP")

    def test_short_lived_identity_passes_job_scoped_oidc(self):
        workflow = """
name: Publish
jobs:
  publish:
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b
"""
        check = {"id": "common.short_lived_identity_policy"}

        findings = repo_validator.evaluate_artifact_check(
            check,
            {},
            {"files": [".github/workflows/publish-pypi.yml"], "texts": {".github/workflows/publish-pypi.yml": workflow}},
            {"artifact_surface": ["pypi_python_package"]},
            {},
            [],
        )

        self.assertEqual(findings[0]["level"], "PASS")

    def test_private_fork_workflows_do_not_require_approval_when_disabled(self):
        findings = repo_validator.private_fork_pr_workflow_findings(
            "actions.private_fork_pr_workflows",
            {
                "run_workflows_from_fork_pull_requests": False,
                "send_write_tokens_to_workflows": False,
                "send_secrets_and_variables": False,
                "require_approval_for_fork_pr_workflows": False,
            },
        )

        self.assertEqual(findings[0]["level"], "PASS")

    def test_contributor_approval_policy_does_not_apply_to_private_repos(self):
        context = {
            "repo.visibility": "private",
            "repo.archived": False,
            "type.workflow_surface": {"has_workflows": True},
        }

        applies = repo_validator.condition_matches(
            "repo.visibility != private && repo.archived == false && type.workflow_surface has has_workflows",
            context,
        )

        self.assertFalse(applies)

    def test_private_fork_workflows_require_approval_when_enabled(self):
        findings = repo_validator.private_fork_pr_workflow_findings(
            "actions.private_fork_pr_workflows",
            {
                "run_workflows_from_fork_pull_requests": True,
                "send_write_tokens_to_workflows": False,
                "send_secrets_and_variables": False,
                "require_approval_for_fork_pr_workflows": False,
            },
        )

        self.assertEqual([item["level"] for item in findings], ["WARN", "ERROR"])
        self.assertEqual(findings[1]["path"], "$.require_approval_for_fork_pr_workflows")

    def test_regex_scan_defers_documented_exceptions_for_review(self):
        check = {
            "id": "stale_state.local_path_references",
            "expected": {
                "forbidden_patterns": [r"[A-Za-z]:\\\\"],
                "allow_when": "external_runtime_requires_absolute_path_and_documented",
            },
        }
        local = {
            "available": True,
            "texts": {"automation.toml": 'cwd = "' + "C:" + '\\\\CodexProjects\\\\repo"'},
        }

        findings = repo_validator.regex_scan_check(check, local)

        self.assertEqual(findings[0]["level"], "NEEDS_REVIEW")
        self.assertEqual(findings[0]["expected"], "external_runtime_requires_absolute_path_and_documented")

    def test_regex_scan_keeps_secret_matches_blocking(self):
        check = {
            "id": "content.local_secret_pattern_scan",
            "expected": {
                "forbidden_patterns": [r"ghp_[A-Za-z0-9]+"],
                "allow_when": "fixture_or_documentation_context_only",
            },
        }
        local = {
            "available": True,
            "texts": {"config.txt": "token=ghp_exampletoken"},
        }

        findings = repo_validator.regex_scan_check(check, local)

        self.assertEqual(findings[0]["level"], "ERROR")

    def test_pr_readiness_emit_errors_on_error_level(self):
        finding = pr_validator.Finding(level="ERROR", check="pr.state_open", message="PR is not open.")
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            status = pr_validator.emit({}, [finding], as_json=True, contract_path=pathlib.Path("contract.json"))

        payload = json.loads(stream.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(payload["counts"]["ERROR"], 1)

    def test_merge_helper_revalidates_after_review_wait(self):
        text = (SCRIPTS / "validate-and-merge-pr.ps1").read_text(encoding="utf-8")
        readiness_call = 'Invoke-QuietNative -FilePath "python" -Arguments $readinessArgs'
        positions = [index for index in range(len(text)) if text.startswith(readiness_call, index)]

        self.assertEqual(len(positions), 2)
        review_wait = text.index('$reviewGateScript,')
        merge_args = text.index('$ghArgs = @("pr", "merge"')
        self.assertLess(positions[0], review_wait)
        self.assertLess(review_wait, positions[1])
        self.assertLess(positions[1], merge_args)

    def test_org_remediation_summary_uses_needs_review_bucket(self):
        summary = org_validator.remediation_summary(
            [{"check_id": "org.identity", "path": "$.login"}],
            {"remediation_policy": {"auto_apply_check_ids": []}},
        )

        self.assertEqual(summary["needs_review_or_report_only"], [{"check_id": "org.identity", "path": "$.login"}])
        self.assertNotIn("manual" + "_or_report_only", summary)


if __name__ == "__main__":
    unittest.main()
