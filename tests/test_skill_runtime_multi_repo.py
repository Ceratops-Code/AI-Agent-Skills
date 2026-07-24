from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "skills-consistency-source-validator.py"
BUILDER = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "runtime" / "managed_runtime_builder.py"
BOOTSTRAP = ROOT / "scripts" / "install-skills.py"
LIFECYCLE_SOURCE = ROOT / "skills" / "ceratops-skill-lifecycle"
INSTALLER_TEMPLATE = LIFECYCLE_SOURCE / "scripts" / "templates" / "install-skills-template.py"
INSTALLER_SYNCHRONIZER = LIFECYCLE_SOURCE / "scripts" / "runtime" / "synchronize-installers.py"
RUNTIME_VALIDATOR = LIFECYCLE_SOURCE / "scripts" / "runtime" / "skills-consistency-runtime-validator.py"
RUNTIME_MANIFEST = ".runtime-manifest.json"
RUNTIME_MANIFEST_SCHEMA = "ceratops-runtime-skill.v3"
INSTALLER_VERSION = 2


def add_skill(repo: pathlib.Path, name: str) -> None:
    """Add one minimal source skill that satisfies the compatible profile."""

    skill_dir = repo / "skills" / name
    (skill_dir / "agents").mkdir(parents=True)
    (skill_dir / "assets").mkdir()
    (skill_dir / "assets" / "icon.png").write_bytes(b"test-icon")
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: Manage {name.replace('-', ' ')} workflows safely across compatible repositories.",
                "---",
                "",
                f"# {name.replace('-', ' ').title()}",
                "",
                "## Workflow",
                "",
                "### Boundaries",
                "",
                "Stay within the selected repository.",
                "",
                "### Output Contract",
                "",
                "Report the validated result.",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    (skill_dir / "agents" / "openai.yaml").write_text(
        "\n".join(
            [
                "interface:",
                f'  display_name: "{name.replace("-", " ").title()}"',
                f'  short_description: "Manage {name.replace("-", " ")} workflows"',
                '  icon_small: "./assets/icon.png"',
                '  icon_large: "./assets/icon.png"',
                f'  default_prompt: "Use ${name} for this workflow."',
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )


def create_compatible_repo(repo: pathlib.Path, source_id: str, skill_names: list[str]) -> None:
    """Create the smallest complete Ceratops-compatible source repository."""

    (repo / "templates" / "sections").mkdir(parents=True)
    (repo / "templates" / "sections" / "core.md").write_text(
        "## Shared Runtime Rules\n\nUse the source repository contract.\n",
        encoding="utf-8",
        newline="\n",
    )
    (repo / "scripts").mkdir()
    shutil.copy2(INSTALLER_TEMPLATE, repo / "scripts" / "install-skills.py")
    for skill_name in skill_names:
        add_skill(repo, skill_name)
    write_manifest(repo, source_id)
    rows = "\n".join(f"| `{name}` | Test skill. |" for name in sorted(skill_names))
    (repo / "README.md").write_text(
        "# Compatible Skills\n\n"
        "| org | repo |\n| --- | --- |\n| `unrelated-row` | value |\n\n"
        "## Skills\n\n| Skill | Purpose |\n| --- | --- |\n"
        f"{rows}\n\n## Notes\n",
        encoding="utf-8",
        newline="\n",
    )


def write_manifest(repo: pathlib.Path, source_id: str) -> None:
    """Rewrite assignments after a test adds or removes source skills."""

    skill_names = sorted(path.parent.name for path in (repo / "skills").glob("*/SKILL.md"))
    manifest = {
        "runtime_source_id": source_id,
        "validation_profile": "ceratops-compatible",
        "sections": {"core": "templates/sections/core.md"},
        "skills": {name: ["core"] for name in skill_names},
    }
    (repo / "templates" / "skill-sections.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def run_builder(
    repo: pathlib.Path,
    install_root: pathlib.Path,
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    """Run the managed runtime builder against one isolated install root."""

    return subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--repo-root",
            str(repo),
            "--install-root",
            str(install_root),
            "--installer-version",
            str(INSTALLER_VERSION),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def runtime_owner(install_root: pathlib.Path, skill_name: str) -> str:
    data = json.loads((install_root / skill_name / RUNTIME_MANIFEST).read_text(encoding="utf-8"))
    return str(data["runtime_source_id"])


def install_bundle_manifest(
    bundle_root: pathlib.Path,
    installer_version: int = INSTALLER_VERSION,
) -> None:
    """Mark one copied lifecycle source folder as a supported installed bundle."""

    (bundle_root / RUNTIME_MANIFEST).write_text(
        json.dumps(
            {
                "schema": RUNTIME_MANIFEST_SCHEMA,
                "skill": "ceratops-skill-lifecycle",
                "validation_profile": "ceratops",
                "installer_version": installer_version,
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def test_compatible_full_validation_accepts_arbitrary_skill_names(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok: 1"


def test_full_validation_excludes_git_ignored_files(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    subprocess.run(
        ["git", "init", "--quiet", str(repo)],
        capture_output=True,
        text=True,
        check=True,
    )
    (repo / ".gitignore").write_text(
        ".venv/\nignored-output/\n",
        encoding="utf-8",
        newline="\n",
    )
    for ignored_dir in (repo / ".venv", repo / "ignored-output"):
        ignored_dir.mkdir()
        (ignored_dir / "generated.md").write_text(
            "C:\\Users\\roman\\generated\nUse $" + "unknown-skill.\n",
            encoding="utf-8",
            newline="\n",
        )

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok: 1"


def test_full_validation_scans_manifest_runtime_inputs_only(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    runtime_input = repo / "runtime-note.md"
    runtime_input.write_text(
        "Generated from C:\\Users\\roman\\private-source.\n",
        encoding="utf-8",
        newline="\n",
    )

    unlisted = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert unlisted.returncode == 0, unlisted.stderr

    manifest_path = repo / "templates" / "skill-sections.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtime_payloads"] = {"alpha-tool": ["runtime-note.md"]}
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    listed = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert listed.returncode == 1
    assert "runtime-note.md: high-confidence secret or private path pattern" in listed.stderr


def test_full_install_removes_only_same_source_stale_skills(tmp_path: pathlib.Path) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo_a, "example/source-a", ["alpha-tool", "retired-tool"])
    create_compatible_repo(repo_b, "example/source-b", ["beta-tool"])

    assert run_builder(repo_a, install_root, "--remove-stale").returncode == 0
    assert run_builder(repo_b, install_root, "--remove-stale").returncode == 0
    shutil.rmtree(repo_a / "skills" / "retired-tool")
    write_manifest(repo_a, "example/source-a")

    result = run_builder(repo_a, install_root, "--remove-stale")

    assert result.returncode == 0, result.stderr
    assert not (install_root / "retired-tool").exists()
    assert runtime_owner(install_root, "alpha-tool") == "example/source-a"
    assert runtime_owner(install_root, "beta-tool") == "example/source-b"


def test_targeted_install_keeps_stale_and_rejects_other_source_collision(tmp_path: pathlib.Path) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo_a, "example/source-a", ["alpha-tool", "retired-tool"])
    create_compatible_repo(repo_b, "example/source-b", ["beta-tool"])
    assert run_builder(repo_a, install_root, "--remove-stale").returncode == 0
    assert run_builder(repo_b, install_root, "--remove-stale").returncode == 0

    shutil.rmtree(repo_a / "skills" / "retired-tool")
    write_manifest(repo_a, "example/source-a")
    targeted = run_builder(repo_a, install_root, "--skill", "alpha-tool")
    assert targeted.returncode == 0, targeted.stderr
    assert (install_root / "retired-tool").is_dir()

    add_skill(repo_b, "alpha-tool")
    write_manifest(repo_b, "example/source-b")
    collision = run_builder(repo_b, install_root, "--skill", "alpha-tool")
    assert collision.returncode == 1
    assert "owned by 'example/source-a'" in collision.stderr
    assert runtime_owner(install_root, "alpha-tool") == "example/source-a"

    unmanaged = install_root / "unmanaged-tool"
    unmanaged.mkdir()
    (unmanaged / "sentinel.txt").write_text("keep\n", encoding="utf-8")
    add_skill(repo_b, "unmanaged-tool")
    write_manifest(repo_b, "example/source-b")
    unmanaged_collision = run_builder(repo_b, install_root, "--skill", "unmanaged-tool")
    assert unmanaged_collision.returncode == 1
    assert "unmanaged runtime skill folder" in unmanaged_collision.stderr
    assert (unmanaged / "sentinel.txt").is_file()

    legacy = install_root / "legacy-tool"
    legacy.mkdir()
    (legacy / RUNTIME_MANIFEST).write_text(
        json.dumps({"schema": "ceratops-runtime-skill.v2", "skill": "legacy-tool"}) + "\n",
        encoding="utf-8",
    )
    add_skill(repo_b, "legacy-tool")
    write_manifest(repo_b, "example/source-b")
    legacy_collision = run_builder(repo_b, install_root, "--skill", "legacy-tool")
    assert legacy_collision.returncode == 1
    assert "unsupported ownership manifest" in legacy_collision.stderr


def test_bootstrap_prefers_installed_bundle_for_external_repo(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    codex_home = tmp_path / "codex-home"
    install_root = tmp_path / "installed"
    installed_bundle = codex_home / "skills" / "ceratops-skill-lifecycle"
    create_compatible_repo(repo, "example/external", ["alpha-tool"])
    shutil.copytree(LIFECYCLE_SOURCE, installed_bundle)
    install_bundle_manifest(installed_bundle)
    env = {**os.environ, "CODEX_HOME": str(codex_home)}

    result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "install-skills.py"),
            "--repo-root",
            str(repo),
            "--install-root",
            str(install_root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert runtime_owner(install_root, "alpha-tool") == "example/external"


def test_bootstrap_falls_back_to_checkout_for_first_install(tmp_path: pathlib.Path) -> None:
    codex_home = tmp_path / "empty-codex-home"
    install_root = tmp_path / "installed"
    env = {**os.environ, "CODEX_HOME": str(codex_home)}

    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP),
            "--repo-root",
            str(ROOT),
            "--install-root",
            str(install_root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert runtime_owner(install_root, "ceratops-skill-lifecycle") == "Ceratops-Code/AI-Agent-Skills"


def test_bootstrap_uses_checkout_resolver_for_outdated_installed_bundle(
    tmp_path: pathlib.Path,
) -> None:
    codex_home = tmp_path / "codex-home"
    install_root = tmp_path / "installed"
    installed_bundle = codex_home / "skills" / "ceratops-skill-lifecycle"
    shutil.copytree(LIFECYCLE_SOURCE, installed_bundle)
    install_bundle_manifest(installed_bundle, installer_version=1)
    installed_resolver = installed_bundle / "scripts" / "runtime" / "resolve-lifecycle-bundle.py"
    installed_resolver.write_text(
        "raise SystemExit('outdated resolver was selected')\n",
        encoding="utf-8",
        newline="\n",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP),
            "--repo-root",
            str(ROOT),
            "--install-root",
            str(install_root),
            "--skill",
            "ceratops-skill-lifecycle",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )

    assert result.returncode == 0, result.stderr
    assert runtime_owner(install_root, "ceratops-skill-lifecycle") == "Ceratops-Code/AI-Agent-Skills"


def test_runtime_manifest_records_source_profile_and_installer_version(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])

    result = run_builder(repo, install_root, "--skill", "alpha-tool")

    assert result.returncode == 0, result.stderr
    manifest = json.loads((install_root / "alpha-tool" / RUNTIME_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["schema"] == RUNTIME_MANIFEST_SCHEMA
    assert manifest["skill"] == "alpha-tool"
    assert manifest["runtime_source_id"] == "example/compatible"
    assert manifest["source_path"] == "skills/alpha-tool"
    assert manifest["source_repository_root"] == str(repo.resolve())
    assert manifest["validation_profile"] == "ceratops-compatible"
    assert manifest["installer_version"] == INSTALLER_VERSION


def test_full_install_runs_full_source_validation(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    codex_home = tmp_path / "codex-home"
    install_root = tmp_path / "installed"
    installed_bundle = codex_home / "skills" / "ceratops-skill-lifecycle"
    create_compatible_repo(repo, "example/external", ["alpha-tool"])
    shutil.copytree(LIFECYCLE_SOURCE, installed_bundle)
    install_bundle_manifest(installed_bundle)
    (repo / "README.md").write_text("# Invalid\n", encoding="utf-8", newline="\n")

    result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "install-skills.py"),
            "--repo-root",
            str(repo),
            "--install-root",
            str(install_root),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )

    assert result.returncode == 1
    assert "Full source-repository validation failed" in result.stderr
    assert not (install_root / "alpha-tool").exists()


def test_targeted_install_validates_only_selected_skill(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    codex_home = tmp_path / "codex-home"
    install_root = tmp_path / "installed"
    installed_bundle = codex_home / "skills" / "ceratops-skill-lifecycle"
    create_compatible_repo(repo, "example/external", ["alpha-tool", "broken-tool"])
    shutil.copytree(LIFECYCLE_SOURCE, installed_bundle)
    install_bundle_manifest(installed_bundle)
    (repo / "skills" / "broken-tool" / "SKILL.md").write_text("invalid\n", encoding="utf-8", newline="\n")

    result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "install-skills.py"),
            "--repo-root",
            str(repo),
            "--install-root",
            str(install_root),
            "--skill",
            "alpha-tool",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )

    assert result.returncode == 0, result.stderr
    assert (install_root / "alpha-tool" / "SKILL.md").is_file()
    assert not (install_root / "broken-tool").exists()

    (repo / "skills" / "alpha-tool" / "SKILL.md").write_text("invalid\n", encoding="utf-8", newline="\n")
    invalid_selected = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "install-skills.py"),
            "--repo-root",
            str(repo),
            "--install-root",
            str(install_root),
            "--skill",
            "alpha-tool",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )

    assert invalid_selected.returncode == 1
    assert "Targeted skill validation failed" in invalid_selected.stderr


def test_installer_synchronization_compares_only_version(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    (repo / ".git").write_text("gitdir: test\n", encoding="utf-8", newline="\n")
    target = repo / "scripts" / "install-skills.py"
    custom = target.read_text(encoding="utf-8") + "\n# same-version local difference\n"
    target.write_text(custom, encoding="utf-8", newline="\n")

    retained = subprocess.run(
        [sys.executable, str(INSTALLER_SYNCHRONIZER), "--target-repo-root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert retained.returncode == 0, retained.stderr
    assert json.loads(retained.stdout)["status"] == "retained"
    assert target.read_text(encoding="utf-8") == custom

    target.write_text(
        custom.replace(
            f"INSTALLER_VERSION = {INSTALLER_VERSION}", "INSTALLER_VERSION = 0"
        ),
        encoding="utf-8",
        newline="\n",
    )
    updated = subprocess.run(
        [sys.executable, str(INSTALLER_SYNCHRONIZER), "--target-repo-root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert updated.returncode == 0, updated.stderr
    assert json.loads(updated.stdout)["status"] == "updated"
    assert target.read_bytes() == INSTALLER_TEMPLATE.read_bytes()


def test_repository_review_uses_only_attributable_direct_manifest_folders(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    other_repo = tmp_path / "other-compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    create_compatible_repo(other_repo, "example/other-compatible", ["beta-tool"])
    assert run_builder(repo, install_root, "--skill", "alpha-tool").returncode == 0
    assert run_builder(other_repo, install_root, "--skill", "beta-tool").returncode == 0
    (install_root / "unmanaged-tool").mkdir()
    nested = install_root / "unmanaged-tool" / "nested-managed"
    nested.mkdir()
    (nested / RUNTIME_MANIFEST).write_text("{}\n", encoding="utf-8", newline="\n")

    result = subprocess.run(
        [
            sys.executable,
            str(RUNTIME_VALIDATOR),
            "--repo-root",
            str(repo),
            "--runtime-root",
            str(install_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "managed": 1,
        "runtime_source_id": "example/compatible",
        "status": "valid",
    }

    installed_metadata = install_root / "alpha-tool" / "agents" / "openai.yaml"
    installed_metadata.write_text("stale: true\n", encoding="utf-8", newline="\n")
    stale_metadata = subprocess.run(
        [
            sys.executable,
            str(RUNTIME_VALIDATOR),
            "--repo-root",
            str(repo),
            "--runtime-root",
            str(install_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert stale_metadata.returncode == 1
    assert "managed file content differs: agents/openai.yaml" in stale_metadata.stderr
    assert run_builder(repo, install_root, "--skill", "alpha-tool").returncode == 0

    installed_skill = install_root / "alpha-tool" / "SKILL.md"
    installed_skill.write_text(
        installed_skill.read_text(encoding="utf-8").replace(
            "Use the source repository contract.",
            "Stale generated section.",
        ),
        encoding="utf-8",
        newline="\n",
    )
    stale = subprocess.run(
        [
            sys.executable,
            str(RUNTIME_VALIDATOR),
            "--repo-root",
            str(repo),
            "--runtime-root",
            str(install_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert stale.returncode == 1
    assert "managed file content differs: SKILL.md" in stale.stderr


def test_selected_skill_review_does_not_audit_sibling_skills(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool", "beta-tool"])
    assert run_builder(repo, install_root, "--remove-stale").returncode == 0
    (install_root / "beta-tool" / "SKILL.md").write_text(
        "stale\n",
        encoding="utf-8",
        newline="\n",
    )

    selected = subprocess.run(
        [
            sys.executable,
            str(RUNTIME_VALIDATOR),
            "--repo-root",
            str(repo),
            "--runtime-root",
            str(install_root),
            "--skill",
            "alpha-tool",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert selected.returncode == 0, selected.stderr
    assert json.loads(selected.stdout) == {
        "managed": 1,
        "runtime_source_id": "example/compatible",
        "status": "valid",
    }
