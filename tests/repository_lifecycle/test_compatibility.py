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
    }
    assert (repo / "scripts" / "deploy-skills.py").is_file()
    assert (repo / "scripts" / "validate-repository.py").is_file()
    assert (repo / ".github" / "workflows" / "validate.yml").is_file()
    assert output["repository_validation"] == {
        "checks": ["npm-markdown-lint"],
        "validator": "applied",
        "workflow": "applied",
    }
    package = json.loads((repo / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((repo / "package-lock.json").read_text(encoding="utf-8"))
    assert package["private"] is True
    assert package["scripts"]["lint:markdown"] == (
        'markdownlint "**/*.md" --ignore node_modules'
    )
    assert package["devDependencies"] == {"markdownlint-cli": "0.49.1"}
    assert lock["packages"][""]["devDependencies"] == package["devDependencies"]
    assert lock["packages"]["node_modules/markdownlint-cli"]["version"] == "0.49.1"
    assert json.loads((repo / ".markdownlint.json").read_text(encoding="utf-8"))["MD013"] == {
        "line_length": 80, "code_blocks": False, "tables": False,
    }
    assert (repo / ".gitignore").read_text(encoding="utf-8").endswith("/node_modules/\n")
    steps = yaml.safe_load(
        (repo / ".github/workflows/validate.yml").read_text(encoding="utf-8")
    )["jobs"]["validate-repository"]["steps"]
    assert next(step["with"] for step in steps if step["name"] == "Set up Node.js") == {
        "node-version": "24",
    }
    assert next(
        step["run"] for step in steps if step["name"] == "Install npm validation dependencies"
    ) == "npm ci"
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
        {"run": ["python", "scripts/validate-repository.py"]}
    ]
    assert "deliverables" not in contract
    assert not (repo / "scripts" / "deploy-skills.py").exists()
    assert output["repository_validation"] == {
        "checks": ["npm-lint", "unittest"],
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
    assert not list(repo.rglob("__pycache__"))

    omitted = tmp_path / "empty-without-sdlc"
    shutil.copytree(repo, omitted)
    omitted_result = run_compatibility_engine(
        engine_scripts,
        "apply",
        "--target-repo-root",
        str(omitted),
        "--no-sdlc-contract",
    )
    assert omitted_result.returncode == 0, omitted_result.stdout
    assert (omitted / "sdlc" / "sdlc.yml").read_bytes() == (repo / "sdlc" / "sdlc.yml").read_bytes()
    assert json.loads(omitted_result.stdout)["repository_validation"] == {
        "checks": [],
        "validator": "preserved",
        "workflow": "preserved",
    }

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

    # A transpiling build does not establish type safety. Preserve an explicit
    # typecheck for either package manager, with or without a build script.
    for manager in ("npm", "pnpm"):
        for has_build in (False, True):
            typecheck_repo = empty_repository(f"{manager}-typecheck-{has_build}")
            scripts = {"typecheck": "tsc --noEmit"}
            if has_build:
                scripts["build"] = "vite build"
            package: dict[str, object] = {"scripts": scripts}
            if manager == "pnpm":
                package["packageManager"] = "pnpm@10.33.4"
                (typecheck_repo / "pnpm-lock.yaml").write_text(
                    "lockfileVersion: '9.0'\n", encoding="utf-8", newline="\n"
                )
            else:
                (typecheck_repo / "package-lock.json").write_text(
                    json.dumps({"lockfileVersion": 3, "requires": True, "packages": {}})
                    + "\n", encoding="utf-8", newline="\n"
                )
            (typecheck_repo / "package.json").write_text(
                json.dumps(package) + "\n", encoding="utf-8", newline="\n"
            )
            typecheck_result = run_compatibility_engine(
                engine_scripts, "apply", "--target-repo-root", str(typecheck_repo)
            )
            assert typecheck_result.returncode == 0, typecheck_result.stdout
            selected = json.loads(typecheck_result.stdout)["repository_validation"]["checks"]
            assert f"{manager}-typecheck" in selected
            assert (f"{manager}-build" in selected) is has_build
            other_manager = "npm" if manager == "pnpm" else "pnpm"
            assert f"{other_manager}-typecheck" not in selected

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
        "pytest",
        "mypy",
    ]
    pnpm_workflow = (
        pnpm_repo / ".github" / "workflows" / "validate.yml"
    ).read_text(encoding="utf-8")
    assert "actions/setup-node@2028fbc5c25fe9cf00d9f06a71cc4710d4507903" in pnpm_workflow
    assert "corepack prepare pnpm@10.33.4 --activate" in pnpm_workflow
    assert "pnpm install --frozen-lockfile" in pnpm_workflow
    assert "python -m pip install -r requirements-dev.txt" in pnpm_workflow
    pnpm_steps = yaml.safe_load(pnpm_workflow)["jobs"]["validate-repository"]["steps"]
    assert [
        step["run"].splitlines()
        for step in pnpm_steps
        if step.get("name") == "Install Python validation dependencies"
    ] == [["python -m pip install -r requirements-dev.txt"]]
    assert 'python-version: "3.12"' in pnpm_workflow

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
        "npm-markdown-lint",
        "pytest",
        "ruff",
        "mypy",
        "yaml-lint",
    ]
    uv_workflow = (uv_repo / ".github" / "workflows" / "validate.yml").read_text(
        encoding="utf-8"
    )
    assert "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9" in uv_workflow
    assert 'python-version-file: "pyproject.toml"' in uv_workflow
    assert 'python-version: "3.12"' not in uv_workflow
    assert "uv sync --extra dev --frozen" in uv_workflow
    uv_steps = yaml.safe_load(uv_workflow)["jobs"]["validate-repository"]["steps"]
    assert [
        step["run"].splitlines()
        for step in uv_steps
        if step.get("name") == "Install Python validation dependencies"
    ] == [["uv sync --extra dev --frozen"]]
    assert "uv run --no-sync python scripts/validate-repository.py" in uv_workflow

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
        "npm-markdown-lint",
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
        "npm-markdown-lint",
        "unittest",
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
        "npm-markdown-lint",
        "unittest",
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
    assert not (authoritative_repo / "package.json").exists()
    assert not (authoritative_repo / ".markdownlint.json").exists()
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

    # Every documented pytest configuration form selects pytest and suppresses
    # unittest, even when the target only declares the tool through its config.
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
        assert json.loads(configured.stdout)["repository_validation"]["checks"] == [
            "npm-markdown-lint", "pytest",
        ]

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
    assert {
        path: (path.read_bytes(), path.stat().st_mode)
        for path in (validator, workflow)
    } == before
    assert json.loads(result.stdout)["repository_validation"] == {
        "checks": [],
        "validator": "preserved",
        "workflow": "preserved",
    }
    assert not (repo / "package.json").exists()
    assert not (repo / ".markdownlint.json").exists()


@pytest.mark.parametrize("configuration", [
    ".markdownlint.jsonc", ".markdownlint.yaml", ".markdownlint.cjs", ".markdownlintrc",
])
def test_compatibility_materializer_preserves_existing_identity_and_custom_sections(
    tmp_path: pathlib.Path,
    configuration: str,
) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "preserved/source", ["alpha-tool"])
    (repo / ".git").write_text("gitdir: test\n", encoding="utf-8", newline="\n")
    markdown_config = repo / configuration
    configuration_bytes = {
        ".markdownlint.jsonc": b'{"MD013": false}\r\n',
        ".markdownlint.yaml": b"MD013: false\r\n",
        ".markdownlint.cjs": b"module.exports = { MD013: false };\r\n",
        ".markdownlintrc": b'{"MD013": false}\r\n',
    }[configuration]
    markdown_config.write_bytes(configuration_bytes)
    ignore = repo / ".gitignore"
    ignore.write_bytes(b"build/\r\n!node_modules/")
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
    assert markdown_config.read_bytes() == configuration_bytes
    assert not (repo / ".markdownlint.json").exists()
    assert ignore.read_bytes() == b"build/\r\n!node_modules/\r\n/node_modules/\r\n"
    package = json.loads((repo / "package.json").read_text(encoding="utf-8"))
    if configuration == ".markdownlint.cjs":
        assert package["scripts"]["lint:markdown"].endswith(" --config .markdownlint.cjs")
    preserved = {
        name: (repo / name).read_bytes()
        for name in (configuration, ".gitignore", "package.json", "package-lock.json")
    }

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
    assert {name: (repo / name).read_bytes() for name in preserved} == preserved


@pytest.mark.parametrize("existing_ignore", [False, True])
def test_compatibility_materializer_rolls_back_every_target_write_on_blocker(
    tmp_path: pathlib.Path,
    existing_ignore: bool,
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
            "__VALIDATOR_PYTHON__ scripts/validate-repository.py",
            "__VALIDATOR_PYTHON__ scripts/not-the-repository-validator.py",
        ),
        encoding="utf-8",
        newline="\n",
    )
    engine_scripts = lifecycle_bundle / "scripts"
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "preserved/source", ["alpha-tool"])
    (repo / ".git").write_text("gitdir: test\n", encoding="utf-8", newline="\n")
    ignore = repo / ".gitignore"
    if existing_ignore:
        ignore.write_bytes(b"build/\r\n")
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
    assert all(not (repo / name).exists() for name in (
        "package.json", "package-lock.json", ".markdownlint.json",
    ))
    if existing_ignore:
        assert ignore.read_bytes() == b"build/\r\n"
    else:
        assert not ignore.exists()


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
