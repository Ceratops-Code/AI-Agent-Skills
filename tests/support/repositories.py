from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]
INSTALLER_TEMPLATE = ROOT / "skills" / "ceratops-repo-lifecycle" / "references" / "templates" / "install-skills-bootstrap-template.py"


def run_git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one isolated test-repository Git command."""

    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def write_deploy_contract(
    repo: pathlib.Path,
    operations: dict[str, object],
) -> pathlib.Path:
    """Write one JSON-compatible YAML deployment contract."""

    contract = repo / "deploy" / "deploy.yml"
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text(
        json.dumps(
            {
                "version": 1,
                "kind": "ceratops-deploy",
                "operations": operations,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return contract


def write_release_contract(
    repo: pathlib.Path,
    operations: dict[str, object],
) -> pathlib.Path:
    """Write one JSON-compatible YAML release-publication contract."""

    contract = repo / "release" / "release.yml"
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text(
        json.dumps(
            {
                "version": 1,
                "kind": "ceratops-release",
                "operations": operations,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return contract


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

    (repo / "skills" / "sections").mkdir(parents=True)
    shutil.copy2(
        ROOT / "skills" / "sections" / "core.md",
        repo / "skills" / "sections" / "core.md",
    )
    write_deploy_contract(
        repo,
        {
            "deploy": {
                "handoff": "ceratops-skill-lifecycle/deploy",
            },
            "bootstrap": {
                "steps": [
                    {
                        "id": "bootstrap-skills",
                        "run": [
                            "python",
                            "scripts/install-skills-bootstrap.py",
                        ],
                    }
                ]
            }
        },
    )
    (repo / "scripts").mkdir()
    shutil.copy2(
        INSTALLER_TEMPLATE,
        repo / "scripts" / "install-skills-bootstrap.py",
    )
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
        "sections": {"core": "skills/sections/core.md"},
        "skills": {name: ["core"] for name in skill_names},
    }
    (repo / "skills" / "skill-sections.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
