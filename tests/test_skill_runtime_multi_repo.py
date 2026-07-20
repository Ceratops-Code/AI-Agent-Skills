from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "validation" / "validate-skills-consistency.py"
RENDERER = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "runtime" / "render-runtime-skills.py"
BOOTSTRAP = ROOT / "scripts" / "install-skills.py"
LIFECYCLE_SOURCE = ROOT / "skills" / "ceratops-skill-lifecycle"
INSTALLER_TEMPLATE = LIFECYCLE_SOURCE / "scripts" / "templates" / "install-skills-template.py"
INSTALLER_SYNCHRONIZER = LIFECYCLE_SOURCE / "scripts" / "runtime" / "synchronize-installers.py"
MANAGED_SKILLS_REVIEWER = LIFECYCLE_SOURCE / "scripts" / "runtime" / "review-managed-skills.py"
RUNTIME_MANIFEST = ".runtime-manifest.json"
RUNTIME_MANIFEST_SCHEMA = "ceratops-runtime-skill.v3"


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


def run_renderer(
    repo: pathlib.Path,
    install_root: pathlib.Path,
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    """Run the renderer against one isolated source and install root."""

    return subprocess.run(
        [
            sys.executable,
            str(RENDERER),
            "--repo-root",
            str(repo),
            "--install-root",
            str(install_root),
            "--installer-version",
            "1",
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def runtime_owner(install_root: pathlib.Path, skill_name: str) -> str:
    data = json.loads((install_root / skill_name / RUNTIME_MANIFEST).read_text(encoding="utf-8"))
    return str(data["runtime_source_id"])


def install_bundle_manifest(bundle_root: pathlib.Path) -> None:
    """Mark one copied lifecycle source folder as a supported installed bundle."""

    (bundle_root / RUNTIME_MANIFEST).write_text(
        json.dumps(
            {
                "schema": RUNTIME_MANIFEST_SCHEMA,
                "skill": "ceratops-skill-lifecycle",
                "validation_profile": "ceratops",
                "installer_version": 1,
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


def test_full_install_removes_only_same_source_stale_skills(tmp_path: pathlib.Path) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo_a, "example/source-a", ["alpha-tool", "retired-tool"])
    create_compatible_repo(repo_b, "example/source-b", ["beta-tool"])

    assert run_renderer(repo_a, install_root, "--remove-stale").returncode == 0
    assert run_renderer(repo_b, install_root, "--remove-stale").returncode == 0
    shutil.rmtree(repo_a / "skills" / "retired-tool")
    write_manifest(repo_a, "example/source-a")

    result = run_renderer(repo_a, install_root, "--remove-stale")

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
    assert run_renderer(repo_a, install_root, "--remove-stale").returncode == 0
    assert run_renderer(repo_b, install_root, "--remove-stale").returncode == 0

    shutil.rmtree(repo_a / "skills" / "retired-tool")
    write_manifest(repo_a, "example/source-a")
    targeted = run_renderer(repo_a, install_root, "--skill", "alpha-tool")
    assert targeted.returncode == 0, targeted.stderr
    assert (install_root / "retired-tool").is_dir()

    add_skill(repo_b, "alpha-tool")
    write_manifest(repo_b, "example/source-b")
    collision = run_renderer(repo_b, install_root, "--skill", "alpha-tool")
    assert collision.returncode == 1
    assert "owned by 'example/source-a'" in collision.stderr
    assert runtime_owner(install_root, "alpha-tool") == "example/source-a"

    unmanaged = install_root / "unmanaged-tool"
    unmanaged.mkdir()
    (unmanaged / "sentinel.txt").write_text("keep\n", encoding="utf-8")
    add_skill(repo_b, "unmanaged-tool")
    write_manifest(repo_b, "example/source-b")
    unmanaged_collision = run_renderer(repo_b, install_root, "--skill", "unmanaged-tool")
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
    legacy_collision = run_renderer(repo_b, install_root, "--skill", "legacy-tool")
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


def test_runtime_manifest_records_source_profile_and_installer_version(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])

    result = run_renderer(repo, install_root, "--skill", "alpha-tool")

    assert result.returncode == 0, result.stderr
    manifest = json.loads((install_root / "alpha-tool" / RUNTIME_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["schema"] == RUNTIME_MANIFEST_SCHEMA
    assert manifest["skill"] == "alpha-tool"
    assert manifest["runtime_source_id"] == "example/compatible"
    assert manifest["source_path"] == "skills/alpha-tool"
    assert manifest["source_repository_root"] == str(repo.resolve())
    assert manifest["validation_profile"] == "ceratops-compatible"
    assert manifest["installer_version"] == 1


def test_every_install_runs_full_target_validation(tmp_path: pathlib.Path) -> None:
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
    assert "Full target-repository validation failed" in result.stderr
    assert not (install_root / "alpha-tool").exists()


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

    target.write_text(custom.replace("INSTALLER_VERSION = 1", "INSTALLER_VERSION = 0"), encoding="utf-8", newline="\n")
    updated = subprocess.run(
        [sys.executable, str(INSTALLER_SYNCHRONIZER), "--target-repo-root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert updated.returncode == 0, updated.stderr
    assert json.loads(updated.stdout)["status"] == "updated"
    assert target.read_bytes() == INSTALLER_TEMPLATE.read_bytes()


def test_global_review_uses_only_direct_manifest_folders(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    assert run_renderer(repo, install_root, "--skill", "alpha-tool").returncode == 0
    (install_root / "unmanaged-tool").mkdir()
    nested = install_root / "unmanaged-tool" / "nested-managed"
    nested.mkdir()
    (nested / RUNTIME_MANIFEST).write_text("{}\n", encoding="utf-8", newline="\n")

    result = subprocess.run(
        [sys.executable, str(MANAGED_SKILLS_REVIEWER), "--runtime-root", str(install_root), "--mode", "consistency"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "groups": {"example/compatible": 1},
        "managed": 1,
        "mode": "consistency",
    }
