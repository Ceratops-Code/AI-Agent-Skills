from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]
INSTALLER_TEMPLATE = ROOT / "skills" / "ceratops-repo-lifecycle" / "references" / "templates" / "deploy-skills-template.py"


def run_git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one isolated test-repository Git command."""

    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def write_sdlc_contract(
    repo: pathlib.Path,
    *,
    repository: dict[str, object] | None = None,
    deliverables: dict[str, object] | None = None,
) -> pathlib.Path:
    """Write or extend the current capability contract without format conversion."""

    contract = repo / "sdlc" / "sdlc.yml"
    contract.parent.mkdir(parents=True, exist_ok=True)
    document: dict[str, object] = {"version": 2, "kind": "ceratops-sdlc"}
    if contract.exists():
        document = json.loads(contract.read_text(encoding="utf-8"))
    for name, group in (("repository", repository), ("deliverables", deliverables)):
        if group is not None:
            document[name] = group
    contract.write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n",
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
    write_sdlc_contract(
        repo,
        deliverables={"skills": {"deploy-local": {
            "managed": {"handoff": "ceratops-skill-lifecycle/deploy"},
            "standalone": {"steps": [{"run": ["python", "scripts/deploy-skills.py"]}]},
        }}},
    )
    (repo / "scripts").mkdir()
    shutil.copy2(
        INSTALLER_TEMPLATE,
        repo / "scripts" / "deploy-skills.py",
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
