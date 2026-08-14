from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

from tests.skill_lifecycle.support import (
    LIVE_SECTION_MANIFEST,
    SECTION_MANIFEST_TEMPLATE,
    VALIDATOR,
    load_source_validator,
    write_multi_action_skill,
)
from tests.support.repositories import (
    ROOT,
    create_compatible_repo,
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


def test_source_validator_ignores_shared_sections_directory(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "sections"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok: sections 1"


def test_skill_sections_template_contains_no_live_repository_inventory() -> None:
    template = json.loads(SECTION_MANIFEST_TEMPLATE.read_text(encoding="utf-8"))
    live = json.loads(LIVE_SECTION_MANIFEST.read_text(encoding="utf-8"))

    assert template == {
        "runtime_source_id": "",
        "validation_profile": "ceratops-compatible",
        "sections": {"core": "skills/sections/core.md"},
        "maintenance_workflows": {},
        "runtime_payloads": {},
        "skills": {},
    }
    assert live["runtime_source_id"]
    assert live["skills"]


def test_source_validator_rejects_section_drift_and_empty_source_identity(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    (repo / "skills" / "sections" / "core.md").write_text(
        "# Drifted core\n",
        encoding="utf-8",
        newline="\n",
    )

    drifted = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert drifted.returncode == 1
    assert "canonical materialized section differs" in drifted.stderr

    manifest_path = repo / "skills" / "skill-sections.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtime_source_id"] = ""
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "sections"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "runtime_source_id must be a nonempty string" in result.stderr


def test_source_validator_rejects_consecutive_name_hyphens(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha--tool"])

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "alpha--tool: invalid directory name" in result.stderr


@pytest.mark.parametrize(
    ("length", "expected_error"),
    [
        (39, "description is too short"),
        (40, None),
        (1024, None),
        (1025, "description exceeds 1024 characters"),
    ],
)
def test_source_validator_enforces_description_boundaries(
    tmp_path: pathlib.Path,
    length: int,
    expected_error: str | None,
) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    skill_md = repo / "skills" / "alpha-tool" / "SKILL.md"
    lines = skill_md.read_text(encoding="utf-8").splitlines()
    seed = "Manage alpha tool workflows safely across compatible repositories. "
    lines[2] = f"description: {(seed * (length // len(seed) + 1))[:length]}"
    skill_md.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo-root", str(repo), "--mode", "full"],
        capture_output=True,
        text=True,
        check=False,
    )

    if expected_error is None:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode == 1
        assert expected_error in result.stderr


def test_openai_example_comparison_is_not_a_per_skill_check() -> None:
    contract = json.loads(
        (
            ROOT
            / "skills"
            / "ceratops-skill-lifecycle"
            / "references"
            / "contracts"
            / "skill-nondeterministic-contract.json"
        ).read_text(encoding="utf-8")
    )
    check_ids = {check["id"] for check in contract["checks"]}
    assert "ND.skill.openai-example-comparison" not in check_ids

    action_root = (
        ROOT / "skills" / "ceratops-skill-lifecycle" / "references"
    )
    ownership_phrase = "installed OpenAI skill examples"
    assert ownership_phrase in (
        action_root / "skills-contract-review.md"
    ).read_text(encoding="utf-8")
    assert ownership_phrase not in (
        action_root / "skills-consistency-review.md"
    ).read_text(encoding="utf-8")


def test_multi_action_membership_is_owned_by_the_skill_index(
    tmp_path: pathlib.Path,
) -> None:
    skills_dir = tmp_path / "skills"
    write_multi_action_skill(
        skills_dir,
        "ceratops-repo-lifecycle",
        ["references/merge-pr.md", "references/new-command.md"],
        {
            "references/merge-pr.md": "# Merge PR Action\n\nMerge the ready pull request.\n",
            "references/new-command.md": "# New Command Action\n\nRun the new command.\n",
        },
    )
    validator = load_source_validator(skills_dir)
    manifest = {
        "skills": {
            "ceratops-repo-lifecycle": ["multi-action-skill"],
        }
    }

    assert validator["check_multi_action_skill_contract"](manifest) == []


def test_multi_action_contract_rejects_structural_drift(
    tmp_path: pathlib.Path,
) -> None:
    skills_dir = tmp_path / "skills"
    write_multi_action_skill(
        skills_dir,
        "example-lifecycle",
        [
            "references/first.md",
            "references/first.md",
            "references/missing.md",
        ],
        {
            "references/first.md": "---\n# First Action\n",
            "references/orphan.md": "# Orphan Action\n",
        },
    )
    validator = load_source_validator(skills_dir)
    manifest = {"skills": {"example-lifecycle": ["multi-action-skill"]}}

    errors = validator["check_multi_action_skill_contract"](manifest)

    assert "example-lifecycle: duplicate action reference references/first.md" in errors
    assert "example-lifecycle: missing action reference references/missing.md" in errors
    assert (
        "example-lifecycle: references/first.md still looks like a standalone skill"
        in errors
    )
    assert "example-lifecycle: unlisted action reference references/orphan.md" in errors


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
        private_path = chr(92).join(("C:", "Users", "fixture", "generated"))
        (ignored_dir / "generated.md").write_text(
            f"{private_path}\nUse $" + "unknown-skill.\n",
            encoding="utf-8",
            newline="\n",
        )
    (repo / "executable.py").write_text(
        "REFERENCE = '$unknown-skill'\n",
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
    private_path = chr(92).join(("C:", "Users", "fixture", "private-source"))
    runtime_input.write_text(
        f"Generated from {private_path}.\n",
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

    manifest_path = repo / "skills" / "skill-sections.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtime_payloads"] = {
        "alpha-tool": [
            {
                "source": "runtime-note.md",
                "target": "references/runtime-note.md",
            }
        ]
    }
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
