#!/usr/bin/env python3
"""Validate Ceratops-compatible skill source and runtime-generation inputs.

Called by CI, explicit skill-maintenance validation, and runtime installation.
The default mode is a full source-repository validation.
``--mode skill`` validates only explicitly selected skills and their required
rendering inputs for targeted installation. ``--mode sections`` checks shared
section assignments and source skill delta-only status without running
unrelated README, metadata, secret, or contract checks.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import cast


ROOT = pathlib.Path(__file__).resolve().parents[3]
SKILLS_DIR = ROOT / "skills"
README = ROOT / "README.md"
SECTION_MANIFEST = ROOT / "templates" / "skill-sections.json"
SKILL_CONTRACT_DIR = pathlib.Path("skills/ceratops-skill-lifecycle/references/contracts")
RUNTIME_MANIFEST_SCHEMA = "ceratops-runtime-skill.v3"
PROFILE_CERATOPS = "ceratops"
PROFILE_COMPATIBLE = "ceratops-compatible"
VALIDATION_PROFILES = {PROFILE_CERATOPS, PROFILE_COMPATIBLE}
BOOTSTRAP_INSTALLER = ROOT / "scripts" / "install-skills.py"
RUNTIME_INSTALLER = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "runtime" / "install-managed-skills.py"
BUNDLE_RESOLVER = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "runtime" / "resolve-lifecycle-bundle.py"
INSTALLER_TEMPLATE = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "templates" / "install-skills-template.py"
INSTALLER_SYNCHRONIZER = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "runtime" / "synchronize-installers.py"
RUNTIME_BUILDER = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "runtime" / "managed_runtime_builder.py"
RUNTIME_VALIDATOR = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "runtime" / "skills-consistency-runtime-validator.py"
FAST_CHANGE_READINESS_HELPER = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "validate-fast-change-readiness.ps1"
PROMOTION_HELPER = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "promote-skill-branches-to-release-and-install.ps1"
VALIDATOR = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "skills-consistency-source-validator.py"
WORKFLOW = ROOT / ".github" / "workflows" / "validate.yml"
SKILL_DETERMINISTIC_CONTRACT = pathlib.Path("skills/ceratops-skill-lifecycle/references/contracts/skill-deterministic-contract.json")
SKILL_NONDETERMINISTIC_CONTRACT = pathlib.Path("skills/ceratops-skill-lifecycle/references/contracts/skill-nondeterministic-contract.json")
REQUIRED_CONTRACT_FILES = [
    pathlib.Path("skills/ceratops-skill-lifecycle/references/skill-source-docs.json"),
    SKILL_DETERMINISTIC_CONTRACT,
    SKILL_NONDETERMINISTIC_CONTRACT,
]
SECTIONS_START = "<!-- CERATOPS_SHARED_SECTIONS_START -->"
SECTIONS_END = "<!-- CERATOPS_SHARED_SECTIONS_END -->"

NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
SKILL_REF_RE = re.compile(r"\$([a-z0-9]+(?:-[a-z0-9]+)+)(?![A-Za-z0-9_-])")
README_SKILL_ROW_RE = re.compile(r"^\|\s*`(?P<name>[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?)`\s*\|", re.MULTILINE)
ACTION_REFERENCES_HEADING = "### Action References"
ACTION_REFERENCE_TOKEN_RE = re.compile(r"`(?P<path>references/[^`\s]+\.md)`")
DIRECT_ACTION_REFERENCE_RE = re.compile(r"references/[a-z0-9]+(?:-[a-z0-9]+)*\.md")
ACTION_TITLE_RE = re.compile(r"# .+ Action")
ALLOWED_EXTERNAL_SKILL_REFS = {"skill-creator", "skill-name"}
INTERFACE_FIELD_RE = re.compile(
    r"^\s*(display_name|short_description|icon_small|icon_large|default_prompt):\s*(.+?)\s*$",
    re.MULTILINE,
)
CERATOPS_ICON_REL = "./assets/ceratops-logo-500.png"
CERATOPS_ICON_SOURCE = ROOT / "assets" / "ceratops-logo-500.png"
ALLOWED_SKILL_RESOURCE_DIRS = {"agents", "assets", "scripts", "references"}
SHORT_DESC_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "before",
    "by",
    "for",
    "from",
    "in",
    "into",
    "it",
    "of",
    "on",
    "or",
    "the",
    "through",
    "to",
    "up",
    "use",
    "when",
    "with",
}
SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY"),
    re.compile(r"[A-Za-z]:\\Users\\[^\\]+", re.IGNORECASE),
]
TEXT_SUFFIXES = {".md", ".py", ".ps1", ".json", ".yml", ".yaml", ".toml", ".txt"}
IGNORED_REPO_DIRS = {".git", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", "node_modules"}
IGNORED_REPO_FALLBACK_DIRS = IGNORED_REPO_DIRS | {".venv"}
GH_LIFECYCLE_ACTIONS = {
    "contracts-review.md": "python -m github_contract_engine validate consistency",
    "create-or-publish.md": "--surface all --subset create",
    "dependency-maintenance.md": "--select repo:dependency --select code:dependency",
    "health-audit.md": "--surface all --subset health",
    "ensure-pr.md": "python -m github_pr_workflow ensure-pr",
    "merge-pr.md": "python -m github_pr_workflow merge",
    "ship-change.md": "merge-pr",
}
SKILL_LIFECYCLE_ACTIONS = {
    "create.md": "templates/skill-sections.json",
    "make-repo-compatible.md": "ceratops-compatible",
    "update.md": "runtime payloads",
    "skills-contract-review.md": "skill-deterministic-contract.json",
    "skills-consistency-review.md": "--repo-root",
    "fast-change.md": "release/*",
    "change-promotion.md": "promote-skill-branches-to-release-and-install.ps1",
    "ship-to-remote.md": "ensure-pr",
}
TASK_LIFECYCLE_ACTIONS = {
    "execute-in-stages.md": "staged contingent execution",
    "fixloop-break.md": "repeated failed fix loop",
    "manual-resume.md": "same-thread task",
    "full-handoff.md": "whole task in a new thread",
    "side-task-handoff.md": "side task in a new thread",
    "closure-check.md": "required work remains",
}


def is_ignored_repo_path(path: pathlib.Path) -> bool:
    """Return true for generated paths excluded by non-Git fallback discovery."""

    return any(part in IGNORED_REPO_FALLBACK_DIRS for part in path.relative_to(ROOT).parts)


def read_json(path: pathlib.Path) -> dict[str, object]:
    """Read one JSON object for cross-file governance checks."""

    return json.loads(path.read_text(encoding="utf-8"))


def installer_version(path: pathlib.Path) -> int | None:
    """Parse only one literal positive integer ``INSTALLER_VERSION``."""

    if not path.is_file():
        return None
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return None
    versions: list[int] = []
    for node in module.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "INSTALLER_VERSION" for target in targets):
            continue
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, int) or isinstance(value.value, bool):
            return None
        versions.append(value.value)
    return versions[0] if len(versions) == 1 and versions[0] > 0 else None


def parse_frontmatter(path: pathlib.Path) -> tuple[dict[str, str], str]:
    """Parse the simple YAML frontmatter format used by source skills."""

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("missing opening YAML frontmatter marker")

    try:
        end = lines[1:].index("---") + 1
    except ValueError as exc:
        raise ValueError("missing closing YAML frontmatter marker") from exc

    data: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"invalid frontmatter line: {line!r}")
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"')

    body = "\n".join(lines[end + 1 :])
    return data, body


def load_section_manifest() -> dict[str, object]:
    """Load shared-section assignments and runtime payload declarations."""

    return json.loads(SECTION_MANIFEST.read_text(encoding="utf-8"))


def check_repo_manifest_identity(manifest: Mapping[str, object]) -> list[str]:
    """Require stable ownership and one supported validation profile."""

    errors: list[str] = []
    source_id = manifest.get("runtime_source_id")
    profile = manifest.get("validation_profile")
    if not isinstance(source_id, str) or not source_id.strip():
        errors.append("section manifest runtime_source_id must be a nonempty string")
    if profile not in VALIDATION_PROFILES:
        errors.append("section manifest validation_profile must be ceratops or ceratops-compatible")
    return errors


def check_source_installer(profile: str) -> list[str]:
    """Require one versioned Python bootstrap and compare Ceratops by version."""

    errors: list[str] = []
    source_version = installer_version(BOOTSTRAP_INSTALLER)
    if source_version is None:
        errors.append("scripts/install-skills.py must declare one positive integer INSTALLER_VERSION")
    if profile != PROFILE_CERATOPS:
        return errors
    template_version = installer_version(INSTALLER_TEMPLATE)
    if template_version is None:
        errors.append("authoritative installer template must declare one positive integer INSTALLER_VERSION")
    elif source_version is not None and source_version != template_version:
        errors.append("repo installer and authoritative template INSTALLER_VERSION values must match")
    return errors


def validation_profile(manifest: Mapping[str, object]) -> str:
    """Return the validated repository profile, or an empty sentinel."""

    value = manifest.get("validation_profile")
    return value if isinstance(value, str) and value in VALIDATION_PROFILES else ""


def parse_openai_interface(path: pathlib.Path) -> dict[str, str]:
    """Extract the flat `interface` fields validated from `openai.yaml`."""

    data: dict[str, str] = {}
    text = path.read_text(encoding="utf-8")
    for key, raw_value in INTERFACE_FIELD_RE.findall(text):
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        data[key] = value
    return data


def normalized_tokens(text: str) -> list[str]:
    """Tokenize names and descriptions for loose metadata relevance checks."""

    return [token.lower() for token in re.findall(r"[A-Za-z0-9]+", text)]


def meaningful_short_description_tokens(text: str) -> set[str]:
    """Drop common filler so short-description comparisons use real terms."""

    return {
        token
        for token in normalized_tokens(text)
        if token not in SHORT_DESC_STOPWORDS and (len(token) > 2 or token in {"gh", "pr", "ci"})
    }


def display_name_sane(skill_name: str, display_name: str, profile: str) -> bool:
    """Check that the UI display name still resembles the skill directory."""

    name_tokens = {token for token in normalized_tokens(skill_name) if token != "ceratops"}
    if not name_tokens:
        return False
    display_tokens = set(normalized_tokens(display_name))
    overlap = len(name_tokens & display_tokens)
    prefix_ok = profile != PROFILE_CERATOPS or display_name.startswith("Ceratops ")
    return prefix_ok and overlap / len(name_tokens) >= 0.5


def short_description_relevant(short_description: str, skill_description: str) -> bool:
    """Check that the UI short description overlaps the trigger description."""

    short_tokens = meaningful_short_description_tokens(short_description)
    if not short_tokens:
        return False
    description_tokens = meaningful_short_description_tokens(skill_description)
    overlap = len(short_tokens & description_tokens)
    required_overlap = min(2, len(short_tokens))
    return overlap >= required_overlap


def rendered_sections_block(skill_name: str, manifest: dict[str, object]) -> str:
    """Render shared sections to prove source assignments are buildable."""

    sections = cast(Mapping[str, str], manifest["sections"])
    assignments = cast(Mapping[str, Sequence[str]], manifest["skills"])
    section_names = assignments[skill_name]
    rendered: list[str] = []
    for section_name in section_names:
        rel_path = sections[section_name]
        raw_lines = (ROOT / rel_path).read_text(encoding="utf-8").splitlines()
        body = "\n".join(line for line in raw_lines if not re.fullmatch(r"\s*<!--\s*INTERNAL:.*?-->\s*", line)).strip("\n")
        rendered.append(f"<!-- SECTION SOURCE: {rel_path} -->")
        rendered.append(body)
    joined = "\n\n".join(rendered)
    return f"{SECTIONS_START}\n{joined}\n{SECTIONS_END}"


def check_runtime_payloads(
    manifest: dict[str, object],
    skill_names: set[str],
    selected_skill_names: set[str] | None = None,
) -> list[str]:
    """Validate applicable runtime payload paths without copying any files."""

    errors: list[str] = []
    payloads = manifest.get("runtime_payloads", {})
    if not isinstance(payloads, dict):
        errors.append("section manifest runtime_payloads must be an object")
        return errors
    for skill_name, values in payloads.items():
        if selected_skill_names is not None and skill_name != "*" and skill_name not in selected_skill_names:
            continue
        if skill_name != "*" and skill_name not in skill_names:
            errors.append(f"runtime_payloads points to unknown skill {skill_name}")
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            errors.append(f"runtime_payloads.{skill_name} must be a list of strings")
            continue
        for rel_path in values:
            if pathlib.PurePath(rel_path).is_absolute() or ".." in pathlib.PurePath(rel_path).parts:
                errors.append(f"runtime_payloads.{skill_name} contains non-portable path {rel_path}")
                continue
            if any(token in rel_path for token in "*?["):
                if not list(ROOT.glob(rel_path)):
                    errors.append(f"runtime_payloads.{skill_name} glob has no matches: {rel_path}")
            elif not (ROOT / rel_path).exists():
                errors.append(f"runtime_payloads.{skill_name} path does not exist: {rel_path}")
    return errors


def manifest_runtime_input_paths(
    manifest: dict[str, object],
    skill_dirs: Sequence[pathlib.Path],
    selected_skill_names: set[str] | None = None,
) -> list[pathlib.Path]:
    """Return source paths copied into or rendered into managed runtime skills."""

    skill_dir_by_name = {skill_dir.name: skill_dir for skill_dir in skill_dirs}
    selected = set(skill_dir_by_name) if selected_skill_names is None else selected_skill_names
    selected &= set(skill_dir_by_name)
    paths = {skill_dir_by_name[name] for name in selected}

    sections = manifest.get("sections", {})
    assignments = manifest.get("skills", {})
    if isinstance(sections, dict) and isinstance(assignments, dict):
        for skill_name in selected:
            section_names = assignments.get(skill_name, [])
            if not isinstance(section_names, list):
                continue
            for section_name in section_names:
                rel_path = sections.get(section_name)
                if not isinstance(rel_path, str):
                    continue
                pure_path = pathlib.PurePath(rel_path)
                if pure_path.is_absolute() or ".." in pure_path.parts:
                    continue
                path = ROOT / rel_path
                if path.exists():
                    paths.add(path)

    payloads = manifest.get("runtime_payloads", {})
    if isinstance(payloads, dict):
        for skill_name in ("*", *sorted(selected)):
            values = payloads.get(skill_name, [])
            if not isinstance(values, list):
                continue
            for rel_path in values:
                if not isinstance(rel_path, str):
                    continue
                pure_path = pathlib.PurePath(rel_path)
                if pure_path.is_absolute() or ".." in pure_path.parts:
                    continue
                paths.update(ROOT.glob(rel_path))
    return sorted(paths)


def readme_skill_rows(readme_text: str) -> set[str]:
    """Return skill names documented in the README skill table."""

    match = re.search(r"^## Skills\s*$\n(?P<body>.*?)(?=^##\s|\Z)", readme_text, re.MULTILINE | re.DOTALL)
    if match is None:
        return set()
    return {row.group("name") for row in README_SKILL_ROW_RE.finditer(match.group("body"))}


def validate_workflow_target(command: str, skill_names: set[str]) -> list[str]:
    """Check that manifest maintenance workflow commands point to real targets.

    The manifest is allowed to contain only the small command shapes used by
    this repo's automation. Rejecting unknown forms keeps maintenance commands
    portable and prevents hidden user-local paths from becoming policy.
    """

    errors: list[str] = []
    normalized = command.strip().replace("\\", "/")
    parts = normalized.split()
    if not parts:
        return ["section manifest maintenance workflow contains an empty command"]

    if normalized.startswith("$"):
        target = normalized[1:]
        if target not in skill_names and target not in ALLOWED_EXTERNAL_SKILL_REFS:
            errors.append(f"section manifest maintenance workflow points to unknown skill {normalized}")
        return errors

    if len(parts) >= 2 and parts[0] in {"python", "py"} and (parts[1].startswith("scripts/") or parts[1].startswith("skills/")):
        script_path = ROOT / parts[1]
        if not script_path.is_file():
            errors.append(f"section manifest maintenance workflow points to missing script {parts[1]}")
        return errors

    if len(parts) >= 4 and parts[0].lower() in {"powershell", "pwsh"} and "-file" in {part.lower() for part in parts}:
        file_index = next(index for index, part in enumerate(parts) if part.lower() == "-file")
        if file_index + 1 >= len(parts):
            errors.append("section manifest maintenance workflow has -File without a script path")
            return errors
        script_rel = pathlib.Path(parts[file_index + 1])
        if script_rel.is_absolute() or ".." in script_rel.parts:
            errors.append(f"section manifest maintenance workflow uses a non-portable script path: {parts[file_index + 1]}")
            return errors
        script_path = ROOT / script_rel
        if not script_path.is_file():
            errors.append(f"section manifest maintenance workflow points to missing script {parts[file_index + 1]}")
        return errors

    if len(parts) >= 3 and parts[0] in {"python", "py"} and parts[1] == "-m":
        module = parts[2]
        module_path = ROOT / "src" / pathlib.Path(module.replace(".", "/"))
        if not (module_path.with_suffix(".py").is_file() or (module_path / "__main__.py").is_file()):
            errors.append(f"section manifest maintenance workflow points to missing module {module}")
        return errors

    errors.append(f"section manifest maintenance workflow uses an unsupported command form: {command}")
    return errors


def check_skill_refs(path: pathlib.Path, text: str, skill_names: set[str]) -> list[str]:
    """Reject hyphenated `$skill-name` references that do not resolve."""

    errors: list[str] = []
    for ref in sorted(set(SKILL_REF_RE.findall(text))):
        if ref in ALLOWED_EXTERNAL_SKILL_REFS:
            continue
        if ref not in skill_names:
            errors.append(f"{path.relative_to(ROOT)}: unknown skill reference ${ref}")
    return errors


def git_repo_source_files() -> list[pathlib.Path] | None:
    """Return tracked and committable files when ``ROOT`` is a Git worktree."""

    try:
        top_level = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            check=False,
        )
    except OSError:
        return None
    if top_level.returncode != 0:
        return None
    try:
        if pathlib.Path(top_level.stdout.strip()).resolve() != ROOT.resolve():
            return None
        listed = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            check=False,
        )
    except OSError:
        return None
    if listed.returncode != 0:
        return None
    return sorted(
        path
        for rel_path in listed.stdout.split("\0")
        if rel_path and (path := ROOT / rel_path).is_file()
    )


def iter_repo_source_files() -> list[pathlib.Path]:
    """Return source candidates, honoring Git ignores when Git is available."""

    git_files = git_repo_source_files()
    if git_files is not None:
        return git_files
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file() and not is_ignored_repo_path(path)
    )


def check_retired_baseline_absent() -> list[str]:
    """Ensure the retired best-practice baseline artifact did not come back."""

    errors: list[str] = []
    for path in iter_repo_source_files():
        if path.name != "best-practice-baseline.md":
            continue
        rel = path.relative_to(ROOT)
        errors.append(f"{rel}: retired best-practice baseline; use {SKILL_CONTRACT_DIR}")
    return errors


def check_contract_source_lines() -> list[str]:
    """Validate deterministic contract source reference metadata."""

    errors: list[str] = []
    for rel_path in REQUIRED_CONTRACT_FILES:
        if rel_path.suffix != ".json":
            continue
        path = ROOT / rel_path
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{rel_path}: invalid JSON: {exc}")
            continue
        checks = data.get("checks", [])
        if not isinstance(checks, list):
            continue
        for index, check in enumerate(checks):
            check_id = check.get("id", f"checks[{index}]") if isinstance(check, dict) else f"checks[{index}]"
            source_lines = check.get("source_lines") if isinstance(check, dict) else None
            if source_lines is None:
                continue
            if not isinstance(source_lines, list) or not all(isinstance(item, str) for item in source_lines):
                errors.append(f"{rel_path}: {check_id}: source_lines must be a list of strings")
                continue
            seen: set[str] = set()
            duplicates: list[str] = []
            for source_line in source_lines:
                if source_line in seen and source_line not in duplicates:
                    duplicates.append(source_line)
                seen.add(source_line)
            if duplicates:
                errors.append(f"{rel_path}: {check_id}: duplicate source_lines: {', '.join(duplicates)}")
    return errors


def iter_repo_text_files() -> list[pathlib.Path]:
    """Return repo text files that can carry skill references or commands."""

    return [
        path
        for path in iter_repo_source_files()
        if path.suffix.lower() in TEXT_SUFFIXES
    ]


def check_repo_skill_refs(skill_names: set[str]) -> list[str]:
    """Reject stale skill references anywhere in portable repo text."""

    errors: list[str] = []
    for path in iter_repo_text_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for ref in sorted(set(SKILL_REF_RE.findall(text))):
            if ref in ALLOWED_EXTERNAL_SKILL_REFS:
                continue
            if ref not in skill_names:
                errors.append(f"{path.relative_to(ROOT)}: unknown skill reference ${ref}")
    return errors


def contract_check_ids(path: pathlib.Path) -> set[str]:
    """Return deterministic check IDs from one JSON contract."""

    data = read_json(ROOT / path)
    checks = data.get("checks", [])
    if not isinstance(checks, list):
        return set()
    return {str(check.get("id")) for check in checks if isinstance(check, dict) and check.get("id")}


def contract_remediation_ids(path: pathlib.Path) -> set[str]:
    """Return check IDs classified by a contract remediation policy."""

    data = read_json(ROOT / path)
    policy = data.get("remediation_policy", {})
    if not isinstance(policy, dict):
        return set()
    classified: set[str] = set()
    for key in ("auto_apply_check_ids", "ai_agent_check_ids"):
        values = policy.get(key, [])
        if isinstance(values, list):
            classified.update(str(value) for value in values if isinstance(value, str) and value)
    return classified


def check_skill_contract_remediation_policy() -> list[str]:
    """Ensure the skill deterministic contract classifies each deterministic check."""

    errors: list[str] = []
    try:
        check_ids = contract_check_ids(SKILL_DETERMINISTIC_CONTRACT)
        classified_ids = contract_remediation_ids(SKILL_DETERMINISTIC_CONTRACT)
    except json.JSONDecodeError as exc:
        return [f"{SKILL_DETERMINISTIC_CONTRACT}: invalid JSON: {exc}"]
    for check_id in sorted(check_ids - classified_ids):
        errors.append(f"{SKILL_DETERMINISTIC_CONTRACT}: deterministic check {check_id} is not classified in remediation_policy")
    for check_id in sorted(classified_ids - check_ids):
        errors.append(f"{SKILL_DETERMINISTIC_CONTRACT}: remediation_policy references unknown check {check_id}")
    return errors


def check_skill_nondeterministic_contract() -> list[str]:
    """Validate the canonical AI-agent skill-review contract."""

    errors: list[str] = []
    try:
        deterministic = read_json(ROOT / SKILL_DETERMINISTIC_CONTRACT)
        contract = read_json(ROOT / SKILL_NONDETERMINISTIC_CONTRACT)
    except json.JSONDecodeError as exc:
        return [f"skill contract JSON is invalid: {exc}"]
    if deterministic.get("non_deterministic_review_file") != SKILL_NONDETERMINISTIC_CONTRACT.name:
        errors.append(
            f"{SKILL_DETERMINISTIC_CONTRACT}: non_deterministic_review_file must be "
            f"{SKILL_NONDETERMINISTIC_CONTRACT.name}"
        )
    if contract.get("kind") != "nondeterministic_review_contract":
        errors.append(
            f"{SKILL_NONDETERMINISTIC_CONTRACT}: kind must be "
            "nondeterministic_review_contract"
        )
    if contract.get("surface") != "skill":
        errors.append(f"{SKILL_NONDETERMINISTIC_CONTRACT}: surface must be skill")
    checks = contract.get("checks", [])
    if not isinstance(checks, list) or not checks:
        return [*errors, f"{SKILL_NONDETERMINISTIC_CONTRACT}: checks must be non-empty"]
    ids: list[str] = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            errors.append(
                f"{SKILL_NONDETERMINISTIC_CONTRACT}: checks[{index}] must be an object"
            )
            continue
        check_id = check.get("id")
        if not isinstance(check_id, str) or not check_id.startswith("ND.skill."):
            errors.append(
                f"{SKILL_NONDETERMINISTIC_CONTRACT}: checks[{index}] has invalid ID"
            )
            continue
        ids.append(check_id)
        for field in ("applies_when", "review_required"):
            if not isinstance(check.get(field), str) or not check[field].strip():
                errors.append(
                    f"{SKILL_NONDETERMINISTIC_CONTRACT}: {check_id} requires {field}"
                )
        evidence_keys = check.get("evidence_keys")
        if (
            not isinstance(evidence_keys, list)
            or not evidence_keys
            or not all(isinstance(key, str) and key for key in evidence_keys)
        ):
            errors.append(
                f"{SKILL_NONDETERMINISTIC_CONTRACT}: {check_id} requires evidence_keys"
            )
    errors.extend(
        f"{SKILL_NONDETERMINISTIC_CONTRACT}: duplicate check ID {check_id}"
        for check_id in sorted({item for item in ids if ids.count(item) > 1})
    )
    return errors


def has_action_title(path: pathlib.Path) -> bool:
    """Return whether a Markdown reference uses the reserved action title."""

    lines = path.read_text(encoding="utf-8").splitlines()
    return bool(lines and ACTION_TITLE_RE.fullmatch(lines[0]) is not None)


def check_multi_action_skill_contract(
    manifest: dict[str, object],
    selected_skill_names: set[str] | None = None,
) -> list[str]:
    """Validate every manifest-declared multi-action index and action file."""

    errors: list[str] = []
    assignments = manifest.get("skills", {})
    if not isinstance(assignments, dict):
        return errors
    multi_action_skill_names = sorted(
        skill_name
        for skill_name, section_names in assignments.items()
        if isinstance(skill_name, str)
        and isinstance(section_names, list)
        and "multi-action-skill" in section_names
        and (selected_skill_names is None or skill_name in selected_skill_names)
    )
    for skill_name in multi_action_skill_names:
        skill_dir = SKILLS_DIR / skill_name
        skill_path = skill_dir / "SKILL.md"
        if not skill_path.is_file():
            errors.append(f"{skill_name}: missing multi-action SKILL.md")
            continue
        skill_lines = skill_path.read_text(encoding="utf-8").splitlines()
        heading_indexes = [
            index for index, line in enumerate(skill_lines) if line == ACTION_REFERENCES_HEADING
        ]
        if len(heading_indexes) != 1:
            errors.append(
                f"{skill_name}: requires exactly one {ACTION_REFERENCES_HEADING} section"
            )
            continue
        section_start = heading_indexes[0] + 1
        section_end = next(
            (
                index
                for index in range(section_start, len(skill_lines))
                if re.match(r"^#{1,3}\s", skill_lines[index])
            ),
            len(skill_lines),
        )
        action_references = ACTION_REFERENCE_TOKEN_RE.findall(
            "\n".join(skill_lines[section_start:section_end])
        )
        duplicates = sorted(
            {path for path in action_references if action_references.count(path) > 1}
        )
        for action_reference in duplicates:
            errors.append(f"{skill_name}: duplicate action reference {action_reference}")
        if len(set(action_references)) < 2:
            errors.append(f"{skill_name}: multi-action index requires at least two actions")

        valid_references: set[str] = set()
        for action_reference in action_references:
            if DIRECT_ACTION_REFERENCE_RE.fullmatch(action_reference) is None:
                errors.append(
                    f"{skill_name}: action reference must be one direct references/*.md path: "
                    f"{action_reference}"
                )
                continue
            valid_references.add(action_reference)
            action_path = skill_dir / pathlib.PurePosixPath(action_reference)
            if not action_path.is_file():
                errors.append(f"{skill_name}: missing action reference {action_reference}")
                continue
            if not has_action_title(action_path):
                errors.append(
                    f"{skill_name}: {action_reference} must be titled # <Action Name> Action"
                )

        action_files: set[str] = set()
        references_dir = skill_dir / "references"
        if references_dir.is_dir():
            for action_path in references_dir.glob("*.md"):
                if has_action_title(action_path):
                    action_files.add(f"references/{action_path.name}")
        for action_reference in sorted(action_files - valid_references):
            errors.append(f"{skill_name}: unlisted action reference {action_reference}")
    return errors


def check_skill_scope_validator() -> list[str]:
    """Check objective multi-action skill rules without judging prose quality."""

    errors: list[str] = []
    multi_action_specs = {
        "ceratops-gh-repo-lifecycle": GH_LIFECYCLE_ACTIONS,
        "ceratops-skill-lifecycle": SKILL_LIFECYCLE_ACTIONS,
        "ceratops-task-lifecycle": TASK_LIFECYCLE_ACTIONS,
    }
    for skill_name, expected_actions in multi_action_specs.items():
        skill_dir = SKILLS_DIR / skill_name
        multi_action_path = skill_dir / "SKILL.md"
        if not multi_action_path.is_file():
            errors.append(f"{skill_name}: missing multi-action SKILL.md")
            continue
        multi_action_text = multi_action_path.read_text(encoding="utf-8")
        actual_actions = {
            path.name
            for path in (skill_dir / "references").glob("*.md")
            if has_action_title(path)
        }
        unexpected_actions = sorted(actual_actions - set(expected_actions))
        for action_file in unexpected_actions:
            errors.append(f"{skill_name}: unexpected action reference references/{action_file}")
        for action_file, snippet in expected_actions.items():
            action_rel = f"references/{action_file}"
            action_path = skill_dir / action_rel
            if action_rel not in multi_action_text:
                errors.append(f"{skill_name}: multi-action skill does not list {action_rel}")
            if not action_path.is_file():
                errors.append(f"{skill_name}: missing action reference {action_rel}")
                continue
            action_text = action_path.read_text(encoding="utf-8")
            if action_text.startswith("---"):
                errors.append(f"{skill_name}: {action_rel} still looks like a standalone skill")
            if snippet not in action_text:
                errors.append(f"{skill_name}: {action_rel} missing expected scope command {snippet}")
    merge_text = (SKILLS_DIR / "ceratops-gh-repo-lifecycle" / "references" / "merge-pr.md").read_text(encoding="utf-8")
    if "python -m github_contract_engine validate repo" in merge_text:
        errors.append("ceratops-gh-repo-lifecycle: merge-pr action must not run repo/artifact contract validation")
    return errors


def check_validation_command_surface() -> list[str]:
    """Keep source-validator modes, lifecycle helper paths, docs, and CI aligned."""

    errors: list[str] = []
    validator_text = VALIDATOR.read_text(encoding="utf-8") if VALIDATOR.is_file() else ""
    bootstrap_installer_text = BOOTSTRAP_INSTALLER.read_text(encoding="utf-8") if BOOTSTRAP_INSTALLER.is_file() else ""
    runtime_installer_text = RUNTIME_INSTALLER.read_text(encoding="utf-8") if RUNTIME_INSTALLER.is_file() else ""
    builder_text = RUNTIME_BUILDER.read_text(encoding="utf-8") if RUNTIME_BUILDER.is_file() else ""
    bundle_resolver_text = BUNDLE_RESOLVER.read_text(encoding="utf-8") if BUNDLE_RESOLVER.is_file() else ""
    installer_template_text = INSTALLER_TEMPLATE.read_text(encoding="utf-8") if INSTALLER_TEMPLATE.is_file() else ""
    synchronizer_text = INSTALLER_SYNCHRONIZER.read_text(encoding="utf-8") if INSTALLER_SYNCHRONIZER.is_file() else ""
    runtime_validator_text = RUNTIME_VALIDATOR.read_text(encoding="utf-8") if RUNTIME_VALIDATOR.is_file() else ""
    fast_change_readiness_text = FAST_CHANGE_READINESS_HELPER.read_text(encoding="utf-8") if FAST_CHANGE_READINESS_HELPER.is_file() else ""
    promotion_helper_text = PROMOTION_HELPER.read_text(encoding="utf-8") if PROMOTION_HELPER.is_file() else ""
    readme_text = README.read_text(encoding="utf-8") if README.is_file() else ""
    workflow_text = WORKFLOW.read_text(encoding="utf-8") if WORKFLOW.is_file() else ""

    for mode in ("skill", "sections", "full"):
        if f'"{mode}"' not in validator_text:
            errors.append(f"validator does not declare --mode {mode}")
    if "-Validate" in bootstrap_installer_text or "-Validate" in runtime_installer_text:
        errors.append("installers must not expose validation flags")
    if "SkipInstall" in bootstrap_installer_text or "SkipInstall" in runtime_installer_text:
        errors.append("installers must not expose validation-only install skipping")
    for name, text in (("repo installer", bootstrap_installer_text), ("authoritative installer template", installer_template_text)):
        if "INSTALLER_VERSION" not in text or "resolve-lifecycle-bundle.py" not in text or "install-managed-skills.py" not in text:
            errors.append(f"{name} must declare its version and call the Python lifecycle resolver and installer")
    if "skills-consistency-source-validator.py" not in runtime_installer_text or '"--mode"' not in runtime_installer_text:
        errors.append("runtime installer must call the source validator")
    if '"full"' not in runtime_installer_text or '"skill"' not in runtime_installer_text:
        errors.append("runtime installer must select full or targeted source validation from install scope")
    if "ValidateSet" in promotion_helper_text or "$Validate" in promotion_helper_text:
        errors.append("release promotion must not expose a validation selector")
    if "scripts\\install-skills.py" not in promotion_helper_text or '"python"' not in promotion_helper_text:
        errors.append("release promotion must install through the target repository Python installer")
    if (
        '"merge", "--ff-only"' not in promotion_helper_text
        or '"merge", "--no-edit"' in promotion_helper_text
    ):
        errors.append("release promotion must fast-forward approved branches and must not create merge commits")
    if "scripts\\install-skills.py" not in fast_change_readiness_text:
        errors.append("fast-change readiness must expose the target repository Python installer")
    if RUNTIME_MANIFEST_SCHEMA not in builder_text:
        errors.append("runtime builder must emit the lifecycle bundle capability schema")
    for field in ("source_repository_root", "installer_version"):
        if field not in builder_text or field not in runtime_validator_text:
            errors.append(f"runtime building and validation must both own manifest field {field}")
    if (
        "compare_managed_tree" not in runtime_validator_text
        or '"--skill"' not in runtime_validator_text
        or '"--inventory"' not in runtime_validator_text
        or '"--mode"' in runtime_validator_text
    ):
        errors.append("runtime validator must compare managed trees through one command")
    if RUNTIME_MANIFEST_SCHEMA not in bundle_resolver_text or "installed_bundle_supported" not in bundle_resolver_text:
        errors.append("lifecycle bundle resolver must enforce installed runtime capability before checkout fallback")
    if "INSTALLER_VERSION" not in synchronizer_text or "shutil.copy2" not in synchronizer_text:
        errors.append("installer synchronizer must compare versions and copy the authoritative template")
    for snippet in ("--mode full", "--mode sections", "--mode skill"):
        if snippet not in readme_text:
            errors.append(f"README is missing validation command snippet {snippet}")
    if "scripts/install-skills.py" not in workflow_text:
        errors.append("CI workflow must render managed skills through the Python repo installer")

    return errors


def check_validator_output_budget() -> list[str]:
    """Keep success output small enough for routine automation use."""

    errors: list[str] = []
    text = VALIDATOR.read_text(encoding="utf-8") if VALIDATOR.is_file() else ""
    success_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("print(") and '"ok:' in line]
    if len(success_lines) != 3:
        errors.append("validator should have exactly one compact ok print per mode")
    for line in success_lines:
        if len(line) > 80:
            errors.append(f"validator success output is too long: {line}")
    return errors


def check_source_governance_consistency(
    manifest: dict[str, object],
    skill_dirs: list[pathlib.Path],
    readme_rows: set[str],
    skill_names: set[str],
    profile: str,
) -> list[str]:
    """Run source-only governance checks included by full validation."""

    errors: list[str] = []
    errors.extend(check_repo_skill_refs(skill_names))
    errors.extend(check_multi_action_skill_contract(manifest))
    if profile == PROFILE_CERATOPS:
        errors.extend(check_validation_command_surface())
        errors.extend(check_skill_contract_remediation_policy())
        errors.extend(check_skill_nondeterministic_contract())
        errors.extend(check_skill_scope_validator())
        errors.extend(check_validator_output_budget())

    assignments = manifest.get("skills", {})
    payloads = manifest.get("runtime_payloads", {})
    if isinstance(assignments, dict):
        for skill_name in skill_names:
            if skill_name not in assignments:
                errors.append(f"{skill_name}: missing section assignment in manifest")
    if isinstance(payloads, dict):
        for skill_name in payloads:
            if skill_name != "*" and skill_name not in skill_names:
                errors.append(f"runtime_payloads points to unknown skill {skill_name}")
    for row_name in readme_rows:
        if row_name not in skill_names:
            errors.append(f"{row_name}: stale README skill table row")
    return errors


def check_section_sources(manifest: dict[str, object], skill_dirs: list[pathlib.Path]) -> list[str]:
    """Run only shared-section checks needed after template or manifest edits."""

    errors: list[str] = []
    sections = manifest.get("sections", {})
    assignments = manifest.get("skills", {})
    skill_names = {skill_dir.name for skill_dir in skill_dirs}
    if not isinstance(sections, dict):
        errors.append("section manifest sections must be an object")
        return errors
    if not isinstance(assignments, dict):
        errors.append("section manifest skills must be an object")
        return errors
    if "core" not in sections:
        errors.append("section manifest must define core")
    for section_name, rel_path in sections.items():
        if not isinstance(rel_path, str):
            errors.append(f"section manifest section {section_name} must map to a path string")
            continue
        if not (ROOT / rel_path).is_file():
            errors.append(f"missing section file for {section_name}: {rel_path}")
    for skill_name, section_names in assignments.items():
        if skill_name not in skill_names:
            errors.append(f"{skill_name}: section assignment points to a missing skill directory")
            continue
        if not isinstance(section_names, list) or not all(isinstance(item, str) for item in section_names):
            errors.append(f"{skill_name}: section assignment must be a list of section names")
            continue
        if "core" not in section_names:
            errors.append(f"{skill_name}: section assignment must include core")
        for section_name in section_names:
            if section_name not in sections:
                errors.append(f"{skill_name}: unknown section assignment {section_name}")
    for skill_dir in skill_dirs:
        skill_md = skill_dir / "SKILL.md"
        if skill_dir.name not in assignments:
            errors.append(f"{skill_dir.name}: missing section assignment in manifest")
            continue
        if not skill_md.is_file():
            errors.append(f"{skill_dir.name}: missing SKILL.md")
            continue
        text = skill_md.read_text(encoding="utf-8")
        if SECTIONS_START in text or SECTIONS_END in text:
            errors.append(f"{skill_dir.name}: source SKILL.md must be delta-only; shared sections are generated at install time")
            continue
        try:
            rendered_sections_block(skill_dir.name, manifest)
        except Exception as exc:
            errors.append(f"{skill_dir.name}: could not render runtime shared sections: {exc}")
    return errors


def check_selected_skills(
    manifest: dict[str, object],
    skill_dirs: list[pathlib.Path],
    selected_skill_names: set[str],
    profile: str,
) -> list[str]:
    """Validate selected skills and only the source inputs needed to render them."""

    errors: list[str] = []
    skill_names = {skill_dir.name for skill_dir in skill_dirs}
    skill_dir_by_name = {skill_dir.name: skill_dir for skill_dir in skill_dirs}
    sections = manifest.get("sections", {})
    assignments = manifest.get("skills", {})
    if not isinstance(sections, dict):
        return ["section manifest sections must be an object"]
    if not isinstance(assignments, dict):
        return ["section manifest skills must be an object"]

    unknown = sorted(selected_skill_names - skill_names)
    for skill_name in unknown:
        errors.append(f"{skill_name}: selected skill does not exist")
    readme_text = README.read_text(encoding="utf-8") if README.is_file() else ""
    readme_rows = readme_skill_rows(readme_text)
    for skill_name in sorted(selected_skill_names & skill_names):
        section_names = assignments.get(skill_name)
        if not isinstance(section_names, list) or not all(isinstance(item, str) for item in section_names):
            errors.append(f"{skill_name}: section assignment must be a list of section names")
            continue
        if "core" not in section_names:
            errors.append(f"{skill_name}: section assignment must include core")
        for section_name in section_names:
            section_path = sections.get(section_name)
            if not isinstance(section_path, str) or not (ROOT / section_path).is_file():
                errors.append(f"{skill_name}: missing section file for {section_name}")
        errors.extend(check_skill(skill_dir_by_name[skill_name], readme_rows, manifest, skill_names, profile))

    errors.extend(check_runtime_payloads(manifest, skill_names, selected_skill_names))
    errors.extend(check_multi_action_skill_contract(manifest, selected_skill_names))
    runtime_inputs = manifest_runtime_input_paths(
        manifest,
        skill_dirs,
        selected_skill_names,
    )
    errors.extend(check_runtime_input_safety(runtime_inputs))
    return errors


def check_resource_layout(skill_dir: pathlib.Path, profile: str) -> list[str]:
    """Validate the skill package layout that should remain portable across agents."""

    errors: list[str] = []
    allowed_dirs = ALLOWED_SKILL_RESOURCE_DIRS if profile == PROFILE_CERATOPS else ALLOWED_SKILL_RESOURCE_DIRS | {"tests"}
    for child in skill_dir.iterdir():
        if child.is_file() and child.name != "SKILL.md":
            errors.append(f"{skill_dir.name}: unsupported top-level file {child.name}")
        if child.is_dir() and child.name not in allowed_dirs:
            errors.append(f"{skill_dir.name}: unsupported top-level directory {child.name}")

    references_dir = skill_dir / "references"
    if references_dir.is_dir():
        allowed_parents = {
            references_dir,
            references_dir / "contracts",
            references_dir / "schemas",
        }
        for path in references_dir.rglob("*"):
            if path.is_file() and path.parent not in allowed_parents:
                rel_path = path.relative_to(skill_dir)
                errors.append(
                    f"{skill_dir.name}: unsupported nested references file: {rel_path}"
                )
    return errors


def check_skill(
    skill_dir: pathlib.Path,
    readme_rows: set[str],
    manifest: dict[str, object],
    skill_names: set[str],
    profile: str,
) -> list[str]:
    """Validate one source skill, metadata file, icon, README row, and refs."""

    errors: list[str] = []
    name = skill_dir.name
    skill_md = skill_dir / "SKILL.md"
    openai_yaml = skill_dir / "agents" / "openai.yaml"

    if not NAME_RE.fullmatch(name):
        errors.append(f"{name}: invalid directory name")
    if not skill_md.is_file():
        errors.append(f"{name}: missing SKILL.md")
        return errors

    try:
        frontmatter, body = parse_frontmatter(skill_md)
    except ValueError as exc:
        errors.append(f"{name}: {exc}")
        return errors

    if set(frontmatter) != {"name", "description"}:
        errors.append(f"{name}: frontmatter must contain only name and description")
    if frontmatter.get("name") != name:
        errors.append(f"{name}: frontmatter name does not match directory")
    if len(frontmatter.get("description", "")) < 40:
        errors.append(f"{name}: description is too short")
    if "TODO" in skill_md.read_text(encoding="utf-8"):
        errors.append(f"{name}: contains TODO placeholder")
    if "publish-github-registry" in skill_md.read_text(encoding="utf-8"):
        errors.append(f"{name}: contains stale publish-github-registry reference")
    if not body.strip():
        errors.append(f"{name}: missing body")
    if name not in readme_rows:
        errors.append(f"{name}: missing README skill table row")
    core_text = skill_md.read_text(encoding="utf-8")
    h2_headings = re.findall(r"^## (.+)$", core_text, flags=re.MULTILINE)
    if not h2_headings:
        errors.append(f"{name}: must contain Markdown H2 sections")
    if profile == PROFILE_CERATOPS:
        if "### Boundaries" not in core_text:
            errors.append(f"{name}: missing Boundaries section")
        if "### Output Contract" not in core_text:
            errors.append(f"{name}: missing Output Contract section")
    if SECTIONS_START in core_text or SECTIONS_END in core_text:
        errors.append(f"{name}: source SKILL.md must be delta-only; shared sections are generated at install time")
    else:
        try:
            rendered_sections_block(name, manifest)
        except Exception as exc:
            errors.append(f"{name}: could not render runtime shared sections: {exc}")
    errors.extend(check_resource_layout(skill_dir, profile))

    if not openai_yaml.is_file():
        errors.append(f"{name}: missing agents/openai.yaml")
    else:
        yaml_text = openai_yaml.read_text(encoding="utf-8")
        required_fields = ["display_name:", "short_description:", "default_prompt:"]
        if profile == PROFILE_CERATOPS:
            required_fields.extend(("icon_small:", "icon_large:"))
        for required in required_fields:
            if required not in yaml_text:
                errors.append(f"{name}: openai.yaml missing {required}")
        if f"${name}" not in yaml_text:
            errors.append(f"{name}: default_prompt should mention ${name}")
        interface = parse_openai_interface(openai_yaml)
        display_name = interface.get("display_name", "")
        short_description = interface.get("short_description", "")
        icon_small = interface.get("icon_small", "")
        icon_large = interface.get("icon_large", "")
        if display_name and not display_name_sane(name, display_name, profile):
            errors.append(f"{name}: display_name no longer matches the skill name closely enough")
        if short_description and not short_description_relevant(short_description, frontmatter.get("description", "")):
            errors.append(f"{name}: short_description no longer matches the skill description closely enough")
        icon_fields = (("icon_small", icon_small), ("icon_large", icon_large)) if profile == PROFILE_CERATOPS else ()
        for field_name, icon_value in icon_fields:
            normalized_icon = icon_value.replace("\\", "/")
            portable_icon = pathlib.PurePosixPath(normalized_icon)
            if not icon_value:
                errors.append(f"{name}: {field_name} must name a relative icon file")
                continue
            if portable_icon.is_absolute() or ".." in portable_icon.parts:
                errors.append(f"{name}: {field_name} must use a portable relative path")
                continue
            if profile == PROFILE_CERATOPS and icon_value != CERATOPS_ICON_REL:
                errors.append(f"{name}: {field_name} should use shared Ceratops icon {CERATOPS_ICON_REL}")
            icon_path = skill_dir / portable_icon
            if not icon_path.is_file():
                errors.append(f"{name}: {field_name} points to missing file {icon_value}")
            elif profile == PROFILE_CERATOPS and CERATOPS_ICON_SOURCE.is_file() and icon_path.read_bytes() != CERATOPS_ICON_SOURCE.read_bytes():
                errors.append(f"{name}: {field_name} does not match repo icon {CERATOPS_ICON_SOURCE.relative_to(ROOT)}")
        errors.extend(check_skill_refs(openai_yaml, yaml_text, skill_names))

    errors.extend(check_skill_refs(skill_md, core_text, skill_names))

    return errors


def check_runtime_input_safety(search_paths: Sequence[pathlib.Path]) -> list[str]:
    """Scan only files that can enter a managed runtime skill."""

    errors: list[str] = []
    files: set[pathlib.Path] = set()
    for search_path in search_paths:
        candidates = (search_path,) if search_path.is_file() else search_path.rglob("*")
        for path in candidates:
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT)
            if any(part in IGNORED_REPO_DIRS for part in rel.parts):
                continue
            files.add(path)
    for path in sorted(files):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = path.relative_to(ROOT)
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"{rel}: high-confidence secret or private path pattern")
    return errors


def main() -> int:
    """Run selected-skill, section, or full source validation."""

    global ROOT, SKILLS_DIR, README, SECTION_MANIFEST, CERATOPS_ICON_SOURCE
    global BOOTSTRAP_INSTALLER, RUNTIME_INSTALLER, BUNDLE_RESOLVER, INSTALLER_TEMPLATE
    global INSTALLER_SYNCHRONIZER, RUNTIME_BUILDER, RUNTIME_VALIDATOR, FAST_CHANGE_READINESS_HELPER
    global PROMOTION_HELPER, VALIDATOR, WORKFLOW

    parser = argparse.ArgumentParser(description="Validate Ceratops-compatible skill source and runtime-generation inputs.")
    parser.add_argument("--repo-root", type=pathlib.Path, help="Source skills repository root.")
    parser.add_argument("--mode", choices=["skill", "sections", "full"], default="full", help="Use skill for selected-skill installation, sections for shared-source changes, or full for source-repository validation.")
    parser.add_argument("--skill", action="append", help="Source skill to validate in skill mode; repeat for multiple skills.")
    args = parser.parse_args()
    selected_skill_names = set(args.skill or [])
    if args.mode == "skill" and not selected_skill_names:
        parser.error("--mode skill requires at least one --skill")
    if args.mode != "skill" and selected_skill_names:
        parser.error("--skill is valid only with --mode skill")

    if args.repo_root is not None:
        ROOT = args.repo_root.resolve()
        SKILLS_DIR = ROOT / "skills"
        README = ROOT / "README.md"
        SECTION_MANIFEST = ROOT / "templates" / "skill-sections.json"
        CERATOPS_ICON_SOURCE = ROOT / "assets" / "ceratops-logo-500.png"
        BOOTSTRAP_INSTALLER = ROOT / "scripts" / "install-skills.py"
        RUNTIME_INSTALLER = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "runtime" / "install-managed-skills.py"
        BUNDLE_RESOLVER = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "runtime" / "resolve-lifecycle-bundle.py"
        INSTALLER_TEMPLATE = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "templates" / "install-skills-template.py"
        INSTALLER_SYNCHRONIZER = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "runtime" / "synchronize-installers.py"
        RUNTIME_BUILDER = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "runtime" / "managed_runtime_builder.py"
        RUNTIME_VALIDATOR = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "runtime" / "skills-consistency-runtime-validator.py"
        FAST_CHANGE_READINESS_HELPER = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "validate-fast-change-readiness.ps1"
        PROMOTION_HELPER = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "promote-skill-branches-to-release-and-install.ps1"
        VALIDATOR = ROOT / "skills" / "ceratops-skill-lifecycle" / "scripts" / "skills-consistency-source-validator.py"
        WORKFLOW = ROOT / ".github" / "workflows" / "validate.yml"

    errors: list[str] = []
    if not SKILLS_DIR.is_dir():
        errors.append("missing skills/ directory")
    if not SECTION_MANIFEST.is_file():
        errors.append("missing templates/skill-sections.json")

    manifest = load_section_manifest() if SECTION_MANIFEST.is_file() else {"sections": {}, "skills": {}}
    errors.extend(check_repo_manifest_identity(manifest))
    profile = validation_profile(manifest)
    skill_dirs = sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()) if SKILLS_DIR.is_dir() else []
    if args.mode == "skill":
        errors.extend(check_selected_skills(manifest, skill_dirs, selected_skill_names, profile))
        if errors:
            print(f"errors: {len(errors)}", file=sys.stderr)
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        print(f"ok: skill {len(selected_skill_names)}")
        return 0

    errors.extend(check_source_installer(profile))
    if args.mode == "sections":
        errors.extend(check_section_sources(manifest, skill_dirs))
        errors.extend(check_multi_action_skill_contract(manifest))
        if errors:
            print(f"errors: {len(errors)}", file=sys.stderr)
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        print(f"ok: sections {len(skill_dirs)}")
        return 0

    if not README.is_file():
        errors.append("missing README.md")
    if profile == PROFILE_CERATOPS:
        if not (ROOT / SKILL_CONTRACT_DIR).is_dir():
            errors.append(f"missing skill contract directory: {SKILL_CONTRACT_DIR}")
        for rel_path in REQUIRED_CONTRACT_FILES:
            if not (ROOT / rel_path).is_file():
                errors.append(f"missing required contract file: {rel_path}")
        if not CERATOPS_ICON_SOURCE.is_file():
            errors.append(f"missing shared Ceratops icon source: {CERATOPS_ICON_SOURCE.relative_to(ROOT)}")

    sections_obj = manifest.get("sections", {})
    workflow_hints_obj = manifest.get("maintenance_workflows", {})
    assignments_obj = manifest.get("skills", {})
    sections: dict[str, object] = sections_obj if isinstance(sections_obj, dict) else {}
    workflow_hints: dict[str, object] = workflow_hints_obj if isinstance(workflow_hints_obj, dict) else {}
    assignments: dict[str, object] = assignments_obj if isinstance(assignments_obj, dict) else {}
    if not isinstance(sections_obj, dict):
        errors.append("section manifest sections must be an object")
    if not isinstance(assignments_obj, dict):
        errors.append("section manifest skills must be an object")
    if "core" not in sections:
        errors.append("section manifest must define core")
    if not isinstance(workflow_hints_obj, dict):
        errors.append("section manifest maintenance_workflows must be an object")
    else:
        for workflow_name, commands in workflow_hints.items():
            if not isinstance(commands, list) or not all(isinstance(item, str) for item in commands):
                errors.append(f"section manifest maintenance_workflows.{workflow_name} must be a list of strings")
    if profile == PROFILE_CERATOPS:
        required_workflows = {
            "shared_source_changes",
            "skill_local_or_metadata_changes",
            "helper_runtime_changes",
            "new_skill_local_availability",
        }
        for workflow_name in required_workflows:
            if workflow_name not in workflow_hints:
                errors.append(f"section manifest maintenance_workflows.{workflow_name} must be a list of strings")
    for section_name, section_rel_path in sections.items():
        if not isinstance(section_rel_path, str) or not (ROOT / section_rel_path).is_file():
            errors.append(f"missing section file for {section_name}: {section_rel_path}")
    for skill_name, section_names in assignments.items():
        if not isinstance(section_names, list) or not all(isinstance(item, str) for item in section_names):
            errors.append(f"{skill_name}: section assignment must be a list of strings")
            continue
        if "core" not in section_names:
            errors.append(f"{skill_name}: section assignment must include core")
        for section_name in section_names:
            if section_name not in sections:
                errors.append(f"{skill_name}: unknown section assignment {section_name}")

    readme_text = README.read_text(encoding="utf-8") if README.is_file() else ""
    readme_rows = readme_skill_rows(readme_text)
    if not skill_dirs:
        errors.append("no skill directories found")

    skill_names = {skill_dir.name for skill_dir in skill_dirs}
    if isinstance(workflow_hints, dict):
        for workflow_name, commands in workflow_hints.items():
            if isinstance(commands, list) and all(isinstance(item, str) for item in commands):
                for command in commands:
                    errors.extend(validate_workflow_target(command, skill_names))
    errors.extend(check_runtime_payloads(manifest, skill_names))
    for skill_name in assignments:
        if skill_name not in skill_names:
            errors.append(f"{skill_name}: section assignment points to a missing skill directory")
    for row_name in sorted(readme_rows):
        if row_name not in skill_names:
            errors.append(f"{row_name}: stale README skill table row")

    for skill_dir in skill_dirs:
        if skill_dir.name not in assignments:
            errors.append(f"{skill_dir.name}: missing section assignment in manifest")
            continue
        errors.extend(check_skill(skill_dir, readme_rows, manifest, skill_names, profile))
    if profile == PROFILE_CERATOPS:
        errors.extend(check_contract_source_lines())
    errors.extend(
        check_runtime_input_safety(
            manifest_runtime_input_paths(manifest, skill_dirs)
        )
    )
    if profile == PROFILE_CERATOPS:
        errors.extend(check_retired_baseline_absent())
    errors.extend(
        check_source_governance_consistency(
            manifest,
            skill_dirs,
            readme_rows,
            skill_names,
            profile,
        )
    )

    if errors:
        print(f"errors: {len(errors)}", file=sys.stderr)
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(f"ok: {len(skill_dirs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
