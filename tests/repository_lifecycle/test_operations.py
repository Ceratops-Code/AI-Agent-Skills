from __future__ import annotations

import importlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

from tests.repository_lifecycle.support import (
    OPERATION_RUNNER,
    SDLC_CONTRACT_TEMPLATE,
    run_operation_cli,
)
from tests.support.repositories import (
    ROOT,
    prepare_script_environment,
    run_ci_action,
    run_git,
    write_sdlc_contract,
)

runner = importlib.import_module("repository_operation")
contracts = importlib.import_module(
    "ceratops_repo_compatibility_engine.sdlc_contract_validation"
)

DEPLOY = "deliverables.sample.deploy-local."
CHECK = "repository.validate."
RECEIPT = {
    "schema": "codex-verified-runtime-deploy-receipt.v1",
    "status": "OK",
    "sourceCommit": "3555d719be3a4312a7bf1d0dbc0146b51355dee7",
    "generation": "verified-generation",
    "appliedPatchCount": 3,
    "suppressedPatchCount": 1,
    "installedSync": "Passed",
    "launcher": "Passed",
    "activeGeneration": "running-generation",
    "activeGenerationUnchanged": True,
}


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


def _v4_fixture() -> dict[str, object]:
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
        "deliverables.tools.insurance-claims-tool.actions.validate",
        "deliverables.tools.insurance-claims-tool.actions.install",
        "deliverables.skills.claims-catalog-invoice.actions.validate",
        "deliverables.skills.claims-catalog-invoice.actions.install",
    }
    assert runner.operation_category("deliverables.packages.claims.actions.build") == "build"
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


@pytest.mark.parametrize("mode", ["skill", "ci", "return"])
def test_v4_runs_commands_then_returns_structured_handoff(
    tmp_path: pathlib.Path, mode: str,
) -> None:
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
])
def test_v4_rejects_invalid_dependency_or_lifecycle_boundary(change, expected: str) -> None:
    fixture = _v4_fixture()
    change(fixture)
    assert any(expected in error for error in contracts.validation_errors(fixture))


@pytest.mark.parametrize("change", [
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


def test_registered_skill_executor_is_portable_and_failure_is_not_completion(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoffs = importlib.import_module("sdlc_handoffs")
    skill = tmp_path / "skills/example-skill"
    (skill / "references").mkdir(parents=True)
    (skill / "scripts").mkdir()
    shutil.copyfile(ROOT / "skills/sections/scripts/run-skill.py", skill / "scripts/run-skill.py")
    shutil.copytree(ROOT / "skills/sections/python", skill / "scripts/python-runtime")
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
    (skill / "scripts/run-skill.py").unlink()
    assert handoffs.execute_handoff("example-skill/check", repo)["status"] == "handoff_required"


def test_registered_skill_executor_uses_installed_authorized_source_bundle(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoffs = importlib.import_module("sdlc_handoffs")
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
    (installed / "scripts" / "run-skill.py").write_text("# launcher\n")
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
    assert str(installed / "scripts" / "run-skill.py") not in calls[0]

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
    handoffs = importlib.import_module("sdlc_handoffs")
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


def test_live_sdlc_v3_selects_validation_and_tests_for_every_deploy() -> None:
    document = contracts.load_contract(ROOT / "sdlc/sdlc.yml")
    assert document["version"] == 3
    for deliverable in ("skills", "hooks", "tools"):
        locations = runner.validation_operations(ROOT, [f"deliverables.{deliverable}.deploy-local.standalone"])
        assert "repository.validate.repository" in locations
        assert "repository.tests.python" in locations
        assert f"deliverables.{deliverable}.tests.repository" in locations
    requests = [runner.OperationRequest("repository.validate.repository"),
                runner.OperationRequest("repository.tests.python")]
    operations = runner.prepare_operations(ROOT, requests, context="ci")
    assert operations[0].steps[0].argv == ("uv", "run", "--locked", "scripts/validate-repository.py")
    assert operations[1].steps[0].argv == ("uv", "run", "--locked", "scripts/testing/run-tests.py", "--auto")


def _step(script: str, *arguments: str) -> dict[str, object]:
    return {"steps": [{"run": [sys.executable, script, *arguments]}]}


def _repository(repo: pathlib.Path) -> str:
    assert run_git(repo, "init", "-b", "main").returncode == 0
    assert run_git(repo, "config", "user.name", "Tests").returncode == 0
    assert (
        run_git(repo, "config", "user.email", "tests@example.invalid").returncode == 0
    )
    assert run_git(repo, "add", ".").returncode == 0
    assert run_git(repo, "commit", "-m", "fixture").returncode == 0
    return run_git(repo, "rev-parse", "HEAD").stdout.strip()


def test_sdlc_template_is_a_schema_valid_empty_skeleton(tmp_path: pathlib.Path) -> None:
    contract = write_sdlc_contract(tmp_path)
    shutil.copy2(SDLC_CONTRACT_TEMPLATE, contract)
    document = contracts.load_contract(contract)
    assert document["version"] == 3
    assert document["repository"]["validate"]["repository"]["steps"] == [
        {"run": ["uv", "run", "--locked", "scripts/validate-repository.py"]}
    ]
    assert "deliverables" not in document
    live = contracts.load_contract(ROOT / "sdlc" / "sdlc.yml")
    assert live["version"] == 3
    entries = contracts.operation_entries(live)
    expected = {
        "deliverables.skills.validate.ceratops-managed":
            "ceratops-skill-lifecycle/source-validate",
        "deliverables.skills.deploy-local.ceratops-managed":
            "ceratops-skill-lifecycle/deploy",
        "deliverables.tools.deploy-local.ceratops-managed":
            "ceratops-tool-lifecycle/install",
    }
    for location, handoff in expected.items():
        assert entries[location] == {"handoff": handoff}
    assert set(live["deliverables"]["skills"]["validate"]) == {"ceratops-managed"}
    selection = entries["repository.test-selection.ci"]
    assert selection["parameters"] == ["base", "head"]
    assert selection["steps"][0]["run"] == [
        "uv", "run", "--locked", "scripts/testing/run-tests.py", "--select-only",
        "--base", "{base}", "--head", "{head}",
    ]
    assert entries["repository.validate.repository"]["steps"] == [
        {"run": ["uv", "run", "--locked", "scripts/validate-repository.py"]},
    ]
    assert entries["repository.tests.python"]["steps"] == [
        {
            "run": [
                "uv", "run", "--locked", "scripts/testing/run-tests.py", "--auto",
            ]
        },
    ]
    assert runner.validation_operations(ROOT) == [
        "repository.validate.repository",
        "deliverables.skills.validate.ceratops-managed",
        "repository.tests.python",
        "deliverables.skills.tests.repository",
        "deliverables.hooks.tests.repository",
        "deliverables.tools.tests.repository",
    ]


def test_absent_sdlc_section_is_a_successful_no_op(tmp_path: pathlib.Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(OPERATION_RUNNER),
            "--repo-root",
            str(tmp_path),
            "--validate",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["results"] == []
    write_sdlc_contract(tmp_path, repository={})
    missing = run_operation_cli(tmp_path, DEPLOY + "missing")
    assert missing.returncode == 1
    optional = run_operation_cli(tmp_path, DEPLOY + "missing", if_declared=True)
    assert optional.returncode == 0, optional.stderr
    assert json.loads(optional.stdout)["results"][0]["status"] == "no_op"


def test_deploy_operation_preserves_argv_without_a_shell(
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / "argv.py").write_text(
        "import json, pathlib, sys\n"
        "pathlib.Path('argv.json').write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n",
        encoding="utf-8",
    )
    literal = "literal; echo injected > injected.txt"
    operation = _step("argv.py", "value with spaces", literal)
    operation["handoff"] = "ceratops-skill-lifecycle/deploy"
    write_sdlc_contract(
        tmp_path,
        deliverables={
            "sample": {
                "deploy-local": {"standalone": operation},
                "publish": {"public": operation},
            }
        },
    )
    for name in (DEPLOY + "standalone", "deliverables.sample.publish.public"):
        result = run_operation_cli(tmp_path, name)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["results"][0]["status"] == "completed"
        assert payload["results"][0]["handoff"] == "ceratops-skill-lifecycle/deploy"
        assert json.loads((tmp_path / "argv.json").read_text()) == [
            "value with spaces",
            literal,
        ]
        assert not (tmp_path / "injected.txt").exists()


def test_deploy_operation_requires_and_expands_exact_declared_parameters(
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / "parameter.py").write_text(
        "import pathlib, sys\npathlib.Path('value.txt').write_text(sys.argv[1])\n",
        encoding="utf-8",
    )
    strict = {
        **_step("parameter.py", "{base_revision}"),
        "parameters": ["base_revision"],
    }
    write_sdlc_contract(
        tmp_path,
        deliverables={
            "sample": {
                "deploy-local": {
                    "strict": strict,
                    "plain": _step("parameter.py", "literal"),
                }
            }
        },
    )
    for parameters, conditional, message in (
        ((), (), "missing base_revision"),
        (("base_revision=x", "unexpected=x"), (), "unexpected unexpected"),
        (("base_revision=x",), ("base_revision=y",), "supplied more than once"),
        (("base_revision=x", "base_revision=y"), (), "Duplicate"),
    ):
        result = run_operation_cli(
            tmp_path,
            DEPLOY + "strict",
            parameters=parameters,
            parameters_if_declared=conditional,
        )
        assert result.returncode == 1
        assert message in json.loads(result.stderr)["message"]
    result = run_operation_cli(
        tmp_path,
        DEPLOY + "strict",
        parameters_if_declared=("base_revision=a b;literal",),
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "value.txt").read_text() == "a b;literal"
    result = run_operation_cli(
        tmp_path, DEPLOY + "plain", parameters=("base_revision=x",)
    )
    assert result.returncode == 1
    result = run_operation_cli(
        tmp_path, DEPLOY + "plain", parameters_if_declared=("base_revision=x",)
    )
    assert result.returncode == 0
    assert (tmp_path / "value.txt").read_text() == "literal"


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        (json.dumps(RECEIPT, indent=2), {"result": RECEIPT}),
        (json.dumps(RECEIPT) + " " * (65536 - len(json.dumps(RECEIPT))),
         {"result": RECEIPT}),
        (json.dumps({**RECEIPT, "status": "FAILED"}),
         {"result": {**RECEIPT, "status": "FAILED"}}),
        ("", {}),
        ("ordinary private log", {}),
        ("ordinary private log\n" + json.dumps(RECEIPT), {}),
        (json.dumps(RECEIPT) + "\nordinary private log", {}),
        (json.dumps(RECEIPT) + "\n" + json.dumps(RECEIPT), {}),
        (json.dumps([RECEIPT]), {}),
        (json.dumps("OK"), {}),
        ('{"status":"OK","private":"unrelated JSON"}', {}),
        ('{"schema":"test.v1","status":true}', {}),
        ('{"schema":" ","status":"OK"}', {}),
        ('{"schema":"test.v1","status":"OK","nested":{"x":1,"x":2}}', {}),
        ('{"schema":"test.v1","status":"OK","value":NaN}', {}),
        ('{"schema":"test.v1","status":"OK","value":1e999}', {}),
        ('{"schema":"test.v1","status":"OK","value":' + '[' * 1100
         + '0' + ']' * 1100 + '}', {}),
        (json.dumps({**RECEIPT, "data": "x" * 65536}),
         {"result_omitted": "stdout_limit"}),
        (json.dumps({**RECEIPT, "data": "\u05d0" * 33000}, ensure_ascii=False),
         {"result_omitted": "stdout_limit"}),
    ],
    ids=["receipt", "size-boundary", "domain-failure", "empty", "text", "log-prefix", "log-suffix",
         "multiple-documents", "array", "scalar", "unrelated-json", "invalid-status",
         "blank-schema", "duplicate-member", "nan", "infinity", "deep-json",
         "oversized", "utf8-size"],
)
def test_deploy_runs_repository_command_once_from_repository_directory(
    tmp_path: pathlib.Path,
    stdout: str,
    expected: dict[str, object],
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (repo / "unrelated-name.py").write_text(
        "import pathlib, sys\n"
        "with pathlib.Path('count.txt').open('a') as out: out.write('ran\\n')\n"
        f"sys.stdout.buffer.write({stdout.encode('utf-8')!r})\n"
        "print('unrelated private stderr', file=sys.stderr)\n",
        encoding="utf-8",
    )
    write_sdlc_contract(
        repo,
        deliverables={
            "sample": {
                "deploy-local": {
                    "standalone": _step("unrelated-name.py"),
                }
            }
        },
    )
    result = subprocess.run(
        [
            sys.executable,
            str(OPERATION_RUNNER),
            "--repo-root",
            str(repo),
            "--operation",
            DEPLOY + "standalone",
        ],
        cwd=elsewhere,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (repo / "count.txt").read_text() == "ran\n"
    payload = json.loads(result.stdout)
    assert payload["status"] == "completed"
    operation = payload["results"][0]
    assert operation["operation"] == DEPLOY + "standalone"
    assert operation["status"] == "completed"
    assert operation["steps"] == [1]
    assert operation.get("step_results", []) == (
        [{"step": 1, **expected}] if expected else []
    )
    assert "private" not in result.stdout
    assert not result.stderr


@pytest.mark.parametrize(
    "invalid",
    [
        {"version": 3, "kind": "ceratops-sdlc", "deploy": {"operations": {}}},
        {
            "version": 2,
            "kind": "ceratops-sdlc",
            "repository": {
                "validate": {
                    "bad": {"steps": [{"run": "python -V"}]},
                }
            },
        },
        {
            "version": 2,
            "kind": "ceratops-sdlc",
            "repository": {
                "bootstrap": {
                    "runtime": {
                        "prerequisites": ["missing"],
                        "steps": [{"run": ["python", "-V"]}],
                    },
                }
            },
        },
        {
            "version": 2,
            "kind": "ceratops-sdlc",
            "repository": {
                "prerequisites": {
                    "python": {
                        "executable": "python",
                        "version-from": {"file": "../outside.toml", "key": "x"},
                    },
                }
            },
        },
    ],
)
def test_deploy_operation_rejects_invalid_schema(invalid: dict[str, object]) -> None:
    assert contracts.validation_errors(invalid)


def test_prepare_operations_validates_the_whole_sequence_before_execution(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    write_sdlc_contract(
        repo,
        deliverables={
            "sample": {
                "deploy-local": {
                    "first": _step(
                        "-c", "import pathlib; pathlib.Path('marker').touch()"
                    ),
                    "escape": {
                        "steps": [{"run": [sys.executable, "-V"], "cwd": "../outside"}]
                    },
                }
            }
        },
    )
    with pytest.raises(
        runner.OperationError, match="step cwd must be a directory inside"
    ):
        runner.prepare_operations(
            repo,
            [
                runner.OperationRequest(DEPLOY + "first"),
                runner.OperationRequest(DEPLOY + "escape"),
            ],
        )
    result = run_operation_cli(repo, (DEPLOY + "first", DEPLOY + "escape"))
    assert result.returncode == 1
    assert not (repo / "marker").exists()
    escaped = run_operation_cli(repo, DEPLOY + "first", contract=outside / "sdlc.yml")
    assert escaped.returncode == 1
    assert "inside the repository" in escaped.stderr


def test_operation_cli_prevalidates_and_runs_explicit_ids_in_order(
    tmp_path: pathlib.Path,
) -> None:
    for script in ("a-different-check.py", "deploy-other.py", "publish-other.py"):
        (tmp_path / script).write_text(
            "import pathlib, sys\nwith pathlib.Path('order.txt').open('a') as out: out.write(sys.argv[1] + '\\n')\n",
            encoding="utf-8",
        )
    write_sdlc_contract(
        tmp_path,
        repository={
            "validate": {
                "one": _step("a-different-check.py", "check-one"),
                "two": _step("a-different-check.py", "check-two"),
            }
        },
        deliverables={
            "sample": {
                "deploy-local": {"local": _step("deploy-other.py", "deployment")},
                "publish": {"public": _step("publish-other.py", "publication")},
            }
        },
    )
    names = (DEPLOY + "local", "deliverables.sample.publish.public", DEPLOY + "local")
    prepared = run_operation_cli(tmp_path, names, prepare_only=True)
    assert prepared.returncode == 0, prepared.stderr
    assert not (tmp_path / "order.txt").exists()
    result = run_operation_cli(tmp_path, names)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "order.txt").read_text().splitlines() == [
        "check-one",
        "check-two",
        "deployment",
        "publication",
        "deployment",
    ]
    assert json.loads(result.stdout)["completed_operations"] == list(names)


@pytest.mark.parametrize("structured", [False, True])
def test_execute_prepared_operations_stops_after_failure_with_a_ledger(
    tmp_path: pathlib.Path,
    structured: bool,
) -> None:
    failure_stdout = {
        "noise": "x" * 10000, "check": "configuration", "exit_code": 7,
        "evidence_file": str(tmp_path / "failure.log"),
    }
    failure_stderr = {
        "schema": "example.failure.v1", "status": "error",
        "message": "Required configuration is missing",
    }
    (tmp_path / "check.py").write_text(
        ("import pathlib, sys\n"
         "if pathlib.Path('fixed').exists(): raise SystemExit(0)\n"
         f"print({json.dumps(failure_stdout)!r})\n"
         f"print({json.dumps(failure_stderr)!r}, file=sys.stderr)\n"
         "raise SystemExit(7)\n")
        if structured else
        "import pathlib, sys\n"
        "print('x' * 10000)\n"
        "for i in range(12): print(f'line-{i}', file=sys.stderr)\n"
        "raise SystemExit(0 if pathlib.Path('fixed').exists() else 7)\n",
        encoding="utf-8",
    )
    write_sdlc_contract(
        tmp_path,
        repository={"validate": {"repository": {"steps": [
            {"run": [sys.executable, "-c", f"print({json.dumps(RECEIPT)!r})"]},
            {"run": [sys.executable, "check.py"]},
        ]}}},
        deliverables={
            "sample": {
                "deploy-local": {
                    "local": _step(
                        "-c", "import pathlib; pathlib.Path('deployed').touch()"
                    ),
                }
            }
        },
    )
    commit = _repository(tmp_path)
    failure = run_operation_cli(tmp_path, (CHECK + "repository", DEPLOY + "local"))
    assert failure.returncode == 1
    evidence = json.loads(failure.stderr)
    assert evidence["status"] == "validation_failed"
    assert evidence["operation"] == CHECK + "repository"
    assert evidence["commit"] == commit
    assert evidence["diagnostic"]["exit_code"] == 7
    assert evidence["steps"] == [1]
    assert evidence["step_results"] == [{"step": 1, "result": RECEIPT}]
    if structured:
        assert evidence["diagnostic"]["child_results"] == {
            "stdout": {"result": failure_stdout}, "stderr": {"result": failure_stderr},
        }
        assert "Required configuration is missing" in evidence["diagnostic"]["message"]
        assert "failure.log" in evidence["diagnostic"]["message"]
    else:
        assert evidence["diagnostic"]["stderr_tail"] == [f"line-{i}" for i in range(4, 12)]
        assert "child_results" not in evidence["diagnostic"]
    assert len("".join(evidence["diagnostic"]["stdout_tail"])) <= 4096
    assert not (tmp_path / "deployed").exists()
    (tmp_path / "fixed").touch()
    assert run_git(tmp_path, "add", "fixed").returncode == 0
    assert run_git(tmp_path, "commit", "-m", "repair").returncode == 0
    repaired = run_operation_cli(tmp_path, (CHECK + "repository", DEPLOY + "local"))
    assert repaired.returncode == 0, repaired.stderr
    assert len(repaired.stdout) < 2500
    assert "line-" not in repaired.stdout and "xxxx" not in repaired.stdout
    assert (tmp_path / "deployed").exists()


def test_prepared_results_cannot_authorize_a_new_commit(tmp_path: pathlib.Path) -> None:
    write_sdlc_contract(
        tmp_path,
        deliverables={
            "sample": {
                "deploy-local": {
                    "local": _step(
                        "-c", "import pathlib; pathlib.Path('deployed').touch()"
                    ),
                }
            }
        },
    )
    _repository(tmp_path)
    prepared = runner.prepare_operations(
        tmp_path, [runner.OperationRequest(DEPLOY + "local")]
    )
    (tmp_path / "repair").touch()
    assert run_git(tmp_path, "add", "repair").returncode == 0
    assert run_git(tmp_path, "commit", "-m", "new commit").returncode == 0
    assert runner.execute_prepared_operations(prepared)["status"] == "state_changed"
    assert not (tmp_path / "deployed").exists()


def test_bootstrap_and_advisory_handoffs_need_no_skill_runtime(
    tmp_path: pathlib.Path,
) -> None:
    write_sdlc_contract(
        tmp_path,
        repository={
            "prerequisites": {
                "python": {
                    "executable": "not-an-installed-command",
                    "version-from": {
                        "file": "pyproject.toml",
                        "key": "project.requires-python",
                    },
                }
            },
            "bootstrap": {
                "runtime": {
                    **_step("-c", "print('setup')"),
                    "prerequisites": ["python"],
                }
            },
        },
        deliverables={
            "skills": {
                "validate": {
                    "ceratops-managed": {
                        "handoff": "ceratops-skill-lifecycle/source-validate"
                    }
                },
                "deploy-local": {
                    "ceratops-managed": {"handoff": "ceratops-skill-lifecycle/deploy"}
                },
            },
            "tools": {
                "validate": {"custom-check": {"handoff": "target-owned/check"}},
                "deploy-local": {
                    "ceratops-managed": {"handoff": "ceratops-tool-lifecycle/install"}
                },
                "publish": {
                    "workflow": {
                        "handoff": "GitHub workflow .github/workflows/publish.yml"
                    }
                },
            }
        },
    )
    result = run_operation_cli(
        tmp_path, "repository.bootstrap.runtime", prepare_only=True
    )
    assert result.returncode == 0, result.stderr
    assert "python" in json.loads(result.stdout)["prerequisites"]
    result = run_operation_cli(tmp_path, "repository.bootstrap.runtime")
    assert result.returncode == 0, result.stderr
    source_check = "deliverables.skills.validate.ceratops-managed"
    tool_check = "deliverables.tools.validate.custom-check"
    for name, check, handoff in (
        ("deliverables.skills.deploy-local.ceratops-managed", source_check,
         "ceratops-skill-lifecycle/source-validate"),
        ("deliverables.tools.deploy-local.ceratops-managed", tool_check,
         "target-owned/check"),
        ("deliverables.tools.publish.workflow", tool_check, "target-owned/check"),
    ):
        assert runner.validation_operations(tmp_path, [name]) == [check]
        assert runner.validation_operations(tmp_path, [name], [source_check]) == [
            source_check
        ]
        result = run_operation_cli(tmp_path, name)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["results"][0]["status"] == "advisory"
        assert payload["results"][0]["handoff"]
        expected_handoffs: list[dict[str, object]] = [{
            "operation": check, "commit": None, "steps": [],
            "status": "advisory", "handoff": handoff,
        }]
        assert payload.get("validation_handoffs", []) == (expected_handoffs if ".publish." in name else [])
    result = run_operation_cli(tmp_path, source_check)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["results"][0]["status"] == "advisory"


def test_duplicate_yaml_operations_are_rejected_before_execution(
    tmp_path: pathlib.Path,
) -> None:
    contract = write_sdlc_contract(tmp_path)
    contract.write_text(
        "version: 2\nkind: ceratops-sdlc\nrepository:\n  validate:\n"
        "    same:\n      steps:\n        - run: [python, -V]\n"
        "    same:\n      handoff: other\n",
        encoding="utf-8",
    )
    result = run_operation_cli(tmp_path, "repository.validate.same")
    assert result.returncode == 1
    assert "unique strings" in result.stderr


def test_each_action_can_select_a_different_validation_script(
    tmp_path: pathlib.Path,
) -> None:
    for stage in ("promotion", "deployment", "shipment"):
        (tmp_path / f"{stage}.py").write_text(
            "import pathlib\n"
            f"with pathlib.Path('checks.txt').open('a') as out: out.write({stage!r} + '\\n')\n",
            encoding="utf-8",
        )
    write_sdlc_contract(
        tmp_path,
        repository={
            "validate": {
                stage: _step(f"{stage}.py")
                for stage in ("promotion", "deployment", "shipment")
            }
        },
    )
    for stage in ("promotion", "deployment", "shipment"):
        result = subprocess.run(
            [
                sys.executable,
                str(OPERATION_RUNNER),
                "--repo-root",
                str(tmp_path),
                "--validate",
                "--validation-operation",
                CHECK + stage,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    assert (tmp_path / "checks.txt").read_text().splitlines() == [
        "promotion",
        "deployment",
        "shipment",
    ]


def test_validation_parameters_remain_strict(tmp_path: pathlib.Path) -> None:
    write_sdlc_contract(tmp_path, repository={"validate": {"check": _step("-V")}})
    result = subprocess.run(
        [
            sys.executable,
            str(OPERATION_RUNNER),
            "--repo-root",
            str(tmp_path),
            "--validate",
            "--parameter",
            "unknown=value",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1 and "unexpected unknown" in result.stderr


@pytest.mark.parametrize("change_head", [False, True])
def test_source_changes_between_steps_prevent_later_mutations(
    tmp_path: pathlib.Path,
    change_head: bool,
) -> None:
    mutation = "import pathlib, subprocess; pathlib.Path('changed').touch(); "
    if change_head:
        mutation += (
            "subprocess.run(['git', 'add', '.'], check=True, capture_output=True); "
            "subprocess.run(['git', 'commit', '-m', 'drift'], check=True, capture_output=True); "
        )
    mutation += f"print({json.dumps(RECEIPT)!r})"
    write_sdlc_contract(
        tmp_path,
        deliverables={
            "sample": {
                "deploy-local": {
                    "local": {
                        "steps": [
                            {
                                "run": [
                                    sys.executable,
                                    "-c",
                                    mutation,
                                ]
                            },
                            {
                                "run": [
                                    sys.executable,
                                    "-c",
                                    "import pathlib; pathlib.Path('deployed').touch()",
                                ]
                            },
                        ]
                    }
                }
            }
        },
    )
    _repository(tmp_path)
    result = run_operation_cli(tmp_path, DEPLOY + "local")
    assert result.returncode == 1
    assert json.loads(result.stderr)["status"] == "state_changed"
    assert json.loads(result.stderr)["step_results"] == [
        {"step": 1, "result": RECEIPT}
    ]
    assert not (tmp_path / "deployed").exists()


def test_artifact_identity_is_collected_from_each_owning_deliverable(
    tmp_path: pathlib.Path,
) -> None:
    artifact_reader = importlib.import_module(
        "github_contract_engine.repository_artifact_contracts"
    )
    records = [
        {
            "artifact_type": "python_package",
            "registry": "pypi.org",
            "package_or_image_name": name,
            "version_source": "pyproject.toml",
            "release_policy": "tagged",
            "tag_style": "v{version}",
            "changelog_source": "CHANGELOG.md",
            "post_publish_consumer_check": "import package",
        }
        for name in ("tool-one", "tool-two")
    ]
    write_sdlc_contract(
        tmp_path,
        deliverables={
            name: {"artifacts": [record]}
            for name, record in zip(("one", "two"), records, strict=True)
        },
    )
    resolve = artifact_reader.resolve_repository_artifact_contracts
    assert resolve(str(tmp_path), None) == records
    with pytest.raises(ValueError, match="declared both"):
        resolve(str(tmp_path), records)


@pytest.mark.parametrize("exit_code", [0, 17])
def test_repository_bootstrap_resolves_platform_npm_and_preserves_failure(
    tmp_path: pathlib.Path,
    exit_code: int,
) -> None:
    """Exercise the declared bootstrap against a harmless fake npm, not an install."""

    executable = tmp_path / ("npm.cmd" if os.name == "nt" else "npm")
    executable.write_text(
        f"@echo SDLC-npm-%*\n@exit /b {exit_code}\n"
        if os.name == "nt"
        else f"#!/bin/sh\nprintf 'SDLC-npm-%s\\n' \"$*\"\nexit {exit_code}\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    contract = contracts.load_contract(
        OPERATION_RUNNER.parents[3] / "sdlc" / "sdlc.yml"
    )
    argv = contract["repository"]["bootstrap"]["development"]["steps"][-1]["run"]
    prepare_script_environment(tmp_path)
    result = subprocess.run(
        argv,
        cwd=tmp_path,
        env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is (exit_code == 0)
    assert result.stdout.strip() == "SDLC-npm---prefix scripts ci"
    if exit_code:
        assert str(exit_code) in result.stderr
    command = importlib.import_module("github_pr_workflow.command")
    if exit_code:
        payload = json.dumps({
            "noise": "x" * 10000, "status": "error",
            "message": "Required configuration is missing", "evidence_file": "failure.log",
        })
        argv = [sys.executable, "-c", f"import sys; print({payload!r}); sys.exit(9)"]
        with pytest.raises(command.CommandError) as failed:
            command.require_output(argv, cwd=tmp_path)
        assert "Required configuration is missing" in str(failed.value)
        assert "failure.log" in str(failed.value) and len(str(failed.value)) <= 2400
        assert failed.value.completed.stdout == payload + "\n"
        assert failed.value.completed.returncode == 9
    else:
        assert command.require_output(
            [sys.executable, "-c", "print('OK')"], cwd=tmp_path,
        ) == "OK"
    with pytest.raises(command.CommandError, match="could not start"):
        command.require_output([str(tmp_path / "missing-command")], cwd=tmp_path)


# Version 1 is the historical f49e575/f671d9b SDLC schema, not a guessed
# compatibility surface. Its operation and step identifiers permit underscores.
def _write_v1(
    root: pathlib.Path, *, deploy: object = None, release: object = None,
) -> pathlib.Path:
    import yaml

    payload: dict[str, object] = {"version": 1, "kind": "ceratops-sdlc"}
    for section, operations in (("deploy", deploy), ("release", release)):
        if operations is not None:
            payload[section] = {"operations": operations}
    path = root / "sdlc/sdlc.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_historical_sdlc_contract_preserves_native_locations(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "sdlc/sdlc.yml"
    path.parent.mkdir()
    # Actual repository contract at f671d9b, before the deliverables refactor.
    original = (
        "version: 1\nkind: ceratops-sdlc\ndeploy:\n  operations:\n"
        "    deploy:\n      handoff: ceratops-skill-lifecycle/deploy\n"
        "    bootstrap:\n      steps:\n        - id: bootstrap-skills\n"
        "          run:\n            - python\n"
        "            - scripts/install-skills-bootstrap.py\n"
    )
    path.write_text(original, encoding="utf-8")
    before = path.read_bytes()
    contract, errors = contracts.read_contract(path)
    assert errors == []
    assert contract is not None and contract["version"] == 1
    assert list(contracts.operation_entries(contract)) == [
        "deploy.operations.deploy", "deploy.operations.bootstrap",
    ]
    prepared = runner.prepare_operations(
        tmp_path,
        [runner.OperationRequest("deploy.operations.bootstrap"),
         runner.OperationRequest("deploy.operations.deploy")],
    )
    assert prepared[0].steps[0].argv == (
        "python", "scripts/install-skills-bootstrap.py",
    )
    assert prepared[0].steps[0].position == "bootstrap-skills"
    assert prepared[1].handoff == "ceratops-skill-lifecycle/deploy"
    assert runner.validation_operations(tmp_path) == []
    assert path.read_bytes() == before


def test_v1_execution_preserves_order_argv_parameters_cwd_and_handoff(
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "record.py").write_text(
        "import json, pathlib, sys\n"
        "path = pathlib.Path(__file__).resolve().parent / 'calls.json'\n"
        "calls = json.loads(path.read_text()) if path.exists() else []\n"
        "calls.append({'argv': sys.argv[1:], 'cwd': str(pathlib.Path.cwd())})\n"
        "path.write_text(json.dumps(calls), encoding='utf-8')\n"
        f"print({json.dumps(RECEIPT)!r})\n",
        encoding="utf-8",
    )
    path = _write_v1(
        tmp_path,
        deploy={
            "preflight": {"steps": [{"id": "not_implicit", "run": [
                sys.executable, "-c", "raise SystemExit(99)",
            ]}]},
            "deploy_one": {
                "parameters": ["value"],
                "steps": [
                    {"id": "first_step", "run": [
                        sys.executable, "record.py", "{value}", "prefix={value}",
                    ]},
                    {"id": "second_step", "cwd": "nested", "run": [
                        sys.executable, "../record.py", "last",
                    ]},
                ],
                "handoff": "ceratops-skill-lifecycle/deploy",
            },
        },
        release={
            "publish_one": {"parameters": ["value"], "steps": [
                {"id": "publish_step", "run": [
                    sys.executable, "record.py", "published", "{value}",
                ]},
            ]},
        },
    )
    original = path.read_bytes()
    literal = "spaces; $(write-file injected.txt)\n" + chr(96) + "literal"
    result = subprocess.run(
        [sys.executable, str(OPERATION_RUNNER), "--repo-root", str(tmp_path),
         "--operation", "release.operations.publish_one",
         "--operation", "deploy.operations.deploy_one",
         "--parameter", "value=" + literal],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["completed_operations"] == [
        "release.operations.publish_one", "deploy.operations.deploy_one",
    ]
    assert payload["results"][0]["steps"] == ["publish_step"]
    assert payload["results"][1]["steps"] == ["first_step", "second_step"]
    assert payload["results"][0]["step_results"] == [
        {"step": "publish_step", "result": RECEIPT}
    ]
    assert payload["results"][1]["step_results"] == [
        {"step": step, "result": RECEIPT} for step in ("first_step", "second_step")
    ]
    assert payload["results"][1]["handoff"] == "ceratops-skill-lifecycle/deploy"
    calls = json.loads((tmp_path / "calls.json").read_text(encoding="utf-8"))
    assert calls == [
        {"argv": ["published", literal], "cwd": str(tmp_path.resolve())},
        {"argv": [literal, "prefix={value}"], "cwd": str(tmp_path.resolve())},
        {"argv": ["last"], "cwd": str((tmp_path / "nested").resolve())},
    ]
    assert runner.validation_operations(tmp_path, payload["completed_operations"]) == []
    assert path.read_bytes() == original
    assert not (tmp_path / "injected.txt").exists()


@pytest.mark.parametrize("failure", ["parameter", "cwd", "undeclared", "schema"])
def test_v1_prepares_entire_batch_before_side_effects(
    tmp_path: pathlib.Path, failure: str,
) -> None:
    marker = tmp_path / "executed.txt"
    safe = {"steps": [{"id": "safe", "run": [
        sys.executable, "-c", "import pathlib; pathlib.Path('executed.txt').touch()",
    ]}]}
    unsafe: dict[str, object] = {
        "steps": [{"id": "next", "run": [sys.executable, "-c", "pass"]}],
    }
    if failure == "parameter":
        unsafe["parameters"] = ["required_value"]
    elif failure == "cwd":
        unsafe["steps"] = [{"id": "next", "cwd": "..", "run": [
            sys.executable, "-c", "pass",
        ]}]
    elif failure == "schema":
        unsafe["steps"] = [{"run": [sys.executable, "-c", "pass"]}]
    _write_v1(tmp_path, deploy={"safe": safe, "unsafe": unsafe})
    result = subprocess.run(
        [sys.executable, str(OPERATION_RUNNER), "--repo-root", str(tmp_path),
         "--operation", "deploy.operations.safe", "--operation",
         "deploy.operations.missing" if failure == "undeclared" else "deploy.operations.unsafe"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert json.loads(result.stderr)["status"] == "error"
    assert not marker.exists()


@pytest.mark.parametrize("startup_error", [False, True])
def test_v1_failure_stops_batch_with_original_step_ids(
    tmp_path: pathlib.Path, startup_error: bool,
) -> None:
    failed_run = (
        [str(tmp_path / "missing-executable")]
        if startup_error else
        [sys.executable, "-c", f"print({json.dumps(RECEIPT)!r}); raise SystemExit(7)"]
    )
    _write_v1(tmp_path, release={
        "first": {"steps": [
            {"id": "before", "run": [sys.executable, "-c", f"print({json.dumps(RECEIPT)!r})"]},
            {"id": "failed_step", "run": failed_run},
            {"id": "unreachable", "run": [sys.executable, "-c", "pass"]},
        ]},
        "second": {"steps": [{"id": "pending", "run": [sys.executable, "-c", "pass"]}]},
    })
    prepared = runner.prepare_operations(tmp_path, [
        runner.OperationRequest("release.operations.first"),
        runner.OperationRequest("release.operations.second"),
    ])
    result = runner.execute_prepared_operations(prepared)
    assert result["status"] == "operation_failed"
    assert result["failed_step"] == "failed_step"
    assert result["steps"] == ["before"]
    assert result["diagnostic"]["exit_code"] == (None if startup_error else 7)
    assert result["step_results"] == [{"step": "before", "result": RECEIPT}]
    assert result["diagnostic"]["stdout_tail"] == ([] if startup_error else [json.dumps(RECEIPT)])
    assert result["pending_operations"] == ["release.operations.first", "release.operations.second"]


def test_v1_absent_section_and_optional_operation_remain_no_ops(tmp_path: pathlib.Path) -> None:
    _write_v1(tmp_path, deploy={})
    prepared = runner.prepare_operations(tmp_path, [
        runner.OperationRequest("release.operations.publish"),
        runner.OperationRequest("deploy.operations.absent", if_declared=True),
    ])
    result = runner.execute_prepared_operations(prepared)
    assert [item["reason"] for item in result["results"]] == [
        "contract_section_not_declared", "operation_not_declared",
    ]
    assert all(item["status"] == "no_op" for item in result["results"])
    with pytest.raises(runner.OperationError, match="not declared"):
        runner.prepare_operations(tmp_path, [runner.OperationRequest("deploy.operations.absent")])


@pytest.mark.parametrize("version", [None, True, 1.0, "1", 0, 5, [], {}])
def test_loader_rejects_unsupported_or_unversioned_contracts(
    tmp_path: pathlib.Path, version: object,
) -> None:
    import yaml

    path = tmp_path / "invalid.yml"
    path.write_text(yaml.safe_dump({
        "version": version, "kind": "ceratops-sdlc", "deploy": {"operations": {}},
    }), encoding="utf-8")
    document, errors = contracts.read_contract(path)
    assert document is None and errors
    assert "unsupported SDLC version" in errors[0]
    with pytest.raises(contracts.SdlcContractError, match="unsupported SDLC version"):
        contracts.load_contract(path)


@pytest.mark.parametrize("invalid", [
    {"version": 1, "kind": "ceratops-sdlc"},
    {"version": 1, "kind": "wrong", "deploy": {"operations": {}}},
    {"version": 1, "kind": "ceratops-sdlc", "repository": {}},
    {"version": 1, "kind": "ceratops-sdlc", "deploy": {"operations": {
        "test": {"steps": [{"run": ["python"]}]},
    }}},
    {"version": 1, "kind": "ceratops-sdlc", "release": {"operations": {
        "test": {"handoff": "ceratops-skill-lifecycle/deploy"},
    }}},
    {"version": 1, "kind": "ceratops-sdlc", "deploy": {"operations": {
        "test": {"steps": [{"id": "a", "run": "python"}]},
    }}},
    {"version": 2, "kind": "ceratops-sdlc", "deploy": {"operations": {}}},
    {"version": 2, "kind": "ceratops-sdlc", "repository": {"validate": {
        "test": {"steps": [{"id": "a", "run": ["python"]}]},
    }}},
    [],
])
def test_version_specific_schema_rejects_invalid_data(
    tmp_path: pathlib.Path, invalid: object,
) -> None:
    path = tmp_path / "invalid.yml"
    path.write_text(json.dumps(invalid), encoding="utf-8")
    assert contracts.validation_errors(invalid)
    assert contracts.read_contract(path)[0] is None
    with pytest.raises(contracts.SdlcContractError):
        contracts.load_contract(path)


def test_v1_duplicate_yaml_keys_and_invalid_schema_are_rejected(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "contract.yml"
    path.write_text(
        "version: 1\nkind: ceratops-sdlc\ndeploy:\n  operations:\n"
        "    a:\n      handoff: skill/deploy\n    a:\n      handoff: skill/deploy\n",
        encoding="utf-8",
    )
    assert "unique strings" in contracts.read_contract(path)[1][0]
    path = _write_v1(tmp_path, deploy={})
    schema = tmp_path / "broken.json"
    schema.write_text("{", encoding="utf-8")
    assert "invalid SDLC schema" in contracts.read_contract(path, schema_path=schema)[1][0]
    assert contracts.read_contract(path, schema_path=contracts.SCHEMA)[1] == []


@pytest.mark.parametrize("installer_version", [1, 12, 1000])
def test_supported_v1_compatibility_is_independent_of_installer_release(
    tmp_path: pathlib.Path, installer_version: int,
) -> None:
    checker = importlib.import_module("ceratops_repo_compatibility_engine.validate_ceratops_compatibility")
    _write_v1(tmp_path, deploy={})
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "deploy-skills.py").write_text(
        f"INSTALLER_VERSION = {installer_version}\n", encoding="utf-8",
    )
    (scripts / "validate-repository.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    workflow = tmp_path / ".github/workflows/validate.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n  validate:\n    steps:\n"
        "      - run: python scripts/validate-repository.py --evidence-file evidence.log\n",
        encoding="utf-8",
    )
    result = checker.validate_ceratops_compatibility(tmp_path)
    assert result["valid"] is False
    assert "current Ceratops compatibility requires SDLC version 3" in result["errors"]
    assert all("INSTALLER_VERSION" not in error for error in result["errors"])


def test_materialization_preserves_supported_v1_without_migration(tmp_path: pathlib.Path) -> None:
    materializer = importlib.import_module("ceratops_repo_compatibility_engine.apply_ceratops_compatibility")
    path = _write_v1(tmp_path, deploy={"deploy": {"handoff": "ceratops-skill-lifecycle/deploy"}})
    original = path.read_bytes()
    for has_skills in (True, False):
        with pytest.raises(RuntimeError, match="operation ownership must be mapped"):
            materializer.build_sdlc_contract_candidate(
                tmp_path, has_skills=has_skills, apply_contract=True,
            )
    assert path.read_bytes() == original


def test_v1_artifact_identity_keeps_repository_precedence(tmp_path: pathlib.Path) -> None:
    import yaml
    resolver = importlib.import_module("github_contract_engine.repository_artifact_contracts")
    record = {
        "artifact_type": "python_package", "registry": "pypi",
        "package_or_image_name": "historical-package", "version_source": "pyproject.toml",
        "release_policy": "manual", "tag_style": "semver",
        "changelog_source": "CHANGELOG.md", "post_publish_consumer_check": "pip download historical-package",
    }
    path = _write_v1(tmp_path, release={})
    contract = yaml.safe_load(path.read_text(encoding="utf-8"))
    contract["release"]["artifacts"] = [record]
    path.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
    assert resolver.resolve_repository_artifact_contracts(str(tmp_path), None) == [record]
    with pytest.raises(ValueError, match="declared both"):
        resolver.resolve_repository_artifact_contracts(str(tmp_path), [record])


@pytest.mark.parametrize("version", [1, 2, 3])
def test_health_migration_proposal_is_advisory_and_reaches_automation_summary(
    tmp_path: pathlib.Path, version: int,
) -> None:
    collector = importlib.import_module("github_contract_engine.collectors.local_repository")
    reports = importlib.import_module("github_contract_engine.format_report")
    levels = importlib.import_module("github_contract_engine.levels")
    path = _write_v1(tmp_path, deploy={}) if version == 1 else write_sdlc_contract(tmp_path)
    if version == 3:
        path.write_text("version: 3\nkind: ceratops-sdlc\n", encoding="utf-8")
    original = path.read_bytes()
    facts = collector._sdlc_contract_facts({"available": True, "root": str(tmp_path)})
    assert facts["valid"] is True
    desired = {
        "parameters": {"owner": "owner", "repo": "sample"}, "contract_paths": {},
        "selected_ids": {"repo": ["content.sdlc_contract"]},
        "rules": [{"id": "content.sdlc_contract"}],
    }
    comparison: dict[str, list[dict[str, object]]] = {"findings": [], "approved_drift": []}
    report = reports.build_report(desired, {"local": {"sdlc_contract": facts}}, comparison)
    # These are the exact levels requested by Global Repo Health Consistency.
    summary = reports.build_summary_report(report, ["ERROR", "WARN", "NEEDS_AI_AGENT_REVIEW"])
    proposals = [f for f in summary["findings"] if f["check_id"] == "content.sdlc_migration"]
    assert len(proposals) == (1 if version in (1, 2) else 0)
    if proposals:
        assert proposals[0]["actual"] == {
            "repository": "owner/sample", "current_version": version, "recommended_version": 3,
            "reason": facts["migration_proposal"]["reason"],
        }
        assert "owner/sample" in proposals[0]["message"]
        assert f"version {version} to 3" in proposals[0]["message"]
        assert "do not automatically migrate" in proposals[0]["message"]
        assert not levels.has_blocking_findings(proposals)
    assert comparison == {"findings": [], "approved_drift": []}
    assert path.read_bytes() == original



def test_nested_uv_projects_keep_independent_pip_manifests() -> None:
    collector = importlib.import_module("github_contract_engine.collectors.local_repository")
    assert collector._dependabot_ecosystems([
        "pyproject.toml", "requirements-dev.txt", "scripts/pyproject.toml",
        "scripts/uv.lock", "apps/api/pyproject.toml", "apps/api/requirements.txt",
    ]) == {
        "pip": ["apps/api/pyproject.toml", "apps/api/requirements.txt", "pyproject.toml", "requirements-dev.txt"],
        "uv": ["scripts/pyproject.toml", "scripts/uv.lock"],
    }


def test_tests_only_cli_preserves_declared_parameters(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    import yaml
    document = {"version": 3, "kind": "ceratops-sdlc", "repository": {
        "tests": {"unit": {"parameters": ["suite"], "steps": [{"run": [
            sys.executable, "-c", "import sys; assert sys.argv[1] == 'selected'", "{suite}",
        ]}]}},
    }}
    path = tmp_path / "sdlc/sdlc.yml"
    path.parent.mkdir()
    path.write_text(yaml.safe_dump(document))
    assert runner.main(["--repo-root", str(tmp_path), "--tests", "--parameter", "suite=selected"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["completed_operations"] == ["repository.tests.unit"]


def test_completed_validation_binding_is_not_returned_as_pending_handoff(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    import yaml
    document = {"version": 3, "kind": "ceratops-sdlc", "deliverables": {"service": {
        "validate": {"source": {"handoff": "example-skill/check"}},
        "tests": {"none": {"no-op": "No tests in this fixture."}},
        "deploy-local": {"local": {"steps": [{"run": [sys.executable, "-c", "pass"]}]}},
    }}}
    path = tmp_path / "sdlc/sdlc.yml"
    path.parent.mkdir()
    path.write_text(yaml.safe_dump(document))
    monkeypatch.setattr(runner, "execute_handoff", lambda route, root: {"status": "completed", "handoff": route})
    assert runner.main(["--repo-root", str(tmp_path), "--operation", "deliverables.service.deploy-local.local"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert "validation_handoffs" not in result



@pytest.mark.skipif(shutil.which("npm") is None, reason="npm is not installed")
def test_sdlc_launches_native_package_manager_test_command(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    import yaml
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "sdlc-command-probe", "private": True, "scripts": {"test": "node --version"},
    }))
    path = tmp_path / "sdlc/sdlc.yml"
    path.parent.mkdir()
    path.write_text(yaml.safe_dump({"version": 3, "kind": "ceratops-sdlc", "repository": {
        "tests": {"package": {"steps": [{"run": ["npm", "test"]}]}},
    }}))
    assert runner.main(["--repo-root", str(tmp_path), "--tests", "--ci"]) == 0
    assert json.loads(capsys.readouterr().out)["completed_operations"] == ["repository.tests.package"]


@pytest.mark.parametrize("mode", ["explicit", "staged", "committed"])
def test_repository_path_rename_updates_exact_references_and_preserves_index(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], mode: str,
) -> None:
    import runpy

    module = runpy.run_path(str(OPERATION_RUNNER.with_name("rename-repository-path.py")))
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "docs").mkdir()
    source = b"print('preserve quotation marks')\r\n"
    (repo / "src/old-name.py").write_bytes(source)
    (repo / "README.md").write_bytes(b'Run "src/old-name.py"; keep old-name.pyc.\r\n')
    (repo / "docs/guide.md").write_bytes(b"[run](../src/old-name.py#entry)\r\n")
    (repo / "references.json").write_bytes(b'{"command": "src\\\\old-name.py"}\r\n')
    base = _repository(repo)
    index = run_git(repo, "diff", "--cached", "--binary").stdout
    arguments = ["--rename", "src/old-name.py", "lib/new-name.py"]
    if mode != "explicit":
        (repo / "lib").mkdir()
        assert run_git(repo, "mv", "src/old-name.py", "lib/new-name.py").returncode == 0
        arguments = ["--from-git"]
        if mode == "committed":
            assert run_git(repo, "commit", "-m", "rename only").returncode == 0
            head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            arguments += ["--base", base, "--head", head]
        index = run_git(repo, "diff", "--cached", "--binary").stdout
    report = tmp_path / "rename-report.json"
    assert module["main"](["--repo-root", str(repo), *arguments, "--report", str(report)]) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "ready"
    assert (repo / "README.md").read_bytes().startswith(b'Run "src/old-name.py"')
    report.unlink()
    assert module["main"](["--repo-root", str(repo), *arguments, "--apply", "--report", str(report)]) == 0
    assert capsys.readouterr().out.splitlines() == ["OK", "OK"]
    assert (repo / "lib/new-name.py").read_bytes() == source
    assert not (repo / "src/old-name.py").exists()
    assert (repo / "README.md").read_bytes() == b'Run "lib/new-name.py"; keep old-name.pyc.\r\n'
    assert (repo / "docs/guide.md").read_bytes() == b"[run](../lib/new-name.py#entry)\r\n"
    assert json.loads((repo / "references.json").read_bytes()) == {"command": "lib\\new-name.py"}
    assert run_git(repo, "diff", "--cached", "--binary").stdout == index
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "applied"


@pytest.mark.parametrize("case", ["ambiguous", "escape", "overwrite", "case-only", "binary", "report", "report-parent"])
def test_repository_path_rename_rejects_unsafe_or_ambiguous_plans_before_writes(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], case: str,
) -> None:
    import runpy

    module = runpy.run_path(str(OPERATION_RUNNER.with_name("rename-repository-path.py")))
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src/old.py").write_bytes(b"original\r\n")
    reference = repo / "references.txt"
    reference.write_bytes(b'parts = ["src", "old.py"]\r\n' if case == "ambiguous" else b"src/old.py\r\n")
    if case == "overwrite":
        (repo / "new.py").write_bytes(b"keep")
    if case == "binary":
        (repo / "binary.dat").write_bytes(b"\0src/old.py")
    _repository(repo)
    before = {p: p.read_bytes() for p in (repo / "src/old.py", reference)}
    destination = {"escape": "../outside.py", "case-only": "src/OLD.py"}.get(case, "new.py")
    argv = ["--repo-root", str(repo), "--rename", "src/old.py", destination, "--apply"]
    if case == "report":
        argv += ["--report", str(repo / "report.json")]
    if case == "report-parent":
        argv += ["--report", str(tmp_path / "absent/report.json")]
    code = module["main"](argv)
    assert code in {1, 2}
    assert {p: p.read_bytes() for p in before} == before
    assert not run_git(repo, "status", "--porcelain").stdout
    if case == "ambiguous":
        assert code == 2
        assert module["main"]([*argv, "--reference", '"src", "old.py"', '"new.py"']) == 0
        assert reference.read_bytes() == b'parts = ["new.py"]\r\n'
        assert not (repo / "src/old.py").exists()
    if case == "binary":
        assert module["main"]([*argv, "--exclude", "binary.dat"]) == 0
        assert (repo / "binary.dat").read_bytes() == b"\0src/old.py"
    capsys.readouterr()


@pytest.mark.parametrize("failure", ["write", "move", "drift"])
def test_repository_path_rename_compensates_file_errors_and_detects_source_drift(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    import runpy

    module = runpy.run_path(str(OPERATION_RUNNER.with_name("rename-repository-path.py")))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "old.py").write_bytes(b"source\r\n")
    (repo / "one.txt").write_bytes(b"old.py\r\n")
    (repo / "two.txt").write_bytes(b"old.py\r\n")
    _repository(repo)
    report, originals, changes, moves = module["build_plan"](
        repo, [("old.py", "nested/new.py")], [], set(),
    )
    assert not report["unresolved"]
    if failure == "drift":
        (repo / "one.txt").write_bytes(b"someone else's edit")
        with pytest.raises(module["RenameError"], match="changed after planning"):
            module["apply_plan"](originals, changes, moves, root=repo)
        assert (repo / "one.txt").read_bytes() == b"someone else's edit"
    else:
        method = "write_bytes" if failure == "write" else "rename"
        original = getattr(pathlib.Path, method)
        calls = 0

        def fail_once(path: pathlib.Path, *args: object, **kwargs: object) -> object:
            nonlocal calls
            calls += 1
            if calls == (2 if failure == "write" else 1):
                raise OSError("simulated file failure")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(pathlib.Path, method, fail_once)
        with pytest.raises(module["RenameError"], match="rolled back"):
            module["apply_plan"](originals, changes, moves, root=repo)
        assert all(path.read_bytes() == content for path, content in originals.items())
    assert (repo / "old.py").exists()
    assert not (repo / "nested").exists()


def test_repository_path_rename_relocates_markdown_links_with_their_document(
    tmp_path: pathlib.Path,
) -> None:
    import runpy

    module = runpy.run_path(str(OPERATION_RUNNER.with_name("rename-repository-path.py")))
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "asset.txt").write_bytes(b"asset")
    (repo / "docs/old.md").write_bytes(b"[asset](../asset.txt)\r\n")
    _repository(repo)
    assert module["main"]([
        "--repo-root", str(repo), "--rename", "docs/old.md", "docs/deeper/new.md", "--apply",
    ]) == 0
    assert (repo / "docs/deeper/new.md").read_bytes() == b"[asset](../../asset.txt)\r\n"


def test_repository_path_rename_requires_explicit_pairs_when_git_has_no_rename(
    tmp_path: pathlib.Path,
) -> None:
    import runpy

    module = runpy.run_path(str(OPERATION_RUNNER.with_name("rename-repository-path.py")))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "old.py").write_bytes(b"unchanged")
    _repository(repo)
    assert module["main"](["--repo-root", str(repo), "--from-git", "--apply"]) == 1
    assert (repo / "old.py").read_bytes() == b"unchanged"


@pytest.mark.parametrize(
    "operation",
    [
        {"parameters": ["base"], "steps": [{"run": ["check"]}]},
        {"parameters": ["base", "head"], "handoff": "run tests"},
        {"parameters": ["base", "head"], "steps": [{"run": ["check"]}], "handoff": "run tests"},
        {"parameters": ["base", "head", "extra"], "steps": [{"run": ["check"]}]},
    ],
)
def test_sdlc_test_selection_requires_executable_commit_context(operation: dict[str, object]) -> None:
    document = {"version": 2, "kind": "ceratops-sdlc", "repository": {"test-selection": {"ci": operation}}}
    assert contracts.validation_errors(document)


def test_repository_path_rename_handles_spaces_same_names_and_multiple_pairs(tmp_path: pathlib.Path) -> None:
    import runpy

    module = runpy.run_path(str(OPERATION_RUNNER.with_name("rename-repository-path.py")))
    repo = tmp_path / "repo with spaces"
    (repo / "src").mkdir(parents=True)
    (repo / "src/old name.py").write_bytes(b"first")
    (repo / "src/same.py").write_bytes(b"second")
    (repo / "README.md").write_bytes(
        b'"src/old name.py" "src/same.py"\r\n[run](src/old%20name.py)\r\n',
    )
    _repository(repo)
    assert module["main"]([
        "--repo-root", str(repo), "--rename", "src/old name.py", "nested/new name.py",
        "--rename", "src/same.py", "nested/same.py", "--apply",
    ]) == 0
    assert (repo / "README.md").read_bytes() == (
        b'"nested/new name.py" "nested/same.py"\r\n[run](nested/new%20name.py)\r\n'
    )
    assert (repo / "nested/new name.py").read_bytes() == b"first"
    assert (repo / "nested/same.py").read_bytes() == b"second"


def test_repository_path_rename_rechecks_links_before_apply(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import runpy

    module = runpy.run_path(str(OPERATION_RUNNER.with_name("rename-repository-path.py")))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "old.py").write_bytes(b"source")
    _repository(repo)
    _, originals, changes, moves = module["build_plan"](repo, [("old.py", "nested/new.py")], [], set())
    original = pathlib.Path.is_symlink
    monkeypatch.setattr(pathlib.Path, "is_symlink", lambda path: path == repo / "nested" or original(path))
    with pytest.raises(module["RenameError"], match="Links and junctions"):
        module["apply_plan"](originals, changes, moves, root=repo)
    assert (repo / "old.py").read_bytes() == b"source"
    assert not (repo / "nested").exists()


def test_repository_path_rename_saves_a_failure_report_before_returning(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import runpy

    module = runpy.run_path(str(OPERATION_RUNNER.with_name("rename-repository-path.py")))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "old.py").write_bytes(b"source")
    _repository(repo)
    report = tmp_path / "report.json"

    def interrupted(*args: object, **kwargs: object) -> None:
        assert json.loads(report.read_text(encoding="utf-8"))["status"] == "ready"
        raise OSError("simulated write failure")

    monkeypatch.setitem(module["main"].__globals__, "apply_plan", interrupted)
    assert module["main"]([
        "--repo-root", str(repo), "--rename", "old.py", "new.py",
        "--apply", "--report", str(report),
    ]) == 1
    retained = json.loads(report.read_text(encoding="utf-8"))
    assert retained["status"] == "failed"
    assert retained["message"] == "simulated write failure"
    assert (repo / "old.py").read_bytes() == b"source"
    assert not (repo / "new.py").exists()
