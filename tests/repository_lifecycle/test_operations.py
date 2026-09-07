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
from tests.support.repositories import run_git, write_sdlc_contract

runner = importlib.import_module("repository_operation")
contracts = importlib.import_module(
    "ceratops_repo_compatibility_engine.sdlc_contract_validation"
)

DEPLOY = "deliverables.sample.deploy-local."
CHECK = "repository.validate."


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
    assert document["repository"]["validate"]["repository"]["steps"] == [
        {"run": ["python", "scripts/validate-repository.py"]}
    ]
    assert "deliverables" not in document


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


def test_deploy_runs_repository_command_once_from_repository_directory(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (repo / "unrelated-name.py").write_text(
        "import pathlib\nwith pathlib.Path('count.txt').open('a') as out: out.write('ran\\n')\n",
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


@pytest.mark.parametrize(
    "invalid",
    [
        {"version": 1, "kind": "ceratops-sdlc", "deploy": {"operations": {}}},
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


def test_execute_prepared_operations_stops_after_failure_with_a_ledger(
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / "check.py").write_text(
        "import pathlib, sys\n"
        "print('x' * 10000)\n"
        "for i in range(12): print(f'line-{i}', file=sys.stderr)\n"
        "raise SystemExit(0 if pathlib.Path('fixed').exists() else 7)\n",
        encoding="utf-8",
    )
    write_sdlc_contract(
        tmp_path,
        repository={"validate": {"repository": _step("check.py")}},
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
    failure = run_operation_cli(tmp_path, DEPLOY + "local")
    assert failure.returncode == 1
    evidence = json.loads(failure.stderr)
    assert evidence["status"] == "validation_failed"
    assert evidence["operation"] == CHECK + "repository"
    assert evidence["commit"] == commit
    assert evidence["diagnostic"]["exit_code"] == 7
    assert evidence["diagnostic"]["stderr_tail"] == [f"line-{i}" for i in range(4, 12)]
    assert len("".join(evidence["diagnostic"]["stdout_tail"])) <= 4096
    assert not (tmp_path / "deployed").exists()
    (tmp_path / "fixed").touch()
    assert run_git(tmp_path, "add", "fixed").returncode == 0
    assert run_git(tmp_path, "commit", "-m", "repair").returncode == 0
    repaired = run_operation_cli(tmp_path, DEPLOY + "local")
    assert repaired.returncode == 0, repaired.stderr
    assert len(repaired.stdout) < 600
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
            "tools": {
                "validate": {
                    "review": {
                        "handoff": "ceratops-skill-lifecycle/skills-consistency-review"
                    }
                },
                "deploy-local": {
                    "managed": {"handoff": "ceratops-tool-lifecycle/install"}
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
    for name in (
        "deliverables.tools.deploy-local.managed",
        "deliverables.tools.publish.workflow",
    ):
        result = run_operation_cli(tmp_path, name)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["results"][0]["status"] == "advisory"
        assert payload["results"][0]["handoff"]
        assert payload["validation_handoffs"][0]["handoff"]


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


def test_source_changes_between_steps_prevent_later_mutations(
    tmp_path: pathlib.Path,
) -> None:
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
                                    "import pathlib; pathlib.Path('changed').touch()",
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
        f"@echo SDLC-npm-%1\n@exit /b {exit_code}\n"
        if os.name == "nt"
        else f"#!/bin/sh\nprintf 'SDLC-npm-%s\\n' \"$1\"\nexit {exit_code}\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    contract = contracts.load_contract(
        OPERATION_RUNNER.parents[3] / "sdlc" / "sdlc.yml"
    )
    argv = contract["repository"]["bootstrap"]["development"]["steps"][-1]["run"]
    result = subprocess.run(
        argv,
        cwd=tmp_path,
        env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is (exit_code == 0)
    assert "SDLC-npm-ci" in result.stdout
    if exit_code:
        assert str(exit_code) in result.stderr
