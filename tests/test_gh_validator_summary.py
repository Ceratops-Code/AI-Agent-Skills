import argparse
import contextlib
import io
import json
import os
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
from github_contract_engine import codeql_disposition  # noqa: E402
from github_contract_engine import audit_snapshot  # noqa: E402
from github_contract_engine.operations import (  # noqa: E402
    TOP_LEVEL_COMMANDS,
    VALIDATION_TARGETS,
)
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

    def test_audit_snapshot_compacts_local_contract_discovery(self):
        snapshot = audit_snapshot.build_snapshot(ROOT)
        self.assertEqual(
            snapshot["schema"], "ceratops-github-contract-audit-snapshot.v1"
        )
        self.assertEqual(
            snapshot["commands"]["top_level"], list(TOP_LEVEL_COMMANDS)
        )
        self.assertEqual(
            snapshot["commands"]["validation_targets"],
            list(VALIDATION_TARGETS),
        )
        self.assertGreaterEqual(len(snapshot["contracts"]), 10)
        self.assertTrue(
            all("check_ids" in contract for contract in snapshot["contracts"])
        )
        self.assertTrue(
            all(
                "missing_source_lines" in contract
                for contract in snapshot["contracts"]
            )
        )
        self.assertEqual(
            [document["path"] for document in snapshot["repo_docs"]],
            ["README.md", "CONTRIBUTING.md", "CHANGELOG.md"],
        )
        self.assertNotIn(str(ROOT), json.dumps(snapshot))

    def test_audit_snapshot_reports_a_compact_incompatible_root_blocker(self):
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary_directory:
            with contextlib.redirect_stdout(stream):
                status = audit_snapshot.main(
                    ["--repo-root", temporary_directory]
                )
        self.assertEqual(status, 1)
        self.assertEqual(
            json.loads(stream.getvalue()),
            {
                "error": "selected root is not a compatible skills checkout",
                "status": "blocked",
            },
        )

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

            windows_path = "D:" + chr(92) + "work"
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

    def test_dependabot_ecosystems_distinguish_uv_and_pip_manifests(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = pathlib.Path(temporary_directory)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "demo"\n',
                encoding="utf-8",
            )

            pip_only = collect_local_repository(temporary_directory, [])
            self.assertEqual(
                pip_only["dependabot"]["ecosystems"],
                {"pip": ["pyproject.toml"]},
            )

            (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
            uv_only = collect_local_repository(temporary_directory, [])
            self.assertEqual(
                uv_only["dependabot"]["ecosystems"],
                {"uv": ["pyproject.toml", "uv.lock"]},
            )

            (root / "requirements-dev.txt").write_text(
                "pytest\n",
                encoding="utf-8",
            )
            mixed = collect_local_repository(temporary_directory, [])
            self.assertEqual(
                mixed["dependabot"]["ecosystems"],
                {
                    "pip": ["requirements-dev.txt"],
                    "uv": ["pyproject.toml", "uv.lock"],
                },
            )

    def test_local_path_scan_ignores_configured_windows_roots(self):
        rule = next(
            item
            for item in self.contracts["code"]["checks"]
            if item["id"] == "stale_state.local_path_references"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = pathlib.Path(temporary_directory)
            excluded = root / "excluded.py"
            excluded.write_text(
                "\n".join(
                    [
                        r'REPO = "C:\repo\fixture"',
                        r'REPOS = "C:\repos\project"',
                        r'PROGRAMS = "C:\Program Files\Git"',
                        r'PROGRAMS_X86 = "C:\Program Files (x86)\Tool"',
                        r'WINDOWS = "C:\WINDOWS\System32\tool.exe"',
                        r'PROJECTS = "c:\\CODEXPROJECTS\\repo"',
                        r'CODEX = "C:\Users\runner\.codex\skills"',
                    ]
                ),
                encoding="utf-8",
            )
            retained = root / "retained.py"
            retained.write_text(
                "\n".join(
                    [
                        r'NEAR_PREFIX = "C:\ReposBackup\project"',
                        r'OTHER_DRIVE_ROOT = "D:\work\project"',
                    ]
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ,
                {
                    "CODEX_HOME": r"C:\Users\runner\.codex",
                    "ProgramFiles": r"C:\Program Files",
                    "ProgramFiles(x86)": r"C:\Program Files (x86)",
                    "SystemRoot": r"C:\Windows",
                },
                clear=False,
            ):
                local = collect_local_repository(temporary_directory, [rule])
            self.assertEqual(
                local["scans"][rule["id"]]["matches"],
                [
                    {
                        "path": "retained.py",
                        "pattern": rule["collection"]["regex_patterns"][0],
                    }
                ],
            )

    def test_local_scan_uses_git_visible_file_inventory(self):
        rule = next(
            item
            for item in self.contracts["code"]["checks"]
            if item["id"] == "stale_state.local_path_references"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = pathlib.Path(temporary_directory)
            subprocess.run(
                ["git", "init", "--quiet", str(root)],
                check=True,
                capture_output=True,
            )
            (root / ".gitignore").write_text(
                "ignored/\nignored.txt\ntracked.txt\n", encoding="utf-8"
            )
            (root / "ignored").mkdir()
            (root / "ignored" / "nested.txt").write_text(
                r"D:\ignored", encoding="utf-8"
            )
            (root / "ignored.txt").write_text(r"D:\ignored", encoding="utf-8")
            (root / "visible.txt").write_text(r"D:\visible", encoding="utf-8")
            (root / "tracked.txt").write_text(r"D:\tracked", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(root), "add", "-f", "tracked.txt"],
                check=True,
                capture_output=True,
            )

            local = collect_local_repository(temporary_directory, [rule])

            self.assertNotIn("ignored.txt", local["files"])
            self.assertNotIn("ignored/nested.txt", local["files"])
            self.assertIn("visible.txt", local["files"])
            self.assertIn("tracked.txt", local["files"])
            self.assertEqual(
                local["scans"][rule["id"]]["matches"],
                [
                    {
                        "path": "tracked.txt",
                        "pattern": rule["collection"]["regex_patterns"][0],
                    },
                    {
                        "path": "visible.txt",
                        "pattern": rule["collection"]["regex_patterns"][0],
                    },
                ],
            )

    def test_local_scan_falls_back_when_git_inventory_fails(self):
        rule = next(
            item
            for item in self.contracts["code"]["checks"]
            if item["id"] == "stale_state.local_path_references"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = pathlib.Path(temporary_directory)
            (root / ".git").mkdir()
            (root / "visible.txt").write_text(r"D:\visible", encoding="utf-8")
            failed_inventory = subprocess.CompletedProcess(
                args=["git", "ls-files"],
                returncode=1,
                stdout=b"",
                stderr=b"blocked",
            )
            with mock.patch(
                "github_contract_engine.collectors.local_repository.subprocess.run",
                return_value=failed_inventory,
            ):
                local = collect_local_repository(temporary_directory, [rule])

            self.assertIn("visible.txt", local["files"])
            self.assertEqual(
                local["scans"][rule["id"]]["matches"],
                [
                    {
                        "path": "visible.txt",
                        "pattern": rule["collection"]["regex_patterns"][0],
                    }
                ],
            )
            self.assertEqual(
                local["errors"],
                ["git visible-file inventory failed: blocked"],
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
        compact_stream = io.StringIO()
        with contextlib.redirect_stdout(compact_stream):
            write_json(report, compact=True)
        compact_output = compact_stream.getvalue()
        self.assertNotIn("secret-value", compact_output)
        self.assertNotIn("private@example.com", compact_output)
        self.assertNotIn("hunter2", compact_output)
        self.assertNotIn("user:pass", compact_output)
        self.assertNotIn("gho_", compact_output)
        self.assertEqual(json.loads(compact_output), safe)

    def test_codeql_evidence_binds_alert_commit_trace_and_sanitized_output(self):
        commit = "a" * 40
        sentinel = "CODEQL_SENTINEL_token_value"
        alert = {
            "number": 42,
            "state": None,
            "tool": {"name": "CodeQL"},
            "rule": {"id": "py/clear-text-logging-sensitive-data"},
            "most_recent_instance": {
                "state": "open",
                "commit_sha": commit,
                "location": {
                    "path": "github_contract_engine/format_report.py",
                    "start_line": 126,
                },
            },
        }
        evidence = {
            "version": 1,
            "repository": "owner/repo",
            "alert_number": 42,
            "commit_sha": commit,
            "disposition": "suppression",
            "rule_id": "py/clear-text-logging-sensitive-data",
            "source_to_sink": {
                "exercised": True,
                "trace": [
                    {
                        "role": "source",
                        "path": "tests/test_gh_validator_summary.py",
                        "line": 1,
                    },
                    {
                        "role": "sink",
                        "path": "github_contract_engine/format_report.py",
                        "line": 126,
                    },
                ],
            },
            "execution": {
                "command": ["python", "-m", "unittest"],
                "exit_code": 0,
                "sentinel_credentials": {"token": sentinel},
                "captured_output": '{"token":"<redacted>"}',
            },
        }

        result = codeql_disposition.validate_evidence(
            evidence,
            alert,
            repository="owner/repo",
            alert_number=42,
            commit=commit,
            disposition="suppression",
        )
        self.assertTrue(result["sanitized"])
        self.assertEqual(result["sentinel_count"], 1)

        execution = evidence["execution"]
        self.assertIsInstance(execution, dict)
        if isinstance(execution, dict):
            execution["captured_output"] = sentinel
        with self.assertRaisesRegex(
            codeql_disposition.DispositionError, "still contains a sentinel"
        ):
            codeql_disposition.validate_evidence(
                evidence,
                alert,
                repository="owner/repo",
                alert_number=42,
                commit=commit,
                disposition="suppression",
            )
        alert_instance = alert["most_recent_instance"]
        self.assertIsInstance(alert_instance, dict)
        if isinstance(alert_instance, dict):
            alert_instance["state"] = "fixed"
        with self.assertRaisesRegex(
            codeql_disposition.DispositionError, "instance must still be open"
        ):
            codeql_disposition.validate_evidence(
                evidence,
                alert,
                repository="owner/repo",
                alert_number=42,
                commit=commit,
                disposition="suppression",
            )

    def test_codeql_dismissal_requires_explicit_authorization_before_patch(self):
        commit = "a" * 40
        alert = {
            "number": 42,
            "state": "open",
            "tool": {"name": "CodeQL"},
            "rule": {"id": "py/clear-text-logging-sensitive-data"},
            "most_recent_instance": {
                "state": "open",
                "commit_sha": commit,
                "location": {"path": "safe.py", "start_line": 10},
            },
        }
        evidence = {
            "version": 1,
            "repository": "owner/repo",
            "alert_number": 42,
            "commit_sha": commit,
            "disposition": "dismissal",
            "rule_id": "py/clear-text-logging-sensitive-data",
            "source_to_sink": {
                "exercised": True,
                "trace": [
                    {"role": "source", "path": "test_safe.py", "line": 5},
                    {"role": "sink", "path": "safe.py", "line": 10},
                ],
            },
            "execution": {
                "command": ["python", "-m", "unittest"],
                "exit_code": 0,
                "sentinel_credentials": {
                    "password": "CODEQL_SENTINEL_password_value"
                },
                "captured_output": '{"password":"<redacted>"}',
            },
        }
        args = argparse.Namespace(
            repo="owner/repo",
            alert_number=42,
            commit=commit,
            evidence=pathlib.Path("evidence.json"),
            action="dismissal",
            dismissed_reason="false positive",
            dismissed_comment="Validated sanitizer path.",
            authorize_dismissal=False,
        )
        with (
            mock.patch.object(codeql_disposition, "load_json", return_value=evidence),
            mock.patch.object(
                codeql_disposition, "fetch_alert", return_value=alert
            ),
            mock.patch.object(codeql_disposition, "run_gh_api") as patch_alert,
        ):
            pending = codeql_disposition.disposition(args)

        self.assertEqual(pending["status"], "authorization_required")
        self.assertFalse(pending["mutated"])
        patch_alert.assert_not_called()
        args.authorize_dismissal = True
        updated = json.loads(json.dumps(alert))
        updated["state"] = "dismissed"
        updated["dismissed_reason"] = "false positive"
        with (
            mock.patch.object(codeql_disposition, "load_json", return_value=evidence),
            mock.patch.object(
                codeql_disposition, "fetch_alert", return_value=alert
            ),
            mock.patch.object(
                codeql_disposition,
                "run_gh_api",
                return_value=ApiResult(
                    True,
                    "PATCH",
                    "/repos/owner/repo/code-scanning/alerts/42",
                    data=updated,
                ),
            ) as patch_alert,
        ):
            result = codeql_disposition.disposition(args)

        self.assertEqual(result["status"], "dismissed")
        self.assertTrue(result["mutated"])
        patch_alert.assert_called_once_with(
            "PATCH",
            "/repos/owner/repo/code-scanning/alerts/42",
            {
                "state": "dismissed",
                "dismissed_reason": "false positive",
                "dismissed_comment": "Validated sanitizer path.",
            },
        )

    def test_contract_entrypoints_use_sanitized_json_writer(self):
        entrypoints = (
            "codeql_disposition.py",
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

    def test_codex_review_uses_the_existing_github_api_client(self):
        text = (SCRIPTS / "github_pr_workflow" / "codex_review.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "from github_contract_engine.github_api import "
            "run_gh_graphql, run_json_command",
            text,
        )
        self.assertNotIn("subprocess.run", text)

    def test_pr_readiness_uses_graphql_rules_only(self):
        text = (SCRIPTS / "github_pr_workflow" / "readiness.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("run_gh_graphql", text)
        self.assertNotIn("/rules/branches/", text)
        self.assertNotIn("urllib.parse", text)

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

    def test_merge_settings_require_and_remediate_merge_commit_availability(
        self,
    ):
        rule = next(
            check
            for check in self.contracts["repo"]["checks"]
            if check["id"] == "repo.merge_settings"
        )
        assertion = next(
            item
            for item in rule["assertions"]
            if item["path"] == "/repository/repo/allow_merge_commit"
        )
        self.assertEqual(
            assertion,
            {
                "path": "/repository/repo/allow_merge_commit",
                "operator": "equal",
                "expected": True,
                "level": "WARN",
            },
        )

        with mock.patch(
            "github_contract_engine.remediations.repository.run_gh_api",
            return_value=ApiResult(
                True,
                "PATCH",
                "/repos/owner/repo",
                status=200,
            ),
        ) as update_repository:
            results = HANDLERS["repository.update_settings"](
                [
                    {
                        **rule,
                        "_mismatch_paths": [
                            "/repository/repo/allow_merge_commit"
                        ],
                    }
                ],
                {"owner": "owner", "repo": "repo"},
            )

        update_repository.assert_called_once_with(
            "PATCH",
            "/repos/owner/repo",
            {"allow_merge_commit": True},
        )
        self.assertTrue(results[0]["ok"])

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

    def test_pr_readiness_matches_github_check_conclusions(self):
        cases = {
            "SUCCESS": "PASS",
            "SKIPPED": "PASS",
            "NEUTRAL": "PASS",
            "FAILURE": "ERROR",
            "STARTUP_FAILURE": "ERROR",
        }
        for conclusion, expected_level in cases.items():
            with self.subTest(conclusion=conclusion):
                findings: list[pr_validator.Finding] = []
                pr_validator.status_rollup_findings(
                    {
                        "statusCheckRollup": [
                            {
                                "name": "CodeQL",
                                "status": "COMPLETED",
                                "conclusion": conclusion,
                            }
                        ]
                    },
                    findings,
                )
                self.assertEqual(findings[0].level, expected_level)

        pending: list[pr_validator.Finding] = []
        pr_validator.status_rollup_findings(
            {
                "statusCheckRollup": [
                    {
                        "name": "CodeQL",
                        "status": "IN_PROGRESS",
                        "conclusion": None,
                    }
                ]
            },
            pending,
        )
        self.assertEqual(pending[0].level, "WARN")

    def test_unparseable_status_rollup_is_an_error(self):
        malformed_rollups: tuple[object, ...] = (
            None,
            {},
            "",
            0,
            False,
            [None],
            [
                {
                    "name": "CI",
                    "status": "UNKNOWN",
                    "conclusion": None,
                }
            ],
            [
                {
                    "name": "CI",
                    "status": "COMPLETED",
                    "conclusion": None,
                }
            ],
        )
        for raw_rollup in malformed_rollups:
            with self.subTest(raw_rollup=raw_rollup):
                findings: list[pr_validator.Finding] = []
                pr_validator.status_rollup_findings(
                    {"statusCheckRollup": raw_rollup},
                    findings,
                )

                self.assertEqual(findings[0].level, "ERROR")

    def test_empty_review_decision_obeys_required_approval_rule(self):
        pr_data = {
            "number": 17,
            "url": "https://example.test/pr/17",
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "reviewDecision": "",
            "statusCheckRollup": [],
            "headRefName": "release/local",
            "headRefOid": "a" * 40,
            "baseRefName": "main",
            "autoMergeRequest": None,
        }
        with (
            mock.patch.object(pr_validator, "gh_pr_view", return_value=pr_data),
            mock.patch.object(
                pr_validator,
                "required_approving_review_count",
                return_value=1,
            ) as required_reviews,
        ):
            _, findings = pr_validator.pr_readiness(
                "17",
                pathlib.Path.cwd(),
                allow_admin_review_bypass=True,
            )

        review = next(
            finding
            for finding in findings
            if finding.check == "pr.review_decision"
        )
        self.assertEqual(review.level, "WARN")
        self.assertEqual(review.actual, "REVIEW_REQUIRED")
        required_reviews.assert_called_once_with("main", pathlib.Path.cwd())

    def test_pr_rule_graphql_paginates_exact_ref_and_aggregates_policies(self):
        cwd = pathlib.Path.cwd()
        classic = {
            "requiresApprovingReviews": True,
            "requiredApprovingReviewCount": 1,
            "requiresConversationResolution": False,
        }
        page_one = {
            "data": {
                "repository": {
                    "ref": {
                        "name": "release/1.x",
                        "branchProtectionRule": classic,
                        "rules": {
                            "nodes": [
                                {
                                    "type": "REQUIRED_STATUS_CHECKS",
                                    "parameters": {
                                        "__typename": "RequiredStatusChecksParameters"
                                    },
                                },
                                {
                                    "type": "PULL_REQUEST",
                                    "parameters": {
                                        "__typename": "PullRequestParameters",
                                        "requiredApprovingReviewCount": 2,
                                        "requiredReviewThreadResolution": False,
                                    },
                                },
                            ],
                            "pageInfo": {
                                "hasNextPage": True,
                                "endCursor": "cursor-1",
                            },
                        },
                    }
                }
            }
        }
        page_two = {
            "data": {
                "repository": {
                    "ref": {
                        "name": "release/1.x",
                        "branchProtectionRule": classic,
                        "rules": {
                            "nodes": [
                                {
                                    "type": "PULL_REQUEST",
                                    "parameters": {
                                        "__typename": "PullRequestParameters",
                                        "requiredApprovingReviewCount": 1,
                                        "requiredReviewThreadResolution": True,
                                    },
                                }
                            ],
                            "pageInfo": {
                                "hasNextPage": False,
                                "endCursor": "cursor-2",
                            },
                        },
                    }
                }
            }
        }
        with (
            mock.patch.object(
                pr_validator,
                "require_command",
                return_value=json.dumps({"nameWithOwner": "owner/repo"}),
            ) as repo_view,
            mock.patch.object(
                pr_validator,
                "run_gh_graphql",
                side_effect=[
                    ApiResult(
                        ok=True,
                        method="GRAPHQL",
                        endpoint="pull-request-rules",
                        data=page_one,
                    ),
                    ApiResult(
                        ok=True,
                        method="GRAPHQL",
                        endpoint="pull-request-rules",
                        data=page_two,
                    ),
                ],
            ) as graphql,
        ):
            parameters = pr_validator.pull_request_rule_parameters(
                "release/1.x", cwd
            )

        self.assertEqual(
            parameters,
            [
                {
                    "required_approving_review_count": 1,
                    "required_review_thread_resolution": False,
                },
                {
                    "required_approving_review_count": 2,
                    "required_review_thread_resolution": False,
                },
                {
                    "required_approving_review_count": 1,
                    "required_review_thread_resolution": True,
                },
            ],
        )
        repo_view.assert_called_once_with(
            ["gh", "repo", "view", "--json", "nameWithOwner"], cwd
        )
        self.assertEqual(graphql.call_count, 2)
        self.assertEqual(
            graphql.call_args_list[0].args[1],
            {
                "owner": "owner",
                "name": "repo",
                "qualifiedName": "refs/heads/release/1.x",
                "cursor": None,
            },
        )
        self.assertEqual(graphql.call_args_list[1].args[1]["cursor"], "cursor-1")
        with mock.patch.object(
            pr_validator,
            "pull_request_rule_parameters",
            return_value=parameters,
        ):
            self.assertEqual(
                pr_validator.required_approving_review_count("release/1.x", cwd),
                2,
            )
            self.assertTrue(
                pr_validator.review_thread_resolution_required(
                    "release/1.x", cwd
                )
            )

    def test_pr_rule_graphql_reports_no_policy_as_zero_requirements(self):
        cwd = pathlib.Path.cwd()
        response = {
            "data": {
                "repository": {
                    "ref": {
                        "name": "main",
                        "branchProtectionRule": None,
                        "rules": {
                            "nodes": [],
                            "pageInfo": {
                                "hasNextPage": False,
                                "endCursor": None,
                            },
                        },
                    }
                }
            }
        }
        with (
            mock.patch.object(
                pr_validator,
                "require_command",
                return_value=json.dumps({"nameWithOwner": "owner/repo"}),
            ),
            mock.patch.object(
                pr_validator,
                "run_gh_graphql",
                return_value=ApiResult(
                    ok=True,
                    method="GRAPHQL",
                    endpoint="pull-request-rules",
                    data=response,
                ),
            ),
        ):
            parameters = pr_validator.pull_request_rule_parameters("main", cwd)

        self.assertEqual(parameters, [])
        with mock.patch.object(
            pr_validator,
            "pull_request_rule_parameters",
            return_value=parameters,
        ):
            self.assertEqual(
                pr_validator.required_approving_review_count("main", cwd), 0
            )
            self.assertFalse(
                pr_validator.review_thread_resolution_required("main", cwd)
            )

    def test_pr_rule_graphql_fails_closed_on_api_error(self):
        with (
            mock.patch.object(
                pr_validator,
                "require_command",
                return_value=json.dumps({"nameWithOwner": "owner/repo"}),
            ),
            mock.patch.object(
                pr_validator,
                "run_gh_graphql",
                return_value=ApiResult(
                    ok=False,
                    method="GRAPHQL",
                    endpoint="pull-request-rules",
                    status=403,
                    message="forbidden",
                ),
            ),
            self.assertRaisesRegex(pr_validator.CommandError, "forbidden"),
        ):
            pr_validator.pull_request_rule_parameters(
                "main", pathlib.Path.cwd()
            )

    def test_pr_rule_graphql_fails_closed_when_pagination_does_not_advance(self):
        response = {
            "data": {
                "repository": {
                    "ref": {
                        "name": "main",
                        "branchProtectionRule": None,
                        "rules": {
                            "nodes": [],
                            "pageInfo": {
                                "hasNextPage": True,
                                "endCursor": None,
                            },
                        },
                    }
                }
            }
        }
        with (
            mock.patch.object(
                pr_validator,
                "require_command",
                return_value=json.dumps({"nameWithOwner": "owner/repo"}),
            ),
            mock.patch.object(
                pr_validator,
                "run_gh_graphql",
                return_value=ApiResult(
                    ok=True,
                    method="GRAPHQL",
                    endpoint="pull-request-rules",
                    data=response,
                ),
            ),
            self.assertRaisesRegex(
                pr_validator.CommandError, "pagination did not advance"
            ),
        ):
            pr_validator.pull_request_rule_parameters(
                "main", pathlib.Path.cwd()
            )

    def test_merge_helper_revalidates_after_review_wait(self):
        text = (SCRIPTS / "github_pr_workflow" / "merge.py").read_text(
            encoding="utf-8"
        )
        merge_section = text[text.index("def merge_pr(") :]
        readiness_call = "_validate_readiness("
        positions = [
            index
            for index in range(len(merge_section))
            if merge_section.startswith(readiness_call, index)
        ]
        self.assertEqual(len(positions), 2)
        wait_position = merge_section.index(
            "review = codex_review.wait_for_codex_threads("
        )
        self.assertLess(positions[0], wait_position)
        self.assertLess(wait_position, positions[1])
        self.assertLess(
            positions[1],
            merge_section.index(
                "return merge_verified_pr(args, expected_head=expected_head)"
            ),
        )
        self.assertIn('"--match-head-commit"', text)

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
