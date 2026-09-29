"""SDLC lifecycle boundaries, registered handoffs, and completion evidence."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import pathlib
import runpy
import shutil
import stat
import subprocess
import sys
import threading
import tomllib
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from tests.repository_lifecycle.support import (
    REPOSITORY_LIFECYCLE_SCRIPTS,
    run_operation_cli,
)
from tests.support.processes import run_compatibility_engine
from tests.support.repositories import ROOT, run_ci_action, run_git

runner = importlib.import_module("repository_operation")
contracts = importlib.import_module(
    "ceratops_repo_compatibility_engine.sdlc_contract_validation"
)
results = importlib.import_module("sdlc_results")


def _repository(repo: pathlib.Path) -> str:
    assert run_git(repo, "init", "-b", "main").returncode == 0
    assert run_git(repo, "config", "user.name", "Tests").returncode == 0
    assert (
        run_git(repo, "config", "user.email", "tests@example.invalid").returncode == 0
    )
    assert run_git(repo, "add", ".").returncode == 0
    assert run_git(repo, "commit", "-m", "fixture").returncode == 0
    return run_git(repo, "rev-parse", "HEAD").stdout.strip()


def _bundle_transaction(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "source.txt").write_text("committed input\n", encoding="utf-8")
    commit = _repository(repo)
    calls = []

    def build(bundle, work):
        calls.append("build")
        (work / "private-environment").mkdir()
        (bundle / "artifacts").mkdir()
        (bundle / "artifacts/example.whl").write_bytes(b"exact built artifact")
        return runner.BuildProduct(artifacts=[{
            "deliverable": "deliverables.packages.example",
            "type": "wheel", "path": "artifacts/example.whl",
        }])

    def test(bundle, artifacts, work):
        calls.append("test")
        assert (work / "private-environment").is_dir()
        evidence = bundle / "supporting-files" / "test.json"
        evidence.parent.mkdir()
        evidence.write_bytes(b'{"status":"passed"}\n')
        return [{
            "id": "installed-artifact", "status": "passed",
            "artifacts": [{"path": item["path"], "sha256": item["sha256"]} for item in artifacts],
            "evidence": {
                "path": evidence.relative_to(bundle).as_posix(),
                "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            },
        }]

    return repo, {
        "selection": {
            "repository": "https://example.invalid/owner/repo",
            "sourceCommit": commit, "releaseUnit": "example", "channel": "alpha",
            "version": "1.0+alpha", "target": "any",
        },
        "inputs": {"dependencySelections": [], "lock": "a" * 64, "adapter": "fixture-v1"},
        "required_tests": ["installed-artifact"],
        "build": build, "test": test,
    }, calls


def _bundle_diagnostic(repo: pathlib.Path, selection: dict[str, str]) -> pathlib.Path:
    store = repo / ".git" / "ceratops" / "builds"
    return runner._build_diagnostic_path(store / ".diagnostics", selection)


def test_bundle_transaction_reuses_exact_success_and_preserves_inputs(tmp_path) -> None:
    repo, kwargs, calls = _bundle_transaction(tmp_path)
    receipt_path = runner.build_bundle(repo, **kwargs)
    saved = {path.relative_to(receipt_path.parent): path.read_bytes()
             for path in receipt_path.parent.rglob("*") if path.is_file()}
    assert calls == ["build", "test"]
    assert runner.build_bundle(repo, **kwargs) == receipt_path
    assert calls == ["build", "test"]
    assert {path.relative_to(receipt_path.parent): path.read_bytes()
            for path in receipt_path.parent.rglob("*") if path.is_file()} == saved
    store = receipt_path.parent.parent
    diagnostic = _bundle_diagnostic(repo, kwargs["selection"])
    assert not list((store / ".staging").iterdir())
    assert [path.name for path in (store / ".locks").iterdir()] == ["store.lock"]
    assert not diagnostic.exists()
    assert not (receipt_path.parent / "work").exists()
    assert run_git(repo, "status", "--porcelain").stdout == ""

    conflicting = {**kwargs, "inputs": {**kwargs["inputs"], "lock": "b" * 64}}
    with pytest.raises(runner.OperationError, match="different locked inputs"):
        runner.build_bundle(repo, **conflicting)
    assert calls == ["build", "test"] and diagnostic.is_file()
    assert runner.build_bundle(repo, **kwargs) == receipt_path
    assert not diagnostic.exists()


@pytest.mark.parametrize("problem", ["failed", "blocked", "skipped", "missing", "evidence", "changed", "unlisted", "coverage"])
def test_bundle_transaction_never_publishes_bad_or_untested_outputs(tmp_path, problem) -> None:
    repo, kwargs, calls = _bundle_transaction(tmp_path)
    good_test = kwargs["test"]

    def bad_test(bundle, artifacts, work):
        records = good_test(bundle, artifacts, work)
        if problem in {"failed", "blocked", "skipped"}:
            records[0]["status"] = problem
        elif problem == "missing":
            records = []
        elif problem == "evidence":
            (bundle / records[0]["evidence"]["path"]).unlink()
        elif problem == "changed":
            (bundle / artifacts[0]["path"]).write_bytes(b"changed after tests")
        elif problem == "unlisted":
            (bundle / "unexpected.txt").write_text("not an artifact", encoding="utf-8")
        elif problem == "coverage":
            records[0]["artifacts"] = []
        return records

    with pytest.raises((runner.OperationError, results.StepResultError, OSError)):
        runner.build_bundle(repo, **{**kwargs, "test": bad_test})
    store = repo / ".git" / "ceratops" / "builds"
    assert not list(store.glob("*/receipt.json"))
    assert not list((store / ".staging").iterdir())
    diagnostic_path = _bundle_diagnostic(repo, kwargs["selection"])
    assert diagnostic_path.is_file()
    diagnostic = json.loads(diagnostic_path.read_text())
    assert diagnostic["requiredTests"] == ["installed-artifact"]
    if problem == "failed":
        assert diagnostic["tests"][0]["id"] == "installed-artifact"
        assert diagnostic["tests"][0]["status"] == "failed"
        assert "evidence" in diagnostic["tests"][0]
    assert runner.build_bundle(repo, **kwargs).is_file()
    assert calls == ["build", "test", "build", "test"]
    assert not diagnostic_path.exists()


def test_bundle_transaction_corruption_does_not_trigger_rebuild(tmp_path) -> None:
    repo, kwargs, calls = _bundle_transaction(tmp_path)
    receipt = runner.build_bundle(repo, **kwargs)
    artifact = receipt.parent / "artifacts/example.whl"
    artifact.write_bytes(b"corrupt saved artifact")
    with pytest.raises(results.StepResultError):
        runner.build_bundle(repo, **kwargs)
    assert calls == ["build", "test"]
    assert artifact.read_bytes() == b"corrupt saved artifact"


def test_bundle_transaction_requires_test_contract_before_build(tmp_path) -> None:
    repo, kwargs, calls = _bundle_transaction(tmp_path)
    with pytest.raises(runner.OperationError, match="required test IDs"):
        runner.build_bundle(repo, **{**kwargs, "required_tests": []})
    assert calls == []
    assert not (repo / ".git" / "ceratops").exists()


@pytest.mark.parametrize("problem", ["duplicate", "identity"])
def test_bundle_transaction_preflights_boundaries_before_tests(tmp_path, problem) -> None:
    repo, kwargs, calls = _bundle_transaction(tmp_path)
    if problem == "identity":
        kwargs["selection"] = {**kwargs["selection"], "sourceCommit": "../unsafe"}
    else:
        original = kwargs["build"]
        def duplicate(bundle, work):
            product = original(bundle, work)
            return runner.BuildProduct(artifacts=[*product.artifacts, *product.artifacts])
        kwargs["build"] = duplicate
    with pytest.raises((runner.OperationError, results.StepResultError)):
        runner.build_bundle(repo, **kwargs)
    assert "test" not in calls
    assert not list((repo / ".git").glob("ceratops/builds/*/receipt.json"))


def test_bundle_transaction_cleans_readonly_scratch_and_interrupted_callbacks(tmp_path) -> None:
    repo, kwargs, calls = _bundle_transaction(tmp_path)
    original = kwargs["build"]
    def interrupted(bundle, work):
        readonly = work / "readonly.txt"
        readonly.write_bytes(b"private scratch")
        readonly.chmod(stat.S_IREAD)
        raise KeyboardInterrupt("fixture interruption")
    with pytest.raises(KeyboardInterrupt):
        runner.build_bundle(repo, **{**kwargs, "build": interrupted})
    assert not list((repo / ".git/ceratops/builds/.staging").iterdir())
    diagnostic = _bundle_diagnostic(repo, kwargs["selection"])
    assert "KeyboardInterrupt" in diagnostic.read_text()
    assert runner.build_bundle(repo, **{**kwargs, "build": original}).is_file()
    assert calls == ["build", "test"]
    assert not diagnostic.exists()


def test_bundle_transaction_serializes_concurrent_callers(tmp_path) -> None:
    repo, kwargs, calls = _bundle_transaction(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = kwargs["build"]

    def paused_build(bundle, work):
        entered.set()
        assert release.wait(10)
        return original(bundle, work)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(runner.build_bundle, repo, **{**kwargs, "build": paused_build})
        try:
            assert entered.wait(10)
            second = executor.submit(runner.build_bundle, repo, **kwargs)
        finally:
            release.set()
        assert first.result(timeout=15) == second.result(timeout=15)
    assert calls == ["build", "test"]


def test_bundle_transaction_worktrees_share_the_same_store(tmp_path) -> None:
    repo, kwargs, calls = _bundle_transaction(tmp_path)
    receipt = runner.build_bundle(repo, **kwargs)
    worktree = tmp_path / "other-worktree"
    added = run_git(repo, "worktree", "add", "-b", "another-task", str(worktree))
    assert added.returncode == 0, added.stderr
    assert runner.build_bundle(worktree, **kwargs) == receipt
    assert calls == ["build", "test"]


def test_bundle_transaction_retains_current_and_two_predecessors_per_group(tmp_path) -> None:
    repo, kwargs, calls = _bundle_transaction(tmp_path)
    receipts = []
    for generation in range(4):
        selection = {
            **kwargs["selection"],
            "sourceCommit": f"{generation + 1:040x}",
            "version": f"1.0+alpha.{generation + 1}",
        }
        receipt = runner.build_bundle(repo, **{**kwargs, "selection": selection})
        receipts.append(receipt)
        completed_ns = (generation + 1) * 1_000_000_000
        os.utime(receipt.parent, ns=(completed_ns, completed_ns))

    store = repo / ".git" / "ceratops" / "builds"
    assert not receipts[0].exists()
    assert all(path.is_file() for path in receipts[1:])
    assert len(list(store.glob("*/receipt.json"))) == runner.BUILD_BUNDLE_RETENTION
    assert calls == ["build", "test"] * 4


def test_bundle_transaction_recovers_all_killed_owner_staging(tmp_path) -> None:
    repo, kwargs, calls = _bundle_transaction(tmp_path)
    serializable = {key: value for key, value in kwargs.items() if key not in {"build", "test"}}
    program = (
        "import os,pathlib,sys; import repository_operation as r\n"
        "def build(bundle, work):\n"
        "    (work / 'unfinished').write_bytes(b'owned scratch')\n"
        "    os._exit(23)\n"
        f"r.build_bundle(pathlib.Path({str(repo)!r}), **{serializable!r}, build=build, "
        "test=lambda *args: [])\n"
    )
    child = subprocess.run([sys.executable, "-c", program], cwd=REPOSITORY_LIFECYCLE_SCRIPTS,
                           capture_output=True, text=True, timeout=15, check=False)
    assert child.returncode == 23, child.stderr
    staging_root = repo / ".git/ceratops/builds/.staging"
    orphan = next(staging_root.iterdir())
    earlier = staging_root / ("f" * 64)
    earlier.mkdir()
    (earlier / "owned-scratch").write_bytes(b"remove")
    unrelated = staging_root / "manual-note"
    unrelated.mkdir()
    sentinel = unrelated / "not-owned"
    sentinel.write_bytes(b"retain")
    assert runner.build_bundle(repo, **kwargs).is_file()
    assert not orphan.exists() and not earlier.exists()
    assert sentinel.read_bytes() == b"retain"
    assert calls == ["build", "test"]


def test_bundle_transaction_cleanup_failure_retains_diagnostic_and_recovers(tmp_path, monkeypatch) -> None:
    repo, kwargs, calls = _bundle_transaction(tmp_path)
    original = runner.shutil.rmtree

    def fail_cleanup(path, *args, **kw):
        raise PermissionError("fixture cleanup refusal")

    with monkeypatch.context() as patch:
        patch.setattr(runner.shutil, "rmtree", fail_cleanup)
        with pytest.raises(PermissionError, match="cleanup refusal"):
            runner.build_bundle(repo, **kwargs)
    diagnostic = _bundle_diagnostic(repo, kwargs["selection"])
    assert "Staging cleanup failed" in diagnostic.read_text()
    assert runner.shutil.rmtree is original
    assert runner.build_bundle(repo, **kwargs).is_file()
    assert calls == ["build", "test"]
    assert not diagnostic.exists()


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
def test_v4_tests_gate_mutations_and_ci_never_dispatches_handoffs(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    """Real subprocess failure must stop the batch before a later mutation."""
    declaration = {
        "version": 4,
        "kind": "ceratops-sdlc",
        "repository": {
            "capabilities": {},
            "actions": {
                "validate": {
                    "requires": {"capabilities": []},
                    "no-op": "No extra structural checks.",
                },
                "test": {
                    "requires": {"capabilities": []},
                    "no-op": "No repository tests.",
                },
            },
        },
        "deliverables": {
            "apps": {
                "service": {
                    "source": "apps/service",
                    "manifest": "apps/service/app.json",
                    "prerequisites": [],
                    "actions": {
                        "test": _v4_action(
                            {"run": [sys.executable, "-c", "raise SystemExit(7)"]}
                        ),
                        "validate": _v4_action(
                            {
                                "handoff": {
                                    "lifecycle": "example-skill",
                                    "action": "check",
                                    "inputs": {},
                                }
                            }
                        ),
                        "install": _v4_action(
                            {
                                "run": [
                                    sys.executable,
                                    "-c",
                                    "raise AssertionError('must not deploy')",
                                ]
                            }
                        ),
                    },
                }
            }
        },
    }
    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(declaration))
    location = "deliverables.apps.service.actions.install"
    selected = runner.validation_operations(
        tmp_path, [location], ["repository.actions.validate"]
    )
    assert "deliverables.apps.service.actions.test" in selected
    calls: list[str] = []

    def record_handoff(
        route: str, root: pathlib.Path, **_kwargs: object
    ) -> dict[str, str]:
        calls.append(route)
        return {"status": "completed"}

    monkeypatch.setattr(runner, "execute_handoff", record_handoff)
    handoff = runner.prepare_operations(
        tmp_path,
        [runner.OperationRequest("deliverables.apps.service.actions.validate")],
        context=mode,
    )[0]
    result = runner.execute_prepared_operation(handoff)
    assert calls == (["example-skill/check"] if mode == "skill" else [])
    assert (
        result["status"]
        == {
            "ci": "deferred_handoff",
            "skill": "completed",
            "return": "handoff_required",
        }[mode]
    )
    prepared = runner.prepare_operations(
        tmp_path,
        [runner.OperationRequest(item) for item in selected]
        + [runner.OperationRequest(location)],
        context=mode,
    )
    failed = runner.execute_prepared_operations(prepared)
    assert failed["status"] == (
        "handoff_required" if mode == "return" else "tests_failed"
    )
    assert location in failed["pending_operations"]
    assert location not in failed["completed_operations"]


@pytest.mark.parametrize("failure", [None, "validation", "tests"])
def test_ci_action_runs_skill_engine_without_repository_copies(
    tmp_path: pathlib.Path,
    failure: str | None,
) -> None:
    repo = tmp_path / "repository with spaces"
    (repo / "sdlc").mkdir(parents=True)
    evidence = tmp_path / "failure evidence.json"
    evidence.write_text("previous failure")

    def command(name: str) -> dict[str, object]:
        program = (
            "from pathlib import Path; p=Path('order.txt'); "
            f"p.write_text((p.read_text() if p.exists() else '') + {name!r} + chr(10)); "
            f"raise SystemExit({7 if failure == name else 0})"
        )
        return {
            "requires": {"capabilities": []},
            "steps": [{"run": [sys.executable, "-c", program]}],
        }

    declaration = {
        "version": 4,
        "kind": "ceratops-sdlc",
        "repository": {
            "capabilities": {},
            "actions": {
                "validate": command("validation"),
                "test": command("tests"),
            },
        },
        "deliverables": {
            "skills": {
                "service": {
                    "source": "skills/service",
                    "prerequisites": [],
                    "actions": {
                        "validate": _v4_action(
                            {
                                "handoff": {
                                    "lifecycle": "ceratops-skill-lifecycle",
                                    "action": "source-validate",
                                    "inputs": {"skill": "service"},
                                }
                            }
                        ),
                        "install": _v4_action(
                            {
                                "handoff": {
                                    "lifecycle": "ceratops-skill-lifecycle",
                                    "action": "deploy",
                                    "inputs": {"skill": "service"},
                                }
                            }
                        ),
                    },
                }
            }
        },
    }
    (repo / "sdlc/sdlc.yml").write_text(json.dumps(declaration))
    result = run_ci_action(repo, evidence, tmp_path / "action checkout")
    assert result.returncode == (1 if failure else 0), result.stderr
    payload = json.loads(result.stderr if failure else result.stdout)
    if failure:
        assert json.loads(evidence.read_text()) == payload
        assert payload["status"] == (
            "validation_failed" if failure == "validation" else "tests_failed"
        )
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
                "test": {
                    "requires": {"capabilities": []},
                    "no-op": "No repository tests.",
                },
            },
        },
        "deliverables": {
            "packages": {
                "core": {
                    "source": "packages/core",
                    "project": "packages/core/pyproject.toml",
                    "prerequisites": [],
                    "artifact": {
                        "type": "python-wheel",
                        "distribution": "core-tool",
                        "output-directory": "dist/core",
                        "filename-pattern": "core_tool-*.whl",
                    },
                    "actions": {
                        "build": _v4_action({"run": ["uv", "build", "packages/core"]})
                    },
                },
                "claims": {
                    "source": "packages/claims",
                    "project": "packages/claims/pyproject.toml",
                    "prerequisites": ["core"],
                    "artifact": {
                        "type": "python-wheel",
                        "distribution": "claims-tool",
                        "output-directory": "dist/claims",
                        "filename-pattern": "claims_tool-*.whl",
                    },
                    "actions": {
                        "build": _v4_action({"run": ["uv", "build", "packages/claims"]})
                    },
                },
            },
            "mcp-servers": {
                "insurance-claims-mcp-server": {
                    "source": "packages/claims",
                    "manifest": "packages/claims/mcp-server.json",
                    "prerequisites": ["claims"],
                    "actions": {
                        "validate": {
                            "requires": {"capabilities": []},
                            "no-op": "Package tests cover the MCP server.",
                        },
                        "install": _v4_action(
                            {
                                "handoff": {
                                    "lifecycle": "ceratops-mcp-server-lifecycle",
                                    "action": "install",
                                    "inputs": {"mcp-server": "insurance-claims-mcp-server"},
                                }
                            }
                        ),
                    },
                },
            },
            "apps": {
                "claims-mobile": {
                    "source": "apps/claims",
                    "manifest": "apps/claims/AndroidManifest.xml",
                    "prerequisites": ["claims"],
                    "actions": {
                        "validate": {
                            "requires": {"capabilities": []},
                            "no-op": "Repository checks cover the app.",
                        },
                        "install": _v4_action(
                            {
                                "run": [
                                    sys.executable,
                                    "-c",
                                    "from pathlib import Path; Path('app-installed.txt').write_text('done')",
                                ]
                            }
                        ),
                    },
                },
            },
            "skills": {
                "claims-catalog-invoice": {
                    "source": "skills/claims-catalog-invoice",
                    "prerequisites": ["claims"],
                    "actions": {
                        "validate": _v4_action(
                            {
                                "handoff": {
                                    "lifecycle": "ceratops-skill-lifecycle",
                                    "action": "source-validate",
                                    "inputs": {"skill": "claims-catalog-invoice"},
                                }
                            }
                        ),
                        "install": _v4_action(
                            {
                                "handoff": {
                                    "lifecycle": "ceratops-skill-lifecycle",
                                    "action": "deploy",
                                    "inputs": {"skill": "claims-catalog-invoice"},
                                }
                            }
                        ),
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
        "repository.actions.validate",
        "repository.actions.test",
    ]

    fixture = _v4_fixture()
    assert contracts.validation_errors(fixture) == []
    entries = contracts.operation_entries(fixture)
    assert set(entries) == {
        "repository.actions.validate",
        "repository.actions.test",
        "deliverables.packages.core.actions.build",
        "deliverables.packages.claims.actions.build",
        "deliverables.apps.claims-mobile.actions.validate",
        "deliverables.apps.claims-mobile.actions.install",
        "deliverables.mcp-servers.insurance-claims-mcp-server.actions.validate",
        "deliverables.mcp-servers.insurance-claims-mcp-server.actions.install",
        "deliverables.skills.claims-catalog-invoice.actions.validate",
        "deliverables.skills.claims-catalog-invoice.actions.install",
    }
    assert (
        runner.operation_category("deliverables.packages.claims.actions.build")
        == "build"
    )
    assert (
        runner.operation_category("deliverables.apps.claims-mobile.actions.install")
        == "deploy-local"
    )
    assert (
        runner.operation_category(
            "deliverables.mcp-servers.insurance-claims-mcp-server.actions.install"
        )
        == "deploy-local"
    )
    with pytest.raises(runner.OperationError, match="Invalid SDLC operation location"):
        runner.operation_category(
            "deliverables.skills.claims-catalog-invoice.actions.build"
        )


def test_v4_prerequisites_are_exposed_without_build_or_install(
    tmp_path: pathlib.Path,
) -> None:
    fixture = _v4_fixture()
    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(fixture))
    _repository(tmp_path)
    (tmp_path / "uncommitted.txt").write_text("inspection must remain read-only")
    location = "deliverables.skills.claims-catalog-invoice.actions.install"
    prepared = runner.prepare_operations(tmp_path, [runner.OperationRequest(location)])[
        0
    ]
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
    assert runner.validation_operations(
        tmp_path, ["deliverables.apps.claims-mobile.actions.install"]
    ) == [
        "repository.actions.validate",
        "deliverables.apps.claims-mobile.actions.validate",
        "repository.actions.test",
    ]
    assert runner.validation_operations(
        tmp_path, ["deliverables.mcp-servers.insurance-claims-mcp-server.actions.install"]
    ) == [
        "repository.actions.validate",
        "deliverables.mcp-servers.insurance-claims-mcp-server.actions.validate",
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


def _build_receipt_fixture(tmp_path: pathlib.Path):
    """The repository runner owns cleanup of all files beneath this pytest root."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    def file(path: str, content: bytes, kind: str, deliverable: str | None = None):
        target = bundle / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        record = {
            "type": kind,
            "path": path,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        return {**record, **({"deliverable": deliverable} if deliverable else {})}

    identity = {
        "repository": "example/project",
        "sourceCommit": "a" * 40,
        "releaseUnit": "claims",
        "channel": "beta",
        "version": "1.2.0b1",
        "target": "python-3.14-windows",
    }
    artifact = file(
        "wheels/claims.whl",
        b"primary wheel",
        "python-wheel",
        "deliverables.packages.claims",
    )
    app = file(
        "apps/desktop.zip", b"non-python artifact", "zip", "deliverables.apps.desktop"
    )
    dependency = file(
        "dependencies/converter.whl",
        b"dependency wheel",
        "python-wheel",
        "deliverables.packages.converter",
    )
    lock = file("locks/pylock.toml", b"", "dependency-lock")
    evidence = file("tests/results.json", b'{"status":"passed"}\n', "test-evidence")

    def reference(entry):
        return {key: entry[key] for key in ("path", "sha256")}

    receipt = {
        "schema": "ceratops-build-result.v2",
        "status": "passed",
        "identity": identity,
        "artifacts": [artifact, app],
        "dependencies": [
            {
                "identity": {
                    **identity,
                    "releaseUnit": "converter",
                    "version": "0.4.0",
                },
                "artifacts": [dependency],
            }
        ],
        "supportingFiles": [lock, evidence],
        "tests": [
            {
                "id": "installed-artifact",
                "status": "passed",
                "artifacts": [
                    reference(artifact),
                    reference(app),
                    reference(dependency),
                ],
                "evidence": reference(evidence),
            }
        ],
    }
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path, bundle, receipt, dict(identity)


def _save_build_receipt(path: pathlib.Path, receipt: dict[str, Any]) -> None:
    path.write_text(json.dumps(receipt), encoding="utf-8")


def test_build_receipt_verifies_complete_bundle_without_mutation(
    tmp_path, monkeypatch
) -> None:
    path, bundle, receipt, expected = _build_receipt_fixture(tmp_path)
    before = {
        item: (item.read_bytes(), item.stat().st_mtime_ns)
        for item in tmp_path.rglob("*")
        if item.is_file()
    }
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: pytest.fail("Verifier must not execute commands"),
    )
    checked = results.verify_release_unit_build(path, bundle, expected=expected)
    assert checked == receipt
    assert {
        item: (item.read_bytes(), item.stat().st_mtime_ns)
        for item in tmp_path.rglob("*")
        if item.is_file()
    } == before


def test_build_receipt_ignores_metadata_only_change_time(tmp_path, monkeypatch) -> None:
    path, bundle, receipt, expected = _build_receipt_fixture(tmp_path)
    original_plain_path = results._plain_path

    def changed_metadata(*args, **kwargs):
        checked, info = original_plain_path(*args, **kwargs)
        values = {
            field: getattr(info, field)
            for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        }
        values["st_ctime_ns"] += 1
        return checked, SimpleNamespace(**values)

    # Simulate Windows metadata changes without touching file identity or bytes.
    monkeypatch.setattr(results, "_plain_path", changed_metadata)
    assert results.verify_release_unit_build(path, bundle, expected=expected) == receipt


@pytest.mark.parametrize("build_status", ["passed", "failed", "blocked"])
@pytest.mark.parametrize(
    "test_status", ["passed", "failed", "blocked", "skipped", None]
)
def test_build_receipt_integrity_does_not_establish_test_success(
    tmp_path,
    build_status: str,
    test_status: str | None,
) -> None:
    path, bundle, receipt, expected = _build_receipt_fixture(tmp_path)
    receipt["status"] = build_status
    if test_status is None:
        receipt["tests"] = []
    else:
        receipt["tests"][0]["status"] = test_status
        if test_status in {"blocked", "skipped"}:
            receipt["tests"][0]["evidence"] = None
    _save_build_receipt(path, receipt)
    assert results.verify_release_unit_build(path, bundle, expected=expected) == receipt


@pytest.mark.parametrize(
    "field",
    ["repository", "sourceCommit", "releaseUnit", "channel", "version", "target"],
)
def test_build_receipt_checks_each_expected_identity_before_payload_reads(
    tmp_path, monkeypatch, field
) -> None:
    path, bundle, _, expected = _build_receipt_fixture(tmp_path)
    expected[field] = "different"
    monkeypatch.setattr(
        results,
        "_verify_bundle_file",
        lambda *a: pytest.fail("Identity must be checked first"),
    )
    with pytest.raises(results.StepResultError, match=f"identity mismatch: {field}"):
        results.verify_release_unit_build(path, bundle, expected=expected)


@pytest.mark.parametrize(
    "problem", ["missing", "extra", "empty", "non-string", "not-mapping"]
)
def test_build_receipt_requires_complete_independent_selection(
    tmp_path, problem
) -> None:
    path, bundle, _, expected = _build_receipt_fixture(tmp_path)
    if problem == "missing":
        expected.pop("channel")
    elif problem == "extra":
        expected["unexpected"] = "value"
    elif problem == "empty":
        expected["target"] = " "
    elif problem == "non-string":
        expected["version"] = 1
    else:
        expected = None
    with pytest.raises(results.StepResultError, match="all six"):
        results.verify_release_unit_build(path, bundle, expected=expected)


@pytest.mark.parametrize(
    "problem",
    [
        "missing-field",
        "unknown-field",
        "bad-channel",
        "bad-commit",
        "bad-owner",
        "bad-digest",
        "negative-size",
        "boolean-size",
        "no-artifacts",
        "missing-test-evidence",
    ],
)
def test_build_receipt_rejects_invalid_schema(tmp_path, problem) -> None:
    path, bundle, receipt, expected = _build_receipt_fixture(tmp_path)
    if problem == "missing-field":
        receipt.pop("dependencies")
    elif problem == "unknown-field":
        receipt["extra"] = "value"
    elif problem in {"bad-channel", "bad-commit"}:
        receipt["identity"][
            "channel" if problem == "bad-channel" else "sourceCommit"
        ] = "invalid"
    elif problem == "no-artifacts":
        receipt["artifacts"] = []
    elif problem == "missing-test-evidence":
        receipt["tests"][0]["evidence"] = None
    else:
        key, value = {
            "bad-owner": ("deliverable", "packages.claims"),
            "bad-digest": ("sha256", "xyz"),
            "negative-size": ("size", -1),
            "boolean-size": ("size", True),
        }[problem]
        receipt["artifacts"][0][key] = value
    _save_build_receipt(path, receipt)
    with pytest.raises(results.StepResultError, match="schema"):
        results.verify_release_unit_build(path, bundle, expected=expected)


@pytest.mark.parametrize(
    "problem",
    [
        "duplicate-artifact",
        "case-alias",
        "dependency-path",
        "support-path",
        "duplicate-dependency",
        "competing-version",
        "self-dependency",
        "duplicate-test",
        "unknown-tested-file",
        "wrong-tested-hash",
        "duplicate-tested-file",
        "unknown-evidence",
        "wrong-evidence-hash",
        "wrong-evidence-type",
    ],
)
def test_build_receipt_rejects_ambiguous_inventory_before_payload_reads(
    tmp_path, monkeypatch, problem
) -> None:
    path, bundle, receipt, expected = _build_receipt_fixture(tmp_path)
    artifact = receipt["artifacts"][0]
    test = receipt["tests"][0]
    if problem in {"duplicate-artifact", "case-alias"}:
        duplicate = deepcopy(artifact)
        if problem == "case-alias":
            duplicate["path"] = duplicate["path"].upper()
        receipt["artifacts"].append(duplicate)
    elif problem == "dependency-path":
        receipt["dependencies"][0]["artifacts"][0]["path"] = artifact["path"]
    elif problem == "support-path":
        receipt["supportingFiles"][0]["path"] = artifact["path"]
    elif problem in {"duplicate-dependency", "competing-version"}:
        duplicate = deepcopy(receipt["dependencies"][0])
        if problem == "competing-version":
            duplicate["identity"]["version"] = "9.0.0"
        receipt["dependencies"].append(duplicate)
    elif problem == "self-dependency":
        receipt["dependencies"][0]["identity"]["releaseUnit"] = expected["releaseUnit"]
    elif problem == "duplicate-test":
        receipt["tests"].append(deepcopy(test))
    elif problem == "unknown-tested-file":
        test["artifacts"][0]["path"] = "unknown.whl"
    elif problem == "wrong-tested-hash":
        test["artifacts"][0]["sha256"] = "b" * 64
    elif problem == "duplicate-tested-file":
        test["artifacts"].append(deepcopy(test["artifacts"][0]))
    elif problem == "unknown-evidence":
        test["evidence"]["path"] = "unknown.json"
    elif problem == "wrong-evidence-hash":
        test["evidence"]["sha256"] = "b" * 64
    else:
        receipt["supportingFiles"][1]["type"] = "dependency-lock"
    _save_build_receipt(path, receipt)
    monkeypatch.setattr(
        results,
        "_verify_bundle_file",
        lambda *a: pytest.fail("Inventory must be checked first"),
    )
    with pytest.raises(results.StepResultError):
        results.verify_release_unit_build(path, bundle, expected=expected)


@pytest.mark.parametrize(
    "bad_path",
    [
        "../outside.whl",
        "/absolute.whl",
        "C:/absolute.whl",
        r"C:\absolute.whl",
        r"\\server\share\wheel.whl",
        "wheels/../claims.whl",
        "wheels//claims.whl",
        "wheels/./claims.whl",
        "wheels/",
        "wheels/claims.whl:stream",
        "wheels/claims.whl.",
        "wheels/claims.whl ",
        "wheels/NUL.whl",
        "wheels/COM1/file.whl",
        "wheels/a?.whl",
        "wheels/a\n.whl",
        "wheels/a\0.whl",
    ],
)
def test_build_receipt_rejects_nonportable_or_escaping_paths(
    tmp_path, monkeypatch, bad_path
) -> None:
    path, bundle, receipt, expected = _build_receipt_fixture(tmp_path)
    receipt["artifacts"][0]["path"] = bad_path
    _save_build_receipt(path, receipt)
    monkeypatch.setattr(
        results,
        "_verify_bundle_file",
        lambda *a: pytest.fail("Unsafe paths must be rejected first"),
    )
    with pytest.raises(results.StepResultError):
        results.verify_release_unit_build(path, bundle, expected=expected)


@pytest.mark.parametrize("group", ["artifact", "dependency", "lock", "evidence"])
@pytest.mark.parametrize("problem", ["missing", "size", "hash", "directory"])
def test_build_receipt_verifies_every_file_category(tmp_path, group, problem) -> None:
    path, bundle, receipt, expected = _build_receipt_fixture(tmp_path)
    record = {
        "artifact": receipt["artifacts"][0],
        "dependency": receipt["dependencies"][0]["artifacts"][0],
        "lock": receipt["supportingFiles"][0],
        "evidence": receipt["supportingFiles"][1],
    }[group]
    target = bundle / record["path"]
    if problem in {"missing", "directory"}:
        target.unlink()
        if problem == "directory":
            target.mkdir()
    elif problem == "size":
        target.write_bytes(target.read_bytes() + b"x")
    else:
        record["sha256"] = "b" * 64
        if group == "evidence":
            receipt["tests"][0]["evidence"]["sha256"] = record["sha256"]
        for reference in receipt["tests"][0]["artifacts"]:
            if reference["path"] == record["path"]:
                reference["sha256"] = record["sha256"]
    _save_build_receipt(path, receipt)
    with pytest.raises(results.StepResultError):
        results.verify_release_unit_build(path, bundle, expected=expected)


@pytest.mark.parametrize(
    "problem",
    [
        "json",
        "duplicate-key",
        "nonfinite",
        "depth",
        "large",
        "utf8",
        "array",
        "old-schema",
    ],
)
def test_build_receipt_rejects_unusable_json(tmp_path, problem) -> None:
    path, bundle, receipt, expected = _build_receipt_fixture(tmp_path)
    raw = {
        "json": b"{",
        "duplicate-key": b'{"schema":"a","schema":"b","status":"passed"}',
        "nonfinite": b'{"schema":"a","status":"passed","extra":NaN}',
        "depth": (
            '{"schema":"a","status":"passed","extra":' + "[" * 70 + "0" + "]" * 70 + "}"
        ).encode(),
        "large": b" " * (results.STEP_RESULT_BYTES + 1),
        "utf8": b"\xff",
        "array": b"[]",
        "old-schema": json.dumps(
            {**receipt, "schema": "ceratops-build-result.v1"}
        ).encode(),
    }[problem]
    path.write_bytes(raw)
    with pytest.raises(results.StepResultError):
        results.verify_release_unit_build(path, bundle, expected=expected)


def test_build_receipt_rejects_hardlinked_payload(tmp_path) -> None:
    path, bundle, receipt, expected = _build_receipt_fixture(tmp_path)
    os.link(bundle / receipt["artifacts"][0]["path"], tmp_path / "other-link.whl")
    with pytest.raises(results.StepResultError, match="regular and unlinked"):
        results.verify_release_unit_build(path, bundle, expected=expected)


@pytest.mark.parametrize("linked_root", [False, True])
def test_build_receipt_rejects_directory_links(tmp_path, linked_root) -> None:
    path, bundle, receipt, expected = _build_receipt_fixture(tmp_path)
    link = tmp_path / "linked-bundle" if linked_root else bundle / "linked-wheels"
    target = bundle if linked_root else bundle / "wheels"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        made = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert made.returncode == 0, made.stderr
    try:
        if linked_root:
            bundle = link
        else:
            receipt["artifacts"][0]["path"] = "linked-wheels/claims.whl"
            receipt["tests"][0]["artifacts"][0]["path"] = "linked-wheels/claims.whl"
            _save_build_receipt(path, receipt)
        with pytest.raises(results.StepResultError, match="traverses a link"):
            results.verify_release_unit_build(path, bundle, expected=expected)
    finally:
        # Remove only the test-owned link, never its target or descendants.
        if link.is_symlink():
            link.unlink()
        else:
            link.rmdir()


def test_build_receipt_detects_changes_during_hashing(tmp_path, monkeypatch) -> None:
    path, bundle, receipt, expected = _build_receipt_fixture(tmp_path)
    target = bundle / receipt["artifacts"][0]["path"]
    original_hash = hashlib.sha256

    class ChangingHash:
        def __init__(self):
            self.digest = original_hash()

        def update(self, data):
            self.digest.update(data)
            target.write_bytes(b"changed")

        def hexdigest(self):
            return self.digest.hexdigest()

    monkeypatch.setattr(results.hashlib, "sha256", ChangingHash)
    with pytest.raises(results.StepResultError, match="changed while reading"):
        results.verify_release_unit_build(path, bundle, expected=expected)


@pytest.mark.parametrize(
    "schema", ["ceratops-build-result.v1", "ceratops-build-result.v2"]
)
def test_build_receipt_does_not_add_artifact_reads_to_capture(
    tmp_path, monkeypatch, schema
) -> None:
    _, _, receipt, _ = _build_receipt_fixture(tmp_path)
    value = (
        receipt
        if schema.endswith("v2")
        else {
            "schema": schema,
            "status": "passed",
            "artifact": {
                key: receipt["artifacts"][0][key]
                for key in ("type", "path", "sha256", "size")
            },
        }
    )
    monkeypatch.setattr(
        results,
        "_plain_path",
        lambda *a, **k: pytest.fail("Capture must not inspect artifacts"),
    )
    assert results.capture_step_result(json.dumps(value), expected_schema=schema) == {
        "result": value
    }


def test_build_receipt_cli_works_from_isolated_skill_and_preserves_inputs(
    tmp_path,
) -> None:
    path, bundle, _, expected = _build_receipt_fixture(tmp_path)
    installed = tmp_path / "installed-skill"
    script = installed / "scripts/sdlc_results.py"
    schema = installed / "references/schemas/operation-result.v1.schema.json"
    script.parent.mkdir(parents=True)
    schema.parent.mkdir(parents=True)
    shutil.copy2(REPOSITORY_LIFECYCLE_SCRIPTS / script.name, script)
    shutil.copy2(results.OPERATION_RESULT_SCHEMA, schema)
    argv = [
        sys.executable,
        "-B",
        str(script),
        "verify-release-unit-build",
        "--receipt",
        str(path),
        "--bundle-root",
        str(bundle),
    ]
    for field, flag in zip(
        results.BUILD_SELECTION_FIELDS,
        [
            "--repository",
            "--source-commit",
            "--release-unit",
            "--channel",
            "--version",
            "--target",
        ],
        strict=True,
    ):
        argv.extend([flag, expected[field]])
    before = {item: item.read_bytes() for item in tmp_path.rglob("*") if item.is_file()}
    passed = subprocess.run(
        argv, cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert (passed.returncode, passed.stdout.strip(), passed.stderr) == (
        0,
        "RECEIPT_VERIFIED",
        "",
    )
    assert {
        item: item.read_bytes() for item in tmp_path.rglob("*") if item.is_file()
    } == before
    wrong = subprocess.run(
        [*argv[:-1], "wrong-target"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert wrong.returncode == 2 and "identity mismatch: target" in wrong.stderr
    assert not wrong.stdout
    missing = subprocess.run(
        argv[:-2], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert missing.returncode == 2 and "--target" in missing.stderr


def test_v4_source_installed_mcp_server_needs_no_package_artifact(
    tmp_path: pathlib.Path,
) -> None:
    fixture = _v4_fixture()
    mcp_server = fixture["deliverables"]["mcp-servers"]["insurance-claims-mcp-server"]
    mcp_server["prerequisites"] = []
    assert contracts.validation_errors(fixture) == []

    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(fixture))
    _repository(tmp_path)
    location = "deliverables.mcp-servers.insurance-claims-mcp-server.actions.install"
    prepared = runner.prepare_operations(tmp_path, [runner.OperationRequest(location)])[
        0
    ]
    assert prepared.prerequisites["packages"] == {}
    assert prepared.steps[0].handoff["action"] == "install"
    assert not (tmp_path / "dist").exists()


def test_v4_mcp_server_install_can_run_standalone_script(tmp_path: pathlib.Path) -> None:
    fixture = _v4_fixture()
    mcp_server = fixture["deliverables"]["mcp-servers"]["insurance-claims-mcp-server"]
    mcp_server["actions"]["install"] = _v4_action(
        {
            "run": [
                sys.executable,
                "-c",
                "from pathlib import Path; Path('installed.txt').write_text('done')",
            ]
        }
    )
    assert contracts.validation_errors(fixture) == []
    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(fixture))
    prepared = runner.prepare_operations(
        tmp_path,
        [
            runner.OperationRequest(
                "deliverables.mcp-servers.insurance-claims-mcp-server.actions.install",
            )
        ],
    )[0]
    result = runner.execute_prepared_operation(prepared)
    assert result["status"] == "completed"
    assert result["steps"] == [1]
    assert (tmp_path / "installed.txt").read_text() == "done"


def test_v4_app_install_can_run_standalone_script(tmp_path: pathlib.Path) -> None:
    fixture = _v4_fixture()
    assert contracts.validation_errors(fixture) == []
    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(fixture))
    prepared = runner.prepare_operations(
        tmp_path,
        [
            runner.OperationRequest(
                "deliverables.apps.claims-mobile.actions.install",
            )
        ],
    )[0]
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
    action["steps"] = [
        {
            "run": [
                sys.executable,
                "-c",
                f"import json; print(json.dumps({payload!r}))",
            ]
        }
    ]
    assert contracts.validation_errors(fixture) == []
    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(fixture))
    prepared = runner.prepare_operations(
        tmp_path,
        [
            runner.OperationRequest(
                "deliverables.apps.claims-mobile.actions.install",
            )
        ],
    )[0]
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
    action["steps"] = [
        {
            "run": [
                sys.executable,
                "-c",
                "from pathlib import Path; Path('installed.txt').write_text('done'); print('{}')",
            ]
        }
    ]
    assert contracts.validation_errors(fixture) == []
    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(fixture))
    prepared = runner.prepare_operations(
        tmp_path,
        [
            runner.OperationRequest(
                "deliverables.apps.claims-mobile.actions.install",
            )
        ],
    )[0]
    result = runner.execute_prepared_operation(prepared)
    assert result["status"] == "result_invalid"
    assert result["steps"] == [1]
    assert "Do not replay" in result["message"]
    assert (tmp_path / "installed.txt").read_text() == "done"


@pytest.mark.parametrize("mode", ["skill", "ci", "return"])
def test_v4_runs_commands_then_returns_structured_handoff(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "unregistered"))
    fixture = _v4_fixture()
    action = fixture["deliverables"]["skills"]["claims-catalog-invoice"]["actions"][
        "install"
    ]
    action["steps"].insert(
        0,
        {
            "run": [
                sys.executable,
                "-c",
                "from pathlib import Path; Path('ran.txt').write_text('done')",
            ]
        },
    )
    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(fixture))
    location = "deliverables.skills.claims-catalog-invoice.actions.install"
    prepared = runner.prepare_operations(
        tmp_path,
        [runner.OperationRequest(location)],
        context=mode,
    )[0]
    result = runner.execute_prepared_operation(prepared)
    assert result["steps"] == [1]
    assert result["status"] == (
        "deferred_handoff" if mode == "ci" else "handoff_required"
    )
    assert result["handoff"] == {
        "lifecycle": "ceratops-skill-lifecycle",
        "action": "deploy",
        "inputs": {"skill": "claims-catalog-invoice"},
    }
    assert (tmp_path / "ran.txt").read_text() == "done"


def test_v4_package_build_waits_for_declared_test_gate(tmp_path: pathlib.Path) -> None:
    fixture = _v4_fixture()
    fixture["repository"]["actions"]["test"] = _v4_action(
        {
            "run": [sys.executable, "-c", "raise SystemExit(7)"],
        }
    )
    fixture["deliverables"]["packages"]["claims"]["actions"]["build"] = _v4_action(
        {
            "run": [
                sys.executable,
                "-c",
                "from pathlib import Path; Path('built.txt').write_text('bad')",
            ],
        }
    )
    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(fixture))
    result = run_operation_cli(tmp_path, "deliverables.packages.claims.actions.build")
    assert result.returncode == 1
    assert json.loads(result.stderr)["status"] == "tests_failed"
    assert not (tmp_path / "built.txt").exists()


@pytest.mark.parametrize(
    "change, expected",
    [
        (
            lambda x: x["deliverables"]["skills"]["claims-catalog-invoice"].update(
                prerequisites=["missing"]
            ),
            "unknown package missing",
        ),
        (
            lambda x: x["deliverables"]["packages"]["core"].update(
                prerequisites=["claims"]
            ),
            "package prerequisite cycle",
        ),
        (
            lambda x: x["deliverables"]["mcp-servers"]["insurance-claims-mcp-server"]["actions"][
                "install"
            ]["steps"][0]["handoff"].update(lifecycle="ceratops-skill-lifecycle"),
            "must hand off to ceratops-mcp-server-lifecycle",
        ),
        (
            lambda x: x["deliverables"]["mcp-servers"]["insurance-claims-mcp-server"][
                "actions"
            ].update(
                install={
                    "requires": {"capabilities": []},
                    "no-op": "Cannot install without lifecycle.",
                }
            ),
            "must end with a handoff",
        ),
        (
            lambda x: x["deliverables"]["skills"]["claims-catalog-invoice"]["actions"][
                "install"
            ].update(
                steps=[
                    {
                        "handoff": {
                            "lifecycle": "ceratops-skill-lifecycle",
                            "action": "deploy",
                            "inputs": {},
                        }
                    },
                    {"run": ["python"]},
                ]
            ),
            "handoff must be the single final step",
        ),
        (
            lambda x: x["deliverables"]["packages"]["claims"]["artifact"].update(
                **{"filename-pattern": "../wrong.whl"}
            ),
            "filename-pattern must be a filename pattern",
        ),
        (
            lambda x: x["deliverables"]["mcp-servers"]["insurance-claims-mcp-server"]["actions"][
                "install"
            ]["steps"][0]["handoff"]["inputs"].update(
                **{"prerequisite-packages": ["core"]}
            ),
            "prerequisite-packages differ from prerequisites",
        ),
        (
            lambda x: x["repository"]["capabilities"]["uv"].update(
                **{
                    "version-from": {
                        "file": "folder\\tool.toml",
                        "key": "project.version",
                    }
                }
            ),
            "capability uv version-from.file must be repository-relative",
        ),
        (
            lambda x: x["repository"]["capabilities"]["uv"].update(
                version="1.0", channel="stable"
            ),
            "multiple version authorities",
        ),
        (
            lambda x: x["deliverables"]["apps"]["claims-mobile"]["actions"][
                "install"
            ].update(**{"result-schema": "ceratops-build-result.v1"}),
            "result-schema must be ceratops-deployment-result.v1",
        ),
        (
            lambda x: x["deliverables"]["skills"]["claims-catalog-invoice"]["actions"][
                "install"
            ].update(**{"result-schema": "ceratops-deployment-result.v1"}),
            "result-schema requires a final run step",
        ),
    ],
)
def test_v4_rejects_invalid_dependency_or_lifecycle_boundary(
    change, expected: str
) -> None:
    fixture = _v4_fixture()
    change(fixture)
    assert any(expected in error for error in contracts.validation_errors(fixture))


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x["deliverables"]["apps"]["claims-mobile"]["actions"].update(
            build=_v4_action({"run": ["python"]})
        ),
        lambda x: x["deliverables"]["mcp-servers"]["insurance-claims-mcp-server"].update(
            package="claims"
        ),
        lambda x: x["deliverables"]["mcp-servers"]["insurance-claims-mcp-server"].update(
            prerequisites=["core", "claims"]
        ),
        lambda x: x["deliverables"]["skills"]["claims-catalog-invoice"]["actions"][
            "install"
        ].update(**{"no-op": "nothing to install"}),
        lambda x: x["deliverables"]["skills"]["claims-catalog-invoice"]["actions"][
            "install"
        ]["steps"][0].update(run=["python"]),
        lambda x: x["deliverables"]["skills"]["claims-catalog-invoice"][
            "actions"
        ].update(build=_v4_action({"run": ["python"]})),
    ],
)
def test_v4_schema_rejects_ambiguous_steps_or_wrong_deliverable_actions(change) -> None:
    fixture = _v4_fixture()
    change(fixture)
    assert contracts.validation_errors(fixture)


@pytest.mark.skipif(
    shutil.which("uv") is None, reason="uv is required for installed Python actions"
)
def test_registered_skill_executor_is_portable_and_failure_is_not_completion(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoffs = runner
    skill = tmp_path / "skills/example-skill"
    (skill / "references").mkdir(parents=True)
    (skill / "scripts").mkdir()
    python = (
        tmp_path
        / "runtimes/ceratops/versions/test/.venv"
        / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    created = subprocess.run(
        [sys.executable, "-m", "venv", "--copies", str(python.parent.parent)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert created.returncode == 0, created.stderr
    assert not python.is_symlink()
    (skill / ".runtime-manifest.json").write_text(
        json.dumps({"python_runtime": str(python)})
    )
    script = skill / "probe.py"
    script.write_text(
        "import pathlib, sys\npathlib.Path(sys.argv[1], 'called.txt').write_text('called')\nraise SystemExit(int(sys.argv[2]))\n"
    )
    binding = skill / "references/action-executors.json"
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    repo = tmp_path / "repository"
    repo.mkdir()
    for code, expected in ((0, "completed"), (9, "operation_failed")):
        binding.write_text(
            json.dumps(
                {
                    "version": 1,
                    "actions": {
                        "check": {
                            "run": [
                                "{python}",
                                "{skill_root}/probe.py",
                                "{repo_root}",
                                str(code),
                            ]
                        }
                    },
                }
            )
        )
        assert (
            handoffs.execute_handoff("example-skill/check", repo)["status"] == expected
        )
        assert (repo / "called.txt").read_text() == "called"
    assert (
        handoffs.execute_handoff("example-skill/unknown", repo)["status"]
        == "handoff_required"
    )
    receipt = {
        "schema": "fixture.deployment.v1",
        "status": "deployed",
        "entities": ["one"],
    }
    script.write_text("import json\nprint(json.dumps(" + repr(receipt) + "))\n")
    binding.write_text(
        json.dumps(
            {
                "version": 1,
                "actions": {
                    "check": {
                        "steps": [
                            {"run": ["{python}", "{skill_root}/probe.py"]},
                            {"run": [sys.executable, "-c", "raise SystemExit(7)"]},
                        ]
                    }
                },
            }
        )
    )
    result = handoffs.execute_handoff("example-skill/check", repo)
    assert result["status"] == "operation_failed"
    assert result["steps"] == [1]
    assert result["step_results"] == [{"step": 1, "result": receipt}]
    (skill / ".runtime-manifest.json").unlink()
    assert (
        handoffs.execute_handoff("example-skill/check", repo)["status"]
        == "handoff_required"
    )


def test_registered_skill_executor_uses_installed_authorized_source_bundle(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
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
        "actions": {"check": {"run": ["{python}", "{skill_root}/scripts/probe.py"]}},
    }
    encoded = json.dumps(binding)
    for root in (installed, source):
        (root / "references" / "action-executors.json").write_text(encoded)
        (root / "scripts" / "probe.py").write_text("print('OK')\n")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(
        handoffs.shutil, "which", lambda name: "uv" if name == "uv" else None
    )
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(handoffs.subprocess, "run", run)
    assert (
        handoffs.execute_handoff("example-skill/check", source_repo)["status"]
        == "completed"
    )
    assert (
        pathlib.Path(calls[0][-1]).resolve()
        == (source / "scripts" / "probe.py").resolve()
    )
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
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    handoffs = runner
    skill = tmp_path / "skills/ceratops-mcp-server-lifecycle/references"
    skill.mkdir(parents=True)
    shutil.copyfile(
        ROOT / "skills/ceratops-mcp-server-lifecycle/references/action-executors.json",
        skill / "action-executors.json",
    )
    source = tmp_path / "repo with spaces & punctuation/skills/ceratops-mcp-server-lifecycle"
    (source / "references").mkdir(parents=True)
    shutil.copyfile(skill / "action-executors.json", source / "references/action-executors.json")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    repo = tmp_path / "repo with spaces & punctuation"
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if failure == "missing_manager":
            raise FileNotFoundError("manager launcher missing")
        return subprocess.CompletedProcess(
            argv, 7 if failure else 0, "OK\n", "candidate failed" if failure else ""
        )

    monkeypatch.setattr(handoffs.subprocess, "run", run)
    result = handoffs.execute_handoff("ceratops-mcp-server-lifecycle/install", repo)
    assert result["status"] == ("operation_failed" if failure else "completed")
    assert calls[0][0] == [
        sys.executable,
        "-I",
        "-B",
        str(source) + "/scripts/install-mcp-server.py",
        "--repo-root",
        str(repo),
    ]
    assert calls[0][1]["cwd"] == repo
    assert not calls[0][1].get("shell", False)


def test_tool_install_helper_attests_existing_manager_result_without_reinstall(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects = tmp_path / "projects"
    repo = projects / "claims"
    repo.mkdir(parents=True)
    (repo / "source.txt").write_text("source\n", encoding="utf-8")
    commit = _repository(repo)
    task = projects / "tmp/claims/task"
    task.mkdir(parents=True)
    operation = "deliverables.mcp-servers.insurance-claims-mcp-server.actions.install"
    promotion = {
        "status": "ready",
        "head": commit,
        "operations": {
            "status": "completed",
            "pending_operations": [],
            "completed_operations": [operation],
            "results": [
                {
                    "operation": operation,
                    "commit": commit,
                    "status": "completed",
                    "steps": [],
                    "handoff": "ceratops-mcp-server-lifecycle/install",
                }
            ],
        },
    }
    promotion_path = task / "promotion.json"
    promotion_path.write_text(json.dumps(promotion), encoding="utf-8")
    manager_result = {
        "installed_version": "1.2.3",
        "manifest_sha256": "a" * 64,
        "reconnection_required": False,
        "running_version": None,
        "mcp_server_name": "insurance-claims-mcp-server",
    }
    manager_path = task / "manager.json"
    manager_path.write_text(json.dumps(manager_result), encoding="utf-8")
    install_root = tmp_path / "installed"
    instance = "b" * 32
    selected = {
        "schema": 1,
        "mcp_server_id": "insurance-claims-mcp-server",
        "version": "1.2.3",
        "manifest_sha256": "a" * 64,
        "instance": instance,
        "module": "insurance_claims_tool",
    }
    mcp_server_root = install_root / "insurance-claims-mcp-server"
    immutable = mcp_server_root / "versions/1.2.3" / instance
    immutable.mkdir(parents=True)
    (mcp_server_root / "current.json").write_text(json.dumps(selected), encoding="utf-8")
    (immutable / "receipt.json").write_text(json.dumps(selected), encoding="utf-8")
    helper = runpy.run_path(
        str(ROOT / "skills/ceratops-mcp-server-lifecycle/scripts/install-mcp-server.py")
    )
    monkeypatch.setitem(helper["main"].__globals__, "INSTALL_ROOT", install_root)
    output = task / "mcp-server-completion.json"
    code = helper["main"](
        [
            "--repo-root",
            str(repo),
            "--mcp-server-name",
            "insurance-claims-mcp-server",
            "--manager-result",
            str(manager_path),
            "--promotion-result",
            str(promotion_path),
            "--operation",
            operation,
            "--evidence-output",
            str(output),
        ]
    )
    assert code == 0
    receipt = json.loads(capsys.readouterr().out)
    assert json.loads(output.read_text(encoding="utf-8")) == receipt
    assert receipt["producer"] == "ceratops-mcp-server-lifecycle/install"
    assert receipt["commit"] == commit
    assert receipt["deployed"] == ["insurance-claims-mcp-server"]
    assert receipt["transaction_id"] == instance
    assert receipt["promotion"]["operation"] == operation
    promote = runpy.run_path(
        str(ROOT / "skills/ceratops-repo-lifecycle/scripts/promote-repository.py")
    )
    binding = dict(receipt["promotion"])
    binding.pop("operation")
    promote["_completed_deployment"](
        promotion,
        commit,
        repo_root=repo,
        external={operation: receipt},
        record_binding=binding,
    )


def test_tool_install_helper_runs_manager_once_and_attests_selection(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "source.txt").write_text("source\n", encoding="utf-8")
    commit = _repository(repo)
    payload = {
        "installed_version": "2.0.0",
        "manifest_sha256": "c" * 64,
        "reconnection_required": False,
        "running_version": None,
        "mcp_server_name": "sample-mcp-server",
    }
    install_root = tmp_path / "installed"
    instance = "d" * 32
    selected = {
        "schema": 1,
        "mcp_server_id": "sample-mcp-server",
        "version": "2.0.0",
        "manifest_sha256": "c" * 64,
        "instance": instance,
        "module": "sample_tool",
    }
    mcp_server_root = install_root / "sample-mcp-server"
    immutable = mcp_server_root / "versions/2.0.0" / instance
    immutable.mkdir(parents=True)
    (mcp_server_root / "current.json").write_text(json.dumps(selected), encoding="utf-8")
    (immutable / "receipt.json").write_text(json.dumps(selected), encoding="utf-8")
    helper = runpy.run_path(
        str(ROOT / "skills/ceratops-mcp-server-lifecycle/scripts/install-mcp-server.py")
    )
    calls = []

    def install(args, source_root):
        calls.append((args.mcp_server_name, source_root))
        return payload

    monkeypatch.setitem(helper["main"].__globals__, "INSTALL_ROOT", install_root)
    monkeypatch.setitem(helper["main"].__globals__, "_install", install)
    assert helper["main"](
        ["--repo-root", str(repo), "--mcp-server-name", "sample-mcp-server"]
    ) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert calls == [("sample-mcp-server", repo)]
    assert receipt["commit"] == commit
    assert receipt["promotion"] is None
    assert receipt["transaction_id"] == instance


def _registered_skill_fixture(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> pathlib.Path:
    """Use real subprocesses with fixture lifecycle CLIs that enforce selection."""
    repo = tmp_path / "source"
    source = repo / "skills/ceratops-skill-lifecycle"
    installed = tmp_path / "codex/skills/ceratops-skill-lifecycle"
    binding = (
        ROOT / "skills/ceratops-skill-lifecycle/references/action-executors.json"
    ).read_bytes()
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
    for script in (
        "scripts/skills-consistency-source-validator.py",
        "scripts/runtime/install-managed-skills.py",
    ):
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
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    action: str,
) -> None:
    repo = _registered_skill_fixture(tmp_path, monkeypatch)
    location = f"deliverables.skills.claims-catalog-invoice.actions.{action}"
    prepared = runner.prepare_operations(
        repo, [runner.OperationRequest(location)], context=mode
    )[0]
    result = runner.execute_prepared_operation(prepared)
    assert list(result["prerequisites"]["packages"]) == ["core", "claims"]
    if mode != "skill":
        assert result["status"] == (
            "deferred_handoff" if mode == "ci" else "handoff_required"
        )
        assert not (repo / "calls.jsonl").exists()
        return
    assert result["status"] == "completed", result
    calls = [
        json.loads(line) for line in (repo / "calls.jsonl").read_text().splitlines()
    ]
    expected: list[dict[str, str | None]] = [
        {"mode": "skill", "skill": "claims-catalog-invoice"}
    ]
    if action == "install":
        expected.append({"mode": None, "skill": "claims-catalog-invoice"})
    assert calls == expected
    assert result["handoff_completed"] is True
    assert result["handoff_inputs"] == {
        "skill": "claims-catalog-invoice",
        "prerequisite-packages": ["claims"],
    }
    if action == "install":
        assert result["steps"] == [1, 2]
        assert result["step_results"][-1]["step"] == 2
        receipt = result["step_results"][-1]["result"]
        assert receipt["deployed"] == ["claims-catalog-invoice"]
        # The public finalizer must recognize the same completion protocol.
        import runpy

        from tests.repository_lifecycle.support import PROMOTE_REPOSITORY

        promote = runpy.run_path(str(PROMOTE_REPOSITORY))
        promote["_completed_deployment"](
            {
                "status": "ready",
                "head": prepared.commit,
                "operations": {
                    "status": "completed",
                    "pending_operations": [],
                    "completed_operations": [location],
                    "results": [result],
                },
            },
            prepared.commit,
            repo_root=repo,
        )


@pytest.mark.parametrize(
    "problem",
    [
        "unknown_input",
        "unknown_route",
        "changed_binding",
        "dirty_source",
        "head_changes",
    ],
)
def test_v4_skill_handoff_rejects_unsafe_or_unhandled_work_before_deployment(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    problem: str,
) -> None:
    repo = _registered_skill_fixture(tmp_path, monkeypatch)
    location = "deliverables.skills.claims-catalog-invoice.actions.install"
    prepared = runner.prepare_operations(
        repo, [runner.OperationRequest(location)], context="skill"
    )[0]
    if problem == "unknown_input":
        prepared.steps[-1].handoff["inputs"]["unexpected"] = "do-not-ignore"
    elif problem == "unknown_route":
        prepared.steps[-1].handoff["action"] = "unknown"
    elif problem == "changed_binding":
        binding = (
            repo / "skills/ceratops-skill-lifecycle/references/action-executors.json"
        )
        binding.write_bytes(binding.read_bytes() + b"\n")
        run_git(repo, "add", ".")
        run_git(repo, "commit", "-m", "Different source authorization")
        prepared = runner.prepare_operations(
            repo, [runner.OperationRequest(location)], context="skill"
        )[0]
    elif problem == "dirty_source":
        (repo / "uncommitted.txt").write_text("must not deploy")
    else:
        original = runner.subprocess.run

        def changing(argv, **kwargs):
            result = original(argv, **kwargs)
            if any(
                str(part).endswith("skills-consistency-source-validator.py")
                for part in argv
            ):
                original(
                    ["git", "commit", "--allow-empty", "-m", "Concurrent change"],
                    cwd=repo,
                    capture_output=True,
                    check=True,
                )
            return result

        monkeypatch.setattr(runner.subprocess, "run", changing)
    result = runner.execute_prepared_operation(prepared)
    assert result["status"] == (
        "state_changed"
        if problem in {"dirty_source", "head_changes"}
        else "handoff_required"
    ), result
    calls = repo / "calls.jsonl"
    if calls.exists():
        assert [
            json.loads(line)["mode"] for line in calls.read_text().splitlines()
        ] == ["skill"]


def test_completed_handoff_record_survives_removed_result_directory(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An output directory removed during delivery must not require replay."""
    import runpy

    from tests.repository_lifecycle.support import PROMOTE_REPOSITORY

    module = runpy.run_path(str(PROMOTE_REPOSITORY))
    namespace = module["main"].__globals__
    result_file = tmp_path / "records/promotion.json"
    result = {
        "status": "ready",
        "head": "a" * 40,
        "operations": {"status": "completed"},
    }
    calls = []

    def promote(args, *, timings):
        assert result_file.parent.is_dir()
        result_file.parent.rmdir()
        calls.append("completed")
        return result

    monkeypatch.setitem(namespace, "promote", promote)
    assert (
        module["main"](
            [
                "--repo-root",
                str(tmp_path / "repo"),
                "--result-file",
                str(result_file),
                "--no-run-operation",
            ]
        )
        == 0
    )
    assert calls == ["completed"]
    assert json.loads(result_file.read_text()) == json.loads(capsys.readouterr().out)
    assert not list(result_file.parent.glob("*.tmp"))


def _v5_fixture() -> dict[str, Any]:
    """Two release units independently consume one separately owned package."""
    document = _v4_fixture()
    document["version"] = 5
    document["repository"]["release-units"] = {
        "core": {"members": ["deliverables.packages.core"]},
        "claims": {
            "members": [
                "deliverables.packages.claims",
                "deliverables.mcp-servers.insurance-claims-mcp-server",
            ]
        },
        "desktop": {"members": ["deliverables.apps.claims-mobile"]},
    }
    mcp_server = document["deliverables"]["mcp-servers"]["insurance-claims-mcp-server"]
    mcp_server["project"] = "mcp-servers/insurance-claims-mcp-server/pyproject.toml"
    mcp_server["artifact"] = {
        "type": "python-wheel",
        "distribution": "insurance-claims-mcp-server",
        "output-directory": "dist/claims-mcp-server",
        "filename-pattern": "insurance_claims_mcp_server-*.whl",
    }
    mcp_server["actions"]["build"] = _v4_action(
        {"run": ["build-claims-mcp-server"]}
    )
    app = document["deliverables"]["apps"]["claims-mobile"]
    app["prerequisites"] = ["core"]
    app["artifact"] = {
        "type": "application-archive",
        "output-directory": "dist/desktop",
        "filename-pattern": "desktop-*.zip",
    }
    app["actions"]["build"] = _v4_action({"run": ["build-desktop"]})
    return document


def test_v5_reader_keeps_shared_dependencies_out_of_membership(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _v5_fixture()
    original = deepcopy(document)
    path = tmp_path / "sdlc.yml"
    path.write_text(json.dumps(document), encoding="utf-8")
    files_before = list(tmp_path.iterdir())

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Reading release units must not execute a command")

    monkeypatch.setattr(subprocess, "run", forbidden)
    loaded = contracts.load_contract(path)
    entries = contracts.release_unit_entries(loaded)
    assert list(entries) == ["core", "claims", "desktop"]
    assert entries["core"]["dependencies"] == {}
    assert list(entries["claims"]["members"]) == [
        "deliverables.packages.claims",
        "deliverables.mcp-servers.insurance-claims-mcp-server",
    ]
    assert list(entries["desktop"]["members"]) == ["deliverables.apps.claims-mobile"]
    for name in ("claims", "desktop"):
        assert list(entries[name]["dependencies"]) == ["deliverables.packages.core"]
        dependency = entries[name]["dependencies"]["deliverables.packages.core"]
        assert dependency["release-unit"] == "core"
        assert dependency["source"] == "packages/core"
        assert dependency["artifact"]["type"] == "python-wheel"
        assert (
            dependency["action-locations"]["build"]
            == "deliverables.packages.core.actions.build"
        )
    mcp_server = entries["claims"]["members"]["deliverables.mcp-servers.insurance-claims-mcp-server"]
    assert (
        mcp_server["action-locations"]["build"]
        == "deliverables.mcp-servers.insurance-claims-mcp-server.actions.build"
    )
    assert mcp_server["prerequisites"] == ["claims"]
    mcp_server["artifact"]["type"] = "changed-view"
    entries["claims"]["dependencies"]["deliverables.packages.core"][
        "prerequisites"
    ].append("changed-view")
    assert loaded == original
    assert document == original
    assert list(tmp_path.iterdir()) == files_before


def test_v5_reader_resolves_transitive_dependency_owners() -> None:
    document = _v5_fixture()
    app = document["deliverables"]["apps"]["claims-mobile"]
    app["prerequisites"] = ["claims"]
    assert contracts.validation_errors(document) == []
    dependencies = contracts.release_unit_entries(document)["desktop"]["dependencies"]
    assert list(dependencies) == [
        "deliverables.packages.core",
        "deliverables.packages.claims",
    ]
    assert [record["release-unit"] for record in dependencies.values()] == [
        "core",
        "claims",
    ]


@pytest.mark.parametrize(
    "kind,name",
    [
        ("packages", "claims"),
        ("mcp-servers", "insurance-claims-mcp-server"),
        ("apps", "claims-mobile"),
        ("skills", "claims-catalog-invoice"),
        ("hooks", "example-hook"),
    ],
)
def test_v5_release_members_support_non_python_artifacts(kind: str, name: str) -> None:
    document = _v5_fixture()
    if kind == "hooks":
        document["deliverables"]["hooks"] = {
            name: {
                "source": "hooks",
                "prerequisites": ["core"],
                "actions": {
                    "validate": {
                        "requires": {"capabilities": []},
                        "no-op": "Covered by repository validation.",
                    },
                    "install": _v4_action({"run": ["install-hook"]}),
                },
            }
        }
    record = document["deliverables"][kind][name]
    record.pop("project", None)
    record["artifact"] = {
        "type": "zip",
        "output-directory": f"dist/{name}",
        "filename-pattern": f"{name}-*.zip",
    }
    record["actions"]["build"] = _v4_action({"run": ["build-archive"]})
    reference = f"deliverables.{kind}.{name}"
    units = document["repository"]["release-units"]
    if kind in {"skills", "hooks"}:
        units["extension"] = {"members": [reference]}
    assert contracts.validation_errors(document) == []
    entries = contracts.release_unit_entries(document)
    owner = next(unit for unit in entries.values() if reference in unit["members"])
    assert owner["members"][reference]["artifact"]["type"] == "zip"
    assert (
        contracts.operation_category(f"{reference}.actions.build", version=5) == "build"
    )


@pytest.mark.parametrize(
    "problem",
    [
        "empty_units",
        "empty_members",
        "duplicate_member",
        "duplicate_owner",
        "unknown_member",
        "invalid_reference",
        "unknown_field",
        "unknown_dependency",
        "unowned_dependency",
        "package_cycle",
        "no_artifact",
        "no_build",
        "noop_build",
        "handoff_build",
        "wheel_without_project",
        "wheel_without_distribution",
    ],
)
def test_v5_rejects_invalid_release_declarations(
    problem: str, tmp_path: pathlib.Path
) -> None:
    document = _v5_fixture()
    units = document["repository"]["release-units"]
    mcp_server = document["deliverables"]["mcp-servers"]["insurance-claims-mcp-server"]
    core = document["deliverables"]["packages"]["core"]
    if problem == "empty_units":
        units.clear()
    elif problem == "empty_members":
        units["claims"]["members"] = []
    elif problem == "duplicate_member":
        units["claims"]["members"].append("deliverables.packages.claims")
    elif problem == "duplicate_owner":
        units["desktop"]["members"].append("deliverables.packages.claims")
    elif problem == "unknown_member":
        units["claims"]["members"].append("deliverables.packages.missing")
    elif problem == "invalid_reference":
        units["claims"]["members"] = ["packages.claims"]
    elif problem == "unknown_field":
        units["claims"]["additional-inputs"] = ["outside/member.py"]
    elif problem == "unknown_dependency":
        core["prerequisites"] = ["missing"]
    elif problem == "unowned_dependency":
        del units["core"]
    elif problem == "package_cycle":
        core["prerequisites"] = ["claims"]
    elif problem == "no_artifact":
        del mcp_server["artifact"]
    elif problem == "no_build":
        del mcp_server["actions"]["build"]
    elif problem == "noop_build":
        mcp_server["actions"]["build"] = {
            "requires": {"capabilities": []},
            "no-op": "No build.",
        }
    elif problem == "handoff_build":
        mcp_server["actions"]["build"] = _v4_action(
            {
                "handoff": {
                    "lifecycle": "some-builder",
                    "action": "build",
                    "inputs": {},
                },
            }
        )
    elif problem == "wheel_without_project":
        del mcp_server["project"]
    else:
        del mcp_server["artifact"]["distribution"]
    errors = contracts.validation_errors(document)
    assert errors, problem
    path = tmp_path / "sdlc.yml"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(contracts.SdlcContractError):
        contracts.load_contract(path)


def test_v5_rejects_unit_cycle_even_when_package_graph_is_acyclic() -> None:
    document = _v5_fixture()
    packages = document["deliverables"]["packages"]
    packages["left-leaf"] = deepcopy(packages["core"])
    packages["right-root"] = deepcopy(packages["core"])
    packages["right-root"]["prerequisites"] = ["left-leaf"]
    units = document["repository"]["release-units"]
    units["claims"]["members"].append("deliverables.packages.left-leaf")
    units["core"]["members"].append("deliverables.packages.right-root")
    errors = contracts.validation_errors(document)
    assert any("release-unit dependency cycle" in error for error in errors)
    assert not any("package prerequisite cycle" in error for error in errors)


@pytest.mark.parametrize(
    "field,bad_path",
    [
        ("source", "../escape"),
        ("source", "C:outside"),
        ("source", "C:/outside"),
        ("project", "/outside/pyproject.toml"),
        ("manifest", r"mcp-servers\outside.json"),
        ("output-directory", "dist/../../escape"),
        ("filename-pattern", "../*.whl"),
        ("filename-pattern", "C:*.whl"),
        ("cwd", "../escape"),
        ("cwd", r"mcp-servers\outside"),
        ("source", "invalid\x00name"),
        ("project", "invalid\nname"),
    ],
)
def test_v5_rejects_unsafe_paths(field: str, bad_path: str) -> None:
    document = _v5_fixture()
    mcp_server = document["deliverables"]["mcp-servers"]["insurance-claims-mcp-server"]
    if field in {"output-directory", "filename-pattern"}:
        mcp_server["artifact"][field] = bad_path
    elif field == "cwd":
        mcp_server["actions"]["build"]["steps"][0]["cwd"] = bad_path
    else:
        mcp_server[field] = bad_path
    assert contracts.validation_errors(document)


def test_v5_does_not_change_v4_or_infer_units() -> None:
    legacy = _v4_fixture()
    before = deepcopy(legacy)
    assert contracts.validation_errors(legacy) == []
    assert contracts.release_unit_entries(legacy) == {}
    assert legacy == before
    legacy["repository"]["release-units"] = {
        "claims": {"members": ["deliverables.packages.claims"]}
    }
    assert contracts.validation_errors(legacy)
    mcp_server = before["deliverables"]["mcp-servers"]["insurance-claims-mcp-server"]
    mcp_server["artifact"] = _v5_fixture()["deliverables"]["mcp-servers"]["insurance-claims-mcp-server"][
        "artifact"
    ]
    mcp_server["actions"]["build"] = _v4_action(
        {"run": ["build-mcp-server"]}
    )
    assert contracts.validation_errors(before)
    document = _v5_fixture()
    del document["repository"]["release-units"]
    assert contracts.validation_errors(document) == []
    assert contracts.release_unit_entries(document) == {}


def test_v5_duplicate_yaml_unit_names_are_rejected(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "sdlc.yml"
    path.write_text(
        "version: 5\nrepository:\n  release-units:\n"
        "    duplicate: {}\n    duplicate: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(contracts.SdlcContractError, match="unique strings"):
        contracts.load_contract(path)


def test_v5_prepare_and_gates_keep_typed_deliverable_selection(
    tmp_path: pathlib.Path,
) -> None:
    document = _v5_fixture()
    mcp_servers = document["deliverables"]["mcp-servers"]
    mcp_servers["other-mcp-server"] = deepcopy(
        mcp_servers["insurance-claims-mcp-server"]
    )
    mcp_servers["other-mcp-server"]["actions"]["install"]["steps"][0]["handoff"]["inputs"][
        "mcp-server"
    ] = "other-mcp-server"
    mcp_servers["other-mcp-server"]["actions"]["test"] = _v4_action(
        {"run": ["other-tests"]}
    )
    selected_mcp_server = mcp_servers["insurance-claims-mcp-server"]
    selected_mcp_server["actions"]["test"] = _v4_action(
        {"run": ["selected-tests"]}
    )
    (tmp_path / "sdlc").mkdir()
    (tmp_path / "sdlc/sdlc.yml").write_text(json.dumps(document), encoding="utf-8")
    _repository(tmp_path)
    location = "deliverables.mcp-servers.insurance-claims-mcp-server.actions.build"
    prepared = runner.prepare_operations(tmp_path, [runner.OperationRequest(location)])[
        0
    ]
    assert prepared.category == "build"
    assert list(prepared.prerequisites["packages"]) == ["core", "claims"]
    gates = runner.validation_operations(tmp_path, [location])
    assert gates == [
        "repository.actions.validate",
        "deliverables.mcp-servers.insurance-claims-mcp-server.actions.validate",
        "repository.actions.test",
        "deliverables.mcp-servers.insurance-claims-mcp-server.actions.test",
    ]
    assert (
        runner.validation_operations(
            tmp_path, [location], ["repository.actions.validate"]
        )
        == gates
    )
    result = run_operation_cli(tmp_path, location, prepare_only=True)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "prepared"
    assert list(payload["prerequisites"]["packages"]) == ["core", "claims"]
