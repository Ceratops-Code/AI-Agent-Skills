#!/usr/bin/env python3
"""Validate Ceratops skill source folders and runtime generation inputs.

Called by CI, governance validation, explicit skill-maintenance validation, and
runtime smoke paths. The default mode is a full repository validation. `--mode
sections` is the lightweight replacement for the retired section-sync script:
it checks shared section assignments and source skill delta-only status without
running unrelated README, metadata, secret, or contract checks.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "skills"
README = ROOT / "README.md"
SECTION_MANIFEST = ROOT / "templates" / "skill-sections.json"
CONTRACTS_DIR = pathlib.Path("contracts")
REQUIRED_CONTRACT_FILES = [
    pathlib.Path("contracts/source-docs.json"),
    pathlib.Path("contracts/code/code-comment-nondeterministic-contract.md"),
    pathlib.Path("contracts/github/github-org-deterministic-contract.json"),
    pathlib.Path("contracts/github/github-repo-deterministic-contract.json"),
    pathlib.Path("contracts/github/github-pr-readiness-deterministic-contract.json"),
    pathlib.Path("contracts/github/github-org-nondeterministic-contract.md"),
    pathlib.Path("contracts/github/github-repo-nondeterministic-contract.md"),
    pathlib.Path("contracts/github/github-pr-readiness-nondeterministic-contract.md"),
    pathlib.Path("contracts/code/code-repo-deterministic-contract.json"),
    pathlib.Path("contracts/code/code-repo-nondeterministic-contract.md"),
    pathlib.Path("contracts/artifacts/artifact-deterministic-contract.json"),
    pathlib.Path("contracts/artifacts/artifact-nondeterministic-contract.md"),
]
SECTIONS_START = "<!-- CERATOPS_SHARED_SECTIONS_START -->"
SECTIONS_END = "<!-- CERATOPS_SHARED_SECTIONS_END -->"

NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
SKILL_REF_RE = re.compile(r"\$([a-z0-9]+(?:-[a-z0-9]+)+)(?![A-Za-z0-9_-])")
README_SKILL_ROW_RE = re.compile(r"^\|\s*`(?P<name>ceratops-[a-z0-9-]+)`\s*\|", re.MULTILINE)
ALLOWED_EXTERNAL_SKILL_REFS = {"skill-creator"}
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
    re.compile(r"C:\\Users\\roman", re.IGNORECASE),
]


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


def display_name_sane(skill_name: str, display_name: str) -> bool:
    """Check that the UI display name still resembles the skill directory."""

    name_tokens = {token for token in normalized_tokens(skill_name) if token != "ceratops"}
    if not name_tokens:
        return False
    display_tokens = set(normalized_tokens(display_name))
    overlap = len(name_tokens & display_tokens)
    return display_name.startswith("Ceratops ") and overlap / len(name_tokens) >= 0.5


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

    sections = manifest["sections"]
    assignments = manifest["skills"]
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


def check_runtime_payloads(manifest: dict[str, object], skill_names: set[str]) -> list[str]:
    """Validate declared runtime payload paths without copying any files."""

    errors: list[str] = []
    payloads = manifest.get("runtime_payloads", {})
    if not isinstance(payloads, dict):
        errors.append("section manifest runtime_payloads must be an object")
        return errors
    for skill_name, values in payloads.items():
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


def readme_skill_rows(readme_text: str) -> set[str]:
    """Return skill names documented in the README skill table."""

    return {match.group("name") for match in README_SKILL_ROW_RE.finditer(readme_text)}


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

    if len(parts) >= 2 and parts[0] in {"python", "py"} and parts[1].startswith("scripts/"):
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


def check_retired_baseline_absent() -> list[str]:
    """Ensure the retired best-practice baseline artifact did not come back."""

    errors: list[str] = []
    for path in ROOT.rglob("best-practice-baseline.md"):
        if not path.is_file() or ".git" in path.parts:
            continue
        rel = path.relative_to(ROOT)
        errors.append(f"{rel}: retired best-practice baseline; use {CONTRACTS_DIR}")
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


def check_section_sources(manifest: dict[str, object], skill_dirs: list[pathlib.Path]) -> list[str]:
    """Run only shared-section checks needed after template or manifest edits."""

    errors: list[str] = []
    sections = manifest.get("sections", {})
    assignments = manifest.get("skills", {})
    skill_names = {skill_dir.name for skill_dir in skill_dirs}
    if "core" not in sections:
        errors.append("section manifest must define core")
    if not isinstance(sections, dict):
        errors.append("section manifest sections must be an object")
        return errors
    if not isinstance(assignments, dict):
        errors.append("section manifest skills must be an object")
        return errors
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


def check_resource_layout(skill_dir: pathlib.Path) -> list[str]:
    """Validate the skill package layout that should remain portable across agents."""

    errors: list[str] = []
    for child in skill_dir.iterdir():
        if child.is_file() and child.name != "SKILL.md":
            errors.append(f"{skill_dir.name}: unsupported top-level file {child.name}")
        if child.is_dir() and child.name not in ALLOWED_SKILL_RESOURCE_DIRS:
            errors.append(f"{skill_dir.name}: unsupported top-level directory {child.name}")

    references_dir = skill_dir / "references"
    if references_dir.is_dir():
        for path in references_dir.rglob("*"):
            if path.is_file() and path.parent != references_dir:
                rel_path = path.relative_to(skill_dir)
                errors.append(f"{skill_dir.name}: references file must be one level deep: {rel_path}")
    return errors


def check_skill(skill_dir: pathlib.Path, readme_rows: set[str], manifest: dict[str, object], skill_names: set[str]) -> list[str]:
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
    if h2_headings != ["Goal", "Context", "Constraints", "Done When"]:
        errors.append(f"{name}: H2 sections must be Goal, Context, Constraints, Done When")
    if "### Boundaries" not in core_text:
        errors.append(f"{name}: missing Boundaries section")
    if SECTIONS_START in core_text or SECTIONS_END in core_text:
        errors.append(f"{name}: source SKILL.md must be delta-only; shared sections are generated at install time")
    else:
        try:
            rendered_sections_block(name, manifest)
        except Exception as exc:
            errors.append(f"{name}: could not render runtime shared sections: {exc}")
    errors.extend(check_resource_layout(skill_dir))

    if not openai_yaml.is_file():
        errors.append(f"{name}: missing agents/openai.yaml")
    else:
        yaml_text = openai_yaml.read_text(encoding="utf-8")
        for required in ("display_name:", "short_description:", "icon_small:", "icon_large:", "default_prompt:"):
            if required not in yaml_text:
                errors.append(f"{name}: openai.yaml missing {required}")
        if f"${name}" not in yaml_text:
            errors.append(f"{name}: default_prompt should mention ${name}")
        interface = parse_openai_interface(openai_yaml)
        display_name = interface.get("display_name", "")
        short_description = interface.get("short_description", "")
        icon_small = interface.get("icon_small", "")
        icon_large = interface.get("icon_large", "")
        if display_name and not display_name_sane(name, display_name):
            errors.append(f"{name}: display_name no longer matches the skill name closely enough")
        if short_description and not short_description_relevant(short_description, frontmatter.get("description", "")):
            errors.append(f"{name}: short_description no longer matches the skill description closely enough")
        for field_name, icon_value in (("icon_small", icon_small), ("icon_large", icon_large)):
            if icon_value and icon_value != CERATOPS_ICON_REL:
                errors.append(f"{name}: {field_name} should use shared Ceratops icon {CERATOPS_ICON_REL}")
            icon_path = (skill_dir / icon_value).resolve() if icon_value else None
            if icon_path and not icon_path.is_file():
                errors.append(f"{name}: {field_name} points to missing file {icon_value}")
            elif icon_path and CERATOPS_ICON_SOURCE.is_file() and icon_path.read_bytes() != CERATOPS_ICON_SOURCE.read_bytes():
                errors.append(f"{name}: {field_name} does not match repo icon {CERATOPS_ICON_SOURCE.relative_to(ROOT)}")
        errors.extend(check_skill_refs(openai_yaml, yaml_text, skill_names))

    errors.extend(check_skill_refs(skill_md, core_text, skill_names))

    return errors


def check_secrets() -> list[str]:
    """Scan text files for high-confidence secrets and local private paths."""

    errors: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
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
    """Run either section-only or full source consistency validation."""

    parser = argparse.ArgumentParser(description="Validate Ceratops skill source and runtime-generation inputs.")
    parser.add_argument("--mode", choices=["full", "sections"], default="full", help="Use sections for the lightweight shared-section check.")
    args = parser.parse_args()

    errors: list[str] = []
    if not SKILLS_DIR.is_dir():
        errors.append("missing skills/ directory")
    if not SECTION_MANIFEST.is_file():
        errors.append("missing templates/skill-sections.json")

    manifest = load_section_manifest() if SECTION_MANIFEST.is_file() else {"sections": {}, "skills": {}}
    skill_dirs = sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()) if SKILLS_DIR.is_dir() else []
    if args.mode == "sections":
        errors.extend(check_section_sources(manifest, skill_dirs))
        if errors:
            print(f"errors: {len(errors)}", file=sys.stderr)
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        print(f"ok: sections {len(skill_dirs)}")
        return 0

    if not README.is_file():
        errors.append("missing README.md")
    if not (ROOT / CONTRACTS_DIR).is_dir():
        errors.append(f"missing contract directory: {CONTRACTS_DIR}")
    for rel_path in REQUIRED_CONTRACT_FILES:
        if not (ROOT / rel_path).is_file():
            errors.append(f"missing required contract file: {rel_path}")
    if not CERATOPS_ICON_SOURCE.is_file():
        errors.append(f"missing shared Ceratops icon source: {CERATOPS_ICON_SOURCE.relative_to(ROOT)}")

    sections = manifest.get("sections", {})
    workflow_hints = manifest.get("maintenance_workflows", {})
    assignments = manifest.get("skills", {})
    if "core" not in sections:
        errors.append("section manifest must define core")
    if not isinstance(workflow_hints, dict):
        errors.append("section manifest maintenance_workflows must be an object")
    else:
        required_workflows = {
            "shared_source_changes",
            "skill_local_or_metadata_changes",
            "helper_runtime_changes",
            "new_skill_local_availability",
        }
        for workflow_name in required_workflows:
            commands = workflow_hints.get(workflow_name)
            if not isinstance(commands, list) or not all(isinstance(item, str) for item in commands):
                errors.append(f"section manifest maintenance_workflows.{workflow_name} must be a list of strings")
        for workflow_name, commands in workflow_hints.items():
            if workflow_name in required_workflows:
                continue
            if not isinstance(commands, list) or not all(isinstance(item, str) for item in commands):
                errors.append(f"section manifest maintenance_workflows.{workflow_name} must be a list of strings")
    for section_name, rel_path in sections.items():
        if not (ROOT / rel_path).is_file():
            errors.append(f"missing section file for {section_name}: {rel_path}")
    for skill_name, section_names in assignments.items():
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
        errors.extend(check_skill(skill_dir, readme_rows, manifest, skill_names))
    errors.extend(check_contract_source_lines())
    errors.extend(check_secrets())
    errors.extend(check_retired_baseline_absent())

    if errors:
        print(f"errors: {len(errors)}", file=sys.stderr)
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(f"ok: {len(skill_dirs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
