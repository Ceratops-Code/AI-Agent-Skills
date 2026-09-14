from __future__ import annotations

import importlib
import json
import pathlib
import shutil
import subprocess
import sys

import pytest
import yaml

from tests.repository_lifecycle.support import (
    REPOSITORY_LIFECYCLE_SCRIPTS,
    REPOSITORY_LIFECYCLE_SOURCE,
    SECTION_MANIFEST_TEMPLATE,
)
from tests.skill_lifecycle.support import add_action_sections
from tests.support.processes import COMPATIBILITY_ENGINE, run_compatibility_engine
from tests.support.repositories import (
    ROOT,
    create_compatible_repo,
    write_sdlc_contract,
)


def test_compatibility_materializer_supplies_target_identity_and_assignments(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "stale/source", ["alpha-tool", "beta-tool"])
    write_sdlc_contract(
        repo,
        deliverables={"tools": {"publish": {
            "public": {"steps": [{"run": [sys.executable, "-V"]}]}
        }}},
    )
    (repo / ".git").write_text("gitdir: test\n", encoding="utf-8", newline="\n")
    shutil.rmtree(repo / "skills" / "sections")
    (repo / "skills" / "skill-sections.json").unlink()
    beta = repo / "skills" / "beta-tool" / "SKILL.md"
    (beta.parent / "references").mkdir()
    (beta.parent / "references" / "run.md").write_text(
        "# Run Action\n\n## Goal\n\nRun the target workflow.\n",
        encoding="utf-8",
        newline="\n",
    )
    (beta.parent / "references" / "check.md").write_text(
        "# Check Action\n\n## Goal\n\nCheck the target workflow.\n",
        encoding="utf-8",
        newline="\n",
    )
    beta.write_text(
        beta.read_text(encoding="utf-8")
        + "\n### Action References\n\n"
        + "- Run: `references/run.md`\n"
        + "- Check: `references/check.md`\n"
        + "\n"
        + "\n".join(
            [
                "<!-- CERATOPS_SHARED_SECTIONS_START -->",
                "<!-- SECTION SOURCE: skills/sections/core.md -->",
                "## Generated Core",
                "",
                "<!-- SECTION SOURCE: skills/sections/multi-action-skill.md -->",
                "## Generated Multi Action",
                "<!-- CERATOPS_SHARED_SECTIONS_END -->",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )

    result = run_compatibility_engine(
        REPOSITORY_LIFECYCLE_SCRIPTS,
        "apply",
        "--target-repo-root",
        str(repo),
        "--runtime-source-id",
        "target/skills",
    )

    assert result.returncode == 0, result.stdout
    output = json.loads(result.stdout)
    manifest = json.loads(
        (repo / "skills" / "skill-sections.json").read_text(encoding="utf-8")
    )
    assert output["status"] == "ok"
    assert output["markers_removed"] == ["beta-tool"]
    assert manifest["runtime_source_id"] == "target/skills"
    assert manifest["validation_profile"] == "ceratops-compatible"
    assert manifest["skills"] == {
        "alpha-tool": ["core"],
        "beta-tool": ["core", "multi-action-skill"],
    }
    assert manifest["runtime_source_id"] != json.loads(
        SECTION_MANIFEST_TEMPLATE.read_text(encoding="utf-8")
    )["runtime_source_id"]
    assert (repo / "skills" / "sections" / "core.md").read_bytes() == (
        ROOT / "skills" / "sections" / "core.md"
    ).read_bytes()
    assert "SECTION SOURCE: skills/sections/" not in beta.read_text(encoding="utf-8")
    contract = yaml.safe_load(
        (repo / "sdlc" / "sdlc.yml").read_text(encoding="utf-8")
    )
    assert contract["kind"] == "ceratops-sdlc"
    assert contract["deliverables"]["skills"]["validate"] == {
        "ceratops-managed": {"handoff": "ceratops-skill-lifecycle/source-validate"}
    }
    assert contract["deliverables"]["skills"]["deploy-local"]["ceratops-managed"] == {
        "handoff": "ceratops-skill-lifecycle/deploy"
    }
    assert contract["deliverables"]["skills"]["deploy-local"]["standalone"] == {
        "steps": [
            {
                "run": ["python", "scripts/deploy-skills.py"],
            }
        ]
    }
    assert contract["deliverables"]["tools"]["publish"] == {
        "public": {
            "steps": [{"run": [sys.executable, "-V"]}]
        }
    }
    materializer = importlib.import_module(
        "ceratops_repo_compatibility_engine.apply_ceratops_compatibility"
    )
    # Current generated entries are idempotent and retire with their skill source.
    assert materializer.build_sdlc_contract_candidate(
        repo, has_skills=True, apply_contract=True,
    ) == contract
    skillless = materializer.build_sdlc_contract_candidate(
        repo, has_skills=False, apply_contract=True,
    )
    assert skillless["deliverables"] == {"tools": contract["deliverables"]["tools"]}

    # A target's custom definitions survive even under a producer-owned name.
    custom = {"handoff": "target-owned/validation"}
    contract["deliverables"]["skills"]["validate"] = {
        "ceratops-managed": custom, "custom-check": custom,
    }
    contract["deliverables"]["skills"]["deploy-local"]["ceratops-managed"] = {
        "handoff": "target-owned/deployment"
    }
    sdlc = repo / "sdlc" / "sdlc.yml"
    sdlc.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
    assert materializer.build_sdlc_contract_candidate(
        repo, has_skills=True, apply_contract=True,
    ) == contract
    skillless = materializer.build_sdlc_contract_candidate(
        repo, has_skills=False, apply_contract=True,
    )
    assert skillless["deliverables"]["skills"] == {
        "validate": {"ceratops-managed": custom, "custom-check": custom},
        "deploy-local": {"ceratops-managed": {"handoff": "target-owned/deployment"}},
        "tests": {"none": {"no-op": "No deliverable-specific test operation is declared; repository tests remain separately selectable."}},
    }
    assert (repo / "scripts" / "deploy-skills.py").is_file()
    assert (repo / "scripts" / "validate-repository.py").is_file()
    assert (repo / ".github" / "workflows" / "validate.yml").is_file()
    assert output["repository_validation"] == {
        "checks": [],
        "validator": "applied",
        "workflow": "applied",
    }
    payload = repo / "skills" / "sections" / "scripts" / "shared.py"
    payload.parent.mkdir()
    payload.write_text("VALUE = True\n", encoding="utf-8", newline="\n")
    manifest["runtime_payloads"] = {
        "alpha-tool": [
            {
                "source": "skills/sections/scripts/shared.py",
                "target": "scripts/shared.py",
            }
        ]
    }
    (repo / "skills" / "skill-sections.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    compatibility = importlib.import_module(
        "ceratops_repo_compatibility_engine.validate_ceratops_compatibility"
    )
    assert compatibility.validate_ceratops_compatibility(repo) == {
        "applicable": True,
        "valid": True,
        "errors": [],
    }


    # Required surfaces are structural checks, including the skill bootstrap.
    for relative in ("scripts/validate-repository.py", ".github/workflows/validate.yml",
                     "scripts/deploy-skills.py"):
        target = repo / relative
        original = target.read_bytes()
        target.unlink()
        missing = compatibility.validate_ceratops_compatibility(repo)
        assert missing["valid"] is False
        assert f"missing {relative}" in missing["errors"]
        target.write_bytes(original)

    workflow = repo / ".github/workflows/validate.yml"
    original_workflow = workflow.read_bytes()
    workflow.write_text(workflow.read_text(encoding="utf-8").replace(
        "--evidence-file ", "--evidence-file=",
    ), encoding="utf-8")
    assert compatibility.validate_ceratops_compatibility(repo)["valid"] is True
    workflow.write_bytes(original_workflow)

    # A real alternate bundle changes generation, bootstrap sync, and checking
    # through contract data, without changing any executable implementation.
    bundle = tmp_path / "alternate-bundle"
    shutil.copytree(REPOSITORY_LIFECYCLE_SOURCE, bundle)
    shutil.copytree(ROOT / "skills/sections", bundle / "skills/sections")
    contract_path = bundle / "references/contracts/ceratops-compatibility-deterministic-contract.json"
    defaults = json.loads(contract_path.read_text(encoding="utf-8"))
    defaults["surfaces"]["skill_bootstrap"]["path"] = "scripts/bootstrap-skills.py"
    defaults["surfaces"]["skill_bootstrap"]["template"] = "bootstrap-skills.py.tmpl"
    defaults["managed_skill_operations"]["validate"]["ceratops-managed"]["handoff"] = "target-lifecycle/source-check"
    defaults["managed_skill_operations"]["deploy-local"]["standalone"]["steps"][0]["run"][1] = "scripts/bootstrap-skills.py"
    templates = bundle / "references/templates"
    (templates / "deploy-skills.py.tmpl").rename(templates / "bootstrap-skills.py.tmpl")
    contract_path.write_text(json.dumps(defaults), encoding="utf-8")
    alternate = tmp_path / "alternate-target"
    create_compatible_repo(alternate, "target/alternate", ["alpha-tool"])
    (alternate / ".git").write_text("gitdir: test\n", encoding="utf-8")
    (alternate / "scripts/deploy-skills.py").unlink()
    # Keep target-owned operation preservation separate from generated defaults.
    (alternate / "sdlc/sdlc.yml").unlink()
    write_sdlc_contract(alternate)
    changed = run_compatibility_engine(bundle / "scripts", "apply", "--target-repo-root", str(alternate))
    assert changed.returncode == 0, changed.stdout + changed.stderr
    assert (alternate / "scripts/bootstrap-skills.py").is_file()
    assert not (alternate / "scripts/deploy-skills.py").exists()
    actual = yaml.safe_load((alternate / "sdlc/sdlc.yml").read_text(encoding="utf-8"))
    assert actual["deliverables"]["skills"]["deploy-local"]["standalone"]["steps"][0]["run"] == [
        "python", "scripts/bootstrap-skills.py",
    ]
    assert actual["deliverables"]["skills"]["validate"]["ceratops-managed"] == {
        "handoff": "target-lifecycle/source-check"
    }


def test_compatibility_materializer_supports_repositories_without_skills(
    tmp_path: pathlib.Path,
) -> None:
    lifecycle_bundle = tmp_path / "lifecycle-bundle"
    shutil.copytree(REPOSITORY_LIFECYCLE_SOURCE, lifecycle_bundle)
    (
        lifecycle_bundle
        / "scripts"
        / COMPATIBILITY_ENGINE
        / "bootstrap_installer_synchronization.py"
    ).write_text(
        "raise SystemExit('bootstrap synchronizer must not run')\n",
        encoding="utf-8",
        newline="\n",
    )
    engine_scripts = lifecycle_bundle / "scripts"
    repo = tmp_path / "empty-compatible"
    repo.mkdir()
    (repo / ".git").write_text(
        "gitdir: test\n", encoding="utf-8", newline="\n"
    )
    (repo / "README.md").write_text(
        "# Empty Compatible Repository\n\n"
        "## Skills\n\n"
        "| Skill | Purpose |\n"
        "| --- | --- |\n",
        encoding="utf-8",
        newline="\n",
    )
    (repo / "package.json").write_text(
        json.dumps({"scripts": {"lint": "echo lint"}}) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_probe.py").write_text(
        "import unittest\n\n"
        "class TestProbe(unittest.TestCase):\n"
        "    def test_probe(self) -> None:\n"
        "        self.assertTrue(True)\n",
        encoding="utf-8",
        newline="\n",
    )

    blocked_result = run_compatibility_engine(
        engine_scripts,
        "apply",
        "--target-repo-root",
        str(repo),
        "--runtime-source-id",
        "example/empty-compatible",
    )

    assert blocked_result.returncode == 1
    assert json.loads(blocked_result.stdout) == {
        "phase": "compatibility_planning",
        "reason": (
            "npm validation checks require package-lock.json for "
            "deterministic npm ci setup"
        ),
        "rollback": "not_started",
        "status": "blocked",
    }
    assert not (repo / "skills").exists()
    assert not (repo / "deploy").exists()
    assert not (repo / "scripts").exists()
    assert not (repo / ".github").exists()

    (repo / "package-lock.json").write_text(
        json.dumps({"lockfileVersion": 3, "requires": True, "packages": {}})
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (repo / "skills").mkdir()
    (repo / "skills" / "skill-sections.json").write_text(
        json.dumps(
            {
                "runtime_source_id": "example/empty-compatible",
                "validation_profile": "ceratops-compatible",
                "sections": {},
                "maintenance_workflows": {},
                "runtime_payloads": {},
                "skills": {},
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    result = run_compatibility_engine(
        engine_scripts,
        "apply",
        "--target-repo-root",
        str(repo),
        "--runtime-source-id",
        "example/empty-compatible",
    )

    assert result.returncode == 0, result.stdout
    output = json.loads(result.stdout)
    assert output["bootstrap"] == "skipped"
    assert output["sdlc_contract"] == "applied"
    assert output["runtime_source_id"] is None
    assert output["skill_manifest"] == "not_configured"
    assert not (repo / "skills").exists()
    contract = yaml.safe_load((repo / "sdlc" / "sdlc.yml").read_text())
    assert contract["repository"]["validate"]["repository"]["steps"] == [
        {"run": ["uv", "run", "--project", "scripts/validation", "--locked", "python", "scripts/validate-repository.py"]}
    ]
    assert "deliverables" not in contract
    assert not (repo / "scripts" / "deploy-skills.py").exists()
    assert output["repository_validation"] == {
        "checks": ["npm-lint"],
        "validator": "applied",
        "workflow": "applied",
    }
    assert (repo / "scripts" / "validate-repository.py").is_file()
    assert (repo / ".github" / "workflows" / "validate.yml").is_file()
    validation_evidence = tmp_path / "zero-skill-validation.log"
    validation_evidence.write_text("stale failure evidence\n", encoding="utf-8")
    validation_temporary = validation_evidence.with_name(
        f".{validation_evidence.name}.tmp"
    )
    validation_temporary.write_text("stale partial evidence\n", encoding="utf-8")
    validation = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "validate-repository.py"),
            "--evidence-file",
            str(validation_evidence),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert validation.returncode == 0, validation.stdout
    assert validation.stdout == "OK\n"
    assert not validation_evidence.exists()
    assert not validation_temporary.exists()
    assert not [path for path in repo.rglob("__pycache__") if ".venv" not in path.parts]

    omitted = run_compatibility_engine(
        engine_scripts, "apply", "--target-repo-root", str(repo), "--no-sdlc-contract",
    )
    assert omitted.returncode != 0
    assert (repo / "sdlc/sdlc.yml").is_file()

    def empty_repository(name: str) -> pathlib.Path:
        target = tmp_path / name
        target.mkdir()
        (target / ".git").write_text("gitdir: test\n", encoding="utf-8", newline="\n")
        (target / "README.md").write_text(
            f"# {name}\n\n## Skills\n\n| Skill | Purpose |\n| --- | --- |\n",
            encoding="utf-8",
            newline="\n",
        )
        return target

    pnpm_repo = empty_repository("pnpm-compatible")
    (pnpm_repo / "package.json").write_text(
        json.dumps(
            {
                "packageManager": "pnpm@10.33.4",
                "scripts": {"build": "tsc --noEmit"},
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (pnpm_repo / "pnpm-lock.yaml").write_text(
        "lockfileVersion: '9.0'\n", encoding="utf-8", newline="\n"
    )
    (pnpm_repo / "requirements-dev.txt").write_text(
        "pytest==9.1.1\n", encoding="utf-8", newline="\n"
    )
    (pnpm_repo / "pyproject.toml").write_text(
        '[tool.mypy]\npython_version = "3.12"\n',
        encoding="utf-8",
        newline="\n",
    )
    pnpm_result = run_compatibility_engine(
        engine_scripts,
        "apply",
        "--target-repo-root",
        str(pnpm_repo),
        "--runtime-source-id",
        "example/pnpm-compatible",
    )
    assert pnpm_result.returncode == 0, pnpm_result.stdout
    assert json.loads(pnpm_result.stdout)["repository_validation"]["checks"] == [
        "pnpm-build",
        "mypy",
    ]
    pnpm_workflow = (
        pnpm_repo / ".github" / "workflows" / "validate.yml"
    ).read_text(encoding="utf-8")
    assert "actions/setup-node@2028fbc5c25fe9cf00d9f06a71cc4710d4507903" in pnpm_workflow
    assert "corepack prepare pnpm@10.33.4 --activate" in pnpm_workflow
    assert "pnpm install --frozen-lockfile" in pnpm_workflow
    assert "python -m pip install" not in pnpm_workflow
    pnpm_steps = yaml.safe_load(pnpm_workflow)["jobs"]["validate-repository"]["steps"]
    assert [
        step["run"].splitlines()
        for step in pnpm_steps
        if step.get("name") == "Install Python validation dependencies"
    ] == []
    assert 'python-version: "3.12"' not in pnpm_workflow
    import tomllib
    pnpm_runtime = tomllib.loads((pnpm_repo / "scripts/validation/pyproject.toml").read_text())
    assert "mypy" in pnpm_runtime["project"]["dependencies"]
    assert (pnpm_repo / "requirements-dev.txt").read_text() == "pytest==9.1.1\n"

    uv_repo = empty_repository("uv-compatible")
    (uv_repo / "uv.lock").write_text("version = 1\n", encoding="utf-8", newline="\n")
    (uv_repo / "pyproject.toml").write_text(
        '[project]\nname = "uv-compatible"\nversion = "1.0.0"\n'
        'requires-python = ">=3.13"\n'
        '[project.optional-dependencies]\ndev = ["pytest", "ruff", "mypy"]\n'
        "[tool.pytest.ini_options]\n"
        "[tool.ruff]\n"
        '[tool.mypy]\npython_version = "3.12"\n',
        encoding="utf-8",
        newline="\n",
    )
    (uv_repo / ".yamllint").write_text("extends: default\n", encoding="utf-8", newline="\n")
    uv_result = run_compatibility_engine(
        engine_scripts,
        "apply",
        "--target-repo-root",
        str(uv_repo),
        "--runtime-source-id",
        "example/uv-compatible",
    )
    assert uv_result.returncode == 0, uv_result.stdout
    assert json.loads(uv_result.stdout)["repository_validation"]["checks"] == [
        "ruff",
        "mypy",
        "yaml-lint",
    ]
    uv_workflow = (uv_repo / ".github" / "workflows" / "validate.yml").read_text(
        encoding="utf-8"
    )
    assert "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9" in uv_workflow
    assert 'python-version-file: "pyproject.toml"' not in uv_workflow
    assert 'python-version: "3.12"' not in uv_workflow
    assert "uv sync --extra dev --frozen" not in uv_workflow
    uv_steps = yaml.safe_load(uv_workflow)["jobs"]["validate-repository"]["steps"]
    assert [
        step["run"].splitlines()
        for step in uv_steps
        if step.get("name") == "Install Python validation dependencies"
    ] == []
    assert "uv run --project scripts/validation --locked python scripts/sdlc.py --validate --ci" in uv_workflow
    assert (uv_repo / "uv.lock").read_text() == "version = 1\n"

    # Synthetic recipes exercise extension behavior without coupling the shipped
    # contract to any repository's private check names or command conventions.
    contract_path = (lifecycle_bundle / "references" / "contracts" / "repository-validation-contract.json")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["checks"].extend(
        [
            {
                "id": "powershell-lint",
                "when": [{"kind": "path-any", "value": ["tools/quality.ps1"]}],
                "command": ["{pwsh}", "-NoProfile", "-File", "tools/quality.ps1"],
                "cwd": ".",
            },
            {
                "id": "custom-validator",
                "when": [{"kind": "path-any", "value": ["scripts/check_project.py"]}],
                "command": [
                    "{python}", "scripts/check_project.py", "--temp-root", "{temp}/custom",
                    "--evidence-file", "{temp}/custom-validation.log",
                ],
                "cwd": ".",
                "exclusive": True,
            },
        ]
    )
    contract_path.write_text(json.dumps(contract) + "\n", encoding="utf-8")

    powershell_repo = empty_repository("powershell-compatible")
    for relative in ("tools/quality.ps1",):
        path = powershell_repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("exit 0\n", encoding="utf-8", newline="\n")
    powershell_result = run_compatibility_engine(
        engine_scripts,
        "apply",
        "--target-repo-root",
        str(powershell_repo),
        "--runtime-source-id",
        "example/powershell-compatible",
    )
    assert powershell_result.returncode == 0, powershell_result.stdout
    assert json.loads(powershell_result.stdout)["repository_validation"]["checks"] == [
        "powershell-lint",
    ]
    powershell_workflow = (
        powershell_repo / ".github" / "workflows" / "validate.yml"
    ).read_text(encoding="utf-8")
    assert "runs-on: windows-latest" in powershell_workflow
    assert "Install-Module PSScriptAnalyzer" in powershell_workflow

    unittest_repo = empty_repository("unittest-compatible")
    (unittest_repo / "scripts").mkdir()
    (unittest_repo / "scripts" / "validate_repository.py").write_text(
        "# --temp-root --build-dir\n"
        "def repository_checks():\n"
        "    raise AssertionError('Undeclared helper must not run')\n",
        encoding="utf-8",
        newline="\n",
    )
    (unittest_repo / "tests").mkdir()
    (unittest_repo / "tests" / "test_example.py").write_text(
        "import unittest\n", encoding="utf-8", newline="\n"
    )
    unittest_result = run_compatibility_engine(
        engine_scripts,
        "apply",
        "--target-repo-root",
        str(unittest_repo),
        "--runtime-source-id",
        "example/unittest-compatible",
    )
    assert unittest_result.returncode == 0, unittest_result.stdout
    assert json.loads(unittest_result.stdout)["repository_validation"]["checks"] == [
    ]

    docs_repo = empty_repository("docs-compatible")
    (docs_repo / "README.md").write_text(
        "python -m ruff check tools/source.py\n", encoding="utf-8", newline="\n"
    )
    (docs_repo / "pyproject.toml").write_text(
        "[tool.ruff]\n", encoding="utf-8", newline="\n"
    )
    (docs_repo / "tests").mkdir()
    (docs_repo / "tests" / "test_example.py").write_text(
        "import unittest\n", encoding="utf-8", newline="\n"
    )
    docs_result = run_compatibility_engine(
        engine_scripts,
        "apply",
        "--target-repo-root",
        str(docs_repo),
        "--runtime-source-id",
        "example/docs-compatible",
    )
    assert docs_result.returncode == 0, docs_result.stdout
    assert json.loads(docs_result.stdout)["repository_validation"]["checks"] == [
        "ruff",
    ]
    docs_workflow = (
        docs_repo / ".github" / "workflows" / "validate.yml"
    ).read_text(encoding="utf-8")
    docs_steps = yaml.safe_load(docs_workflow)["jobs"]["validate-repository"]["steps"]
    assert all(
        step.get("name") != "Install Python validation dependencies"
        for step in docs_steps
    )

    authoritative_repo = empty_repository("authoritative-compatible")
    (authoritative_repo / "scripts").mkdir()
    (authoritative_repo / "scripts" / "check_project.py").write_text(
        "import argparse\n"
        "import pathlib\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--temp-root')\n"
        "parser.add_argument('--evidence-file', type=pathlib.Path, required=True)\n"
        "args = parser.parse_args()\n"
        "if not pathlib.Path(args.temp_root).is_dir():\n"
        "    args.evidence_file.write_text('temp root missing\\n', encoding='utf-8')\n"
        "    raise SystemExit(2)\n"
        "args.evidence_file.write_text('inner diagnostic\\n', encoding='utf-8')\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
        newline="\n",
    )
    (authoritative_repo / "pyproject.toml").write_text(
        '[tool.mypy]\npython_version = "3.12"\n',
        encoding="utf-8",
        newline="\n",
    )
    authoritative_result = run_compatibility_engine(
        engine_scripts,
        "apply",
        "--target-repo-root",
        str(authoritative_repo),
        "--runtime-source-id",
        "example/authoritative-compatible",
    )
    assert authoritative_result.returncode == 0, authoritative_result.stdout
    assert json.loads(authoritative_result.stdout)["repository_validation"]["checks"] == [
        "custom-validator"
    ]
    authoritative_validator = (
        authoritative_repo / "scripts" / "validate-repository.py"
    ).read_text(encoding="utf-8")
    assert max(len(line) for line in authoritative_validator.splitlines()) <= 100
    authoritative_evidence = tmp_path / "authoritative-validation.log"
    authoritative_validation = subprocess.run(
        [
            sys.executable,
            str(authoritative_repo / "scripts" / "validate-repository.py"),
            "--evidence-file",
            str(authoritative_evidence),
        ],
        cwd=authoritative_repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert authoritative_validation.returncode == 1
    retained_evidence = authoritative_evidence.read_text(encoding="utf-8")
    assert "child_evidence: custom-validation.log" in retained_evidence
    assert "inner diagnostic" in retained_evidence

    # Every supported configuration identifies repository-owned Python tests;
    # no test framework belongs to the generated repository validator.
    for index, (config, contents) in enumerate([
        ("pytest.toml", "[pytest]\n"),
        (".pytest.toml", "[pytest]\n"),
        (".pytest.ini", "[pytest]\n"),
        ("tox.ini", "[pytest]\n"),
        ("setup.cfg", "[tool:pytest]\n"),
    ]):
        config_repo = empty_repository(f"pytest-config-{index}")
        (config_repo / config).write_text(contents, encoding="utf-8")
        (config_repo / "tests").mkdir()
        (config_repo / "tests" / "test_probe.py").write_text(
            "def test_probe(): pass\n", encoding="utf-8"
        )
        configured = run_compatibility_engine(
            engine_scripts, "apply", "--target-repo-root", str(config_repo)
        )
        assert configured.returncode == 0, configured.stdout
        assert json.loads(configured.stdout)["repository_validation"]["checks"] == []
        assert (config_repo / "scripts/run-tests.py").is_file()
        assert "python" in yaml.safe_load((config_repo / "sdlc/sdlc.yml").read_text())["repository"]["tests"]

    # Contract validation covers entries which do not match the target and
    # rejects broken metadata or evidence links before target mutation.
    valid_contract = json.loads(contract_path.read_text(encoding="utf-8"))
    broken_contracts = []
    for field, value in (
        ("contract_format_version", 2),
        ("captured_on", False),
        ("source_doc_scopes", ["missing-evidence-scope"]),
        ("unknown_policy", True),
    ):
        candidate = json.loads(json.dumps(valid_contract))
        candidate[field] = value
        broken_contracts.append(candidate)
    duplicate = json.loads(json.dumps(valid_contract))
    duplicate["checks"].append(duplicate["checks"][0])
    broken_contracts.append(duplicate)
    for condition in (
        {"kind": "unknown", "value": "unmatched"},
        {"kind": "path-any", "value": ["../outside"]},
    ):
        candidate = json.loads(json.dumps(valid_contract))
        candidate["checks"][0]["when"] = [condition]
        broken_contracts.append(candidate)
    for index, candidate in enumerate(broken_contracts):
        contract_path.write_text(json.dumps(candidate) + "\n", encoding="utf-8")
        invalid_repo = empty_repository(f"invalid-contract-{index}")
        invalid = run_compatibility_engine(
            engine_scripts, "apply", "--target-repo-root", str(invalid_repo)
        )
        assert invalid.returncode == 1, invalid.stdout
        assert json.loads(invalid.stdout)["rollback"] == "not_started"
        assert not (invalid_repo / "scripts").exists()
        assert not (invalid_repo / "sdlc").exists()
    contract_path.write_text(json.dumps(valid_contract) + "\n", encoding="utf-8")

    # The contract-review checker also rejects new schema fields which lack
    # a declared executable consumer or an explicit annotation role.
    schema_path = lifecycle_bundle / "references" / "schemas" / "repository-validation-contract.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["properties"]["unconsumed_policy"] = {"type": "string"}
    schema_path.write_text(json.dumps(schema) + "\n", encoding="utf-8")
    consistency_result = subprocess.run(
        [sys.executable, "-m", "github_contract_engine", "validate", "consistency"],
        cwd=engine_scripts, capture_output=True, text=True, check=False,
    )
    assert consistency_result.returncode == 1
    assert "unclassified contract field root.unconsumed_policy" in consistency_result.stdout


def test_compatibility_materializer_preserves_existing_validator_and_ci(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "preserved/source", ["alpha-tool"])
    (repo / ".git").write_text("gitdir: test\n", encoding="utf-8", newline="\n")
    validator = repo / "scripts" / "validate-repository.py"
    validator.write_text(
        "#!/usr/bin/env python3\nprint('target-owned')\n",
        encoding="utf-8",
        newline="\n",
    )
    validator.chmod(0o744)
    workflow = repo / ".github" / "workflows" / "validate.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n"
        "  validate:\n"
        "    steps:\n"
        "      - run: python scripts/validate-repository.py "
        "--evidence-file evidence.log\n",
        encoding="utf-8",
        newline="\n",
    )
    before = {
        path: (path.read_bytes(), path.stat().st_mode)
        for path in (validator, workflow)
    }

    result = run_compatibility_engine(
        REPOSITORY_LIFECYCLE_SCRIPTS,
        "apply",
        "--target-repo-root",
        str(repo),
    )

    assert result.returncode == 0, result.stdout
    assert (validator.read_bytes(), validator.stat().st_mode) == before[validator]
    workflow_steps = yaml.safe_load(workflow.read_text())["jobs"]["validate"]["steps"]
    assert any("scripts/sdlc.py --validate --ci" in step.get("run", "") for step in workflow_steps)
    assert json.loads(result.stdout)["custom_validation_review_required"] is True
    assert json.loads(result.stdout)["repository_validation"] == {
        "checks": [],
        "validator": "preserved",
        "workflow": "applied",
    }


def test_compatibility_materializer_preserves_existing_identity_and_custom_sections(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "preserved/source", ["alpha-tool"])
    (repo / ".git").write_text("gitdir: test\n", encoding="utf-8", newline="\n")
    custom = repo / "skills" / "sections" / "custom.md"
    custom.write_text(
        "## Custom Rules\n\nPreserve this target behavior.\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest_path = repo / "skills" / "skill-sections.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sections"]["custom"] = "skills/sections/custom.md"
    manifest["skills"]["alpha-tool"].append("custom")
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    result = run_compatibility_engine(
        REPOSITORY_LIFECYCLE_SCRIPTS,
        "apply",
        "--target-repo-root",
        str(repo),
    )

    assert result.returncode == 0, result.stdout
    output = json.loads(result.stdout)
    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert output["runtime_source_id"] == "preserved/source"
    assert output["rollback"] == "not_needed"
    assert updated["runtime_source_id"] == "preserved/source"
    assert updated["sections"]["custom"] == "skills/sections/custom.md"
    assert updated["skills"]["alpha-tool"] == ["core", "custom"]
    assert custom.read_text(encoding="utf-8").endswith(
        "Preserve this target behavior.\n"
    )

    overridden = run_compatibility_engine(
        REPOSITORY_LIFECYCLE_SCRIPTS,
        "apply",
        "--target-repo-root",
        str(repo),
        "--runtime-source-id",
        "explicit/source",
    )
    assert overridden.returncode == 0, overridden.stdout
    assert json.loads(manifest_path.read_text(encoding="utf-8"))[
        "runtime_source_id"
    ] == "explicit/source"


def test_compatibility_materializer_rolls_back_every_target_write_on_blocker(
    tmp_path: pathlib.Path,
) -> None:
    lifecycle_bundle = tmp_path / "lifecycle-bundle"
    shutil.copytree(REPOSITORY_LIFECYCLE_SOURCE, lifecycle_bundle)
    shutil.copytree(
        ROOT / "skills" / "sections",
        lifecycle_bundle / "skills" / "sections",
    )
    workflow_template = (
        lifecycle_bundle / "references" / "templates" / "validate.yml.tmpl"
    )
    workflow_template.write_text(
        workflow_template.read_text(encoding="utf-8").replace(
            "python scripts/sdlc.py",
            "python scripts/not-the-sdlc-runner.py",
        ),
        encoding="utf-8",
        newline="\n",
    )
    engine_scripts = lifecycle_bundle / "scripts"
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "preserved/source", ["alpha-tool"])
    (repo / ".git").write_text("gitdir: test\n", encoding="utf-8", newline="\n")
    skill_md = repo / "skills" / "alpha-tool" / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8")
        + "\n<!-- CERATOPS_SHARED_SECTIONS_START -->\n"
        + "<!-- SECTION SOURCE: skills/sections/core.md -->\n"
        + "## Generated Core\n"
        + "<!-- CERATOPS_SHARED_SECTIONS_END -->\n",
        encoding="utf-8",
        newline="\n",
    )
    changed_paths = (
        skill_md,
        repo / "skills" / "sections" / "core.md",
        repo / "skills" / "skill-sections.json",
        repo / "scripts" / "deploy-skills.py",
        repo / "sdlc" / "sdlc.yml",
    )
    original = {path: path.read_bytes() for path in changed_paths}

    result = run_compatibility_engine(
        engine_scripts,
        "apply",
        "--target-repo-root",
        str(repo),
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["status"] == "blocked"
    assert output["phase"] == "compatibility_validation"
    assert output["rollback"] == "completed"
    assert {path: path.read_bytes() for path in changed_paths} == original
    assert not (repo / "scripts" / "validate-repository.py").exists()
    assert not (repo / ".github" / "workflows" / "validate.yml").exists()


def test_compatibility_materializer_blocks_invalid_assignments_before_writes(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "preserved/source", ["alpha-tool"])
    (repo / ".git").write_text("gitdir: test\n", encoding="utf-8", newline="\n")
    manifest_path = repo / "skills" / "skill-sections.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["skills"]["alpha-tool"].append("missing-section")
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    observed_paths = (
        repo / "skills" / "alpha-tool" / "SKILL.md",
        repo / "skills" / "sections" / "core.md",
        manifest_path,
        repo / "scripts" / "deploy-skills.py",
        repo / "sdlc" / "sdlc.yml",
    )
    original = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in observed_paths
    }

    result = run_compatibility_engine(
        REPOSITORY_LIFECYCLE_SCRIPTS,
        "apply",
        "--target-repo-root",
        str(repo),
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["phase"] == "compatibility_planning"
    assert output["rollback"] == "not_started"
    assert {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in observed_paths
    } == original


    # Malformed bundled policy fails before touching even an invalid target.
    loader = importlib.import_module("ceratops_repo_compatibility_engine.compatibility_contract")
    bundle = tmp_path / "invalid-contract-bundle"
    shutil.copytree(REPOSITORY_LIFECYCLE_SOURCE, bundle)
    contract_path = bundle / "references/contracts" / loader.CONTRACT_NAME
    current = json.loads(contract_path.read_text(encoding="utf-8"))
    invalid_values = []
    unknown = json.loads(json.dumps(current))
    unknown["python_packages"] = ["pytest"]
    invalid_values.append((unknown, "python_packages"))
    escaping = json.loads(json.dumps(current))
    escaping["surfaces"]["validator"]["path"] = "../outside.py"
    invalid_values.append((escaping, "surfaces/validator/path"))
    duplicate = json.loads(json.dumps(current))
    duplicate["surfaces"]["workflow"]["path"] = duplicate["surfaces"]["validator"]["path"]
    invalid_values.append((duplicate, "destinations must be unique"))
    unsupported = json.loads(json.dumps(current))
    unsupported["generated_manifest_profile"] = "unknown"
    invalid_values.append((unsupported, "profile must be accepted"))
    missing_template = json.loads(json.dumps(current))
    missing_template["surfaces"]["sdlc"]["template"] = "absent.tmpl"
    invalid_values.append((missing_template, "missing regular compatibility template"))
    for value, message in invalid_values:
        contract_path.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(RuntimeError, match=message):
            loader.load_compatibility_contract(bundle)
    blocked = run_compatibility_engine(bundle / "scripts", "apply", "--target-repo-root", str(repo))
    assert blocked.returncode == 1
    blocked_output = json.loads(blocked.stdout)
    assert blocked_output["rollback"] == "not_started"
    assert "compatibility template" in blocked_output["reason"]
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in observed_paths} == original

    contract_path.write_text(json.dumps(current), encoding="utf-8")
    review_path = contract_path.with_name(current["non_deterministic_review_file"])
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["evidence"] = {"command": "python -m github_contract_engine collect"}
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(RuntimeError, match="invalid compatibility contract"):
        loader.load_compatibility_contract(bundle)
    review.pop("evidence")
    review["deterministic_contract"] = "unrelated-contract.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(RuntimeError, match="review must reference"):
        loader.load_compatibility_contract(bundle)
    review["deterministic_contract"] = loader.CONTRACT_NAME
    review["checks"].append(review["checks"][0])
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(RuntimeError, match="check IDs must be unique"):
        loader.load_compatibility_contract(bundle)


@pytest.mark.parametrize("invalid", [False, True])
def test_compatibility_materializes_action_assignments(tmp_path: pathlib.Path, invalid: bool) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/actions", ["alpha-tool"])
    (repo / ".git").write_text("gitdir: test\n", encoding="utf-8")
    manifest = add_action_sections(repo)
    if invalid:
        manifest["actions"]["alpha-tool"]["references/notes.md"] = ["review-policy"]
        (repo / "skills/skill-sections.json").write_text(json.dumps(manifest), encoding="utf-8")
    before = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    result = run_compatibility_engine(REPOSITORY_LIFECYCLE_SCRIPTS, "apply", "--target-repo-root", str(repo))
    if invalid:
        assert result.returncode != 0
        assert "routed exactly once" in result.stdout
        assert before == {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    else:
        assert result.returncode == 0, result.stdout
        updated = json.loads((repo / "skills/skill-sections.json").read_text(encoding="utf-8"))
        assert updated["actions"] == manifest["actions"]
        assert updated["skills"] == manifest["skills"]
        for relative in manifest["actions"]["alpha-tool"]:
            assert (repo / "skills/alpha-tool" / relative).read_bytes() == before[pathlib.Path("skills/alpha-tool") / relative]



def test_generated_runtime_runs_without_installed_skills_and_keeps_tests_separate(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "independent"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: test\n")
    # A nested tooling workspace must not rewrite the application's lock or
    # adopt its incompatible Python constraint.
    application = '[project]\nname="application"\nversion="1.0"\nrequires-python=">=3.11"\n[tool.uv.workspace]\nmembers=[]\n'
    (repo / "pyproject.toml").write_text(application)
    (repo / "requirements.txt").write_text("# repository-owned\n")
    tests = repo / "tests"
    tests.mkdir()
    probe = tests / "test_probe.py"
    probe.write_text("def test_probe():\n    assert False, 'test-gate-evidence'\n")
    # Leave application uv.lock absent: test setup remains independent of the
    # generated validator's resolved dependency set.
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-installed-skills"))
    created = run_compatibility_engine(REPOSITORY_LIFECYCLE_SCRIPTS, "apply", "--target-repo-root", str(repo))
    assert created.returncode == 0, created.stdout + created.stderr
    assert (repo / "pyproject.toml").read_text() == application
    assert (repo / "requirements.txt").read_text() == "# repository-owned\n"
    assert not (repo / "uv.lock").exists()
    prefix = ["uv", "run", "--project", "scripts/validation", "--locked", "python"]
    validation = subprocess.run([*prefix, "scripts/validate-repository.py"], cwd=repo, capture_output=True, text=True)
    assert validation.returncode == 0, validation.stderr
    evidence = tmp_path / "sdlc-failure.json"
    command = [*prefix, "scripts/sdlc.py", "--validate", "--ci", "--evidence-file", str(evidence)]
    failed = subprocess.run(command, cwd=repo, capture_output=True, text=True)
    assert failed.returncode == 1, failed.stdout + failed.stderr
    result = json.loads(evidence.read_text())
    assert result["status"] == "tests_failed"
    assert result["operation"] == "repository.tests.python"
    assert any("test-gate-evidence" in line for line in result["diagnostic"]["stdout_tail"])
    probe.write_text("def test_probe():\n    assert True\n")
    passed = subprocess.run(command, cwd=repo, capture_output=True, text=True)
    assert passed.returncode == 0, passed.stdout + passed.stderr
    assert not evidence.exists()
    assert json.loads(passed.stdout)["completed_operations"] == ["repository.validate.repository", "repository.tests.python"]
    lock = (repo / "scripts/validation/uv.lock").read_bytes()
    reapplied = run_compatibility_engine(REPOSITORY_LIFECYCLE_SCRIPTS, "apply", "--target-repo-root", str(repo))
    assert reapplied.returncode == 0, reapplied.stdout
    assert (repo / "scripts/validation/uv.lock").read_bytes() == lock


def test_generated_python_runner_cleans_owned_temp_even_with_overrides(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "runner"
    (repo / "scripts").mkdir(parents=True)
    marker = tmp_path / "observed.json"
    (repo / "test_probe.py").write_text(
        "import json, pathlib\n"
        "def test_probe(tmp_path):\n"
        f"    pathlib.Path({str(marker)!r}).write_text(json.dumps(str(tmp_path)))\n"
        "    assert False\n"
    )
    template = (REPOSITORY_LIFECYCLE_SOURCE / "references/templates/run-tests.py.tmpl").read_text()
    runner = repo / "scripts/run-tests.py"
    runner.write_text(template.replace("__TEST_TARGETS__", "['test_probe.py']"))
    outside = tmp_path / "caller-temp"
    result = subprocess.run([
        sys.executable, str(runner), "--pytest-arg=--basetemp", "--pytest-arg=" + str(outside),
    ], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    observed = pathlib.Path(json.loads(marker.read_text()))
    assert not observed.exists()
    assert not outside.exists()


def test_missing_uv_rolls_back_generated_files_before_compatibility_claim(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    generator = importlib.import_module("ceratops_repo_compatibility_engine.apply_ceratops_compatibility")
    runtime = importlib.import_module("ceratops_repo_compatibility_engine.validation_environment")
    (tmp_path / ".git").write_text("gitdir: test\n")
    monkeypatch.setattr(runtime.shutil, "which", lambda name: None)
    assert generator.main(["--target-repo-root", str(tmp_path)]) == 1
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["phase"] == "validator_environment_setup"
    assert outcome["rollback"] == "completed"
    assert {p.name for p in tmp_path.iterdir()} == {".git"}
