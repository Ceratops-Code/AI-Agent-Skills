from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

import yaml

from tests.repository_lifecycle.support import (
    REPOSITORY_LIFECYCLE_SCRIPTS,
    REPOSITORY_LIFECYCLE_SOURCE,
    SECTION_MANIFEST_TEMPLATE,
)
from tests.support.processes import COMPATIBILITY_ENGINE, run_compatibility_engine
from tests.support.repositories import (
    ROOT,
    create_compatible_repo,
)


def test_compatibility_materializer_supplies_target_identity_and_assignments(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "stale/source", ["alpha-tool", "beta-tool"])
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
        "materialize",
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
        (repo / "deploy" / "deploy.yml").read_text(encoding="utf-8")
    )
    assert contract["kind"] == "ceratops-deploy"
    assert contract["operations"]["deploy"] == {
        "handoff": "ceratops-skill-lifecycle/deploy"
    }
    assert contract["operations"]["bootstrap"] == {
        "steps": [
            {
                "id": "bootstrap-skills",
                "run": ["python", "scripts/install-skills-bootstrap.py"],
            }
        ]
    }
    assert (repo / "scripts" / "install-skills-bootstrap.py").is_file()
    assert (repo / "scripts" / "validate-repository.py").is_file()
    assert (repo / ".github" / "workflows" / "validate.yml").is_file()
    assert output["repository_validation"] == {
        "checks": [],
        "validator": "materialized",
        "workflow": "materialized",
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

    blocked_result = run_compatibility_engine(
        engine_scripts,
        "materialize",
        "--target-repo-root",
        str(repo),
        "--runtime-source-id",
        "example/empty-compatible",
    )

    assert blocked_result.returncode == 1
    assert json.loads(blocked_result.stdout) == {
        "phase": "materialization_planning",
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

    result = run_compatibility_engine(
        engine_scripts,
        "materialize",
        "--target-repo-root",
        str(repo),
        "--runtime-source-id",
        "example/empty-compatible",
    )

    assert result.returncode == 0, result.stdout
    manifest = json.loads(
        (repo / "skills" / "skill-sections.json").read_text(encoding="utf-8")
    )
    contract = yaml.safe_load(
        (repo / "deploy" / "deploy.yml").read_text(encoding="utf-8")
    )
    assert manifest["skills"] == {}
    assert manifest["sections"] == {}
    assert json.loads(result.stdout)["bootstrap"] == "skipped"
    assert contract == {
        "version": 1,
        "kind": "ceratops-deploy",
        "operations": {},
    }
    assert not (repo / "skills" / "sections").exists()
    assert not (repo / "scripts" / "install-skills-bootstrap.py").exists()
    output = json.loads(result.stdout)
    assert output["repository_validation"] == {
        "checks": ["npm-lint"],
        "validator": "materialized",
        "workflow": "materialized",
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

    omitted = tmp_path / "empty-without-deploy"
    shutil.copytree(repo, omitted)
    (omitted / "deploy" / "deploy.yml").unlink()
    omitted_result = run_compatibility_engine(
        engine_scripts,
        "materialize",
        "--target-repo-root",
        str(omitted),
        "--no-deploy-contract",
    )
    assert omitted_result.returncode == 0, omitted_result.stdout
    assert not (omitted / "deploy" / "deploy.yml").exists()
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
        "materialize",
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
    assert "python -m pip install mypy==2.3.0" in pnpm_workflow
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
    uv_result = run_compatibility_engine(
        engine_scripts,
        "materialize",
        "--target-repo-root",
        str(uv_repo),
        "--runtime-source-id",
        "example/uv-compatible",
    )
    assert uv_result.returncode == 0, uv_result.stdout
    assert json.loads(uv_result.stdout)["repository_validation"]["checks"] == [
        "pytest",
        "ruff",
        "mypy",
    ]
    uv_workflow = (uv_repo / ".github" / "workflows" / "validate.yml").read_text(
        encoding="utf-8"
    )
    assert "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9" in uv_workflow
    assert 'python-version-file: "pyproject.toml"' in uv_workflow
    assert 'python-version: "3.12"' not in uv_workflow
    assert "uv sync --extra dev --frozen" in uv_workflow
    assert "uv run --no-sync python scripts/validate-repository.py" in uv_workflow

    powershell_repo = empty_repository("powershell-compatible")
    for relative in (
        "scripts/Test-CodexSourceReadiness.ps1",
        "scripts/Test-CodexRuntimeHealth.ps1",
        "tests/Run-PowerShellQuality.ps1",
        "tests/Run-SmokeTests.ps1",
    ):
        path = powershell_repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("exit 0\n", encoding="utf-8", newline="\n")
    powershell_result = run_compatibility_engine(
        engine_scripts,
        "materialize",
        "--target-repo-root",
        str(powershell_repo),
        "--runtime-source-id",
        "example/powershell-compatible",
    )
    assert powershell_result.returncode == 0, powershell_result.stdout
    assert json.loads(powershell_result.stdout)["repository_validation"]["checks"] == [
        "powershell-source-readiness",
        "powershell-runtime-health",
        "powershell-lint",
        "powershell-smoke",
    ]
    powershell_workflow = (
        powershell_repo / ".github" / "workflows" / "validate.yml"
    ).read_text(encoding="utf-8")
    assert "runs-on: windows-latest" in powershell_workflow
    assert "Install-Module PSScriptAnalyzer" in powershell_workflow

    unittest_repo = empty_repository("unittest-compatible")
    (unittest_repo / "deploy").mkdir()
    (unittest_repo / "deploy" / "validate-automations.py").write_text(
        "print('OK')\n", encoding="utf-8", newline="\n"
    )
    (unittest_repo / "tests").mkdir()
    (unittest_repo / "tests" / "test_example.py").write_text(
        "import unittest\n", encoding="utf-8", newline="\n"
    )
    unittest_result = run_compatibility_engine(
        engine_scripts,
        "materialize",
        "--target-repo-root",
        str(unittest_repo),
        "--runtime-source-id",
        "example/unittest-compatible",
    )
    assert unittest_result.returncode == 0, unittest_result.stdout
    assert json.loads(unittest_result.stdout)["repository_validation"]["checks"] == [
        "automation-source-validation",
        "unittest",
    ]

    docs_repo = empty_repository("docs-compatible")
    (docs_repo / "README.md").write_text(
        "python -m ruff check --select E9,F63,F7,F82 scripts/run_form.py "
        "skills/claims-catalog-invoice/scripts tests/test_claims_tracker.py\n",
        encoding="utf-8",
        newline="\n",
    )
    (docs_repo / "requirements.txt").write_text(
        "python-docx==1.2.0\n", encoding="utf-8", newline="\n"
    )
    (docs_repo / "scripts").mkdir()
    (docs_repo / "scripts" / "run_form.py").write_text(
        "print('OK')\n", encoding="utf-8", newline="\n"
    )
    (docs_repo / "skills" / "claims-catalog-invoice" / "scripts").mkdir(
        parents=True
    )
    (docs_repo / "skills" / "claims-catalog-invoice" / "scripts" / "claim.py").write_text(
        "CLAIM = True\n", encoding="utf-8", newline="\n"
    )
    (docs_repo / "tests").mkdir()
    (docs_repo / "tests" / "test_claims_tracker.py").write_text(
        "import unittest\n", encoding="utf-8", newline="\n"
    )
    docs_result = run_compatibility_engine(
        engine_scripts,
        "materialize",
        "--target-repo-root",
        str(docs_repo),
        "--runtime-source-id",
        "example/docs-compatible",
    )
    assert docs_result.returncode == 0, docs_result.stdout
    assert json.loads(docs_result.stdout)["repository_validation"]["checks"] == [
        "unittest",
        "ruff-critical",
    ]
    docs_workflow = (
        docs_repo / ".github" / "workflows" / "validate.yml"
    ).read_text(encoding="utf-8")
    assert "ruff==0.16.1" in docs_workflow

    authoritative_repo = empty_repository("authoritative-compatible")
    (authoritative_repo / "scripts").mkdir()
    (authoritative_repo / "scripts" / "validate_repository.py").write_text(
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
        "materialize",
        "--target-repo-root",
        str(authoritative_repo),
        "--runtime-source-id",
        "example/authoritative-compatible",
    )
    assert authoritative_result.returncode == 0, authoritative_result.stdout
    assert json.loads(authoritative_result.stdout)["repository_validation"]["checks"] == [
        "hasbaratops-validator"
    ]
    authoritative_validator = (
        authoritative_repo / "scripts" / "validate-repository.py"
    ).read_text(encoding="utf-8")
    assert "{temp}/hasbaratops" in authoritative_validator
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
    assert "child_evidence: hasbaratops-validation.log" in retained_evidence
    assert "inner diagnostic" in retained_evidence


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
        "materialize",
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
        "materialize",
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
        "materialize",
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
        repo / "scripts" / "install-skills-bootstrap.py",
        repo / "deploy" / "deploy.yml",
    )
    original = {path: path.read_bytes() for path in changed_paths}

    result = run_compatibility_engine(
        engine_scripts,
        "materialize",
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
        repo / "scripts" / "install-skills-bootstrap.py",
        repo / "deploy" / "deploy.yml",
    )
    original = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in observed_paths
    }

    result = run_compatibility_engine(
        REPOSITORY_LIFECYCLE_SCRIPTS,
        "materialize",
        "--target-repo-root",
        str(repo),
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["phase"] == "materialization_planning"
    assert output["rollback"] == "not_started"
    assert {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in observed_paths
    } == original
