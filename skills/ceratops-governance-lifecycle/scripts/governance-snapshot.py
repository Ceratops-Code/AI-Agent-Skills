#!/usr/bin/env python3
"""Build the compact deterministic inventory for governance consistency audits.

The helper is read-only. It inventories only declared governance surfaces and
emits one JSON document consumed by the governance lifecycle audit action.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import tomllib
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable

from rule_graph import (
    history_limit_findings,
    load_history_references,
    load_history_source,
    parse_rule_source,
    rule_source_summary,
    validate_rule_stack,
)


D_RULE_CHAR_LIMIT = 220
D_RULE_RE = re.compile(r"^\s*-\s+\(D\)\s+(.+)$")
ALL_BULLETS_FORCE_RE = re.compile(
    r"All instruction bullets in this file are mandatory,\s*blocking,\s*and\s*closure-gating",
    re.IGNORECASE,
)
D_FORCE_PRESERVATION_RE = re.compile(
    r"The\s+`?\(D\)`?\s+label\s+marks\b.*?\bdoes not change the mandatory status",
    re.IGNORECASE | re.DOTALL,
)
MEMORY_TERM_RE = re.compile(r"\bmemory(?:\.md)?\b", re.IGNORECASE)
MEMORY_FORBIDDEN_RE = re.compile(
    r"\b(?:do\s+not|must\s+not)\b[^\n.]*\b(?:read|use|create|append|update|write|rely\s+on)\b[^\n.]*\bmemory(?:\.md)?\b"
    r"|\bdo\s+not\s+use\s+automation\s+memory\b",
    re.IGNORECASE,
)
MEMORY_REQUIRED_RE = re.compile(
    r"\b(?:must|always|required\s+to)\b[^\n.]*\b(?:read|use|create|append|update|write)\b[^\n.]*\bmemory(?:\.md)?\b"
    r"|\b(?:read|create|append|update|write)\b[^\n.]*\bmemory(?:\.md)?\b",
    re.IGNORECASE,
)
REFERENCE_RE = re.compile(
    r"(?:[`\"'](?P<quoted>[^`\"'\r\n]+\.(?:py|ps1|json|toml|md)|[^`\"'\r\n]*\.gitignore)[`\"']"
    r"|(?P<bare>[^\s`\"']+\.(?:py|ps1|json|toml|md)|[^\s`\"']*\.gitignore))",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_codex_home() -> pathlib.Path:
    return pathlib.Path(os.environ.get("CODEX_HOME") or pathlib.Path.home() / ".codex")


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def maybe_rel(path: pathlib.Path, base: pathlib.Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def reference_inventory(prompt: str) -> dict[str, list[str]]:
    """Classify referenced paths so helpers never include memory or result artifacts."""
    helpers: set[str] = set()
    memory: set[str] = set()
    artifacts: set[str] = set()
    controls: set[str] = set()

    for match in REFERENCE_RE.finditer(prompt):
        reference = str(match.group("quoted") or match.group("bare")).rstrip(".,;:)]}")
        reference = re.sub(
            r"^\$env:CODEX_HOME", "$CODEX_HOME", reference, flags=re.IGNORECASE
        ).replace("\\", "/")
        lowered = reference.lower()
        if lowered.endswith((".py", ".ps1")):
            helpers.add(reference)
        elif lowered.endswith("memory.md"):
            memory.add(reference)
        elif lowered.endswith(("automation.toml", "agents.md", ".gitignore")):
            controls.add(reference)
        else:
            artifacts.add(reference)

    return {
        "helper_refs": sorted(helpers),
        "memory_refs": sorted(memory),
        "artifact_refs": sorted(artifacts),
        "control_refs": sorted(controls),
    }


def parse_automation(path: pathlib.Path, root: pathlib.Path) -> dict[str, object]:
    data = tomllib.loads(read_text(path))
    prompt = str(data.get("prompt", ""))
    references = reference_inventory(prompt)
    memory_contract = classify_memory_contract(prompt)
    inbox_contract = classify_inbox_contract(prompt)
    return {
        "path": maybe_rel(path, root),
        "id": data.get("id"),
        "name": data.get("name"),
        "status": data.get("status"),
        "schedule": data.get("rrule"),
        "model": data.get("model"),
        "reasoning_effort": data.get("reasoning_effort"),
        "cwds": data.get("cwds", []),
        "prompt_chars": len(prompt),
        **references,
        "memory_contract": memory_contract["contract"],
        "memory_mention_count": memory_contract["mention_count"],
        "memory_incidental_mentions": memory_contract["incidental_mentions"],
        "inbox_contract": inbox_contract,
    }


def classify_memory_contract(prompt: str) -> dict[str, object]:
    mention_count = len(MEMORY_TERM_RE.findall(prompt))
    if mention_count == 0:
        return {"contract": "not_mentioned", "mention_count": 0, "incidental_mentions": 0}

    forbidden = False
    required = False
    incidental_mentions = 0
    for line in prompt.splitlines():
        if not MEMORY_TERM_RE.search(line):
            continue
        if MEMORY_FORBIDDEN_RE.search(line):
            forbidden = True
            continue
        if MEMORY_REQUIRED_RE.search(line):
            required = True
            continue
        incidental_mentions += len(MEMORY_TERM_RE.findall(line))

    if forbidden and required:
        contract = "conflicting"
    elif forbidden:
        contract = "forbidden"
    elif required:
        contract = "required"
    else:
        contract = "not_mentioned"
    return {
        "contract": contract,
        "mention_count": mention_count,
        "incidental_mentions": incidental_mentions,
    }


def classify_inbox_contract(prompt: str) -> str:
    lowered = prompt.lower()
    if "::inbox-item" not in prompt and "inbox item" not in lowered:
        return "not_mentioned"
    if re.search(r"(?:always|exactly one)[^\n.]*inbox item", lowered):
        return "required"
    if "do not emit an inbox item" in lowered and not re.search(r"(?:when|if)[^\n.]*inbox item", lowered):
        return "forbidden"
    if re.search(r"(?:when|if|only when)[^\n.]*inbox item", lowered) or "inbox_required" in prompt:
        return "conditional"
    if "alert state" in lowered and "inbox item" in lowered:
        return "conditional"
    return "mentioned"


def automations_inventory(automation_root: pathlib.Path) -> dict[str, object]:
    paths = sorted(automation_root.glob("*/automation.toml"))
    items = [parse_automation(path, automation_root) for path in paths]
    schedules = Counter(str(item["schedule"]) for item in items)
    models = Counter(str(item["model"]) for item in items)
    return {
        "root": str(automation_root),
        "count": len(items),
        "items": items,
        "duplicate_schedules": {key: value for key, value in schedules.items() if value > 1},
        "models": dict(models),
    }


def iter_agents(projects_root: pathlib.Path, codex_home: pathlib.Path) -> Iterable[pathlib.Path]:
    global_agents = codex_home / "AGENTS.md"
    if global_agents.exists():
        yield global_agents
    if projects_root.exists():
        local_paths = {
            path.resolve()
            for path in projects_root.rglob("AGENTS.md")
            if ".git" not in path.parts and path.resolve() != global_agents.resolve()
        }
        yield from sorted(local_paths)


def run_git(repo: pathlib.Path, *args: str) -> tuple[str | None, str | None]:
    """Run a bounded read-only Git probe and return compact output or an error."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout).strip()[:240]
    return result.stdout.rstrip("\r\n"), None


def parse_worktrees(output: str) -> list[dict[str, object]]:
    """Reduce `git worktree list --porcelain` to stable branch/path evidence."""
    worktrees: list[dict[str, object]] = []
    current: dict[str, object] = {}
    for line in [*output.splitlines(), ""]:
        if not line:
            if current:
                worktrees.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current["path"] = str(pathlib.Path(value).resolve())
        elif key == "HEAD":
            current["head"] = value
        elif key == "branch":
            current["branch"] = value.removeprefix("refs/heads/")
        elif key in {"bare", "detached", "locked", "prunable"}:
            current[key] = True
    return worktrees


def is_within(path: pathlib.Path, root: pathlib.Path) -> bool:
    """Return whether a resolved path stays within the expected worktree root."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def repo_git_state(repo: pathlib.Path, kind: str) -> dict[str, object]:
    """Inventory branch, dirty state, and secondary-worktree placement without mutation."""
    top_level, top_error = run_git(repo, "rev-parse", "--show-toplevel")
    if top_error or not top_level:
        return {
            "kind": kind,
            "path": str(repo.resolve()),
            "is_git_repo": False,
            "error": top_error,
        }

    root = pathlib.Path(top_level).resolve()
    branch, branch_error = run_git(root, "branch", "--show-current")
    head, head_error = run_git(root, "rev-parse", "HEAD")
    upstream, upstream_error = run_git(
        root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    )
    status, status_error = run_git(root, "status", "--porcelain=v1", "--untracked-files=normal")
    worktree_output, worktree_error = run_git(root, "worktree", "list", "--porcelain")

    status_lines = status.splitlines() if status is not None else []
    changed_paths = [line[3:] for line in status_lines if len(line) > 3]
    worktrees = parse_worktrees(worktree_output or "")
    primary_root = (
        pathlib.Path(str(worktrees[0]["path"])).resolve() if worktrees else root
    )
    expected_root = primary_root.parent / "worktrees" / primary_root.name
    misplaced = [
        str(item["path"])
        for item in worktrees
        if pathlib.Path(str(item["path"])).resolve() != primary_root
        and not is_within(pathlib.Path(str(item["path"])), expected_root)
    ]
    errors = [
        error
        for error in (branch_error, head_error, status_error, worktree_error)
        if error
    ]
    if upstream_error and "no upstream configured" not in upstream_error.lower():
        errors.append(upstream_error)

    return {
        "kind": kind,
        "path": str(root),
        "primary_worktree": str(primary_root),
        "is_git_repo": True,
        "branch": branch,
        "head": head,
        "upstream": upstream,
        "active_release_branch": bool(branch and branch.startswith("release/")),
        "dirty": bool(status_lines),
        "changed_count": len(status_lines),
        "changed_paths": changed_paths[:20],
        "changed_paths_truncated": len(changed_paths) > 20,
        "expected_secondary_worktree_root": str(expected_root.resolve()),
        "worktrees": worktrees,
        "misplaced_worktrees": misplaced,
        "errors": errors,
    }


def git_inventory(automation_root: pathlib.Path, projects_root: pathlib.Path) -> dict[str, object]:
    """Collect compact Git/worktree state for the automation repo and AGENTS projects."""
    targets = [("automation", automation_root)]
    if projects_root.exists():
        targets.extend(
            ("project", path.parent) for path in sorted(projects_root.glob("*/AGENTS.md"))
        )
    items = [repo_git_state(path, kind) for kind, path in targets]
    return {
        "count": len(items),
        "dirty_count": sum(1 for item in items if item.get("dirty")),
        "misplaced_worktree_count": sum(
            len(item.get("misplaced_worktrees", [])) for item in items
        ),
        "items": items,
    }


def classify_force_definitions(text: str) -> dict[str, bool]:
    return {
        "all_instruction_bullets_mandatory_blocking": bool(ALL_BULLETS_FORCE_RE.search(text)),
        "d_label_preserves_force": bool(D_FORCE_PRESERVATION_RE.search(text)),
    }


def _path_is_within(path: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _history_inventory(
    path: pathlib.Path,
    current_rule_ids: set[str],
    owned_rule_ids: set[str],
) -> dict[str, object]:
    history_path = path.with_name("AGENTS.history.json")
    if not history_path.exists():
        return {
            "path": str(history_path),
            "exists": False,
            "findings": [{"code": "missing_rule_history"}],
        }
    try:
        entries = load_history_source(history_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {
            "path": str(history_path),
            "exists": True,
            "findings": [
                {"code": "invalid_rule_history", "detail": str(error)}
            ],
        }
    findings = [
        *load_history_references(entries, current_rule_ids),
        *history_limit_findings(history_path, entries),
    ]
    for entry_index, entry in enumerate(entries):
        if "*" in entry["rules"]:
            continue
        owned_references = {
            str(value) for value in entry["rules"] if value != "*"
        }
        if owned_rule_ids and not owned_references.intersection(owned_rule_ids):
            findings.append(
                {
                    "code": "history_entry_without_owned_rule",
                    "entry": entry_index,
                }
            )
    return {
        "path": str(history_path),
        "exists": True,
        "entry_count": len(entries),
        "findings": findings,
    }


def _touches_rules(item: dict[str, object], rule_ids: set[str]) -> bool:
    values: set[str] = set()
    for key in ("rule_id", "source", "target"):
        value = item.get(key)
        if isinstance(value, str):
            values.add(value)
    members = item.get("rules")
    if isinstance(members, list):
        values.update(str(value) for value in members)
    return bool(values.intersection(rule_ids))


def _compact_edges(edges: list[dict[str, object]]) -> list[dict[str, object]]:
    compact = []
    for edge in edges:
        item = {
            key: edge[key] for key in ("source", "relation", "target")
        }
        if edge.get("source_file") != edge.get("target_file"):
            item["cross_scope"] = True
        compact.append(item)
    return compact


def agents_rule_graph_inventory(
    projects_root: pathlib.Path, codex_home: pathlib.Path
) -> dict[str, object]:
    """Validate every global-to-local AGENTS stack against one graph parser."""
    paths = list(iter_agents(projects_root, codex_home))
    global_path = (codex_home / "AGENTS.md").resolve()
    parsed = {path.resolve(): parse_rule_source(path) for path in paths}
    local_paths = sorted(path for path in parsed if path != global_path)
    file_items: list[dict[str, object]] = []
    stacks: list[dict[str, object]] = []

    if global_path in parsed:
        global_source = parsed[global_path]
        global_ids = {record.rule_id for record in global_source.records}
        global_summary = rule_source_summary(global_source)
        global_summary["scope"] = "global"
        global_summary["history"] = _history_inventory(
            global_path, global_ids, global_ids
        )
        file_items.append(global_summary)
        global_validation = validate_rule_stack(
            [global_source], global_source=global_source.source
        )
        global_validation["edges"] = _compact_edges(global_validation["edges"])
        global_validation["path"] = str(global_path)
        global_validation["scope"] = "global"
        stacks.append(global_validation)

    for path in local_paths:
        ancestor_paths = sorted(
            (
                candidate
                for candidate in local_paths
                if _path_is_within(path.parent, candidate.parent)
            ),
            key=lambda candidate: len(candidate.parts),
        )
        stack_sources = [parsed[candidate] for candidate in ancestor_paths]
        if global_path in parsed:
            stack_sources.insert(0, parsed[global_path])
        current_ids = {
            record.rule_id
            for source in stack_sources
            for record in source.records
        }
        local_summary = rule_source_summary(parsed[path])
        local_summary["scope"] = "local"
        local_ids = {record.rule_id for record in parsed[path].records}
        local_summary["history"] = _history_inventory(
            path, current_ids, local_ids
        )
        file_items.append(local_summary)

        validation = validate_rule_stack(
            stack_sources,
            global_source=parsed[global_path].source
            if global_path in parsed
            else "",
        )
        validation["edges"] = [
            edge
            for edge in validation["edges"]
            if edge.get("source_file") == parsed[path].source
        ]
        validation["relation_counts"] = dict(
            sorted(
                Counter(str(edge["relation"]) for edge in validation["edges"]).items()
            )
        )
        validation["rule_count"] = len(local_ids)
        validation["edges"] = _compact_edges(validation["edges"])
        validation["cycles"] = [
            cycle
            for cycle in validation["cycles"]
            if _touches_rules(cycle, local_ids)
        ]
        validation["findings"] = [
            finding
            for finding in validation["findings"]
            if _touches_rules(finding, local_ids)
        ]
        validation["semantic_reviews"] = [
            review
            for review in validation["semantic_reviews"]
            if _touches_rules(review, local_ids)
        ]
        validation["path"] = str(path)
        validation["scope"] = "local-stack-delta"
        validation["stack_paths"] = [source.source for source in stack_sources]
        stacks.append(validation)

    structural_finding_count = sum(
        int(item["findings"]["count"]) + len(item["history"]["findings"])
        for item in file_items
    ) + sum(len(stack["findings"]) for stack in stacks)
    return {
        "standard": "references/rule-design.md",
        "file_count": len(file_items),
        "files": file_items,
        "stacks": stacks,
        "structural_finding_count": structural_finding_count,
        "approved_debt_count": sum(
            int(item["approved_debt"]["count"]) for item in file_items
        ),
        "semantic_review_count": sum(
            len(stack["semantic_reviews"]) for stack in stacks
        )
        + sum(int(item["semantic_reviews"]["count"]) for item in file_items),
    }


def agents_inventory(projects_root: pathlib.Path, codex_home: pathlib.Path) -> dict[str, object]:
    items = []
    repeated_lines: Counter[str] = Counter()
    global_path = codex_home / "AGENTS.md"
    global_force = classify_force_definitions(read_text(global_path)) if global_path.exists() else {
        "all_instruction_bullets_mandatory_blocking": False,
        "d_label_preserves_force": False,
    }
    for path in iter_agents(projects_root, codex_home):
        text = read_text(path)
        lines = text.splitlines()
        declared_force = classify_force_definitions(text)
        effective_force = {
            key: declared_force[key] or global_force[key]
            for key in declared_force
        }
        label_counts: Counter[str] = Counter()
        instruction_bullets = 0
        for raw_line in lines:
            if raw_line.startswith("- "):
                line = raw_line.strip()
                instruction_bullets += 1
                repeated_lines[line] += 1
                d_rule_match = D_RULE_RE.match(line)
                if d_rule_match:
                    label_counts["d"] += 1
                else:
                    label_match = re.match(r"^-\s+([A-Za-z]+):", line)
                    if label_match:
                        label_counts[label_match.group(1).lower()] += 1
        classification_complete = (
            effective_force["all_instruction_bullets_mandatory_blocking"]
            and (label_counts.get("d", 0) == 0 or effective_force["d_label_preserves_force"])
        )
        items.append(
            {
                "path": str(path),
                "instruction_bullets": instruction_bullets,
                "explicit_class_labels": dict(sorted(label_counts.items())),
                "force_definitions": {
                    "declared": declared_force,
                    "effective": effective_force,
                },
                "classification_complete": classification_complete,
                "classification_review_required": not classification_complete,
                "blocking": label_counts.get("blocking", 0),
                "mandatory": label_counts.get("mandatory", 0),
                "metadata": label_counts.get("metadata", 0),
            }
        )
    return {
        "count": len(items),
        "items": items,
        "repeated_rule_lines": [
            {"line": line, "count": count}
            for line, count in repeated_lines.most_common(30)
            if count > 1
        ],
    }


def gitignore_inventory(automation_root: pathlib.Path) -> dict[str, object]:
    path = automation_root / ".gitignore"
    text = read_text(path) if path.exists() else ""
    expected = (
        ".run-jitter-salt",
        "*.bck",
        "*/memory.md",
        "*/downloads/",
        "*/__pycache__/",
        "pc-cleanup/deleted-files/",
        "global-dependabot-alert-review/dependabot-org-queue-snapshot.json",
        "global-dependabot-alert-review/local-checkout-sync.json",
        "worktrees/",
    )
    return {
        "path": str(path),
        "exists": path.exists(),
        "missing_expected_entries": [entry for entry in expected if entry not in text],
    }


def collect_overlong_d_rules(text: str, source: str, source_kind: str) -> list[dict[str, object]]:
    candidates = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not D_RULE_RE.match(line):
            continue
        rule = line.strip()
        if len(rule) <= D_RULE_CHAR_LIMIT:
            continue
        candidates.append(
            {
                "source": source,
                "source_kind": source_kind,
                "line": line_number,
                "chars": len(rule),
                "text": rule[:360] + ("..." if len(rule) > 360 else ""),
            }
        )
    return candidates


def d_rule_brevity_inventory(
    automation_root: pathlib.Path,
    projects_root: pathlib.Path,
    codex_home: pathlib.Path,
) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    sources_checked = 0

    for path in sorted(automation_root.glob("*/automation.toml")):
        data = tomllib.loads(read_text(path))
        prompt = str(data.get("prompt", ""))
        sources_checked += 1
        candidates.extend(
            collect_overlong_d_rules(prompt, maybe_rel(path, automation_root), "automation_prompt")
        )

    for path in iter_agents(projects_root, codex_home):
        sources_checked += 1
        candidates.extend(collect_overlong_d_rules(read_text(path), str(path), "agents_file"))

    candidates.sort(key=lambda item: (-int(item["chars"]), str(item["source"]), int(item["line"])))
    return {
        "char_limit": D_RULE_CHAR_LIMIT,
        "sources_checked": sources_checked,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def build_snapshot(args: argparse.Namespace) -> dict[str, object]:
    return {
        "schema": "global-governance-consistency-audit/snapshot.v2",
        "generated_at": utc_now(),
        "automations": automations_inventory(args.automation_root.resolve()),
        "agents": agents_inventory(args.projects_root.resolve(), args.codex_home.resolve()),
        "agents_rule_graph": agents_rule_graph_inventory(
            args.projects_root.resolve(), args.codex_home.resolve()
        ),
        "git": git_inventory(args.automation_root.resolve(), args.projects_root.resolve()),
        "automation_gitignore": gitignore_inventory(args.automation_root.resolve()),
        "d_rule_brevity": d_rule_brevity_inventory(
            args.automation_root.resolve(),
            args.projects_root.resolve(),
            args.codex_home.resolve(),
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=pathlib.Path, default=default_codex_home())
    parser.add_argument("--automation-root", type=pathlib.Path, default=default_codex_home() / "automations")
    parser.add_argument("--projects-root", type=pathlib.Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_snapshot(args)
    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True, separators=None if args.pretty else (",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
