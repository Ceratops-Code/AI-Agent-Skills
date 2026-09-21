"""SDLC lifecycle boundaries, registered handoffs, and completion evidence."""
from __future__ import annotations

import importlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tomllib
from typing import Any

import pytest

from tests.repository_lifecycle.support import (
    REPOSITORY_LIFECYCLE_SCRIPTS,
    run_operation_cli,
)
from tests.support.processes import run_compatibility_engine
from tests.support.repositories import ROOT, run_ci_action, run_git

runner = importlib.import_module("repository_operation")
contracts = importlib.import_module("ceratops_repo_compatibility_engine.sdlc_contract_validation")


def _repository(repo: pathlib.Path) -> str:
    assert run_git(repo, "init", "-b", "main").returncode == 0
    assert run_git(repo, "config", "user.name", "Tests").returncode == 0
    assert (
        run_git(repo, "config", "user.email", "tests@example.invalid").returncode == 0
    )
    assert run_git(repo, "add", ".").returncode == 0
    assert run_git(repo, "commit", "-m", "fixture").returncode == 0
    return run_git(repo, "rev-parse", "HEAD").stdout.strip()


def test_compatibility_preserves_custom_unittest_runner_without_pytest(
    tmp_path: pathlib.Path,
) -> None:
    """An existing test runner owns its framework dependency declaration."""

    repo = tmp_path / "repository"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    (repo / ".git").write_text("gitdir: fixture\n", encoding="utf-8")
    (scripts / "pyproject.toml").write_text(
        "[project]\n"
        'name = "repository-tools"\n'
        'version = "0.0.0"\n'
        'requires-python = ">=3.11"\n'
        'dependencies = ["mypy", "ruff"]\n',
        encoding="utf-8",
    )
    runner = scripts / "run-tests.py"
    runner_text = "import unittest\n\nunittest.main(module=None)\n"
    runner.write_text(runner_text, encoding="utf-8")
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_example.py").write_text("import unittest\n", encoding="utf-8")

    result = run_compatibility_engine(
        REPOSITORY_LIFECYCLE_SCRIPTS,
        "apply",
        "--target-repo-root",
        str(repo),
    )

    assert result.returncode == 0, result.stdout
    assert runner.read_text(encoding="utf-8") == runner_text
    project = tomllib.loads((scripts / "pyproject.toml").read_text(encoding="utf-8"))
    assert "pytest" not in project["project"]["dependencies"]
    assert "scripts/run-tests.py" in (repo / "sdlc/sdlc.yml").read_text(
        encoding="utf-8"
    )



@pytest.mark.parametrize("mode", ["ci", "skill", "return"])
def test_v3_tests_gate_mutations_and_ci_never_dispatches_handoffs(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    """Real subprocess failure must stop the batch before a later mutation."""
    declaration = {
        "version": 3, "kind": "ceratops-sdlc",
        "repository": {"validate": {"structure": {"no-op": "No extra structural checks."}}},
        "deliverables": {"service": {
            "tests": {"unit": {"steps": [{"run": [sys.executable, "-c", "raise SystemExit(7)"]}]}},
            "validate": {"source": {"handoff": "example-skill/check"}},
            "deploy-local": {"local": {"steps": [{"run": [sys.executable, "-c", "raise AssertionError('must not deploy')"]}]}},
        }},
    }
    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(declaration))
    location = "deliverables.service.deploy-local.local"
    selected = runner.validation_operations(tmp_path, [location], ["repository.validate.structure"])
    assert "deliverables.service.tests.unit" in selected
    calls: list[str] = []

    def record_handoff(route: str, root: pathlib.Path) -> dict[str, str]:
        calls.append(route)
        return {"status": "completed"}

    monkeypatch.setattr(runner, "execute_handoff", record_handoff)
    handoff = runner.prepare_operations(tmp_path, [runner.OperationRequest("deliverables.service.validate.source")], context=mode)[0]
    result = runner.execute_prepared_operation(handoff)
    assert calls == (["example-skill/check"] if mode == "skill" else [])
    assert result["status"] == {"ci": "deferred_handoff", "skill": "completed", "return": "handoff_required"}[mode]
    prepared = runner.prepare_operations(tmp_path, [runner.OperationRequest(item) for item in selected] + [runner.OperationRequest(location)], context=mode)
    failed = runner.execute_prepared_operations(prepared)
    assert failed["status"] == ("handoff_required" if mode == "return" else "tests_failed")
    assert location in failed["pending_operations"]
    assert location not in failed["completed_operations"]


@pytest.mark.parametrize("failure", [None, "validation", "tests"])
def test_ci_action_runs_skill_engine_without_repository_copies(
    tmp_path: pathlib.Path, failure: str | None,
) -> None:
    repo = tmp_path / "repository with spaces"
    (repo / "sdlc").mkdir(parents=True)
    evidence = tmp_path / "failure evidence.json"
    evidence.write_text("previous failure")

    def command(name: str) -> dict[str, object]:
        program = ("from pathlib import Path; p=Path('order.txt'); "
                   f"p.write_text((p.read_text() if p.exists() else '') + {name!r} + chr(10)); "
                   f"raise SystemExit({7 if failure == name else 0})")
        return {"steps": [{"run": [sys.executable, "-c", program]}]}

    declaration = {"version": 3, "kind": "ceratops-sdlc",
                   "repository": {"validate": {"structure": command("validation")}},
                   "deliverables": {"service": {
                       "validate": {"source": {"handoff": "nonexistent-skill/check"}},
                       "tests": {"unit": command("tests")},
                   }}}
    (repo / "sdlc/sdlc.yml").write_text(json.dumps(declaration))
    result = run_ci_action(repo, evidence, tmp_path / "action checkout")
    assert result.returncode == (1 if failure else 0), result.stderr
    payload = json.loads(result.stderr if failure else result.stdout)
    if failure:
        assert json.loads(evidence.read_text()) == payload
        assert payload["status"] == ("validation_failed" if failure == "validation" else "tests_failed")
    else:
        assert not evidence.exists()
        assert payload["status"] == "completed"
    expected = "validation\n" if failure == "validation" else "validation\ntests\n"
    assert (repo / "order.txt").read_text() == expected
    if failure != "validation":
        handoff = next(item for item in payload["results"] if item.get("handoff"))
        assert handoff["status"] == "deferred_handoff"
    assert not (repo / "scripts/sdlc.py").exists()
    assert not (repo / "scripts/runtime").exists()


@pytest.mark.parametrize("tests", [None, {}, {"none": {"no-op": " "}}, {"unit": {"steps": [], "no-op": "ambiguous"}}])
def test_v3_requires_explicit_unambiguous_test_declarations(tests: object) -> None:
    deliverable = {} if tests is None else {"tests": tests}
    assert contracts.validation_errors({"version": 3, "kind": "ceratops-sdlc", "deliverables": {"service": deliverable}})
    assert not contracts.validation_errors({"version": 3, "kind": "ceratops-sdlc", "deliverables": {"service": {"tests": {"none": {"no-op": "No executable behavior."}}}}})


def _v4_action(*steps: dict[str, object]) -> dict[str, object]:
    return {"requires": {"capabilities": []}, "steps": list(steps)}


def _v4_fixture() -> dict[str, Any]:
    """Exercise package dependency records and separate lifecycle ownership."""

    return {
        "version": 4,
        "kind": "ceratops-sdlc",
        "repository": {
            "capabilities": {"uv": {"executable": "uv"}},
            "actions": {
                "validate": _v4_action({"run": [sys.executable, "-c", "pass"]}),
                "test": {"requires": {"capabilities": []}, "no-op": "No repository tests."},
            },
        },
        "deliverables": {
            "packages": {
                "core": {
                    "source": "packages/core", "project": "packages/core/pyproject.toml",
                    "prerequisites": [],
                    "artifact": {
                        "type": "python-wheel", "distribution": "core-tool",
                        "output-directory": "dist/core", "filename-pattern": "core_tool-*.whl",
                    },
                    "actions": {"build": _v4_action({"run": ["uv", "build", "packages/core"]})},
                },
                "claims": {
                    "source": "packages/claims", "project": "packages/claims/pyproject.toml",
                    "prerequisites": ["core"],
                    "artifact": {
                        "type": "python-wheel", "distribution": "claims-tool",
                        "output-directory": "dist/claims", "filename-pattern": "claims_tool-*.whl",
                    },
                    "actions": {"build": _v4_action({"run": ["uv", "build", "packages/claims"]})},
                },
            },
            "tools": {
                "insurance-claims-tool": {
                    "source": "packages/claims", "manifest": "packages/claims/tool.json",
                    "prerequisites": ["claims"],
                    "actions": {
                        "validate": {"requires": {"capabilities": []}, "no-op": "Package tests cover the tool."},
                        "install": _v4_action({"handoff": {
                            "lifecycle": "ceratops-tool-lifecycle", "action": "install",
                            "inputs": {"tool": "insurance-claims-tool"},
                        }}),
                    },
                },
            },
            "apps": {
                "claims-mobile": {
                    "source": "apps/claims", "manifest": "apps/claims/AndroidManifest.xml",
                    "prerequisites": ["claims"],
                    "actions": {
                        "validate": {"requires": {"capabilities": []}, "no-op": "Repository checks cover the app."},
                        "install": _v4_action({"run": [
                            sys.executable, "-c", "from pathlib import Path; Path('app-installed.txt').write_text('done')",
                        ]}),
                    },
                },
            },
            "skills": {
                "claims-catalog-invoice": {
                    "source": "skills/claims-catalog-invoice", "prerequisites": ["claims"],
                    "actions": {
                        "validate": _v4_action({"handoff": {
                            "lifecycle": "ceratops-skill-lifecycle", "action": "source-validate",
                            "inputs": {"skill": "claims-catalog-invoice"},
                        }}),
                        "install": _v4_action({"handoff": {
                            "lifecycle": "ceratops-skill-lifecycle", "action": "deploy",
                            "inputs": {"skill": "claims-catalog-invoice"},
                        }}),
                    },
                },
            },
        },
    }


def test_v4_template_and_typed_operation_index(tmp_path: pathlib.Path) -> None:
    template = (
        ROOT / "skills/ceratops-repo-lifecycle/references/templates/sdlc.v4.yml.tmpl"
    )
    path = tmp_path / "sdlc.yml"
    shutil.copyfile(template, path)
    document = contracts.load_contract(path)
    assert document["version"] == 4
    assert list(contracts.operation_entries(document)) == [
        "repository.actions.validate", "repository.actions.test",
    ]

    fixture = _v4_fixture()
    assert contracts.validation_errors(fixture) == []
    entries = contracts.operation_entries(fixture)
    assert set(entries) == {
        "repository.actions.validate", "repository.actions.test",
        "deliverables.packages.core.actions.build",
        "deliverables.packages.claims.actions.build",
        "deliverables.apps.claims-mobile.actions.validate",
        "deliverables.apps.claims-mobile.actions.install",
        "deliverables.tools.insurance-claims-tool.actions.validate",
        "deliverables.tools.insurance-claims-tool.actions.install",
        "deliverables.skills.claims-catalog-invoice.actions.validate",
        "deliverables.skills.claims-catalog-invoice.actions.install",
    }
    assert runner.operation_category("deliverables.packages.claims.actions.build") == "build"
    assert runner.operation_category("deliverables.apps.claims-mobile.actions.install") == "deploy-local"
    assert runner.operation_category("deliverables.tools.insurance-claims-tool.actions.install") == "deploy-local"
    with pytest.raises(runner.OperationError, match="Invalid SDLC operation location"):
        runner.operation_category("deliverables.skills.claims-catalog-invoice.actions.build")


def test_v4_prerequisites_are_exposed_without_build_or_install(tmp_path: pathlib.Path) -> None:
    fixture = _v4_fixture()
    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(fixture))
    _repository(tmp_path)
    (tmp_path / "uncommitted.txt").write_text("inspection must remain read-only")
    location = "deliverables.skills.claims-catalog-invoice.actions.install"
    prepared = runner.prepare_operations(tmp_path, [runner.OperationRequest(location)])[0]
    assert list(prepared.prerequisites["packages"]) == ["core", "claims"]
    assert prepared.prerequisites["packages"]["claims"]["action-locations"] == {
        "build": "deliverables.packages.claims.actions.build"
    }
    assert prepared.steps[0].handoff["action"] == "deploy"
    assert runner.validation_operations(tmp_path, [location]) == [
        "repository.actions.validate",
        "deliverables.skills.claims-catalog-invoice.actions.validate",
        "repository.actions.test",
    ]
    assert runner.validation_operations(tmp_path, [
        "deliverables.apps.claims-mobile.actions.install"
    ]) == [
        "repository.actions.validate",
        "deliverables.apps.claims-mobile.actions.validate",
        "repository.actions.test",
    ]
    assert runner.validation_operations(tmp_path, [
        "deliverables.tools.insurance-claims-tool.actions.install"
    ]) == [
        "repository.actions.validate",
        "deliverables.tools.insurance-claims-tool.actions.validate",
        "repository.actions.test",
    ]
    result = run_operation_cli(tmp_path, location, prepare_only=True)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert list(payload["prerequisites"]["packages"]) == ["core", "claims"]

    app_location = "deliverables.apps.claims-mobile.actions.install"
    app_prepared = runner.prepare_operations(
        tmp_path, [runner.OperationRequest(app_location)]
    )[0]
    assert list(app_prepared.prerequisites["packages"]) == ["core", "claims"]
    assert app_prepared.prerequisites["packages"]["claims"]["action-locations"] == {
        "build": "deliverables.packages.claims.actions.build"
    }


def test_v4_source_installed_tool_needs_no_package_artifact(tmp_path: pathlib.Path) -> None:
    fixture = _v4_fixture()
    tool = fixture["deliverables"]["tools"]["insurance-claims-tool"]
    tool["prerequisites"] = []
    assert contracts.validation_errors(fixture) == []

    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(fixture))
    _repository(tmp_path)
    location = "deliverables.tools.insurance-claims-tool.actions.install"
    prepared = runner.prepare_operations(tmp_path, [runner.OperationRequest(location)])[0]
    assert prepared.prerequisites["packages"] == {}
    assert prepared.steps[0].handoff["action"] == "install"
    assert not (tmp_path / "dist").exists()


def test_v4_tool_install_can_run_standalone_script(tmp_path: pathlib.Path) -> None:
    fixture = _v4_fixture()
    tool = fixture["deliverables"]["tools"]["insurance-claims-tool"]
    tool["actions"]["install"] = _v4_action({"run": [
        sys.executable, "-c", "from pathlib import Path; Path('installed.txt').write_text('done')",
    ]})
    assert contracts.validation_errors(fixture) == []
    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(fixture))
    prepared = runner.prepare_operations(tmp_path, [runner.OperationRequest(
        "deliverables.tools.insurance-claims-tool.actions.install",
    )])[0]
    result = runner.execute_prepared_operation(prepared)
    assert result["status"] == "completed"
    assert result["steps"] == [1]
    assert (tmp_path / "installed.txt").read_text() == "done"


def test_v4_app_install_can_run_standalone_script(tmp_path: pathlib.Path) -> None:
    fixture = _v4_fixture()
    assert contracts.validation_errors(fixture) == []
    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(fixture))
    prepared = runner.prepare_operations(tmp_path, [runner.OperationRequest(
        "deliverables.apps.claims-mobile.actions.install",
    )])[0]
    result = runner.execute_prepared_operation(prepared)
    assert result["status"] == "completed"
    assert result["steps"] == [1]
    assert (tmp_path / "app-installed.txt").read_text() == "done"


def test_v4_declared_operation_result_is_validated(tmp_path: pathlib.Path) -> None:
    fixture = _v4_fixture()
    action = fixture["deliverables"]["apps"]["claims-mobile"]["actions"]["install"]
    action["result-schema"] = "ceratops-deployment-result.v1"
    payload = {
        "schema": "ceratops-deployment-result.v1",
        "status": "passed",
        "target": "tablet:37111",
        "artifact": {
            "type": "android-apk",
            "path": "app/build/app.apk",
            "sha256": "0" * 64,
            "size": 1,
        },
    }
    action["steps"] = [{"run": [
        sys.executable, "-c", f"import json; print(json.dumps({payload!r}))",
    ]}]
    assert contracts.validation_errors(fixture) == []
    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(fixture))
    prepared = runner.prepare_operations(tmp_path, [runner.OperationRequest(
        "deliverables.apps.claims-mobile.actions.install",
    )])[0]
    assert prepared.result_schema == "ceratops-deployment-result.v1"
    result = runner.execute_prepared_operation(prepared)
    assert result["status"] == "completed"
    assert result["step_results"] == [{"step": 1, "result": payload}]


def test_v4_invalid_required_result_retains_completed_side_effect(
    tmp_path: pathlib.Path,
) -> None:
    fixture = _v4_fixture()
    action = fixture["deliverables"]["apps"]["claims-mobile"]["actions"]["install"]
    action["result-schema"] = "ceratops-deployment-result.v1"
    action["steps"] = [{"run": [
        sys.executable,
        "-c",
        "from pathlib import Path; Path('installed.txt').write_text('done'); print('{}')",
    ]}]
    assert contracts.validation_errors(fixture) == []
    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(fixture))
    prepared = runner.prepare_operations(tmp_path, [runner.OperationRequest(
        "deliverables.apps.claims-mobile.actions.install",
    )])[0]
    result = runner.execute_prepared_operation(prepared)
    assert result["status"] == "result_invalid"
    assert result["steps"] == [1]
    assert "Do not replay" in result["message"]
    assert (tmp_path / "installed.txt").read_text() == "done"


@pytest.mark.parametrize("mode", ["skill", "ci", "return"])
def test_v4_runs_commands_then_returns_structured_handoff(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "unregistered"))
    fixture = _v4_fixture()
    action = fixture["deliverables"]["skills"]["claims-catalog-invoice"]["actions"]["install"]
    action["steps"].insert(0, {"run": [
        sys.executable, "-c", "from pathlib import Path; Path('ran.txt').write_text('done')",
    ]})
    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(fixture))
    location = "deliverables.skills.claims-catalog-invoice.actions.install"
    prepared = runner.prepare_operations(
        tmp_path, [runner.OperationRequest(location)], context=mode,
    )[0]
    result = runner.execute_prepared_operation(prepared)
    assert result["steps"] == [1]
    assert result["status"] == ("deferred_handoff" if mode == "ci" else "handoff_required")
    assert result["handoff"] == {
        "lifecycle": "ceratops-skill-lifecycle", "action": "deploy",
        "inputs": {"skill": "claims-catalog-invoice"},
    }
    assert (tmp_path / "ran.txt").read_text() == "done"


def test_v4_package_build_waits_for_declared_test_gate(tmp_path: pathlib.Path) -> None:
    fixture = _v4_fixture()
    fixture["repository"]["actions"]["test"] = _v4_action({
        "run": [sys.executable, "-c", "raise SystemExit(7)"],
    })
    fixture["deliverables"]["packages"]["claims"]["actions"]["build"] = _v4_action({
        "run": [sys.executable, "-c", "from pathlib import Path; Path('built.txt').write_text('bad')"],
    })
    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(fixture))
    result = run_operation_cli(tmp_path, "deliverables.packages.claims.actions.build")
    assert result.returncode == 1
    assert json.loads(result.stderr)["status"] == "tests_failed"
    assert not (tmp_path / "built.txt").exists()


@pytest.mark.parametrize("change, expected", [
    (lambda x: x["deliverables"]["skills"]["claims-catalog-invoice"].update(
        prerequisites=["missing"]), "unknown package missing"),
    (lambda x: x["deliverables"]["packages"]["core"].update(
        prerequisites=["claims"]), "package prerequisite cycle"),
    (lambda x: x["deliverables"]["tools"]["insurance-claims-tool"]["actions"]["install"]["steps"][0]["handoff"].update(
        lifecycle="ceratops-skill-lifecycle"), "must hand off to ceratops-tool-lifecycle"),
    (lambda x: x["deliverables"]["tools"]["insurance-claims-tool"]["actions"].update(
        install={"requires": {"capabilities": []}, "no-op": "Cannot install without lifecycle."}),
     "must end with a handoff"),
    (lambda x: x["deliverables"]["skills"]["claims-catalog-invoice"]["actions"]["install"].update(
        steps=[{"handoff": {"lifecycle": "ceratops-skill-lifecycle", "action": "deploy", "inputs": {}}}, {"run": ["python"]}]),
     "handoff must be the single final step"),
    (lambda x: x["deliverables"]["packages"]["claims"]["artifact"].update(
        **{"filename-pattern": "../wrong.whl"}), "filename-pattern must be a filename pattern"),
    (lambda x: x["deliverables"]["tools"]["insurance-claims-tool"]["actions"]["install"]["steps"][0]["handoff"]["inputs"].update(
        **{"prerequisite-packages": ["core"]}), "prerequisite-packages differ from prerequisites"),
    (lambda x: x["repository"]["capabilities"]["uv"].update(
        **{"version-from": {"file": "folder\\tool.toml", "key": "project.version"}}),
     "capability uv version-from.file must be repository-relative"),
    (lambda x: x["repository"]["capabilities"]["uv"].update(
        version="1.0", channel="stable"), "multiple version authorities"),
    (lambda x: x["deliverables"]["apps"]["claims-mobile"]["actions"]["install"].update(
        **{"result-schema": "ceratops-build-result.v1"}),
     "result-schema must be ceratops-deployment-result.v1"),
    (lambda x: x["deliverables"]["skills"]["claims-catalog-invoice"]["actions"]["install"].update(
        **{"result-schema": "ceratops-deployment-result.v1"}),
     "result-schema requires a final run step"),
])
def test_v4_rejects_invalid_dependency_or_lifecycle_boundary(change, expected: str) -> None:
    fixture = _v4_fixture()
    change(fixture)
    assert any(expected in error for error in contracts.validation_errors(fixture))


@pytest.mark.parametrize("change", [
    lambda x: x["deliverables"]["apps"]["claims-mobile"]["actions"].update(
        build=_v4_action({"run": ["python"]})),
    lambda x: x["deliverables"]["tools"]["insurance-claims-tool"].update(package="claims"),
    lambda x: x["deliverables"]["tools"]["insurance-claims-tool"].update(prerequisites=["core", "claims"]),
    lambda x: x["deliverables"]["skills"]["claims-catalog-invoice"]["actions"]["install"].update(
        **{"no-op": "nothing to install"}),
    lambda x: x["deliverables"]["skills"]["claims-catalog-invoice"]["actions"]["install"]["steps"][0].update(
        run=["python"]),
    lambda x: x["deliverables"]["skills"]["claims-catalog-invoice"]["actions"].update(
        build=_v4_action({"run": ["python"]})),
])
def test_v4_schema_rejects_ambiguous_steps_or_wrong_deliverable_actions(change) -> None:
    fixture = _v4_fixture()
    change(fixture)
    assert contracts.validation_errors(fixture)


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is required for installed Python actions")
def test_registered_skill_executor_is_portable_and_failure_is_not_completion(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoffs = runner
    skill = tmp_path / "skills/example-skill"
    (skill / "references").mkdir(parents=True)
    (skill / "scripts").mkdir()
    python = tmp_path / "runtimes/ceratops/versions/test/.venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    created = subprocess.run([sys.executable, "-m", "venv", "--copies", str(python.parent.parent)], capture_output=True, text=True, check=False)
    assert created.returncode == 0, created.stderr
    assert not python.is_symlink()
    (skill / ".runtime-manifest.json").write_text(json.dumps({"python_runtime": str(python)}))
    script = skill / "probe.py"
    script.write_text("import pathlib, sys\npathlib.Path(sys.argv[1], 'called.txt').write_text('called')\nraise SystemExit(int(sys.argv[2]))\n")
    binding = skill / "references/action-executors.json"
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    repo = tmp_path / "repository"
    repo.mkdir()
    for code, expected in ((0, "completed"), (9, "operation_failed")):
        binding.write_text(json.dumps({"version": 1, "actions": {"check": {"run": ["{python}", "{skill_root}/probe.py", "{repo_root}", str(code)]}}}))
        assert handoffs.execute_handoff("example-skill/check", repo)["status"] == expected
        assert (repo / "called.txt").read_text() == "called"
    assert handoffs.execute_handoff("example-skill/unknown", repo)["status"] == "handoff_required"
    receipt = {"schema": "fixture.deployment.v1", "status": "deployed", "entities": ["one"]}
    script.write_text("import json\nprint(json.dumps(" + repr(receipt) + "))\n")
    binding.write_text(json.dumps({"version": 1, "actions": {"check": {"steps": [
        {"run": ["{python}", "{skill_root}/probe.py"]},
        {"run": [sys.executable, "-c", "raise SystemExit(7)"]},
    ]}}}))
    result = handoffs.execute_handoff("example-skill/check", repo)
    assert result["status"] == "operation_failed"
    assert result["steps"] == [1]
    assert result["step_results"] == [{"step": 1, "result": receipt}]
    (skill / ".runtime-manifest.json").unlink()
    assert handoffs.execute_handoff("example-skill/check", repo)["status"] == "handoff_required"


def test_registered_skill_executor_uses_installed_authorized_source_bundle(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoffs = runner
    codex_home = tmp_path / "codex"
    installed = codex_home / "skills" / "example-skill"
    source_repo = tmp_path / "repository"
    source = source_repo / "skills" / "example-skill"
    for root in (installed, source):
        (root / "references").mkdir(parents=True)
        (root / "scripts").mkdir()
    binding = {
        "version": 1,
        "actions": {
            "check": {
                "run": ["{python}", "{skill_root}/scripts/probe.py"]
            }
        },
    }
    encoded = json.dumps(binding)
    for root in (installed, source):
        (root / "references" / "action-executors.json").write_text(encoded)
        (root / "scripts" / "probe.py").write_text("print('OK')\n")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(handoffs.shutil, "which", lambda name: "uv" if name == "uv" else None)
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(handoffs.subprocess, "run", run)
    assert handoffs.execute_handoff("example-skill/check", source_repo)["status"] == "completed"
    assert pathlib.Path(calls[0][-1]).resolve() == (
        source / "scripts" / "probe.py"
    ).resolve()
    assert calls[0][0] == sys.executable

    changed_binding = json.loads(encoded)
    changed_binding["actions"]["check"]["run"].append("changed")
    (source / "references" / "action-executors.json").write_text(
        json.dumps(changed_binding)
    )
    result = handoffs.execute_handoff("example-skill/check", source_repo)
    assert result == {
        "status": "handoff_required",
        "handoff": "example-skill/check",
        "message": "Source skill executor binding differs from the installed authorization.",
    }
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [None, "candidate", "missing_manager"])
def test_tool_install_binding_uses_checkout_metadata_and_propagates_failures(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, failure: str | None,
) -> None:
    handoffs = runner
    skill = tmp_path / "skills/ceratops-tool-lifecycle/references"
    skill.mkdir(parents=True)
    shutil.copyfile(ROOT / "skills/ceratops-tool-lifecycle/references/action-executors.json", skill / "action-executors.json")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    repo = tmp_path / "repo with spaces & punctuation"
    repo.mkdir()
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if failure == "missing_manager":
            raise FileNotFoundError("manager launcher missing")
        return subprocess.CompletedProcess(argv, 7 if failure else 0, "OK\n", "candidate failed" if failure else "")

    monkeypatch.setattr(handoffs.subprocess, "run", run)
    result = handoffs.execute_handoff("ceratops-tool-lifecycle/install", repo)
    assert result["status"] == ("operation_failed" if failure else "completed")
    assert calls[0][0] == ["python", "-I", "-B",
                           "C:/AI-Agents-Tools/ceratops_tool_manager/bin/ceratops_tool_manager.py",
                           "install", "--source", str(repo)]
    assert calls[0][1]["cwd"] == repo
    assert not calls[0][1].get("shell", False)


def _registered_skill_fixture(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Use real subprocesses with fixture lifecycle CLIs that enforce selection."""
    repo = tmp_path / "source"
    source = repo / "skills/ceratops-skill-lifecycle"
    installed = tmp_path / "codex/skills/ceratops-skill-lifecycle"
    binding = (ROOT / "skills/ceratops-skill-lifecycle/references/action-executors.json").read_bytes()
    for skill in (source, installed):
        (skill / "references").mkdir(parents=True)
        (skill / "references/action-executors.json").write_bytes(binding)
    (source / "scripts/runtime").mkdir(parents=True)
    probe = """import argparse, json, pathlib, subprocess
parser = argparse.ArgumentParser()
parser.add_argument('--repo-root', type=pathlib.Path, required=True)
parser.add_argument('--mode')
parser.add_argument('--skill', required=True)
args = parser.parse_args()
with (args.repo_root / 'calls.jsonl').open('a') as stream:
    stream.write(json.dumps({'mode': args.mode, 'skill': args.skill}) + chr(10))
if args.mode is not None:
    assert args.mode == 'skill'
else:
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=args.repo_root, text=True).strip()
    print(json.dumps({'schema': 'ceratops-deployment-completion.v1',
        'producer': 'ceratops-skill-lifecycle/deploy', 'status': 'completed',
        'repo_root': str(args.repo_root), 'commit': commit,
        'install_root': str(args.repo_root.parent / 'installed'),
        'deployed': [args.skill], 'removed': [], 'transaction_id': 'a' * 32,
        'cleanup_debt': [], 'promotion': None}))
"""
    for script in ("scripts/skills-consistency-source-validator.py", "scripts/runtime/install-managed-skills.py"):
        (source / script).write_text(probe)
    fixture = _v4_fixture()
    skill = fixture["deliverables"]["skills"]["claims-catalog-invoice"]
    for action in skill["actions"].values():
        action["steps"][-1]["handoff"]["inputs"]["prerequisite-packages"] = ["claims"]
    (repo / "sdlc").mkdir()
    (repo / "sdlc/sdlc.yml").write_text(json.dumps(fixture))
    (repo / ".gitignore").write_text("calls.jsonl\nran.txt\n")
    _repository(repo)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    return repo


@pytest.mark.parametrize("mode", ["skill", "ci", "return"])
@pytest.mark.parametrize("action", ["validate", "install"])
def test_v4_registered_skill_handoff_preserves_selection_prerequisites_and_receipt(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, mode: str, action: str,
) -> None:
    repo = _registered_skill_fixture(tmp_path, monkeypatch)
    location = f"deliverables.skills.claims-catalog-invoice.actions.{action}"
    prepared = runner.prepare_operations(repo, [runner.OperationRequest(location)], context=mode)[0]
    result = runner.execute_prepared_operation(prepared)
    assert list(result["prerequisites"]["packages"]) == ["core", "claims"]
    if mode != "skill":
        assert result["status"] == ("deferred_handoff" if mode == "ci" else "handoff_required")
        assert not (repo / "calls.jsonl").exists()
        return
    assert result["status"] == "completed", result
    calls = [json.loads(line) for line in (repo / "calls.jsonl").read_text().splitlines()]
    expected: list[dict[str, str | None]] = [{"mode": "skill", "skill": "claims-catalog-invoice"}]
    if action == "install":
        expected.append({"mode": None, "skill": "claims-catalog-invoice"})
    assert calls == expected
    assert result["handoff_completed"] is True
    assert result["handoff_inputs"] == {"skill": "claims-catalog-invoice", "prerequisite-packages": ["claims"]}
    if action == "install":
        assert result["steps"] == [1, 2]
        assert result["step_results"][-1]["step"] == 2
        receipt = result["step_results"][-1]["result"]
        assert receipt["deployed"] == ["claims-catalog-invoice"]
        # The public finalizer must recognize the same completion protocol.
        import runpy

        from tests.repository_lifecycle.support import PROMOTE_REPOSITORY
        promote = runpy.run_path(str(PROMOTE_REPOSITORY))
        promote["_completed_deployment"]({"status": "ready", "head": prepared.commit,
            "operations": {"status": "completed", "pending_operations": [],
                "completed_operations": [location], "results": [result]}},
            prepared.commit, repo_root=repo)


@pytest.mark.parametrize("problem", ["unknown_input", "unknown_route", "changed_binding", "dirty_source", "head_changes"])
def test_v4_skill_handoff_rejects_unsafe_or_unhandled_work_before_deployment(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, problem: str,
) -> None:
    repo = _registered_skill_fixture(tmp_path, monkeypatch)
    location = "deliverables.skills.claims-catalog-invoice.actions.install"
    prepared = runner.prepare_operations(repo, [runner.OperationRequest(location)], context="skill")[0]
    if problem == "unknown_input":
        prepared.steps[-1].handoff["inputs"]["unexpected"] = "do-not-ignore"
    elif problem == "unknown_route":
        prepared.steps[-1].handoff["action"] = "unknown"
    elif problem == "changed_binding":
        binding = repo / "skills/ceratops-skill-lifecycle/references/action-executors.json"
        binding.write_bytes(binding.read_bytes() + b"\n")
        run_git(repo, "add", ".")
        run_git(repo, "commit", "-m", "Different source authorization")
        prepared = runner.prepare_operations(repo, [runner.OperationRequest(location)], context="skill")[0]
    elif problem == "dirty_source":
        (repo / "uncommitted.txt").write_text("must not deploy")
    else:
        original = runner.subprocess.run
        def changing(argv, **kwargs):
            result = original(argv, **kwargs)
            if any(str(part).endswith("skills-consistency-source-validator.py") for part in argv):
                original(["git", "commit", "--allow-empty", "-m", "Concurrent change"], cwd=repo, capture_output=True, check=True)
            return result
        monkeypatch.setattr(runner.subprocess, "run", changing)
    result = runner.execute_prepared_operation(prepared)
    assert result["status"] == ("state_changed" if problem in {"dirty_source", "head_changes"} else "handoff_required"), result
    calls = (repo / "calls.jsonl")
    if calls.exists():
        assert [json.loads(line)["mode"] for line in calls.read_text().splitlines()] == ["skill"]


def test_completed_handoff_record_survives_removed_result_directory(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """An output directory removed during delivery must not require replay."""
    import runpy

    from tests.repository_lifecycle.support import PROMOTE_REPOSITORY
    module = runpy.run_path(str(PROMOTE_REPOSITORY))
    namespace = module["main"].__globals__
    result_file = tmp_path / "records/promotion.json"
    result = {"status": "ready", "head": "a" * 40, "operations": {"status": "completed"}}
    calls = []
    def promote(args, *, timings):
        assert result_file.parent.is_dir()
        result_file.parent.rmdir()
        calls.append("completed")
        return result
    monkeypatch.setitem(namespace, "promote", promote)
    assert module["main"](["--repo-root", str(tmp_path / "repo"), "--result-file", str(result_file), "--no-run-operation"]) == 0
    assert calls == ["completed"]
    assert json.loads(result_file.read_text()) == json.loads(capsys.readouterr().out)
    assert not list(result_file.parent.glob("*.tmp"))
