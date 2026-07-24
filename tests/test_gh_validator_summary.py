import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "ceratops-gh-repo-lifecycle" / "scripts"
REFERENCES = SCRIPTS.parent / "references" / "contracts"
sys.path.insert(0, str(SCRIPTS))

from github_contract_engine import levels  # noqa: E402
from github_contract_engine import schema_validation  # noqa: E402
from github_contract_engine import github_api  # noqa: E402
from github_contract_engine.collectors import registries  # noqa: E402
from github_contract_engine.collectors.local_repository import (  # noqa: E402
    classify_repository,
    collect_local_repository,
)
from github_contract_engine.collectors.repository import (  # noqa: E402
    stale_branch_candidates,
    stale_pull_request_candidates,
    stale_release_candidates,
)
from github_contract_engine.collect_observed_states import (  # noqa: E402
    _fetch_all,
    state_producer,
)
from github_contract_engine.compare_states import (  # noqa: E402
    OPERATORS,
    compare_states,
    condition_matches,
    pointer_get,
)
from github_contract_engine.compose_desired_state import compose_desired_state, repo_subset_ids  # noqa: E402
from github_contract_engine.format_report import (  # noqa: E402
    build_report,
    build_summary_report,
    sanitize_for_output,
    write_json,
)
from github_contract_engine.github_api import ApiResult, load_json  # noqa: E402
from github_contract_engine.remediations import HANDLERS  # noqa: E402
from github_pr_workflow import readiness as pr_validator  # noqa: E402


class GHContractStateEngineTests(unittest.TestCase):
    paths: dict[str, str]
    contracts: dict[str, dict[str, Any]]

    @classmethod
    def setUpClass(cls):
        cls.paths = {
            "repo": str(REFERENCES / "github-repo-deterministic-contract.json"),
            "code": str(REFERENCES / "code-repo-deterministic-contract.json"),
            "artifact": str(REFERENCES / "artifact-deterministic-contract.json"),
        }
        cls.contracts = {
            surface: load_json(path) for surface, path in cls.paths.items()
        }

    def test_levels_use_explicit_agent_review_name(self):
        selected_levels = levels.parse_levels("ERROR,WARN,NEEDS_AI_AGENT_REVIEW")
        self.assertEqual(
            selected_levels, ["ERROR", "WARN", "NEEDS_AI_AGENT_REVIEW"]
        )
        with self.assertRaises(ValueError):
            levels.parse_levels("NEEDS_" + "REVIEW")

    def test_local_path_scan_distinguishes_regex_syntax_from_windows_paths(self):
        rule = next(
            item
            for item in self.contracts["code"]["checks"]
            if item["id"] == "stale_state.local_path_references"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = pathlib.Path(temporary_directory) / "fixture.py"
            fixture.write_text(
                'USES_RE = re.compile(r"^\\s*uses:\\s*")\n', encoding="utf-8"
            )
            local = collect_local_repository(temporary_directory, [rule])
            self.assertEqual(local["scans"][rule["id"]]["matches"], [])

            windows_path = "C:" + chr(92) + "repo"
            fixture.write_text(f"ROOT = {windows_path!r}\n", encoding="utf-8")
            local = collect_local_repository(temporary_directory, [rule])
            self.assertEqual(
                local["scans"][rule["id"]]["matches"],
                [
                    {
                        "path": "fixture.py",
                        "pattern": rule["collection"]["regex_patterns"][0],
                    }
                ],
            )

    def test_private_node_app_with_docker_publish_is_not_an_npm_artifact(self):
        local = {
            "files": [
                ".github/workflows/publish.yml",
                "Dockerfile",
                "package.json",
            ],
            "texts": {
                ".github/workflows/publish.yml": "uses: docker/build-push-action@sha\n",
                "Dockerfile": "FROM node:24\n",
                "package.json": json.dumps(
                    {"name": "private-app", "version": "1.0.0", "private": True}
                ),
            },
        }
        classification = classify_repository(
            {"has_pages": False},
            local,
            [],
            self.contracts["artifact"]["artifact_type_system"],
        )
        self.assertIn("docker_oci_image", classification["artifact_surface"])
        self.assertNotIn("npm_package", classification["artifact_surface"])

    def test_contracts_compose_to_one_desired_state(self):
        desired_state = compose_desired_state(
            self.paths,
            {"owner": "owner", "repo": "repo", "default_branch": "main"},
            repo_subset_ids(self.contracts, "all"),
        )
        self.assertEqual(len(desired_state["rules"]), 75)
        self.assertTrue(all(rule["assertions"] for rule in desired_state["rules"]))
        self.assertTrue(
            any(
                request.get("paginate")
                and "/releases?per_page=100" in request["endpoint"]
                for request in desired_state["requests"]
            )
        )

    def test_dependency_review_request_uses_visibility_and_owner_plan(self):
        desired_state = compose_desired_state(
            self.paths,
            {"owner": "owner", "repo": "repo", "default_branch": "main"},
            repo_subset_ids(self.contracts, "all"),
            explicit_check_ids={"security.dependency_review_availability"},
        )
        dependency_review_endpoint = (
            "/repos/owner/repo/dependency-graph/compare/main...main"
        )

        cases = (
            ("private", None, 0),
            ("private", "free", 0),
            ("private", "pro", 1),
            ("internal", "free", 1),
            ("public", "free", 1),
        )
        for visibility, owner_plan, expected_call_count in cases:
            calls: list[str] = []

            def fake_run_gh_api(method, endpoint, *, paginate=False):
                calls.append(endpoint)
                if endpoint == "/repos/owner/repo":
                    return ApiResult(
                        True,
                        method,
                        endpoint,
                        data={
                            "archived": False,
                            "default_branch": "main",
                            "visibility": visibility,
                        },
                    )
                if endpoint == "/orgs/owner":
                    return ApiResult(
                        True,
                        method,
                        endpoint,
                        data={"plan": {"name": owner_plan}} if owner_plan else {},
                    )
                return ApiResult(True, method, endpoint, data={})

            with mock.patch(
                "github_contract_engine.collect_observed_states.run_gh_api",
                side_effect=fake_run_gh_api,
            ):
                _fetch_all(desired_state)

            self.assertEqual(
                calls.count(dependency_review_endpoint), expected_call_count
            )

    def test_every_assertion_has_an_operator_and_producer(self):
        for contract in self.contracts.values():
            for rule in contract["checks"]:
                for assertion in rule["assertions"]:
                    self.assertIn(assertion["operator"], OPERATORS)
                    self.assertIsNotNone(state_producer(assertion["path"]))

    def test_compare_states_is_generic_and_path_addressed(self):
        desired_state = {
            "contracts": [],
            "rules": [
                {
                    "id": "example.setting",
                    "desired": {"enabled": True},
                    "assertions": [
                        {
                            "path": "/repository/enabled",
                            "operator": "equal",
                            "desired_path": "/desired/enabled",
                        }
                    ],
                }
            ],
        }
        result = compare_states({"repository": {"enabled": False}}, desired_state)
        self.assertEqual(result["findings"][0]["check_id"], "example.setting")
        self.assertEqual(result["findings"][0]["actual"], False)
        self.assertEqual(result["findings"][0]["expected"], True)

    def test_missing_observation_is_collection_error_not_review(self):
        desired_state = {
            "contracts": [],
            "rules": [
                {
                    "id": "example.missing",
                    "assertions": [
                        {
                            "path": "/repository/missing",
                            "operator": "equal",
                            "expected": True,
                        }
                    ],
                }
            ],
        }
        finding = compare_states({"repository": {}}, desired_state)["findings"][0]
        self.assertEqual(finding["level"], "ERROR")
        self.assertEqual(finding["kind"], "collection_error")

    def test_failed_api_source_is_collection_error_not_policy_mismatch(self):
        desired_state = {
            "contracts": [],
            "rules": [
                {
                    "id": "example.api",
                    "endpoint": "/repos/owner/repo/settings",
                    "assertions": [
                        {
                            "path": "/repository/enabled",
                            "operator": "equal",
                            "expected": True,
                        }
                    ],
                }
            ],
        }
        observed = {
            "api": {
                "example.api": {
                    "ok": False,
                    "endpoint": "/repos/owner/repo/settings",
                    "status": 403,
                    "message": "forbidden",
                }
            },
            "repository": {"enabled": False},
        }
        finding = compare_states(observed, desired_state)["findings"][0]
        self.assertEqual(finding["kind"], "collection_error")
        self.assertEqual(finding["source_error"]["status"], 403)

    def test_agent_review_is_only_contract_declared_judgment_routing(self):
        desired_state = {
            "contracts": [],
            "rules": [
                {
                    "id": "stale.candidates",
                    "assertions": [
                        {
                            "path": "/repository/candidates",
                            "operator": "empty",
                            "level": "NEEDS_AI_AGENT_REVIEW",
                        }
                    ],
                }
            ],
        }
        finding = compare_states(
            {"repository": {"candidates": [{"id": 1}]}}, desired_state
        )["findings"][0]
        self.assertEqual(finding["level"], "NEEDS_AI_AGENT_REVIEW")

    def test_json_pointer_preserves_dotted_keys(self):
        self.assertEqual(
            pointer_get(
                {"api": {"org.settings": {"ok": True}}}, "/api/org.settings/ok"
            ),
            True,
        )

    def test_conditions_use_observed_facts(self):
        states = {
            "repo": {"visibility": "public", "archived": False},
            "type": {"workflow_surface": {"has_workflows": True}},
            "artifact_type": ["npm_package"],
        }
        self.assertTrue(
            condition_matches(
                "repo.visibility == public && repo.archived == false", states
            )
        )
        self.assertTrue(
            condition_matches("type.workflow_surface has has_workflows", states)
        )
        self.assertTrue(condition_matches("artifact_type contains npm_package", states))

    def test_classifier_ignores_tool_only_manifests(self):
        local = {
            "files": [
                "pyproject.toml",
                "package.json",
                "references/contracts.md",
                "scripts/check.py",
            ],
            "texts": {
                "pyproject.toml": '[tool.mypy]\npython_version = "3.11"\n',
                "package.json": '{"name":"dev-tools","private":true}',
                "references/contracts.md": (
                    "Examples: [project], actions/deploy-pages@, and scoop."
                ),
            },
        }
        types = classify_repository(
            {"visibility": "public"},
            local,
            [],
            self.contracts["artifact"]["artifact_type_system"],
        )
        self.assertEqual(types["artifact_surface"], ["no_artifact"])
        self.assertIn("python", types["language_or_iac"])

    def test_classifier_keeps_publishable_manifests(self):
        local = {
            "files": ["pyproject.toml", "package.json"],
            "texts": {
                "pyproject.toml": '[project]\nname = "demo"\nversion = "1.0.0"\n',
                "package.json": json.dumps(
                    {"name": "demo", "version": "1.0.0", "license": "MIT"}
                ),
            },
        }
        types = classify_repository(
            {}, local, [], self.contracts["artifact"]["artifact_type_system"]
        )
        self.assertEqual(
            types["artifact_surface"], ["npm_package", "pypi_python_package"]
        )

    def test_aggregate_live_metadata_activates_registry_collectors(self):
        rules = [{"assertions": [{"path": "/artifact/live_metadata/all_resolved"}]}]
        local = {
            "manifests": {"pypi": {"name_present": True}},
            "texts": {"pyproject.toml": '[project]\nname = "demo"\n'},
        }

        def fake_pypi(name: str) -> dict[str, object]:
            return {"ok": True, "name": name}

        with mock.patch.dict(
            registries.FETCHERS,
            {"pypi_python_package": ("pypi", fake_pypi)},
            clear=True,
        ):
            state = registries.collect_registries(
                {}, local, ["pypi_python_package"], rules
            )
        self.assertTrue(state["pypi"]["all_resolved"])
        self.assertEqual(state["pypi"]["packages"]["demo"]["name"], "demo")

    def test_ghcr_metadata_verifies_the_named_package(self):
        parameters = {
            "owner": "owner",
            "artifact_contracts": [
                {
                    "artifact_type": "docker_oci_image",
                    "registry": "ghcr.io",
                    "package_or_image_name": "ghcr.io/owner/image:latest",
                }
            ],
        }
        rules = [{"assertions": [{"path": "/artifact/live_metadata/all_resolved"}]}]
        response = ApiResult(
            True,
            "GET",
            "/orgs/owner/packages?package_type=container",
            data=[{"name": "image"}],
        )
        with mock.patch.object(registries, "run_gh_api", return_value=response):
            state = registries.collect_registries(
                parameters,
                {},
                ["docker_oci_image", "github_container_registry_image"],
                rules,
                {"repo": {"owner": {"type": "Organization"}}},
            )
        self.assertEqual(state["dockerhub"]["packages"], {})
        self.assertTrue(state["github_packages"]["all_resolved"])
        self.assertTrue(state["github_packages"]["packages"]["container"]["ok"])

    def test_paginated_object_responses_merge_item_arrays(self):
        process = mock.Mock(
            returncode=0,
            stdout=json.dumps(
                [
                    {"total_count": 2, "items": [{"id": 1}]},
                    {"total_count": 2, "items": [{"id": 2}]},
                ]
            ),
            stderr="",
        )
        with mock.patch.object(github_api.subprocess, "run", return_value=process):
            result = github_api.run_gh_api(
                "GET", "/search/issues?q=test&per_page=100", paginate=True
            )
        self.assertTrue(result.ok)
        self.assertEqual(result.data["items"], [{"id": 1}, {"id": 2}])

    def test_stale_helpers_preserve_history_and_classify_candidates(self):
        self.assertEqual(
            stale_pull_request_candidates([], {"report_open_prs_older_than_days": 30}),
            [],
        )
        releases = [
            {
                "tag_name": "v1.0.0",
                "draft": False,
                "prerelease": False,
                "published_at": "2026-01-01T00:00:00Z",
            }
        ]
        self.assertEqual(
            stale_release_candidates(releases, [{"name": "v1.0.0"}], {}), []
        )
        candidates = stale_release_candidates(
            [
                {
                    "tag_name": "v2.0.0-rc1",
                    "draft": False,
                    "prerelease": True,
                    "published_at": "2000-01-01T00:00:00Z",
                }
            ],
            [{"name": "v2.0.0-rc1"}],
            {},
        )
        self.assertIn("prerelease older than 30 days", candidates[0]["stale_reason"])

    def test_stale_helpers_honor_contract_collection_inputs(self):
        branches = [{"name": "release/1.x", "protected": False}]
        self.assertEqual(
            stale_branch_candidates(
                branches,
                [],
                "main",
                {"retained_branch_name_patterns": ["^release/"]},
            ),
            [],
        )
        self.assertEqual(
            stale_release_candidates(
                [
                    {
                        "tag_name": "v1",
                        "draft": True,
                        "created_at": "2999-01-01T00:00:00Z",
                    }
                ],
                [{"name": "v1"}],
                {"draft_review_after_days": 7},
            ),
            [],
        )

    def test_summary_filters_levels_and_keeps_stale_inventory(self):
        desired_state = {
            "parameters": {"owner": "owner", "repo": "repo"},
            "contract_paths": {},
            "selected_ids": {"repo": ["stale_state.tags"]},
            "rules": [{"id": "stale_state.tags"}],
        }
        observed = {
            "repository": {
                "stale": {
                    "tags": {
                        "inventory": [{"name": "v1"}],
                        "candidates": [{"name": "v1"}],
                    },
                    "releases": {
                        "inventory": [
                            {
                                "tag_name": "v1",
                                "body": "large release body",
                                "assets": [{"name": "bundle.zip"}],
                            }
                        ],
                        "candidates": [],
                    },
                }
            },
            "local": {"available": True, "root": ".", "errors": []},
        }
        comparison = {
            "findings": [
                {
                    "level": "NEEDS_AI_AGENT_REVIEW",
                    "check_id": "stale_state.tags",
                    "path": "/repository/stale/tags/candidates",
                    "message": "review",
                    "actual": [{"name": "v1"}],
                }
            ],
            "approved_drift": [],
        }
        report = build_report(desired_state, observed, comparison)
        summary = build_summary_report(
            report, ["ERROR", "WARN", "NEEDS_AI_AGENT_REVIEW"]
        )
        self.assertEqual(summary["stale_state_inventory"]["tags"]["count"], 1)
        release = summary["stale_state_inventory"]["releases"]["sample"][0]
        self.assertEqual(release["asset_names"], ["bundle.zip"])
        self.assertNotIn("body", release)
        self.assertEqual(summary["findings"][0]["level"], "NEEDS_AI_AGENT_REVIEW")

    def test_machine_output_removes_sensitive_and_raw_collected_content(self):
        report = {
            "private": True,
            "token": "secret-value",
            "observed_states": {
                "local": {
                    "texts": {"config.json": "password=secret-value"},
                    "workflows": {"text": "token: secret-value"},
                },
                "api": {
                    "repo.settings": {
                        "raw_stdout": "secret-value",
                        "raw_stderr": "secret-value",
                    },
                    "secret_scanning": {"enabled": True},
                },
            },
            "findings": [
                {
                    "path": "/organization/billing_email",
                    "actual": "private@example.com",
                    "expected": "owner@example.com",
                },
                {
                    "path": "/api/repository",
                    "source_error": {
                        "message": (
                            "request failed: Authorization: Bearer gho_"
                            + "a" * 36
                            + " password=hunter2 "
                            + "https://user:pass@example.com/private"
                        )
                    },
                },
            ],
        }
        safe = sanitize_for_output(report)
        self.assertTrue(safe["private"])
        self.assertEqual(safe["token"], "<redacted>")
        self.assertEqual(
            safe["observed_states"]["local"]["texts"],
            {"count": 1, "content": "<omitted>"},
        )
        self.assertEqual(
            safe["observed_states"]["api"]["repo.settings"]["raw_stdout"],
            "<omitted>",
        )
        self.assertTrue(
            safe["observed_states"]["api"]["secret_scanning"]["enabled"]
        )
        self.assertEqual(safe["findings"][0]["actual"], "<redacted>")
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            write_json(report)
        output = stream.getvalue()
        self.assertNotIn("secret-value", output)
        self.assertNotIn("private@example.com", output)
        self.assertNotIn("hunter2", output)
        self.assertNotIn("user:pass", output)
        self.assertNotIn("gho_", output)
        self.assertEqual(json.loads(output), safe)

    def test_contract_entrypoints_use_sanitized_json_writer(self):
        entrypoints = (
            "collect_non_deterministic_evidence.py",
            "organization_validator.py",
            "repository_validator.py",
        )
        for name in entrypoints:
            text = (SCRIPTS / "github_contract_engine" / name).read_text(
                encoding="utf-8"
            )
            self.assertIn("write_json(", text)
            self.assertNotIn("print(json.dumps(", text)

    def test_remediation_registry_covers_contract_actions(self):
        actions = {
            check["remediation_action"]
            for contract in self.contracts.values()
            for check in contract["checks"]
            if check.get("remediation_action")
        }
        org = load_json(REFERENCES / "github-org-deterministic-contract.json")
        actions.update(
            check["remediation_action"]
            for check in org["checks"]
            if check.get("remediation_action")
        )
        self.assertEqual(actions, set(HANDLERS))

    def test_consistency_validator_passes(self):
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "github_contract_engine",
                "validate",
                "consistency",
            ],
            cwd=SCRIPTS,
            text=True,
            capture_output=True,
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        schema = load_json(
            SCRIPTS.parent
            / "references"
            / "schemas"
            / "state-contract.schema.json"
        )
        misspelled = json.loads(json.dumps(self.contracts["repo"]))
        assertion = misspelled["checks"][0]["assertions"][0]
        assertion["operatr"] = assertion.pop("operator")
        errors = schema_validation.validate_contract_document(
            misspelled,
            schema,
            document_name="misspelled.json",
            schema_name="state-contract.schema.json",
        )
        self.assertTrue(
            any(
                "operatr" in error and "/checks/0/assertions/0" in error
                for error in errors
            )
        )
        inert = json.loads(json.dumps(self.contracts["repo"]))
        inert["checks"][0]["settable"] = True
        inert_errors = schema_validation.validate_contract_document(
            inert,
            schema,
            document_name="inert.json",
            schema_name="state-contract.schema.json",
        )
        self.assertTrue(
            any("settable" in error and "/checks/0" in error for error in inert_errors)
        )

    def test_pr_readiness_emit_errors_on_error_level(self):
        finding = pr_validator.Finding(
            level="ERROR", check="pr.state_open", message="PR is not open."
        )
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            status = pr_validator.emit(
                {}, [finding], as_json=True, contract_path=pathlib.Path("contract.json")
            )
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(stream.getvalue())["counts"]["ERROR"], 1)

    def test_merge_helper_revalidates_after_review_wait(self):
        text = (SCRIPTS / "github_pr_workflow" / "merge.py").read_text(
            encoding="utf-8"
        )
        readiness_call = "    _validate_readiness("
        positions = [
            index
            for index in range(len(text))
            if text.startswith(readiness_call, index)
        ]
        self.assertEqual(len(positions), 2)
        wait_position = text.index("review = codex_review.wait_for_codex_threads(")
        self.assertLess(positions[0], wait_position)
        self.assertLess(wait_position, positions[1])
        self.assertLess(positions[1], text.index('gh_args = ["gh", "pr", "merge"'))

        sync_text = (SCRIPTS / "github_pr_workflow" / "sync.py").read_text(
            encoding="utf-8"
        )
        first_clean = sync_text.index('_assert_clean(repo_root, "before syncing main")')
        fetch = sync_text.index('"fetch", "--prune", args.remote_name')
        switch = sync_text.index('"switch", args.main_branch')
        fast_forward = sync_text.index('"--ff-only"')
        second_clean = sync_text.index('_assert_clean(repo_root, f"after fast-forwarding')
        align = sync_text.index('"branch", "-f", branch, args.main_branch')
        self.assertLess(first_clean, fetch)
        self.assertLess(fetch, switch)
        self.assertLess(switch, fast_forward)
        self.assertLess(fast_forward, second_clean)
        self.assertLess(second_clean, align)


if __name__ == "__main__":
    unittest.main()
