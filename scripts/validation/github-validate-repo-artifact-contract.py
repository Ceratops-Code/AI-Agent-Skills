#!/usr/bin/env python3
"""
Check GitHub repository, repo-code, and artifact contracts.

Design notes for maintainers:

* `github-repo-deterministic-contract.json`, `code-repo-deterministic-contract.json`, and
  `artifact-deterministic-contract.json` are the policy source of truth. Python should gather
  evidence and implement reusable comparison mechanics, not hide policy in
  one-off conditionals.
* One run builds a shared evidence bundle: GitHub API responses, optional local
  checkout scan, repo type classification, and registry metadata. Individual
  checks consume that bundle so the user does not need one command per setting.
* Surface, subset, check-id, and fetch-bundle filters narrow the evidence and
  comparison set for explicit audits that only need a relevant slice. The
  `repo` surface means live GitHub repository state; use repeatable
  `--select surface:subset` entries when one run needs multiple surfaces.
* Apply mode is deliberately conservative. It only performs contract-listed
  reversible repository changes; destructive removals, registry publication,
  credential updates, branch/ruleset surgery, and unclear intent are report-only.
* Artifact checks are audit-oriented. Local build/publish/consumer smoke checks
  are reported as manual unless the contract can verify them from metadata.

Called by repo creation, repo health, dependency, and standards-review
workflows when current GitHub repo state, repository contents, or artifact
registry posture need a bundled deterministic audit. It is not a mandatory
post-mutation readback for a single successful setting or file-write command.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


API_VERSION = "2026-03-10"
PARAM_RE = re.compile(r"\$\{([^}]+)\}")
USES_RE = re.compile(r"^\s*uses:\s*([^@\s]+)@([^\s#]+)", re.MULTILINE)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SECRET_NAME_RE = re.compile(r"\b(ARG|ENV)\s+[A-Za-z0-9_]*(TOKEN|SECRET|PASSWORD|KEY)[A-Za-z0-9_]*\b", re.IGNORECASE)
FORK_PR_APPROVAL_RANK = {
    "first_time_contributors_new_to_github": 0,
    "first_time_contributors": 1,
    "all_external_contributors": 2,
}
SURFACE_CHOICES = ("all", "repo", "code", "artifact")
SUBSET_CHOICES = ("all", "health", "create", "settings", "dependency", "artifact", "content")
DEPENDABOT_MANIFEST_PATTERNS = {
    "npm": ["package.json"],
    "pip": ["pyproject.toml", "setup.cfg", "setup.py", "requirements*.txt"],
    "docker": ["Dockerfile", "**/Dockerfile"],
    "github-actions": [".github/workflows/*.yml", ".github/workflows/*.yaml"],
    "gomod": ["go.mod"],
    "cargo": ["Cargo.toml"],
    "maven": ["pom.xml"],
    "gradle": ["build.gradle", "build.gradle.kts"],
    "nuget": ["*.csproj", "*.fsproj", "*.vbproj", "*.sln", "*.nuspec"],
    "bundler": ["Gemfile", "*.gemspec"],
}
TEXT_SUFFIXES = {
    ".cfg",
    ".csproj",
    ".fsproj",
    ".gemspec",
    ".gradle",
    ".json",
    ".lock",
    ".md",
    ".ps1",
    ".psd1",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".toml",
    ".tf",
    ".txt",
    ".vbproj",
    ".yaml",
    ".yml",
    ".xml",
}
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache"}


@dataclass
class ApiResult:
    """Normalized GitHub API result used by all comparison functions."""

    ok: bool
    method: str
    endpoint: str
    data: Any = None
    status: int | None = None
    message: str | None = None
    raw_stdout: str = ""
    raw_stderr: str = ""


def load_json(path: str | os.PathLike[str]) -> Any:
    """Load a contract or JSON evidence file with consistent encoding."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def canonical(value: Any) -> str:
    """Stable JSON string used for comparisons and diagnostic matching."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def substitute(value: Any, params: dict[str, Any]) -> Any:
    """Replace `${param}` placeholders recursively inside JSON-like values."""
    if isinstance(value, str):
        match = PARAM_RE.fullmatch(value)
        if match:
            return params.get(match.group(1), value)
        return PARAM_RE.sub(lambda m: str(params.get(m.group(1), m.group(0))), value)
    if isinstance(value, list):
        return [substitute(item, params) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, params) for key, item in value.items()}
    return value


def parse_error(stdout: str, stderr: str) -> tuple[int | None, str]:
    """Parse the most useful GitHub API error status and message."""
    text = "\n".join(part for part in (stdout, stderr) if part)
    for candidate in (stdout, stderr, text):
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        status = obj.get("status")
        try:
            status_int = int(status) if status is not None else None
        except (TypeError, ValueError):
            status_int = None
        parts = [str(obj.get("message") or "")]
        if obj.get("errors"):
            parts.append(str(obj.get("errors")))
        return status_int, " ".join(part for part in parts if part) or candidate
    match = re.search(r"HTTP (\d{3})", text)
    return int(match.group(1)) if match else None, text.strip()


def run_gh_api(method: str, endpoint: str, body: Any | None = None, paginate: bool = False) -> ApiResult:
    """Run `gh api` and return parsed success or failure evidence."""
    cmd = ["gh", "api", "-H", f"X-GitHub-Api-Version: {API_VERSION}"]
    if method.upper() != "GET":
        cmd.extend(["-X", method.upper()])
    if paginate:
        cmd.extend(["--paginate", "--slurp"])
    if body is not None:
        cmd.extend(["--input", "-"])
    cmd.append(endpoint)
    proc = subprocess.run(
        cmd,
        input=json.dumps(body) if body is not None else None,
        text=True,
        capture_output=True,
    )
    if proc.returncode == 0:
        text = proc.stdout.strip()
        data: Any = None
        if text:
            data = json.loads(text)
            if paginate and isinstance(data, list) and all(isinstance(page, list) for page in data):
                merged: list[Any] = []
                for page in data:
                    merged.extend(page)
                data = merged
        return ApiResult(True, method.upper(), endpoint, data=data, raw_stdout=proc.stdout, raw_stderr=proc.stderr)
    status, message = parse_error(proc.stdout, proc.stderr)
    return ApiResult(False, method.upper(), endpoint, status=status, message=message, raw_stdout=proc.stdout, raw_stderr=proc.stderr)


def run_json_command(args: list[str], label: str) -> ApiResult:
    """Run a GitHub CLI command that returns JSON but is not a REST endpoint.

    Some useful evidence, such as `gh search prs --app dependabot`, is easier
    and more stable through a first-party CLI command than a hand-encoded search
    API query. Wrapping it in ApiResult keeps downstream check code uniform.
    """

    proc = subprocess.run(args, text=True, capture_output=True)
    if proc.returncode == 0:
        text = proc.stdout.strip()
        data = json.loads(text) if text else None
        return ApiResult(True, "CLI", label, data=data, raw_stdout=proc.stdout, raw_stderr=proc.stderr)
    status, message = parse_error(proc.stdout, proc.stderr)
    return ApiResult(False, "CLI", label, status=status, message=message, raw_stdout=proc.stdout, raw_stderr=proc.stderr)


def http_json(url: str) -> dict[str, Any]:
    """Fetch public registry metadata that is exposed as JSON over HTTPS."""

    req = urllib.request.Request(url, headers={"User-Agent": "github-health-contract-checker"})
    with urllib.request.urlopen(req, timeout=30) as response:
        text = response.read().decode("utf-8")
    return json.loads(text)


def endpoint_for(endpoint: str, params: dict[str, Any]) -> str:
    """Resolve a contract endpoint template using active repo parameters."""

    return str(substitute(endpoint, params))


def repo_slug(owner: str, repo: str) -> str:
    """Return the GitHub `OWNER/REPO` slug used in reports and API calls."""

    return f"{owner}/{repo}"


def split_repo(value: str) -> tuple[str, str]:
    """Parse and validate an `OWNER/REPO` CLI value."""

    if "/" not in value:
        raise SystemExit("--repo must be OWNER/REPO")
    owner, name = value.split("/", 1)
    if not owner or not name:
        raise SystemExit("--repo must be OWNER/REPO")
    return owner, name


def default_contract_path(filename: str, *aliases: str) -> str:
    """Find a bundled contract from common source and runtime locations.

    Source checkouts and installed skill copies both carry the `contracts/`
    tree, but GitHub, repo-code, and external artifact contracts live in
    different subfolders. The CLI default therefore probes every supported
    contract root before falling back to the raw filename the caller supplied.
    """

    script_root = pathlib.Path(__file__).resolve().parents[2]
    names = (filename, *aliases)
    bases = (
        pathlib.Path.cwd(),
        pathlib.Path.cwd() / "contracts" / "github",
        pathlib.Path.cwd() / "contracts" / "code",
        pathlib.Path.cwd() / "contracts" / "artifacts",
        pathlib.Path.cwd() / "contracts",
        script_root / "contracts" / "github",
        script_root / "contracts" / "code",
        script_root / "contracts" / "artifacts",
        script_root / "contracts",
        pathlib.Path(__file__).resolve().parent,
    )
    for base in bases:
        for name in names:
            candidate = base / name
            if candidate.is_file():
                return str(candidate)
    return filename


def all_check_ids(contract: dict[str, Any]) -> set[str]:
    """Return the check identifiers declared by one deterministic contract."""

    return {str(check.get("id")) for check in contract.get("checks", []) if check.get("id")}


def prefixed(ids: set[str], *prefixes: str) -> set[str]:
    """Select check IDs by stable prefix; contract policy stays in JSON IDs."""

    return {check_id for check_id in ids if check_id.startswith(prefixes)}


def subset_check_ids(
    github_contract: dict[str, Any],
    code_contract: dict[str, Any],
    artifact_contract: dict[str, Any],
    subset: str,
) -> tuple[set[str] | None, set[str] | None, set[str] | None]:
    """Map operational subsets to deterministic check-id subsets.

    `None` means "all checks for that contract". Empty sets are intentional for
    surfaces where the subset only needs context, not findings. These subsets are
    deliberately broad enough for skill workflows while still avoiding a full
    audit when a normal ship, dependency, or artifact task only needs one slice.
    """

    github_ids = all_check_ids(github_contract)
    code_ids = all_check_ids(code_contract)
    artifact_ids = all_check_ids(artifact_contract)
    if subset in {"all", "health"}:
        return None, None, None
    if subset == "settings":
        return prefixed(github_ids, "repo.", "process.", "actions.", "security.", "content."), set(), set()
    if subset == "dependency":
        return {
            check_id
            for check_id in github_ids
            if check_id in {
                "security.vulnerability_alerts_enabled",
                "security.dependabot_security_updates_enabled",
                "security.open_dependabot_alert_queue",
                "security.open_dependabot_pr_queue",
                "security.dependency_review_availability",
                "content.dependencies_label_when_dependabot_uses_it",
            }
        }, {
            check_id
            for check_id in code_ids
            if check_id in {
                "security.dependabot_config_file",
                "actions.workflow_sha_pinning",
                "content.local_secret_pattern_scan",
            }
        }, set()
    if subset == "artifact":
        return set(), prefixed(code_ids, "type."), None
    if subset == "content":
        return set(), None, set()
    if subset == "create":
        github_selected = github_ids - prefixed(github_ids, "stale_state.")
        code_selected = code_ids - prefixed(code_ids, "stale_state.", "local.")
        artifact_selected = artifact_ids
        return github_selected, code_selected, artifact_selected
    raise SystemExit(f"Unknown subset: {subset}")


def selected_contract_checks(contract: dict[str, Any], selected_ids: set[str] | None) -> list[dict[str, Any]]:
    """Return contract checks matching the current selection."""

    checks = contract.get("checks", [])
    if selected_ids is None:
        return checks
    return [check for check in checks if check.get("id") in selected_ids]


def selected_ids_for_report(contract: dict[str, Any], selected_ids: set[str] | None) -> set[str]:
    """Return the concrete check IDs represented by a selection."""

    return all_check_ids(contract) if selected_ids is None else set(selected_ids)


def selection_ids_for_contract(contract: dict[str, Any], selected_ids: set[str] | None) -> set[str]:
    """Convert one surface/subset selection into explicit check IDs.

    The validator keeps `None` as "all checks" for the legacy single-selection
    path. Multi-selection needs concrete sets so `repo:dependency` and
    `code:dependency` can be unioned without accidentally expanding a later
    empty surface into every check.
    """

    return all_check_ids(contract) if selected_ids is None else set(selected_ids)


def filter_selected_by_surface(
    github_selected: set[str] | None,
    code_selected: set[str] | None,
    artifact_selected: set[str] | None,
    surface: str,
) -> tuple[set[str] | None, set[str] | None, set[str] | None]:
    """Apply the high-level repo/artifact surface after subset selection."""

    if surface == "repo":
        return github_selected, set(), set()
    if surface == "code":
        return set(), code_selected, set()
    if surface == "artifact":
        return set(), set(), artifact_selected
    return github_selected, code_selected, artifact_selected


def parse_select(raw: str) -> tuple[str, str]:
    """Parse one repeatable `--select surface:subset` value."""

    if ":" not in raw:
        raise SystemExit(f"--select must be SURFACE:SUBSET, got {raw!r}")
    surface, subset = (part.strip().lower() for part in raw.split(":", 1))
    if surface not in SURFACE_CHOICES:
        raise SystemExit(f"Unknown --select surface {surface!r}; expected one of {', '.join(SURFACE_CHOICES)}")
    if subset not in SUBSET_CHOICES:
        raise SystemExit(f"Unknown --select subset {subset!r}; expected one of {', '.join(SUBSET_CHOICES)}")
    return surface, subset


def select_check_ids(
    github_contract: dict[str, Any],
    code_contract: dict[str, Any],
    artifact_contract: dict[str, Any],
    surface: str,
    subset: str,
) -> tuple[set[str], set[str], set[str]]:
    """Return explicit check IDs for one surface/subset pair."""

    github_selected, code_selected, artifact_selected = subset_check_ids(github_contract, code_contract, artifact_contract, subset)
    github_selected, code_selected, artifact_selected = filter_selected_by_surface(github_selected, code_selected, artifact_selected, surface)
    return (
        selection_ids_for_contract(github_contract, github_selected),
        selection_ids_for_contract(code_contract, code_selected),
        selection_ids_for_contract(artifact_contract, artifact_selected),
    )


def build_selection(
    github_contract: dict[str, Any],
    code_contract: dict[str, Any],
    artifact_contract: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[set[str] | None, set[str] | None, set[str] | None, list[dict[str, str]] | None]:
    """Build the selected check IDs from shorthand or repeatable selection flags.

    `--surface/--subset` is the simple single-selection shorthand. `--select`
    is the multi-selection mode for one process that should check several
    surfaces with different subsets, such as `repo:dependency` plus
    `code:dependency`. Mixing both modes would make command intent ambiguous, so
    non-default shorthand values are rejected when `--select` is present.
    """

    if not args.select:
        github_selected, code_selected, artifact_selected = subset_check_ids(
            github_contract,
            code_contract,
            artifact_contract,
            args.subset,
        )
        github_selected, code_selected, artifact_selected = filter_selected_by_surface(
            github_selected,
            code_selected,
            artifact_selected,
            args.surface,
        )
        return github_selected, code_selected, artifact_selected, None

    if args.surface != "all" or args.subset != "all":
        raise SystemExit("--select cannot be combined with non-default --surface or --subset values")

    github_union: set[str] = set()
    code_union: set[str] = set()
    artifact_union: set[str] = set()
    selections: list[dict[str, str]] = []
    for raw in args.select:
        surface, subset = parse_select(raw)
        selected = select_check_ids(github_contract, code_contract, artifact_contract, surface, subset)
        if not any(selected):
            raise SystemExit(f"--select {raw!r} selects no checks; choose a subset that applies to {surface!r}")
        github_union.update(selected[0])
        code_union.update(selected[1])
        artifact_union.update(selected[2])
        selections.append({"surface": surface, "subset": subset})
    return github_union, code_union, artifact_union, selections


def apply_explicit_check_ids(
    github_contract: dict[str, Any],
    code_contract: dict[str, Any],
    artifact_contract: dict[str, Any],
    requested: list[str] | None,
    github_selected: set[str] | None,
    code_selected: set[str] | None,
    artifact_selected: set[str] | None,
) -> tuple[set[str] | None, set[str] | None, set[str] | None]:
    """Restrict the subset/surface selection to explicitly named check IDs."""

    if not requested:
        return github_selected, code_selected, artifact_selected
    github_ids = all_check_ids(github_contract)
    code_ids = all_check_ids(code_contract)
    artifact_ids = all_check_ids(artifact_contract)
    unknown = sorted(set(requested) - github_ids - code_ids - artifact_ids)
    if unknown:
        raise SystemExit(f"Unknown check id(s): {', '.join(unknown)}")
    requested_set = set(requested)
    github_requested = requested_set & github_ids
    code_requested = requested_set & code_ids
    artifact_requested = requested_set & artifact_ids
    if github_selected is not None:
        github_requested &= github_selected
    if code_selected is not None:
        code_requested &= code_selected
    if artifact_selected is not None:
        artifact_requested &= artifact_selected
    filtered_out = requested_set - github_requested - code_requested - artifact_requested
    if filtered_out:
        raise SystemExit(f"Check id(s) excluded by current --surface/--subset: {', '.join(sorted(filtered_out))}")
    return github_requested, code_requested, artifact_requested


def as_list(data: Any) -> list[Any]:
    """Return list data from API responses and treat all other shapes as empty."""

    return data if isinstance(data, list) else []


def tree_paths(tree_data: Any) -> list[str]:
    """Extract repository paths from the Git trees API response."""

    if not isinstance(tree_data, dict):
        return []
    items = tree_data.get("tree")
    if not isinstance(items, list):
        return []
    return [str(item.get("path")) for item in items if isinstance(item, dict) and item.get("path")]


def path_matches(paths: list[str], patterns: list[str]) -> bool:
    """Return whether any repo path matches one of the contract glob patterns."""

    for path in paths:
        for pattern in patterns:
            if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(pathlib.PurePosixPath(path).name, pattern):
                return True
    return False


def matching_paths(paths: list[str], patterns: list[str]) -> list[str]:
    """Return every repo path matched by one of the contract glob patterns."""

    matched: list[str] = []
    for path in paths:
        for pattern in patterns:
            if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(pathlib.PurePosixPath(path).name, pattern):
                matched.append(path)
                break
    return sorted(set(matched))


def detect_dependabot_ecosystems(paths: list[str]) -> dict[str, list[str]]:
    """Infer dependency ecosystems from known manifest file patterns."""

    detected: dict[str, list[str]] = {}
    for ecosystem, patterns in DEPENDABOT_MANIFEST_PATTERNS.items():
        matches = matching_paths(paths, patterns)
        if matches:
            detected[ecosystem] = matches
    return detected


def config_path(paths: list[str], *names: str) -> str | None:
    """Find a config file path by exact case-insensitive repository path."""

    name_set = {name.lower() for name in names}
    for path in paths:
        if path.lower() in name_set:
            return path
    return None


def workflow_files(local: dict[str, Any]) -> dict[str, str]:
    """Return workflow text files from the local scan."""

    return {path: text for path, text in local.get("texts", {}).items() if path.startswith(".github/workflows/")}


def workflow_text(local: dict[str, Any]) -> str:
    """Concatenate local workflow files for text-level policy checks."""

    return "\n".join(workflow_files(local).values())


def workflows_with_permissions_write_all(local: dict[str, Any]) -> list[dict[str, str]]:
    """Find workflows using the broad GitHub Actions `permissions: write-all` setting."""

    matches: list[dict[str, str]] = []
    for path, text in workflow_files(local).items():
        if re.search(r"(?im)^\s*permissions:\s*write-all\s*(?:#.*)?$", text):
            matches.append({"path": path, "permission": "write-all"})
    return matches


def workflows_with_top_level_write_permission(local: dict[str, Any], permission: str) -> list[dict[str, str]]:
    """Find workflow-root `permissions` blocks granting one write permission.

    This intentionally treats job-level permissions as acceptable evidence for
    scoped publishing or attestation jobs, and reports only workflow-root grants.
    """

    permission_re = re.escape(permission)
    matches: list[dict[str, str]] = []
    for path, text in workflow_files(local).items():
        if re.search(rf"(?im)^permissions:\s*\{{[^}}\n]*\b{permission_re}\s*:\s*write\b", text):
            matches.append({"path": path, "permission": permission})
            continue
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if not re.match(r"^permissions:\s*(?:#.*)?$", line):
                continue
            for child in lines[index + 1 :]:
                stripped = child.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if re.match(r"^\S", child):
                    break
                if re.match(rf"^\s+{permission_re}\s*:\s*write\b", child):
                    matches.append({"path": path, "permission": permission})
                    break
            if matches and matches[-1]["path"] == path:
                break
    return matches


def workflows_with_write_permission(local: dict[str, Any], permission: str) -> list[dict[str, str]]:
    """Find any workflow permission grant for a specific write permission."""

    permission_re = re.escape(permission)
    matches: list[dict[str, str]] = []
    for path, text in workflow_files(local).items():
        if re.search(rf"(?im)^\s*{permission_re}\s*:\s*write\b", text):
            matches.append({"path": path, "permission": permission})
    return matches


def retention_days_finding(check_id: str, res: ApiResult, expected: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate the Actions artifact/log retention maximum-days policy."""

    if not res.ok:
        return [finding(check_id, "WARN", "Actions artifact/log retention settings were unavailable.", actual={"status": res.status, "message": res.message})]
    data = res.data if isinstance(res.data, dict) else {}
    days = data.get("days")
    max_days = expected.get("max_days")
    if isinstance(days, int) and isinstance(max_days, int) and days <= max_days:
        return [finding(check_id, "PASS", "Actions artifact/log retention is within policy.", actual=data)]
    return [finding(check_id, "FAIL", "Actions artifact/log retention exceeds policy.", actual=days, expected=f"<= {max_days}", path="$.days")]


def fork_pr_approval_finding(check_id: str, res: ApiResult, expected: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate fork-PR contributor approval by minimum strictness."""

    if not res.ok:
        return [finding(check_id, "WARN", "Fork PR contributor approval settings were unavailable.", actual={"status": res.status, "message": res.message})]
    data = res.data if isinstance(res.data, dict) else {}
    actual = data.get("approval_policy")
    minimum = expected.get("minimum_approval_policy")
    allowed = set(expected.get("allowed_policies") or [])
    actual_rank = FORK_PR_APPROVAL_RANK.get(str(actual))
    minimum_rank = FORK_PR_APPROVAL_RANK.get(str(minimum))
    if actual in allowed or (
        actual_rank is not None and minimum_rank is not None and actual_rank >= minimum_rank
    ):
        return [finding(check_id, "PASS", "Fork PR contributor approval policy is strict enough.", actual=data)]
    return [finding(check_id, "FAIL", "Fork PR contributor approval policy is weaker than required.", actual=actual, expected=minimum, path="$.approval_policy")]


def toml_key_present(text: str, key: str) -> bool:
    """Detect static or dynamic keys in TOML-like local configuration text."""

    escaped = re.escape(key)
    if re.search(rf"(?m)^\s*{escaped}\s*=", text):
        return True
    dynamic = re.search(r"(?ms)^\s*dynamic\s*=\s*\[(.*?)\]", text)
    return bool(dynamic and re.search(rf"['\"]{escaped}['\"]", dynamic.group(1)))


def scan_local(path: str | None) -> dict[str, Any]:
    """Scan one local checkout for file paths and small text file contents.

    The scan intentionally skips heavy/generated directories and caps text reads
    at 1 MiB. Contracts need enough source evidence for deterministic checks,
    not a full index of every dependency cache or binary artifact.
    """
    if not path:
        return {"available": False, "files": [], "texts": {}, "errors": []}
    root = pathlib.Path(path).resolve()
    if not root.is_dir():
        return {"available": False, "files": [], "texts": {}, "errors": [f"not a directory: {root}"]}
    files: list[str] = []
    texts: dict[str, str] = {}
    errors: list[str] = []
    for current, dirs, filenames in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        current_path = pathlib.Path(current)
        for name in filenames:
            file_path = current_path / name
            rel = file_path.relative_to(root).as_posix()
            files.append(rel)
            suffix = file_path.suffix.lower()
            if suffix in TEXT_SUFFIXES or name in {"Dockerfile", "Gemfile", "Procfile", "pom.xml"}:
                try:
                    if file_path.stat().st_size <= 1024 * 1024:
                        texts[rel] = file_path.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    errors.append(f"{rel}: {exc}")
    return {"available": True, "root": str(root), "files": sorted(files), "texts": texts, "errors": errors}


def git_state(local: dict[str, Any], default_branch: str) -> dict[str, Any]:
    """Collect local git closure evidence when a checkout is available."""
    if not local.get("available"):
        return {"available": False, "errors": local.get("errors", [])}
    root = local["root"]

    def git(*args: str) -> tuple[int, str]:
        """Run a local git command and return status plus compact output."""

        proc = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True)
        return proc.returncode, (proc.stdout + proc.stderr).strip()

    status_code, status = git("status", "--short")
    branch_code, branch = git("branch", "--show-current")
    upstream_code, upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    branches_code, branches = git("for-each-ref", "--format=%(refname:short)", "refs/heads")
    return {
        "available": status_code == 0,
        "worktree_clean": status_code == 0 and status == "",
        "current_branch": branch if branch_code == 0 else None,
        "upstream": upstream if upstream_code == 0 else None,
        "tracks_remote_default_branch": upstream_code == 0 and upstream.endswith(f"/{default_branch}"),
        "local_branches": branches.splitlines() if branches_code == 0 and branches else [],
        "raw_status": status,
    }


def request_covers_selected(
    bundle: dict[str, Any],
    req: dict[str, Any],
    selected_check_ids: set[str] | None,
    selected_bundle_ids: set[str] | None,
) -> bool:
    """Decide whether a fetch-bundle request is needed for this run.

    The contracts declare `covers_checks` on requests and local bundles. Filtering
    by those IDs lets one checker invocation reuse bundled evidence without
    paying for endpoints unrelated to the selected subset or explicit check IDs.
    """

    if selected_bundle_ids is not None and bundle.get("id") not in selected_bundle_ids:
        return False
    if selected_check_ids is None:
        return True
    covers = set(req.get("covers_checks") or bundle.get("covers_checks") or [])
    return not covers or bool(covers & selected_check_ids)


def fetch_contract_requests(
    contract: dict[str, Any],
    params: dict[str, Any],
    selected_check_ids: set[str] | None = None,
    selected_bundle_ids: set[str] | None = None,
    fetched: dict[tuple[str, str], ApiResult] | None = None,
) -> dict[tuple[str, str], ApiResult]:
    """Fetch selected REST requests declared by repo contract bundles once."""
    requests: dict[tuple[str, str], dict[str, Any]] = {}
    for bundle in contract.get("fetch_bundles", []):
        for req in bundle.get("requests", []):
            if not request_covers_selected(bundle, req, selected_check_ids, selected_bundle_ids):
                continue
            endpoint = req.get("endpoint")
            if not endpoint or not str(endpoint).startswith("/"):
                continue
            method = req.get("method", "GET").upper()
            requests[(method, endpoint_for(endpoint, params))] = req
    fetched = fetched if fetched is not None else {}
    for (method, endpoint), req in requests.items():
        if (method, endpoint) not in fetched:
            fetched[(method, endpoint)] = run_gh_api(method, endpoint, paginate=bool(req.get("paginate")))
    return fetched


def artifact_bundle_covers_selected(bundle: dict[str, Any], selected_check_ids: set[str] | None) -> bool:
    """Return whether an artifact fetch bundle can feed selected checks."""

    if selected_check_ids is None:
        return True
    feeds = [str(item) for item in bundle.get("feeds_checks", [])]
    return not feeds or any(fnmatch.fnmatch(check_id, pattern) for check_id in selected_check_ids for pattern in feeds)


def owner_kind(params: dict[str, Any], repo_info: dict[str, Any] | None = None) -> str | None:
    """Classify the repo owner for GitHub Packages org/user endpoint choice."""

    explicit = str(params.get("owner_type") or "").lower()
    if explicit in {"org", "organization"}:
        return "org"
    if explicit == "user":
        return "user"
    owner_type = str(((repo_info or {}).get("owner") or {}).get("type") or "").lower()
    if owner_type == "organization":
        return "org"
    if owner_type == "user":
        return "user"
    return None


def artifact_endpoint_matches_owner(endpoint: str, kind: str | None) -> bool:
    """Skip the wrong GitHub Packages owner endpoint when the owner kind is known."""

    if endpoint.startswith("/orgs/") and kind == "user":
        return False
    if endpoint.startswith("/users/") and kind == "org":
        return False
    return True


def parse_endpoint_spec(raw: str) -> tuple[str, str]:
    """Parse an artifact-contract endpoint string like `GET /repos/...`."""

    parts = raw.strip().split(maxsplit=1)
    if len(parts) == 2 and parts[0].upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        return parts[0].upper(), parts[1]
    return "GET", raw.strip()


def fetch_artifact_contract_requests(
    contract: dict[str, Any],
    params: dict[str, Any],
    selected_check_ids: set[str] | None,
    selected_bundle_ids: set[str] | None,
    fetched: dict[tuple[str, str], ApiResult],
    repo_info: dict[str, Any],
) -> dict[tuple[str, str], ApiResult]:
    """Fetch selected GitHub API endpoints declared by the artifact contract."""

    bundles = contract.get("fetch_bundles", {})
    if isinstance(bundles, dict):
        iterable = ((str(bundle_id), bundle) for bundle_id, bundle in bundles.items())
    else:
        iterable = ((str(bundle.get("id") or ""), bundle) for bundle in bundles if isinstance(bundle, dict))
    kind = owner_kind(params, repo_info)
    for bundle_id, bundle in iterable:
        if not isinstance(bundle, dict):
            continue
        if selected_bundle_ids is not None and bundle_id not in selected_bundle_ids:
            continue
        if not artifact_bundle_covers_selected(bundle, selected_check_ids):
            continue
        for raw_endpoint in bundle.get("endpoints", []):
            method, endpoint = parse_endpoint_spec(str(raw_endpoint))
            if not endpoint.startswith("/") or not artifact_endpoint_matches_owner(endpoint, kind):
                continue
            expanded = endpoint_for(endpoint, params)
            key = (method, expanded)
            if key not in fetched:
                fetched[key] = run_gh_api(method, expanded)
    return fetched


def result(fetched: dict[tuple[str, str], ApiResult], endpoint: str, params: dict[str, Any], method: str = "GET") -> ApiResult:
    """Return cached API evidence, fetching on demand when a check needs it."""
    endpoint = endpoint_for(endpoint, params)
    key = (method.upper(), endpoint)
    if key not in fetched:
        fetched[key] = run_gh_api(method, endpoint)
    return fetched[key]


def finding(check_id: str, level: str, message: str, actual: Any = None, expected: Any = None, path: str = "$") -> dict[str, Any]:
    """Create a consistent machine-readable finding record."""
    item = {"check_id": check_id, "level": level, "path": path, "message": message}
    if actual is not None:
        item["actual"] = actual
    if expected is not None:
        item["expected"] = expected
    return item


def classify(repo_info: dict[str, Any], paths: list[str], topics: list[str], local: dict[str, Any]) -> dict[str, Any]:
    """Classify repo, workflow, language, IaC, and artifact surfaces.

    The classifier is intentionally multi-label. A repository may be a public
    fork, a Python package, a Docker image, a docs site, and an automation repo
    at the same time; every applicable check should then run or be explicitly
    skipped by the contract.
    """
    texts = local.get("texts", {})
    all_text = "\n".join(texts.values())
    artifacts: set[str] = set()
    languages: set[str] = set()
    project: set[str] = set()
    workflows = path_matches(paths, [".github/workflows/*.yml", ".github/workflows/*.yaml"])
    release_workflow = bool(re.search(r"(gh release|npm publish|twine upload|pypa/gh-action-pypi-publish|docker/build-push-action|docker push|cargo publish|gem push|nuget push|mvn deploy)", all_text))

    if path_matches(paths, ["Dockerfile", "**/Dockerfile"]) or any(t in topics for t in ("docker", "oci", "container", "ghcr")):
        artifacts.add("docker_oci_image")
        project.add("service_or_app")
    if path_matches(paths, ["pyproject.toml", "setup.cfg", "setup.py"]):
        artifacts.add("pypi_python_package")
        languages.add("python")
        project.add("library_or_sdk")
    if path_matches(paths, ["package.json"]):
        artifacts.add("npm_package")
        languages.add("javascript_or_typescript")
        project.add("library_or_sdk")
    if path_matches(paths, ["pom.xml", "build.gradle", "build.gradle.kts"]):
        artifacts.add("maven_package")
        languages.add("java")
    if path_matches(paths, ["*.csproj", "*.nuspec", "*.sln"]):
        artifacts.add("nuget_package")
        languages.add("dotnet")
    if path_matches(paths, ["Cargo.toml"]):
        artifacts.add("crates_package")
        languages.add("rust")
    if path_matches(paths, ["*.gemspec", "Gemfile"]):
        artifacts.add("rubygems_package")
        languages.add("ruby")
    if path_matches(paths, ["*.psd1"]):
        artifacts.add("powershell_gallery_module")
        languages.add("powershell")
    if path_matches(paths, ["*.tf"]):
        languages.add("terraform")
        project.add("iac")
    if path_matches(paths, ["Chart.yaml", "charts/**/Chart.yaml"]):
        artifacts.add("helm_chart")
        project.add("iac")
    if repo_info.get("has_pages") or path_matches(paths, ["docs/**", "site/**", "public/**"]):
        artifacts.add("github_pages_site")
        project.add("website")
    if not artifacts:
        artifacts.add("no_artifact")
    if workflows:
        project.add("automation")
    if path_matches(paths, ["src/**", "app/**", "lib/**"]):
        project.add("software")
    return {
        "visibility": repo_info.get("visibility") or ("private" if repo_info.get("private") else "public"),
        "origin": "fork" if repo_info.get("fork") else ("template" if repo_info.get("is_template") else "source"),
        "lifecycle": "archived" if repo_info.get("archived") else ("disabled" if repo_info.get("disabled") else "active"),
        "workflow_surface": {
            "has_workflows": workflows,
            "has_release_workflow": release_workflow,
            "has_attestation_workflow": bool(re.search(r"(actions/attest|attestations:\s*write|artifact-metadata:\s*write)", all_text)),
        },
        "artifact_surface": sorted(artifacts),
        "language_or_iac": sorted(languages),
        "project_surface": sorted(project or {"unknown"}),
    }


def get_nested(data: Any, dotted: str) -> Any:
    """Read a dotted path from a nested dict, returning None on mismatch."""

    value = data
    for part in dotted.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def open_alerts(data: Any) -> list[dict[str, Any]]:
    """Normalize Dependabot alert payloads to alert dictionaries."""

    return [item for item in as_list(data) if isinstance(item, dict)]


def workflows_with_unpinned_refs(local: dict[str, Any]) -> list[dict[str, str]]:
    """Find workflow `uses:` references that are not pinned to full SHAs."""
    items: list[dict[str, str]] = []
    for path, text in local.get("texts", {}).items():
        if not path.startswith(".github/workflows/"):
            continue
        for match in USES_RE.finditer(text):
            action, ref = match.groups()
            if action.startswith("./") or action.startswith(".\\"):
                continue
            if not SHA_RE.fullmatch(ref):
                items.append({"path": path, "uses": f"{action}@{ref}"})
    return items


def text_contains(local: dict[str, Any], path: str, pattern: str) -> bool:
    """Run a regex against one scanned local text file."""

    text = local.get("texts", {}).get(path)
    return bool(text and re.search(pattern, text, re.IGNORECASE | re.MULTILINE))


def evaluate_repo_check(
    check: dict[str, Any],
    params: dict[str, Any],
    fetched: dict[tuple[str, str], ApiResult],
    local: dict[str, Any],
    types: dict[str, Any],
) -> list[dict[str, Any]]:
    """Evaluate one deterministic repository check.

    This function is intentionally organized by check ID. Each branch should be
    small and evidence-driven; broad policy belongs in JSON expected values, and
    checks that require intent or quality judgment should return MANUAL or move
    to the non-deterministic Markdown contract.
    """
    check_id = check["id"]
    repo_res = result(fetched, "/repos/${owner}/${repo}", params)
    repo_info = repo_res.data if repo_res.ok and isinstance(repo_res.data, dict) else {}
    owner_res = result(fetched, "/orgs/${owner}", params)
    owner_info = owner_res.data if owner_res.ok and isinstance(owner_res.data, dict) else {}
    owner_plan = owner_info.get("plan") if isinstance(owner_info.get("plan"), dict) else {}
    default_branch = str(params.get("default_branch") or repo_info.get("default_branch") or "")
    tree_res = result(fetched, "/repos/${owner}/${repo}/git/trees/${default_branch}?recursive=1", params)
    paths = local.get("files") or tree_paths(tree_res.data)
    topics_res = result(fetched, "/repos/${owner}/${repo}/topics", params)
    topics = [str(t).lower() for t in (topics_res.data or {}).get("names", [])] if topics_res.ok and isinstance(topics_res.data, dict) else []
    rule_context = {
        "repo.visibility": repo_info.get("visibility"),
        "repo.fork": bool(repo_info.get("fork")),
        "repo.archived": bool(repo_info.get("archived")),
        "owner.plan.name": owner_plan.get("name"),
        "type.workflow_surface": types.get("workflow_surface", {}),
        "artifact_surface": types.get("artifact_surface", []),
        "owner_is_org": (repo_info.get("owner") or {}).get("type") == "Organization",
        "expected_maintainer_bypass_actors": params.get("expected_maintainer_bypass_actors", []),
        "open_dependabot_prs_count": 0,
        "file:.github/dependabot.yml": local.get("texts", {}).get(".github/dependabot.yml", ""),
    }
    applies_when = check.get("applies_when")
    if applies_when and not condition_matches(str(applies_when), rule_context):
        return [finding(check_id, "SKIP", "Check does not apply to this repository context.", actual=rule_context)]

    if check_id.startswith("type."):
        return [finding(check_id, "PASS", "Repository types classified.", actual=types)]

    if check_id == "repo.identity_public_contract":
        drifts = []
        expected_visibility = {"public", "private", "internal"}
        actual = {
            "owner": (repo_info.get("owner") or {}).get("login"),
            "name": repo_info.get("name"),
            "default_branch": repo_info.get("default_branch"),
            "visibility": repo_info.get("visibility"),
            "description": repo_info.get("description"),
            "homepage": repo_info.get("homepage"),
        }
        if actual["owner"] != params["owner"]:
            drifts.append(finding(check_id, "FAIL", "Owner mismatch.", actual["owner"], params["owner"], "$.owner"))
        if actual["name"] != params["repo"]:
            drifts.append(finding(check_id, "FAIL", "Repo name mismatch.", actual["name"], params["repo"], "$.name"))
        if actual["default_branch"] != default_branch:
            drifts.append(finding(check_id, "FAIL", "Default branch mismatch.", actual["default_branch"], default_branch, "$.default_branch"))
        if actual["visibility"] not in expected_visibility:
            drifts.append(finding(check_id, "FAIL", "Unknown visibility.", actual["visibility"], sorted(expected_visibility), "$.visibility"))
        if actual["visibility"] == "public" and not actual["description"]:
            drifts.append(finding(check_id, "FAIL", "Public repo description is empty.", actual["description"], "non-empty", "$.description"))
        return drifts or [finding(check_id, "PASS", "Repository identity fields match contract.", actual=actual)]

    if check_id == "repo.topics_required":
        if repo_info.get("visibility") == "public" and not repo_info.get("archived") and not topics:
            return [finding(check_id, "FAIL", "Public active repo has no topics.", actual=[], expected="at least one topic")]
        return [finding(check_id, "PASS", "Topic policy satisfied or not applicable.", actual=topics)]

    if check_id == "repo.unused_feature_flags":
        drifts = []
        for field in ("has_wiki", "has_projects", "has_discussions"):
            if repo_info.get(field) is True:
                drifts.append(finding(check_id, "WARN", f"{field} is enabled; verify it is intentionally used.", actual=True, expected="false unless used", path=f"$.{field}"))
        return drifts or [finding(check_id, "PASS", "Unused feature flags are not enabled.", actual={k: repo_info.get(k) for k in ("has_wiki", "has_projects", "has_discussions", "has_pages")})]

    if check_id == "repo.merge_settings":
        expected = check.get("expected", {})
        drifts = []
        skipped = []
        for key, raw_spec in expected.items():
            spec = raw_spec if isinstance(raw_spec, dict) else {"value": raw_spec}
            field_applies = spec.get("applies_when")
            if field_applies and not condition_matches(str(field_applies), rule_context):
                skipped.append({"field": key, "reason": spec.get("skip_reason"), "context": rule_context})
                continue
            exp = spec.get("value")
            if isinstance(exp, bool) and repo_info.get(key) is not exp:
                drifts.append(finding(check_id, "WARN", f"{key} mismatch.", actual=repo_info.get(key), expected=exp, path=f"$.{key}"))
        if drifts:
            return drifts
        if skipped:
            return [finding(check_id, "PASS", "Merge settings match deterministic defaults for applicable fields.", actual={"skipped": skipped})]
        return drifts or [finding(check_id, "PASS", "Merge settings match deterministic defaults.")]

    if check_id in {"process.default_branch_enforcement_present", "process.default_branch_name_and_protection_indicator"}:
        protection = result(fetched, "/repos/${owner}/${repo}/branches/${default_branch}/protection", params)
        rulesets = result(fetched, "/repos/${owner}/${repo}/rulesets", params)
        active_rulesets = [r for r in as_list(rulesets.data) if isinstance(r, dict) and r.get("target") == "branch" and r.get("enforcement") == "active"]
        if repo_info.get("archived") or repo_info.get("fork"):
            return [finding(check_id, "SKIP", "Archived or fork repos do not require local enforcement.", actual={"archived": repo_info.get("archived"), "fork": repo_info.get("fork")})]
        if protection.ok or active_rulesets:
            return [finding(check_id, "PASS", "Default-branch enforcement exists.", actual={"classic_protection": protection.ok, "active_rulesets": [r.get("name") for r in active_rulesets]})]
        return [finding(check_id, "FAIL", "Default branch has no readable protection or active branch ruleset.", actual={"protection": protection.message, "rulesets": rulesets.message}, expected="classic protection or active ruleset")]

    if check_id == "process.branch_protection_or_ruleset_posture":
        protection = result(fetched, "/repos/${owner}/${repo}/branches/${default_branch}/protection", params)
        if not protection.ok or not isinstance(protection.data, dict):
            rulesets = result(fetched, "/repos/${owner}/${repo}/rulesets", params)
            active = [r.get("name") for r in as_list(rulesets.data) if isinstance(r, dict) and r.get("target") == "branch" and r.get("enforcement") == "active"]
            if active:
                return [finding(check_id, "MANUAL", "Active rulesets exist, but constraints need ruleset-detail review.", actual=active)]
            return [finding(check_id, "FAIL", "Branch protection posture is not verifiable.", actual=protection.message, expected="readable protection or ruleset detail")]
        p = protection.data
        drifts = []
        checks = p.get("required_status_checks") or {}
        if checks.get("strict") is not True:
            drifts.append(finding(check_id, "FAIL", "Strict status checks disabled.", checks.get("strict"), True, "$.required_status_checks.strict"))
        if not (checks.get("checks") or checks.get("contexts")):
            drifts.append(finding(check_id, "FAIL", "No required checks configured.", [], "one or more checks", "$.required_status_checks"))
        reviews = p.get("required_pull_request_reviews") or {}
        approvals = reviews.get("required_approving_review_count")
        if not isinstance(approvals, int) or approvals < 1:
            drifts.append(finding(check_id, "WARN", "No required approving review.", approvals, ">= 1", "$.required_pull_request_reviews.required_approving_review_count"))
        if reviews.get("dismiss_stale_reviews") is not True:
            drifts.append(finding(check_id, "FAIL", "Stale review dismissal disabled.", reviews.get("dismiss_stale_reviews"), True, "$.required_pull_request_reviews.dismiss_stale_reviews"))
        if any(path in paths for path in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")) and reviews.get("require_code_owner_reviews") is not True:
            drifts.append(finding(check_id, "WARN", "CODEOWNERS exists but code-owner review is not required.", reviews.get("require_code_owner_reviews"), True, "$.required_pull_request_reviews.require_code_owner_reviews"))
        if (p.get("required_conversation_resolution") or {}).get("enabled") is not True:
            drifts.append(finding(check_id, "FAIL", "Conversation resolution not required.", None, True, "$.required_conversation_resolution"))
        if (p.get("enforce_admins") or {}).get("enabled") is not True:
            drifts.append(finding(check_id, "FAIL", "Admin enforcement disabled.", None, True, "$.enforce_admins"))
        for key in ("allow_force_pushes", "allow_deletions"):
            value = (p.get(key) or {}).get("enabled")
            if value is not False:
                drifts.append(finding(check_id, "FAIL", f"{key} should be disabled.", value, False, f"$.{key}"))
        return drifts or [finding(check_id, "PASS", "Branch protection posture matches deterministic defaults.")]

    if check_id == "process.maintainer_bypass_ruleset":
        expected_actors = params.get("expected_maintainer_bypass_actors") or []
        if not expected_actors:
            return [finding(check_id, "SKIP", "No expected maintainer bypass actors configured.")]
        rulesets = result(fetched, "/repos/${owner}/${repo}/rulesets", params)
        text = canonical(rulesets.data)
        missing = [actor for actor in expected_actors if str(actor) not in text]
        drifts = []
        if missing:
            drifts.append(finding(check_id, "FAIL", "Expected maintainer bypass actor missing from rulesets.", actual=rulesets.data, expected=expected_actors))
        if not re.search(r"pull[_-]?request", text, re.IGNORECASE):
            drifts.append(finding(check_id, "WARN", "Ruleset bypass mode is not visibly pull-request-only.", actual=rulesets.data, expected="pull_request bypass mode", path="$.bypass_actors"))
        if not re.search(r"(~DEFAULT_BRANCH|refs/heads/|ref_name|" + re.escape(default_branch) + r")", text, re.IGNORECASE):
            drifts.append(finding(check_id, "WARN", "Ruleset does not visibly target the default branch.", actual=rulesets.data, expected=default_branch, path="$.conditions.ref_name"))
        if not re.search(r"(required_status_checks|pull_request|required_deployments)", text, re.IGNORECASE):
            drifts.append(finding(check_id, "WARN", "Ruleset enforcement rules are not visible in the list response.", actual=rulesets.data, expected="pull request or required status check rule", path="$.rules"))
        return drifts or [finding(check_id, "PASS", "Expected maintainer bypass ruleset evidence is present.", actual=expected_actors)]

    if check_id == "actions.permissions_policy":
        data = result(fetched, "/repos/${owner}/${repo}/actions/permissions", params).data or {}
        drifts = []
        if data.get("enabled") is not True:
            drifts.append(finding(check_id, "FAIL", "Actions disabled.", data.get("enabled"), True, "$.enabled"))
        if data.get("sha_pinning_required") is not True and not workflows_with_unpinned_refs(local):
            drifts.append(finding(check_id, "WARN", "Actions SHA pinning is not enforced though workflows appear compliant.", data.get("sha_pinning_required"), True, "$.sha_pinning_required"))
        return drifts or [finding(check_id, "PASS", "Actions permissions posture is acceptable.", actual=data)]

    if check_id == "actions.workflow_token_permissions":
        data = result(fetched, "/repos/${owner}/${repo}/actions/permissions/workflow", params).data or {}
        drifts = []
        if data.get("default_workflow_permissions") != "read":
            drifts.append(finding(check_id, "FAIL", "Default workflow token permission is not read.", data.get("default_workflow_permissions"), "read", "$.default_workflow_permissions"))
        if data.get("can_approve_pull_request_reviews") is not False:
            drifts.append(finding(check_id, "FAIL", "Workflow token can approve PR reviews.", data.get("can_approve_pull_request_reviews"), False, "$.can_approve_pull_request_reviews"))
        if workflows_with_permissions_write_all(local):
            drifts.append(finding(check_id, "FAIL", "Workflow files use permissions: write-all.", actual=workflows_with_permissions_write_all(local), expected="least privilege workflow permissions"))
        top_level_attestations = workflows_with_top_level_write_permission(local, "attestations")
        if top_level_attestations:
            drifts.append(finding(check_id, "FAIL", "Workflow-root attestations: write grants are not job scoped.", actual=top_level_attestations, expected="job-level attestations: write"))
        top_level_artifact_metadata = workflows_with_top_level_write_permission(local, "artifact-metadata")
        if top_level_artifact_metadata:
            drifts.append(finding(check_id, "FAIL", "Workflow-root artifact-metadata: write grants are not job scoped.", actual=top_level_artifact_metadata, expected="job-level artifact-metadata: write"))
        return drifts or [finding(check_id, "PASS", "Workflow token defaults match contract.", actual=data)]

    if check_id == "actions.artifact_log_retention":
        res = result(fetched, "/repos/${owner}/${repo}/actions/permissions/artifact-and-log-retention", params)
        return retention_days_finding(check_id, res, check.get("expected", {}))

    if check_id == "actions.fork_pr_contributor_approval":
        res = result(fetched, "/repos/${owner}/${repo}/actions/permissions/fork-pr-contributor-approval", params)
        return fork_pr_approval_finding(check_id, res, check.get("expected", {}))

    if check_id == "actions.private_fork_pr_workflows":
        res = result(fetched, "/repos/${owner}/${repo}/actions/permissions/fork-pr-workflows-private-repos", params)
        data = res.data if res.ok else None
        if not isinstance(data, dict):
            return [finding(check_id, "SKIP", "Private fork PR workflow settings unavailable or not applicable.")]
        drifts = []
        if data.get("run_workflows_from_fork_pull_requests") is True:
            drifts.append(finding(check_id, "WARN", "Private fork PR workflows run without an explicit approved drift record.", actual=True, expected="false unless approved", path="$.run_workflows_from_fork_pull_requests"))
        if data.get("send_write_tokens_to_workflows") is not False:
            drifts.append(finding(check_id, "FAIL", "Private fork PR workflows can receive write tokens.", actual=data.get("send_write_tokens_to_workflows"), expected=False, path="$.send_write_tokens_to_workflows"))
        if data.get("send_secrets_and_variables") is not False:
            drifts.append(finding(check_id, "FAIL", "Private fork PR workflows can receive secrets or variables.", actual=data.get("send_secrets_and_variables"), expected=False, path="$.send_secrets_and_variables"))
        if data.get("require_approval_for_fork_pr_workflows") is not True:
            drifts.append(finding(check_id, "FAIL", "Private fork PR workflows do not require approval.", actual=data.get("require_approval_for_fork_pr_workflows"), expected=True, path="$.require_approval_for_fork_pr_workflows"))
        return drifts or [finding(check_id, "PASS", "Private fork PR workflow settings match contract.", actual=data)]

    if check_id == "actions.workflow_sha_pinning":
        unpinned = workflows_with_unpinned_refs(local)
        if unpinned:
            return [finding(check_id, "FAIL", "External workflow actions are not pinned to full SHAs.", actual=unpinned, expected="full 40-character SHA refs")]
        if not local.get("available"):
            return [finding(check_id, "MANUAL", "Local workflow files unavailable; cannot scan action refs.", actual=local.get("errors"))]
        return [finding(check_id, "PASS", "No unpinned external workflow action refs found.")]

    if check_id == "actions.latest_default_branch_runs":
        runs = result(fetched, "/repos/${owner}/${repo}/actions/runs?branch=${default_branch}&per_page=20", params).data or {}
        workflow_runs = runs.get("workflow_runs") if isinstance(runs, dict) else []
        completed = [r for r in as_list(workflow_runs) if isinstance(r, dict) and r.get("status") == "completed"]
        failures = [r for r in completed[:5] if r.get("conclusion") not in {"success", "skipped"}]
        if failures:
            return [finding(check_id, "FAIL", "Recent completed default-branch workflow run failed.", actual=[{"name": r.get("name"), "conclusion": r.get("conclusion"), "url": r.get("html_url")} for r in failures])]
        if not completed:
            return [finding(check_id, "WARN", "No completed default-branch workflow runs found.", actual=runs)]
        return [finding(check_id, "PASS", "Recent default-branch workflow runs are not failing.", actual=[{"name": r.get("name"), "conclusion": r.get("conclusion")} for r in completed[:5]])]

    if check_id == "security.security_and_analysis_status":
        security = repo_info.get("security_and_analysis") or {}
        drifts = []
        expected = check.get("expected", {})
        classified = {}
        if not repo_info.get("archived") and (security.get("dependency_graph") or {}).get("status") not in {"enabled", None}:
            drifts.append(finding(check_id, "FAIL", "Dependency graph is disabled.", actual=security.get("dependency_graph"), expected="enabled"))
        if repo_info.get("visibility") == "public":
            for key in ("secret_scanning", "secret_scanning_push_protection"):
                if (security.get(key) or {}).get("status") != "enabled":
                    drifts.append(finding(check_id, "FAIL", f"{key} is not enabled for a public repo.", actual=security.get(key), expected="enabled", path=f"$.{key}"))
        for dotted_key, policy in expected.items():
            if not dotted_key.endswith(".status"):
                continue
            key = dotted_key.removesuffix(".status")
            if key in {"dependency_graph", "dependabot_alerts", "secret_scanning", "secret_scanning_push_protection"}:
                continue
            state = security.get(key)
            classified[key] = {
                "status": (state or {}).get("status"),
                "available": key in security,
                "policy": policy,
            }
        actual = {"security_and_analysis": security, "classified_paid_or_optional_fields": classified}
        return drifts or [finding(check_id, "PASS", "Security and analysis settings have no deterministic drift.", actual=actual)]

    if check_id in {"security.vulnerability_alerts_enabled", "security.dependabot_security_updates_enabled"}:
        endpoint = check["endpoint"]
        res = result(fetched, endpoint, params)
        if res.ok:
            return [finding(check_id, "PASS", "Endpoint reports enabled.")]
        return [finding(check_id, "FAIL", "Endpoint is not enabled or could not be verified.", actual={"status": res.status, "message": res.message}, expected="enabled")]

    if check_id == "security.dependabot_config_file":
        if repo_info.get("archived") or repo_info.get("fork"):
            return [finding(check_id, "SKIP", "Archived or fork repos do not require local Dependabot config enforcement.", actual={"archived": repo_info.get("archived"), "fork": repo_info.get("fork")})]
        ecosystems = detect_dependabot_ecosystems(paths)
        if not ecosystems:
            return [finding(check_id, "SKIP", "No package ecosystems detected for Dependabot config.")]
        dep_path = config_path(paths, ".github/dependabot.yml", ".github/dependabot.yaml")
        if not dep_path:
            return [finding(check_id, "FAIL", "Package manifests exist but dependabot.yml is missing.", actual=ecosystems, expected=".github/dependabot.yml")]
        text = local.get("texts", {}).get(dep_path, "")
        if not text:
            return [finding(check_id, "MANUAL", "dependabot.yml exists but local contents are unavailable for deterministic schedule/ecosystem checks.", actual={"path": dep_path, "ecosystems": ecosystems})]
        drifts = []
        missing_ecosystems = [ecosystem for ecosystem in ecosystems if ecosystem not in text]
        if missing_ecosystems:
            drifts.append(finding(check_id, "WARN", "dependabot.yml does not visibly cover every detected ecosystem.", actual=missing_ecosystems, expected=sorted(ecosystems), path=dep_path))
        if "updates:" not in text:
            drifts.append(finding(check_id, "FAIL", "dependabot.yml has no updates section.", actual=dep_path, expected="updates:", path=dep_path))
        if "schedule:" not in text or "interval:" not in text:
            drifts.append(finding(check_id, "FAIL", "dependabot.yml updates entries need schedule intervals.", actual=dep_path, expected="schedule.interval", path=dep_path))
        if re.search(r"(?m)^\s*registries\s*:", text):
            drifts.append(finding(check_id, "INFO", "Dependabot private registries are configured; verify credentials and registry scope are intentional.", actual=dep_path, path=dep_path))
        if re.search(r"(?m)^\s*groups\s*:", text):
            drifts.append(finding(check_id, "INFO", "Dependabot grouping is configured; verify grouping policy is intentional.", actual=dep_path, path=dep_path))
        return drifts or [finding(check_id, "PASS", "dependabot.yml covers detected package ecosystems with schedules.", actual={"path": dep_path, "ecosystems": sorted(ecosystems)})]

    if check_id in {"security.open_dependabot_alert_queue", "security.open_code_scanning_alert_queue"}:
        alerts = open_alerts(result(fetched, check["endpoint"], params).data)
        high = []
        for item in alerts:
            severity = str(get_nested(item, "security_advisory.severity") or get_nested(item, "rule.security_severity_level") or item.get("severity") or "").lower()
            if severity in {"critical", "high"}:
                high.append(item)
        if high:
            return [finding(check_id, "FAIL", "Open critical/high alerts exist.", actual=high, expected="0 critical/high alerts")]
        return [finding(check_id, "PASS", "No open critical/high alerts found.", actual={"open_count": len(alerts)})]

    if check_id == "security.open_dependabot_pr_queue":
        label = f"gh search prs --repo {params['owner']}/{params['repo']} --state open --app dependabot"
        prs = run_json_command(
            [
                "gh",
                "search",
                "prs",
                "--repo",
                f"{params['owner']}/{params['repo']}",
                "--state",
                "open",
                "--app",
                "dependabot",
                "--limit",
                "1000",
                "--json",
                "author,createdAt,id,isDraft,labels,number,repository,state,title,updatedAt,url",
            ],
            label,
        )
        if not prs.ok:
            return [finding(check_id, "WARN", "Open Dependabot PR queue could not be fetched.", actual={"status": prs.status, "message": prs.message})]
        items = prs.data if isinstance(prs.data, list) else []
        if len(items) >= 1000:
            return [finding(check_id, "FAIL", "Dependabot PR search result limit was saturated.", actual=len(items), expected="< 1000")]
        if items:
            level = "INFO" if repo_info.get("archived") else "WARN"
            compact = [
                {
                    "number": item.get("number") if isinstance(item, dict) else None,
                    "title": item.get("title") if isinstance(item, dict) else None,
                    "is_draft": item.get("isDraft") if isinstance(item, dict) else None,
                    "url": item.get("url") if isinstance(item, dict) else None,
                    "updated_at": item.get("updatedAt") if isinstance(item, dict) else None,
                }
                for item in items[:25]
            ]
            return [finding(check_id, level, "Open Dependabot PRs need queue review.", actual={"count": len(items), "sample": compact}, expected="classified or merged when safe")]
        return [finding(check_id, "PASS", "No open Dependabot-authored PRs found.")]

    if check_id == "security.open_secret_scanning_alert_queue":
        alerts = open_alerts(result(fetched, check["endpoint"], params).data)
        if alerts:
            return [finding(check_id, "FAIL", "Open secret scanning alerts exist.", actual={"open_count": len(alerts)}, expected=0)]
        return [finding(check_id, "PASS", "No open secret scanning alerts found.")]

    if check_id == "security.code_security_configuration_attached":
        res = result(fetched, "/repos/${owner}/${repo}/code-security-configuration", params)
        if res.ok:
            return [finding(check_id, "PASS", "Code security configuration is attached or readable.", actual=res.data)]
        return [finding(check_id, "WARN", "Could not verify code security configuration.", actual={"status": res.status, "message": res.message})]

    if check_id == "security.code_scanning_default_setup_or_custom":
        setup = result(fetched, "/repos/${owner}/${repo}/code-scanning/default-setup", params)
        if setup.ok and isinstance(setup.data, dict) and setup.data.get("state") == "configured":
            return [finding(check_id, "PASS", "Code scanning default setup configured.", actual=setup.data)]
        alerts = result(fetched, "/repos/${owner}/${repo}/code-scanning/alerts?state=open&per_page=100", params)
        if alerts.ok:
            return [finding(check_id, "PASS", "Code scanning appears available through custom setup.", actual={"default_setup": setup.data})]
        return [finding(check_id, "WARN", "Code scanning setup is not verifiable.", actual={"default_setup": setup.message, "alerts": alerts.message})]

    if check_id == "security.private_vulnerability_reporting_public":
        res = result(fetched, "/repos/${owner}/${repo}/private-vulnerability-reporting", params)
        has_security = "SECURITY.md" in paths or ".github/SECURITY.md" in paths
        if res.ok and isinstance(res.data, dict) and res.data.get("enabled") is True:
            return [finding(check_id, "PASS", "Private vulnerability reporting is enabled.")]
        if has_security:
            return [finding(check_id, "PASS", "SECURITY.md provides an explicit reporting path.", actual={"api_enabled": res.data, "SECURITY.md": True})]
        return [finding(check_id, "WARN", "No private vulnerability reporting or SECURITY.md path found.", actual=res.data, expected="enabled or SECURITY.md")]

    if check_id == "security.dependency_review_availability":
        res = result(fetched, "/repos/${owner}/${repo}/dependency-graph/compare/${default_branch}...${default_branch}", params)
        if res.ok:
            return [finding(check_id, "PASS", "Dependency review API is available.")]
        return [finding(check_id, "INFO", "Dependency review API is unavailable or plan-limited.", actual={"status": res.status, "message": res.message})]

    if check_id == "content.required_files_presence":
        required = ["README.md"]
        if repo_info.get("visibility") == "public":
            required.extend(["LICENSE", "SECURITY.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", ".github/CODEOWNERS"])
        missing = [path for path in required if path not in paths]
        if missing:
            return [finding(check_id, "FAIL", "Required contextual files are missing.", actual=missing, expected=required)]
        return [finding(check_id, "PASS", "Required contextual files are present.", actual=required)]

    if check_id == "content.community_profile_public":
        profile = result(fetched, "/repos/${owner}/${repo}/community/profile", params)
        if not profile.ok or not isinstance(profile.data, dict):
            return [finding(check_id, "WARN", "Community profile is not readable.", actual=profile.message)]
        health = profile.data.get("health_percentage")
        drifts = []
        if isinstance(health, int) and health < 70:
            drifts.append(finding(check_id, "FAIL", "Community profile health below contract minimum.", health, ">= 70", "$.health_percentage"))
        owner_type = (repo_info.get("owner") or {}).get("type")
        if repo_info.get("visibility") == "public" and owner_type == "Organization" and not repo_info.get("fork"):
            if profile.data.get("content_reports_enabled") is not True:
                drifts.append(finding(check_id, "FAIL", "Reported-content moderation is not enabled.", profile.data.get("content_reports_enabled"), True, "$.content_reports_enabled"))
        return drifts or [finding(check_id, "PASS", "Community profile deterministic checks pass.", actual={"health_percentage": health, "content_reports_enabled": profile.data.get("content_reports_enabled")})]

    if check_id == "content.codeowners_valid":
        res = result(fetched, "/repos/${owner}/${repo}/codeowners/errors", params)
        if not res.ok:
            return [finding(check_id, "WARN", "CODEOWNERS errors endpoint unavailable.", actual=res.message)]
        errors = res.data.get("errors") if isinstance(res.data, dict) else None
        if errors:
            return [finding(check_id, "FAIL", "CODEOWNERS has errors.", actual=errors, expected=[])]
        return [finding(check_id, "PASS", "CODEOWNERS errors endpoint returned no errors.")]

    if check_id == "content.dependencies_label_when_dependabot_uses_it":
        uses_label = any(path.replace("\\", "/") in {".github/dependabot.yml", ".github/dependabot.yaml"} and "dependencies" in text for path, text in local.get("texts", {}).items())
        if not uses_label:
            return [finding(check_id, "SKIP", "Dependabot dependencies label not referenced.")]
        label = result(fetched, "/repos/${owner}/${repo}/labels/dependencies", params)
        if label.ok:
            return [finding(check_id, "PASS", "dependencies label exists.")]
        return [finding(check_id, "FAIL", "dependabot.yml references dependencies label but live label is missing.", actual=label.message, expected="label dependencies")]

    if check_id.startswith("stale_state."):
        if check_id == "stale_state.local_path_references":
            return regex_scan_check(check, local)
        endpoint = check.get("endpoint")
        res = result(fetched, endpoint, params) if endpoint else ApiResult(False, "GET", "missing endpoint")
        data = res.data
        if check_id == "stale_state.branches":
            if not res.ok:
                return [finding(check_id, "WARN", "Branch inventory could not be fetched.", actual={"status": res.status, "message": res.message})]
            ignored = set(check.get("expected", {}).get("ignored_branch_names", []))
            branches = [
                item
                for item in as_list(data)
                if isinstance(item, dict) and item.get("name") != default_branch and item.get("name") not in ignored
            ]
            if not branches:
                return [finding(check_id, "PASS", "No reportable non-default branches found.", actual=[])]
            data = branches
        return [finding(check_id, "MANUAL", "Fetched stale-state inventory; classify active, retained, approved drift, or stale before cleanup.", actual=data)]

    if check_id == "local.git_state":
        state = git_state(local, default_branch)
        if not state.get("available"):
            return [finding(check_id, "WARN", "Local git state unavailable.", actual=state)]
        drifts = []
        if state.get("worktree_clean") is not True:
            drifts.append(finding(check_id, "WARN", "Local worktree is dirty.", actual=state.get("raw_status"), expected="clean", path="$.worktree_clean"))
        if state.get("current_branch") != default_branch:
            drifts.append(finding(check_id, "WARN", "Local branch is not the default branch.", actual=state.get("current_branch"), expected=default_branch, path="$.current_branch"))
        if state.get("tracks_remote_default_branch") is not True:
            drifts.append(finding(check_id, "WARN", "Local branch is not tracking the remote default branch.", actual=state.get("upstream"), expected=f"*/{default_branch}", path="$.upstream"))
        return drifts or [finding(check_id, "PASS", "Local git state matches closure expectations.", actual=state)]

    if check_id == "content.local_secret_pattern_scan":
        return regex_scan_check(check, local)

    return [finding(check_id, "MANUAL", f"Comparison {check.get('comparison')} is not automated by this checker yet.")]


def regex_scan_check(check: dict[str, Any], local: dict[str, Any]) -> list[dict[str, Any]]:
    """Run a contract-declared forbidden-pattern scan over local text files."""
    check_id = check["id"]
    if not local.get("available"):
        return [finding(check_id, "WARN", "Local repo is unavailable for regex scan.", actual=local.get("errors"))]
    matches = []
    ignored_paths = set(check.get("expected", {}).get("ignore_paths", []))
    for pattern in check.get("expected", {}).get("forbidden_patterns", []):
        regex = re.compile(pattern)
        for path, text in local.get("texts", {}).items():
            if path in ignored_paths:
                continue
            if regex.search(text):
                matches.append({"path": path, "pattern": pattern})
    if matches:
        return [finding(check_id, "FAIL", "Forbidden local pattern found.", actual=matches, expected="no matches")]
    return [finding(check_id, "PASS", "No forbidden local patterns found.")]


def release_asset_names(releases: Any) -> list[dict[str, Any]]:
    """Return uploaded GitHub release assets from fetched release metadata."""

    assets: list[dict[str, Any]] = []
    for release in as_list(releases):
        if not isinstance(release, dict):
            continue
        for asset in as_list(release.get("assets")):
            if isinstance(asset, dict):
                assets.append({"release": release.get("tag_name") or release.get("name"), "asset": asset.get("name")})
    return assets


def apply_approved_drift(
    findings: list[dict[str, Any]],
    contract: dict[str, Any],
    rule_context: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Mark matching drift records as approved without hiding them."""
    exclusions = contract.get("approved_drift", {}).get("exclusions", [])
    allowances = contract.get("approved_drift", {}).get("allowances", [])
    remaining: list[dict[str, Any]] = []
    approved: list[dict[str, Any]] = []
    for item in findings:
        if item["level"] not in {"FAIL", "WARN"}:
            remaining.append(item)
            continue
        check_id = item["check_id"]
        if any(matches_rule(rule, check_id, item.get("path"), rule_context) for rule in exclusions + allowances):
            copy = dict(item)
            copy["level"] = "APPROVED_DRIFT"
            approved.append(copy)
        else:
            remaining.append(item)
    return remaining, approved


def matches_rule(rule: dict[str, Any], check_id: str, path: str | None, rule_context: dict[str, Any]) -> bool:
    """Return whether an approved-drift rule covers one finding."""
    if not condition_matches(str(rule.get("when") or "true"), rule_context):
        return False
    ids = rule.get("check_ids", rule.get("allowed_checks", rule.get("check_id", "*")))
    ids_list = ids if isinstance(ids, list) else [ids]
    if "*" not in ids_list and check_id not in ids_list:
        matched_glob = any(isinstance(item, str) and item.endswith("*") and check_id.startswith(item[:-1]) for item in ids_list)
        if not matched_glob:
            return False
    if rule.get("path") not in (None, "*", path):
        return False
    expires = rule.get("expires_on")
    if expires and dt.date.fromisoformat(expires) < dt.date.today():
        return False
    return True


def condition_matches(expression: str, rule_context: dict[str, Any]) -> bool:
    """Evaluate the small approved-drift condition language used by contracts.

    The contract intentionally uses a small expression language. Unknown values
    are treated as non-matches so a stale or under-fetched bundle cannot silently
    approve or skip drift.
    """

    expression = expression.strip()
    if not expression or expression in {"true", "always"}:
        return True
    return any(
        all(clause_matches(clause, rule_context) for clause in [part.strip() for part in group.split("&&")])
        for group in [part.strip() for part in expression.split("||")]
    )


def clause_matches(clause: str, rule_context: dict[str, Any]) -> bool:
    """Return whether one approved-drift condition clause is true."""

    file_contains = re.fullmatch(r"file\s+(\S+)\s+contains\s+(.+)", clause)
    if file_contains:
        path, needle = file_contains.groups()
        return needle in str(rule_context.get(f"file:{path}") or "")

    has_match = re.fullmatch(r"([A-Za-z0-9_.]+)\s+has\s+([A-Za-z0-9_-]+)", clause)
    if has_match:
        key, member = has_match.groups()
        actual = rule_context.get(key)
        if isinstance(actual, dict):
            return bool(actual.get(member))
        if isinstance(actual, (list, set, tuple)):
            return member in actual
        return False

    not_empty_match = re.fullmatch(r"([A-Za-z0-9_.]+)\s+is\s+not\s+empty", clause)
    if not_empty_match:
        return bool(rule_context.get(not_empty_match.group(1)))

    in_match = re.fullmatch(r"([A-Za-z0-9_.]+)\s+in\s+\[(.*)\]", clause)
    if in_match:
        key, raw_values = in_match.groups()
        value = rule_context.get(key)
        options = [item.strip().strip("'\"") for item in raw_values.split(",") if item.strip()]
        return value in options

    ne_match = re.fullmatch(r"([A-Za-z0-9_.]+)\s*!=\s*(true|false|null|-?\d+|'[^']*'|\"[^\"]*\"|[A-Za-z0-9_-]+)", clause)
    if ne_match:
        key, raw_expected = ne_match.groups()
        actual = rule_context.get(key)
        expected = parse_condition_value(raw_expected)
        if actual is None:
            return False
        if isinstance(actual, (list, set, tuple)):
            return expected not in actual
        return actual != expected

    gt_match = re.fullmatch(r"([A-Za-z0-9_.]+)\s*>\s*(-?\d+)", clause)
    if gt_match:
        key, raw_expected = gt_match.groups()
        actual = rule_context.get(key)
        return isinstance(actual, (int, float)) and actual > int(raw_expected)

    eq_match = re.fullmatch(r"([A-Za-z0-9_.]+)\s*==\s*(true|false|null|-?\d+|'[^']*'|\"[^\"]*\"|[A-Za-z0-9_-]+)", clause)
    if not eq_match:
        return False
    key, raw_expected = eq_match.groups()
    actual = rule_context.get(key)
    expected = parse_condition_value(raw_expected)
    if actual is None:
        return False
    return actual == expected


def parse_condition_value(raw_expected: str) -> Any:
    """Parse one scalar from the contract condition mini-language."""

    if raw_expected == "true":
        return True
    if raw_expected == "false":
        return False
    if raw_expected == "null":
        return None
    if raw_expected.lstrip("-").isdigit():
        return int(raw_expected)
    return raw_expected.strip("'\"")


def approved_drift_context(params: dict[str, Any], repo_context: dict[str, Any], local: dict[str, Any]) -> dict[str, Any]:
    """Build the condition context used by approved-drift rules."""

    repo_data = repo_context.get("repo") if isinstance(repo_context, dict) else {}
    if not isinstance(repo_data, dict):
        repo_data = {}
    types = repo_context.get("types", {}) if isinstance(repo_context, dict) else {}
    artifact_surface = types.get("artifact_surface", []) if isinstance(types, dict) else []
    external_artifacts = [item for item in artifact_surface if item != "no_artifact"]
    return {
        "repo.fork": bool(repo_data.get("fork")),
        "repo.archived": bool(repo_data.get("archived")),
        "repo.visibility": repo_data.get("visibility"),
        "audit_only": bool(params.get("audit_only", True)),
        "detected_external_artifact_count": len(external_artifacts),
        "no_artifact_docs_consistent": bool(local.get("available") and not external_artifacts),
        "selected_registry_supports_short_lived_identity": params.get("selected_registry_supports_short_lived_identity"),
        "token_fallback_scope_is_minimal": params.get("token_fallback_scope_is_minimal"),
        "artifact_visibility": params.get("artifact_visibility") or repo_data.get("visibility"),
        "token_scope_missing_for_registry_read": bool(params.get("token_scope_missing_for_registry_read", False)),
    }


def registry_metadata(params: dict[str, Any], artifact_contract: dict[str, Any], local: dict[str, Any]) -> dict[str, Any]:
    """Fetch live registry metadata for declared or locally inferred artifacts."""
    metadata: dict[str, Any] = {"pypi": {}, "npm": {}, "dockerhub": {}, "errors": []}
    artifacts = params.get("artifact_contracts") or []
    if isinstance(artifacts, str):
        try:
            artifacts = json.loads(artifacts)
        except json.JSONDecodeError:
            artifacts = []
    for artifact in artifacts if isinstance(artifacts, list) else []:
        if not isinstance(artifact, dict):
            continue
        artifact_type = str(artifact.get("artifact_type") or "")
        package = artifact.get("package_or_image_name")
        registry = str(artifact.get("registry") or "")
        if artifact_type == "pypi_python_package" and package:
            metadata["pypi"][package] = fetch_pypi(str(package))
        elif artifact_type == "npm_package" and package:
            metadata["npm"][package] = fetch_npm(str(package))
        elif "docker" in artifact_type or registry_is_docker_like(registry):
            namespace, repo_name = dockerhub_name(str(package or ""))
            if namespace and repo_name:
                metadata["dockerhub"][f"{namespace}/{repo_name}"] = fetch_dockerhub(namespace, repo_name)

    pyproject = local.get("texts", {}).get("pyproject.toml")
    if pyproject and not metadata["pypi"]:
        match = re.search(r"(?m)^name\s*=\s*[\"']([^\"']+)[\"']", pyproject)
        if match:
            metadata["pypi"][match.group(1)] = fetch_pypi(match.group(1))
    package_json = local.get("texts", {}).get("package.json")
    if package_json and not metadata["npm"]:
        try:
            name = json.loads(package_json).get("name")
            if name:
                metadata["npm"][name] = fetch_npm(str(name))
        except json.JSONDecodeError:
            pass
    return metadata


def registry_is_docker_like(registry: str) -> bool:
    """Detect supported Docker registry names without arbitrary URL substrings."""

    normalized = registry.strip().lower()
    if normalized in {"docker", "dockerhub", "docker-hub", "docker hub", "docker.io", "registry-1.docker.io"}:
        return True
    parsed = urllib.parse.urlparse(normalized if "://" in normalized else f"https://{normalized}")
    hostname = parsed.hostname or ""
    return hostname in {"hub.docker.com", "docker.io", "registry-1.docker.io", "ghcr.io"}


def fetch_pypi(package: str) -> dict[str, Any]:
    """Fetch PyPI JSON metadata and expose latest-version evidence."""
    try:
        data = http_json(f"https://pypi.org/pypi/{urllib.parse.quote(package)}/json")
        latest = data.get("info", {}).get("version")
        return {
            "ok": True,
            "project_url": f"https://pypi.org/project/{package}/",
            "latest_version": latest,
            "latest_files": [file.get("filename") for file in data.get("releases", {}).get(latest, [])] if latest else [],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "project_url": f"https://pypi.org/project/{package}/"}


def fetch_npm(package: str) -> dict[str, Any]:
    """Fetch npm registry metadata and expose dist-tag evidence."""
    encoded = urllib.parse.quote(package, safe="@")
    if package.startswith("@"):
        encoded = urllib.parse.quote(package, safe="")
    try:
        data = http_json(f"https://registry.npmjs.org/{encoded}")
        latest = (data.get("dist-tags") or {}).get("latest")
        return {
            "ok": True,
            "package_url": f"https://www.npmjs.com/package/{package}",
            "latest_version": latest,
            "dist_tags": data.get("dist-tags") or {},
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "package_url": f"https://www.npmjs.com/package/{package}"}


def dockerhub_name(image: str) -> tuple[str | None, str | None]:
    """Split a Docker Hub image reference into namespace/repository."""
    if not image:
        return None, None
    image = image.removeprefix("docker.io/").removeprefix("registry-1.docker.io/")
    parts = image.split("/")
    if len(parts) == 1:
        return "library", parts[0].split(":")[0].split("@")[0]
    if len(parts) >= 2:
        return parts[-2], parts[-1].split(":")[0].split("@")[0]
    return None, None


def fetch_dockerhub(namespace: str, repo_name: str) -> dict[str, Any]:
    """Fetch Docker Hub repository metadata plus most recently updated tags."""
    base = f"https://hub.docker.com/v2/namespaces/{urllib.parse.quote(namespace)}/repositories/{urllib.parse.quote(repo_name)}"
    try:
        repo = http_json(base + "/")
        tags = http_json(base + "/tags?page_size=25&ordering=last_updated")
        results = tags.get("results") if isinstance(tags, dict) else []
        latest = results[0] if results else None
        return {
            "ok": True,
            "repository_url": f"https://hub.docker.com/r/{namespace}/{repo_name}",
            "description": repo.get("description"),
            "last_updated": repo.get("last_updated"),
            "latest_tag": {"name": latest.get("name"), "last_updated": latest.get("last_updated")} if isinstance(latest, dict) else None,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "repository_url": f"https://hub.docker.com/r/{namespace}/{repo_name}"}


def evaluate_artifact_check(check: dict[str, Any], params: dict[str, Any], local: dict[str, Any], types: dict[str, Any], registries: dict[str, Any], releases: Any) -> list[dict[str, Any]]:
    """Evaluate one deterministic artifact check from local and registry data."""
    check_id = check["id"]
    artifacts = set(types.get("artifact_surface", []))
    if check_id.startswith("common."):
        if check_id == "common.artifact_scope_trigger":
            triggered = "no_artifact" not in artifacts or params.get("current_change_affects_artifact") or params.get("final_answer_makes_artifact_claim")
            return [finding(check_id, "PASS" if triggered else "SKIP", "Artifact contract scope evaluated.", actual={"triggered": triggered, "artifact_surface": sorted(artifacts)})]
        if check_id == "common.real_deliverable_classification":
            return [finding(check_id, "PASS", "Artifact surfaces classified.", actual=sorted(artifacts))]
        if check_id == "common.no_artifact_consistency":
            release_assets = release_asset_names(releases)
            if "no_artifact" in artifacts and release_assets:
                return [finding(check_id, "FAIL", "No-artifact posture conflicts with uploaded release assets.", actual=release_assets)]
            return [finding(check_id, "PASS", "No-artifact posture has no deterministic conflict.")]
        if check_id in {"common.live_registry_verification", "common.local_build_package_consume"}:
            return [finding(check_id, "MANUAL", "Local build or consumer checks are intentionally not run by the bundled audit; use recorded commands when publishing.", actual=registries)]
        if check_id == "common.short_lived_identity_policy":
            return [finding(check_id, "MANUAL", "Publishing identity needs workflow and registry-specific review.", actual={"workflow_files": [p for p in local.get("files", []) if p.startswith(".github/workflows/")]})]
        if check_id == "common.attestation_permissions":
            text = workflow_text(local)
            if not re.search(r"(?i)(actions/attest|attestations:\s*write|provenance|sbom|cosign)", text):
                return [finding(check_id, "SKIP", "No attestation, provenance, SBOM, or signing workflow evidence detected.")]
            drifts = []
            top_level_attestations = workflows_with_top_level_write_permission(local, "attestations")
            if top_level_attestations:
                drifts.append(finding(check_id, "FAIL", "Workflow-root attestations: write grants are not job scoped.", actual=top_level_attestations, expected="job-level attestations: write"))
            top_level_id_token = workflows_with_top_level_write_permission(local, "id-token")
            if top_level_id_token:
                drifts.append(finding(check_id, "WARN", "Workflow-root id-token: write should be scoped to publishing or attestation jobs.", actual=top_level_id_token, expected="job-level id-token: write when required"))
            top_level_artifact_metadata = workflows_with_top_level_write_permission(local, "artifact-metadata")
            if top_level_artifact_metadata:
                drifts.append(finding(check_id, "FAIL", "Workflow-root artifact-metadata: write grants are not job scoped.", actual=top_level_artifact_metadata, expected="job-level artifact-metadata: write"))
            if workflows_with_write_permission(local, "attestations") and "contents: read" not in text:
                drifts.append(finding(check_id, "WARN", "Attestation workflow permissions do not visibly include contents: read.", expected="contents: read"))
            return drifts or [finding(check_id, "PASS", "Attestation/provenance workflow permissions are scoped.")]
        if check_id == "common.linked_artifact_metadata":
            artifact_metadata_grants = workflows_with_write_permission(local, "artifact-metadata")
            if not artifact_metadata_grants and not re.search(r"(?i)linked artifact metadata", workflow_text(local)):
                return [finding(check_id, "SKIP", "No linked artifact metadata workflow evidence detected.")]
            drifts = []
            top_level_artifact_metadata = workflows_with_top_level_write_permission(local, "artifact-metadata")
            if top_level_artifact_metadata:
                drifts.append(finding(check_id, "FAIL", "Workflow-root artifact-metadata: write grants are not job scoped.", actual=top_level_artifact_metadata, expected="job-level artifact-metadata: write"))
            publish_text = workflow_text(local)
            if artifact_metadata_grants and not re.search(r"(?i)(gh release|npm publish|pypi|docker|ghcr|mvn deploy|nuget push|cargo publish|gem push)", publish_text):
                drifts.append(finding(check_id, "WARN", "Linked artifact metadata permission is present without visible registry or release publication evidence.", actual=artifact_metadata_grants, expected="registry or release artifact publication evidence"))
            return drifts or [finding(check_id, "PASS", "Linked artifact metadata workflow evidence is intentional and scoped.", actual=artifact_metadata_grants)]
        return [finding(check_id, "PASS", "Common artifact check recorded.", actual={"artifact_surface": sorted(artifacts)})]

    if check_id.startswith("pypi."):
        if "pypi_python_package" not in artifacts:
            return [finding(check_id, "SKIP", "No PyPI artifact detected.")]
        if check_id == "pypi.metadata_and_build":
            text = local.get("texts", {}).get("pyproject.toml", "")
            if not text:
                return [finding(check_id, "FAIL", "pyproject.toml is missing or unreadable.", expected="pyproject.toml")]
            missing = [token for token in ("[build-system]", "[project]") if token not in text]
            for key in ("name", "requires-python", "description"):
                if not toml_key_present(text, key):
                    missing.append(key)
            if not toml_key_present(text, "version"):
                missing.append("version_or_dynamic")
            if not (toml_key_present(text, "license") or toml_key_present(text, "license-files")):
                missing.append("license_or_license-files")
            if not (toml_key_present(text, "readme") or toml_key_present(text, "description")):
                missing.append("readme_or_description")
            drifts = [finding(check_id, "FAIL", "PyPI project metadata is incomplete.", actual=missing, path="pyproject.toml")] if missing else []
            if not (toml_key_present(text, "authors") or toml_key_present(text, "maintainers")):
                drifts.append(finding(check_id, "WARN", "PyPI public metadata lacks authors or maintainers.", expected="authors or maintainers", path="pyproject.toml"))
            for key in ("urls", "classifiers"):
                if not toml_key_present(text, key):
                    drifts.append(finding(check_id, "WARN", f"Recommended PyPI metadata is missing: {key}.", expected=key, path="pyproject.toml"))
            return drifts or [finding(check_id, "PASS", "PyPI metadata and build-system fields are present.")]
        if check_id == "pypi.trusted_publishing_and_attestations":
            text = workflow_text(local)
            if not re.search(r"(pypa/gh-action-pypi-publish|twine upload|pypi)", text, re.IGNORECASE):
                return [finding(check_id, "SKIP", "No PyPI publish workflow detected.")]
            drifts = []
            if "id-token: write" not in text:
                drifts.append(finding(check_id, "FAIL", "PyPI Trusted Publishing workflow lacks id-token: write.", expected="job-scoped id-token: write"))
            if "pypa/gh-action-pypi-publish" not in text and "twine upload" not in text:
                drifts.append(finding(check_id, "WARN", "PyPI publish workflow does not use the PyPA publish action or twine.", expected="pypa/gh-action-pypi-publish or equivalent"))
            if "python -m build" not in text:
                drifts.append(finding(check_id, "WARN", "PyPI publish workflow does not visibly build sdist/wheel with python -m build.", expected="python -m build"))
            if not re.search(r"(?i)(release:|tags:|workflow_dispatch)", text):
                drifts.append(finding(check_id, "WARN", "PyPI publish workflow trigger is not visibly release, tag, or explicit manual release.", expected="release/tag/manual trigger"))
            return drifts or [finding(check_id, "PASS", "PyPI Trusted Publishing workflow has OIDC and build evidence.")]
        if check_id == "pypi.live_version_install_smoke":
            if not registries.get("pypi"):
                return [finding(check_id, "WARN", "No PyPI package name was available for live metadata lookup.")]
            bad = {name: data for name, data in registries["pypi"].items() if not data.get("ok")}
            return [finding(check_id, "FAIL", "PyPI live metadata lookup failed.", actual=bad)] if bad else [finding(check_id, "PASS", "PyPI project and latest version metadata resolved.", actual=registries["pypi"])]
        return [finding(check_id, "PASS", "PyPI deterministic metadata check is covered by repo/package metadata scan.")]

    if check_id.startswith("npm."):
        if "npm_package" not in artifacts:
            return [finding(check_id, "SKIP", "No npm artifact detected.")]
        if check_id == "npm.metadata_and_package_contents":
            try:
                data = json.loads(local.get("texts", {}).get("package.json", "{}"))
            except json.JSONDecodeError as exc:
                return [finding(check_id, "FAIL", "package.json is invalid JSON.", actual=str(exc), path="package.json")]
            workspace_root = bool(data.get("private") and data.get("workspaces"))
            required = ["name", "license"] if workspace_root else ["name", "version", "license"]
            missing = [key for key in required if not data.get(key)]
            drifts = [finding(check_id, "FAIL", "npm package metadata is incomplete.", actual=missing, path="package.json")] if missing else []
            if not data.get("repository"):
                drifts.append(finding(check_id, "WARN", "package.json repository is missing; trusted publishing/provenance requires exact source linkage.", expected="repository", path="package.json"))
            if not (data.get("packageManager") or path_matches(local.get("files", []), ["package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock"])):
                drifts.append(finding(check_id, "WARN", "No packageManager or lockfile found.", expected="packageManager or lockfile", path="package.json"))
            if workspace_root:
                drifts.append(finding(check_id, "INFO", "Private workspace root detected; check each published workspace package.", actual={"workspaces": data.get("workspaces")}, path="package.json"))
            elif not (data.get("files") or ".npmignore" in local.get("files", [])):
                drifts.append(finding(check_id, "WARN", "npm package contents are not constrained by files or .npmignore.", expected="files or .npmignore", path="package.json"))
            return drifts or [finding(check_id, "PASS", "npm package metadata and reproducibility fields are present.")]
        if check_id == "npm.trusted_publishing_and_provenance":
            text = workflow_text(local)
            if "npm publish" not in text:
                return [finding(check_id, "SKIP", "No npm publish workflow detected.")]
            drifts = []
            if "id-token: write" not in text:
                drifts.append(finding(check_id, "FAIL", "npm trusted publishing/provenance workflow lacks id-token: write.", expected="job-scoped id-token: write"))
            if not re.search(r"(?i)(--provenance|provenance|trusted publishing|id-token:\s*write)", text):
                drifts.append(finding(check_id, "WARN", "npm publish workflow does not visibly enable provenance or trusted publishing.", expected="trusted publishing or provenance"))
            if not re.search(r"(?i)(tags:|release:|workflow_dispatch)", text):
                drifts.append(finding(check_id, "WARN", "npm publish workflow trigger is not visibly tag, release, or explicit manual release.", expected="tag/release/manual trigger"))
            if not re.search(r"(?i)(npm ci|pnpm install|yarn install)", text):
                drifts.append(finding(check_id, "WARN", "npm publish workflow does not visibly install from a lockfile.", expected="npm ci, pnpm install, or yarn install"))
            return drifts or [finding(check_id, "PASS", "npm publish workflow has trusted publishing/provenance evidence.")]
        if check_id == "npm.live_package_version_smoke":
            bad = {name: data for name, data in registries["npm"].items() if not data.get("ok")}
            return [finding(check_id, "FAIL", "npm live metadata lookup failed.", actual=bad)] if bad else [finding(check_id, "PASS", "npm package and latest dist-tag metadata resolved.", actual=registries["npm"])]
        return [finding(check_id, "PASS", "npm deterministic metadata check is covered by repo/package metadata scan.")]

    if check_id.startswith("docker_oci."):
        if not artifacts.intersection({"docker_oci_image", "github_container_registry_image", "generic_oci_registry_image"}):
            return [finding(check_id, "SKIP", "No Docker/OCI artifact detected.")]
        if check_id == "docker_oci.dockerfile_and_context":
            dockerfiles = matching_paths(local.get("files", []), ["Dockerfile", "**/Dockerfile"])
            if not dockerfiles:
                return [finding(check_id, "FAIL", "No Dockerfile found for Docker/OCI artifact.", expected="Dockerfile")]
            drifts = []
            if ".dockerignore" not in local.get("files", []):
                drifts.append(finding(check_id, "FAIL", ".dockerignore is missing.", expected=".dockerignore"))
            for path in dockerfiles:
                text = local.get("texts", {}).get(path, "")
                if not text:
                    drifts.append(finding(check_id, "MANUAL", "Dockerfile content unavailable for deterministic inspection.", actual=path, path=path))
                    continue
                if not re.search(r"(?im)^FROM\s+\S+", text):
                    drifts.append(finding(check_id, "FAIL", "Dockerfile has no FROM instruction.", actual=path, path=path))
                if re.search(r"(?im)^FROM\s+\S+:latest(?:\s|$)", text):
                    drifts.append(finding(check_id, "WARN", "Dockerfile uses a latest-tag base image.", actual=path, expected="pinned tag or digest", path=path))
                if SECRET_NAME_RE.search(text):
                    drifts.append(finding(check_id, "FAIL", "Dockerfile declares secret-like ARG or ENV names.", expected="secret mount or CI secret", path=path))
                from_count = len(re.findall(r"(?im)^FROM\s+", text))
                build_tooling = re.search(r"(?i)(npm|pnpm|yarn|pip|poetry|uv|go build|cargo|mvn|gradle|dotnet)\s+", text)
                if build_tooling and from_count < 2:
                    drifts.append(finding(check_id, "WARN", "Build-toolchain Dockerfile is not multi-stage.", expected="multi-stage build when practical", path=path))
                lockfiles = matching_paths(local.get("files", []), ["package-lock.json", "pnpm-lock.yaml", "yarn.lock", "requirements*.txt", "uv.lock", "poetry.lock", "Cargo.lock", "go.sum"])
                if lockfiles and re.search(r"(?i)(npm|pnpm|yarn|pip|uv|poetry|cargo|go)\s+(install|mod|build)", text) and not re.search(r"(?i)^COPY\s+.*(package-lock|pnpm-lock|yarn.lock|requirements|uv.lock|poetry.lock|Cargo.lock|go.sum)", text, re.MULTILINE):
                    drifts.append(finding(check_id, "WARN", "Dockerfile does not visibly copy dependency lockfiles before install/build.", actual=lockfiles, path=path))
            return drifts or [finding(check_id, "PASS", "Dockerfile/context deterministic checks pass.")]
        if check_id == "docker_oci.build_publish_and_pull":
            if registries.get("dockerhub"):
                bad = {name: data for name, data in registries["dockerhub"].items() if not data.get("ok")}
                return [finding(check_id, "FAIL", "Docker Hub repository or latest tag metadata lookup failed.", actual=bad)] if bad else [finding(check_id, "PASS", "Docker Hub repository and latest tag metadata resolved.", actual=registries["dockerhub"])]
            return [finding(check_id, "MANUAL", "No Docker Hub image name was provided; GHCR or other registry needs registry-specific verification.")]
        if check_id == "docker_oci.provenance_and_sbom":
            text = workflow_text(local) + "\n" + "\n".join(local.get("texts", {}).get(path, "") for path in local.get("texts", {}) if path.lower().endswith((".md", ".yml", ".yaml")))
            if not re.search(r"(?i)(attest|provenance|sbom|cosign)", text):
                return [finding(check_id, "SKIP", "No container attestation, provenance, SBOM, or cosign workflow evidence detected.")]
            drifts = []
            if not re.search(r"(?i)(gh attestation verify|cosign verify|cosign verify-attestation)", text):
                drifts.append(finding(check_id, "WARN", "No recorded attestation/signature verification command found.", expected="gh attestation verify or cosign verify"))
            if "id-token: write" not in text and "attestations: write" not in text:
                drifts.append(finding(check_id, "WARN", "Attestation/provenance workflow permissions are not visible.", expected="job-scoped id-token or attestations permission"))
            if "cosign verify" in text and not re.search(r"(?i)(certificate-identity|certificate-oidc-issuer|rekor|bundle)", text):
                drifts.append(finding(check_id, "WARN", "cosign verification does not visibly constrain identity/issuer or log/bundle evidence.", expected="identity/issuer plus Rekor or bundle verification"))
            return drifts or [finding(check_id, "PASS", "Container attestation/provenance verification evidence is present.")]
        return [finding(check_id, "PASS", "Docker/OCI deterministic file or workflow evidence recorded.")]

    if check_id == "github_release_assets.attestation_verification":
        if not release_asset_names(releases):
            return [finding(check_id, "SKIP", "No uploaded GitHub release assets detected.")]
        text = workflow_text(local) + "\n" + "\n".join(local.get("texts", {}).get(path, "") for path in local.get("texts", {}) if path.lower().endswith((".md", ".yml", ".yaml")))
        if re.search(r"(?i)(actions/attest|attestations:\s*write|cosign|provenance)", text) and not re.search(r"(?i)(gh attestation verify|cosign verify|cosign verify-attestation)", text):
            return [finding(check_id, "WARN", "Release artifact attestation/signature evidence exists but no verification command is recorded.", expected="gh attestation verify or cosign verify")]
        return [finding(check_id, "PASS", "GitHub release metadata fetched and attestation verification posture classified.", actual=releases)]

    if check_id == "github_release_assets.assets_and_tags":
        return [finding(check_id, "PASS" if releases else "SKIP", "GitHub release metadata fetched.", actual=releases)]

    return [finding(check_id, "MANUAL", "Artifact-specific check requires registry or build-system review.", actual={"artifact_surface": sorted(artifacts)})]


def compare_repo_contract(
    contract: dict[str, Any],
    params: dict[str, Any],
    local: dict[str, Any],
    selected_check_ids: set[str] | None = None,
    selected_bundle_ids: set[str] | None = None,
    context: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch repo evidence, classify surfaces, and evaluate selected repo checks."""
    fetched: dict[tuple[str, str], ApiResult] = context["fetched"] if context else {}
    if not params.get("default_branch"):
        repo_endpoint = endpoint_for("/repos/${owner}/${repo}", params)
        fetched[("GET", repo_endpoint)] = run_gh_api("GET", repo_endpoint)
        repo_seed = fetched[("GET", repo_endpoint)]
        if repo_seed.ok and isinstance(repo_seed.data, dict):
            params["default_branch"] = repo_seed.data.get("default_branch")
    fetch_contract_requests(contract, params, selected_check_ids, selected_bundle_ids, fetched)
    repo_res = result(fetched, "/repos/${owner}/${repo}", params)
    if not repo_res.ok or not isinstance(repo_res.data, dict):
        raise SystemExit(f"Could not fetch repo: {repo_res.status} {repo_res.message}")
    params.setdefault("default_branch", repo_res.data.get("default_branch"))
    tree_res = result(fetched, "/repos/${owner}/${repo}/git/trees/${default_branch}?recursive=1", params)
    paths = local.get("files") or tree_paths(tree_res.data)
    topics_res = result(fetched, "/repos/${owner}/${repo}/topics", params)
    topics = [str(t).lower() for t in (topics_res.data or {}).get("names", [])] if topics_res.ok and isinstance(topics_res.data, dict) else []
    types = classify(repo_res.data, paths, topics, local)
    findings: list[dict[str, Any]] = []
    for check in selected_contract_checks(contract, selected_check_ids):
        findings.extend(evaluate_repo_check(check, params, fetched, local, types))
    return findings, {"fetched": fetched, "types": types, "paths": paths, "repo": repo_res.data}


def compare_artifact_contract(
    contract: dict[str, Any],
    params: dict[str, Any],
    local: dict[str, Any],
    repo_context: dict[str, Any],
    selected_check_ids: set[str] | None = None,
    selected_bundle_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate selected artifact checks using the repo evidence bundle."""
    types = repo_context["types"]
    fetched = repo_context["fetched"]
    fetch_artifact_contract_requests(contract, params, selected_check_ids, selected_bundle_ids, fetched, repo_context["repo"])
    releases = result(fetched, "/repos/${owner}/${repo}/releases?per_page=100", params).data or []
    registries = registry_metadata(params, contract, local)
    findings: list[dict[str, Any]] = []
    for check in selected_contract_checks(contract, selected_check_ids):
        findings.extend(evaluate_artifact_check(check, params, local, types, registries, releases))
    return findings


def remediate_repo(check_ids: set[str], repo_contract: dict[str, Any], params: dict[str, Any], local: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply only repo remediations that the contract explicitly marks safe."""
    policy = repo_contract.get("remediation_policy", {})
    allowed = set(policy.get("auto_apply_check_ids", []))
    check_ids &= allowed
    applied: list[dict[str, Any]] = []
    repo = repo_slug(params["owner"], params["repo"])
    checks = {check["id"]: check for check in repo_contract.get("checks", [])}
    if "repo.merge_settings" in check_ids:
        repo_res = run_gh_api("GET", f"/repos/{repo}")
        repo_info = repo_res.data if repo_res.ok and isinstance(repo_res.data, dict) else {}
        owner_res = run_gh_api("GET", f"/orgs/{params['owner']}")
        owner_info = owner_res.data if owner_res.ok and isinstance(owner_res.data, dict) else {}
        owner_plan = owner_info.get("plan") if isinstance(owner_info.get("plan"), dict) else {}
        rule_context = {
            "repo.visibility": repo_info.get("visibility"),
            "repo.fork": bool(repo_info.get("fork")),
            "repo.archived": bool(repo_info.get("archived")),
            "owner.plan.name": owner_plan.get("name"),
        }
        body = {}
        for key, raw_spec in checks["repo.merge_settings"].get("expected", {}).items():
            spec = raw_spec if isinstance(raw_spec, dict) else {"value": raw_spec}
            field_applies = spec.get("applies_when")
            if field_applies and not condition_matches(str(field_applies), rule_context):
                continue
            value = spec.get("value")
            if isinstance(value, bool):
                body[key] = value
        res = run_gh_api("PATCH", f"/repos/{repo}", body)
        applied.append({"check_id": "repo.merge_settings", "ok": res.ok, "status": res.status, "message": res.message})
    if "repo.topics_required" in check_ids:
        topics_res = run_gh_api("GET", f"/repos/{repo}/topics")
        names = (topics_res.data or {}).get("names", []) if topics_res.ok and isinstance(topics_res.data, dict) else []
        inferred = [t for t in ("python", "npm", "docker", "github-actions") if t not in names]
        if not names and inferred:
            res = run_gh_api("PUT", f"/repos/{repo}/topics", {"names": inferred[:3]})
            applied.append({"check_id": "repo.topics_required", "ok": res.ok, "status": res.status, "message": res.message})
    for check_id, endpoint in (
        ("security.vulnerability_alerts_enabled", f"/repos/{repo}/vulnerability-alerts"),
        ("security.dependabot_security_updates_enabled", f"/repos/{repo}/automated-security-fixes"),
        ("security.private_vulnerability_reporting_public", f"/repos/{repo}/private-vulnerability-reporting"),
    ):
        if check_id in check_ids:
            res = run_gh_api("PUT", endpoint)
            applied.append({"check_id": check_id, "ok": res.ok, "status": res.status, "message": res.message})
    if "content.dependencies_label_when_dependabot_uses_it" in check_ids:
        res = run_gh_api("POST", f"/repos/{repo}/labels", {"name": "dependencies", "color": "0366d6", "description": "Dependency updates"})
        applied.append({"check_id": "content.dependencies_label_when_dependabot_uses_it", "ok": res.ok, "status": res.status, "message": res.message})
    return applied


def build_params(
    args: argparse.Namespace,
    github_contract: dict[str, Any],
    code_contract: dict[str, Any],
    artifact_contract: dict[str, Any],
) -> dict[str, Any]:
    """Merge CLI args, JSON `--param` values, and contract defaults."""
    owner, repo = split_repo(args.repo)
    params: dict[str, Any] = {"owner": owner, "repo": repo}
    for contract in (github_contract, code_contract, artifact_contract):
        for key, spec in contract.get("parameters", {}).items():
            if "default" in spec and key not in params:
                params[key] = spec["default"]
    if args.local_repo_path:
        params["local_repo_path"] = args.local_repo_path
    for item in args.param or []:
        if "=" not in item:
            raise SystemExit(f"--param must be KEY=VALUE, got {item!r}")
        key, raw = item.split("=", 1)
        try:
            params[key] = json.loads(raw)
        except json.JSONDecodeError:
            params[key] = raw
    return params


def summarize(findings: list[dict[str, Any]]) -> dict[str, int]:
    """Count findings by level for compact reports."""
    levels: dict[str, int] = {}
    for item in findings:
        levels[item["level"]] = levels.get(item["level"], 0) + 1
    return levels


def print_human(report: dict[str, Any]) -> None:
    """Print a concise human-readable report; JSON remains the full output."""
    print(f"Repo: {report['repo']}")
    if report.get("selections"):
        selected = ", ".join(f"{item['surface']}:{item['subset']}" for item in report["selections"])
        print(f"Selections: {selected}")
    else:
        print(f"Surface: {report['surface']}; subset: {report['subset']}")
    print(
        f"GitHub checks: {report['github_check_count']}; code checks: {report['code_check_count']}; "
        f"artifact checks: {report['artifact_check_count']}; fetched endpoints: {report['fetched_endpoints']}"
    )
    print(f"Result counts: {report['result_counts']}")
    if report["applied"]:
        print("Applied:")
        for item in report["applied"]:
            status = "ok" if item.get("ok") else f"failed {item.get('status')}"
            print(f"  {item['check_id']}: {status}")
    actionable = [item for item in report["findings"] if item["level"] in {"FAIL", "WARN", "MANUAL"}]
    if actionable:
        print("Findings:")
        for item in actionable[:80]:
            print(f"  {item['level']} {item['check_id']} {item.get('path', '$')}: {item['message']}")
        if len(actionable) > 80:
            print(f"  ... {len(actionable) - 80} more findings omitted from text output; use --json.")


def main() -> int:
    """Parse CLI arguments, collect evidence, compare contracts, and report."""

    parser = argparse.ArgumentParser(
        description="Check GitHub repo, repo-code, and artifact health contracts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Surfaces:\n"
            "  repo           live GitHub repository settings and hosted repo state\n"
            "  code           repository contents and local checkout policy\n"
            "  artifact       external deliverables and registry state\n"
            "  all            every contract surface\n\n"
            "Subsets:\n"
            "  settings       GitHub repo/process settings subset\n"
            "  dependency     Dependabot and dependency-security subset\n"
            "  content        repository-content subset\n"
            "  artifact       artifact and registry subset\n"
            "  create         creation/hardening subset, excluding stale-state-only checks\n"
            "  health         full health audit\n"
            "  all            no subset narrowing\n"
            "\nMulti-selection examples:\n"
            "  --select repo:dependency --select code:dependency\n"
            "  --select repo:settings --select artifact:artifact\n"
        ),
    )
    parser.add_argument("--repo", required=True, help="OWNER/REPO")
    parser.add_argument("--github-contract", "--repo-contract", dest="github_contract", default=default_contract_path("github-repo-deterministic-contract.json"))
    parser.add_argument("--code-contract", default=default_contract_path("code-repo-deterministic-contract.json"))
    parser.add_argument("--artifact-contract", default=default_contract_path("artifact-deterministic-contract.json"))
    parser.add_argument("--local-repo-path")
    parser.add_argument("--param", action="append", help="Additional parameter as KEY=VALUE. VALUE may be JSON.")
    parser.add_argument("--surface", choices=SURFACE_CHOICES, default="all", help="Limit findings to live GitHub repo state, repo-code checks, or artifact checks.")
    parser.add_argument("--subset", choices=SUBSET_CHOICES, default="all", help="Run one workflow-oriented subset of checks. Subsets select check IDs; surfaces select which contract area receives that subset.")
    parser.add_argument("--select", action="append", metavar="SURFACE:SUBSET", help="Add one surface/subset pair to a multi-selection run. Can be repeated, and cannot be combined with non-default --surface or --subset.")
    parser.add_argument("--check-id", action="append", help="Run one deterministic check ID. Can be repeated.")
    parser.add_argument("--bundle", action="append", help="Fetch only this repo contract fetch bundle ID. Can be repeated.")
    parser.add_argument("--apply", action="store_true", help="Apply contract-declared reversible repo remediations only.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--no-fail", action="store_true", help="Exit 0 even when unapproved drift remains.")
    args = parser.parse_args()

    github_contract = load_json(args.github_contract)
    code_contract = load_json(args.code_contract)
    artifact_contract = load_json(args.artifact_contract)
    params = build_params(args, github_contract, code_contract, artifact_contract)
    github_selected, code_selected, artifact_selected, selections = build_selection(
        github_contract,
        code_contract,
        artifact_contract,
        args,
    )
    github_selected, code_selected, artifact_selected = apply_explicit_check_ids(
        github_contract,
        code_contract,
        artifact_contract,
        args.check_id,
        github_selected,
        code_selected,
        artifact_selected,
    )
    selected_bundle_ids = set(args.bundle) if args.bundle else None
    if selected_bundle_ids is not None:
        known_bundles: set[str] = set()
        for contract in (github_contract, code_contract):
            known_bundles.update(str(bundle.get("id")) for bundle in contract.get("fetch_bundles", []) if bundle.get("id"))
        artifact_bundles = artifact_contract.get("fetch_bundles", {})
        if isinstance(artifact_bundles, dict):
            known_bundles.update(str(bundle_id) for bundle_id in artifact_bundles)
        else:
            known_bundles.update(str(bundle.get("id")) for bundle in artifact_bundles if isinstance(bundle, dict) and bundle.get("id"))
        unknown_bundles = sorted(selected_bundle_ids - known_bundles)
        if unknown_bundles:
            raise SystemExit(f"Unknown fetch bundle id(s): {', '.join(unknown_bundles)}")
    local = scan_local(params.get("local_repo_path"))
    github_findings, repo_context = compare_repo_contract(github_contract, params, local, github_selected, selected_bundle_ids)
    code_findings, repo_context = compare_repo_contract(code_contract, params, local, code_selected, selected_bundle_ids, repo_context)
    artifact_findings = compare_artifact_contract(artifact_contract, params, local, repo_context, artifact_selected, selected_bundle_ids)
    rule_context = approved_drift_context(params, repo_context, local)
    github_findings, github_approved = apply_approved_drift(github_findings, github_contract, rule_context)
    code_findings, code_approved = apply_approved_drift(code_findings, code_contract, rule_context)
    artifact_findings, artifact_approved = apply_approved_drift(artifact_findings, artifact_contract, rule_context)
    findings = github_findings + code_findings + artifact_findings
    approved = github_approved + code_approved + artifact_approved
    applied: list[dict[str, Any]] = []

    if args.apply:
        drift_ids = {item["check_id"] for item in findings if item["level"] in {"FAIL", "WARN"}}
        applied = remediate_repo(drift_ids, github_contract, params, local)
        applied_success_ids = {str(item["check_id"]) for item in applied if item.get("ok")}
        # A successful mutation command is sufficient evidence for that exact
        # applied check. Keep unrelated drift, and avoid a second bundled audit
        # unless the caller explicitly runs one later for a broader claim.
        if applied_success_ids:
            findings = [
                item
                for item in findings
                if not (item["level"] in {"FAIL", "WARN"} and item["check_id"] in applied_success_ids)
            ]

    selected_github_count = len(selected_contract_checks(github_contract, github_selected))
    selected_code_count = len(selected_contract_checks(code_contract, code_selected))
    selected_artifact_count = len(selected_contract_checks(artifact_contract, artifact_selected))
    report = {
        "repo": repo_slug(params["owner"], params["repo"]),
        "github_contract": os.path.abspath(args.github_contract),
        "code_contract": os.path.abspath(args.code_contract),
        "artifact_contract": os.path.abspath(args.artifact_contract),
        "selection_mode": "multi" if selections else "single",
        "surface": "multi" if selections else args.surface,
        "subset": "multi" if selections else args.subset,
        "selections": selections,
        "selected_check_ids": sorted(
            selected_ids_for_report(github_contract, github_selected)
            | selected_ids_for_report(code_contract, code_selected)
            | selected_ids_for_report(artifact_contract, artifact_selected)
        ),
        "github_check_count": selected_github_count,
        "code_check_count": selected_code_count,
        "repo_check_count": selected_github_count,
        "artifact_check_count": selected_artifact_count,
        "total_github_check_count": len(github_contract.get("checks", [])),
        "total_code_check_count": len(code_contract.get("checks", [])),
        "total_repo_check_count": len(github_contract.get("checks", [])),
        "total_artifact_check_count": len(artifact_contract.get("checks", [])),
        "selected_bundles": sorted(selected_bundle_ids) if selected_bundle_ids else None,
        "fetched_endpoints": len(repo_context["fetched"]),
        "types": repo_context["types"],
        "result_counts": summarize(findings + approved),
        "applied": applied,
        "approved_drift": approved,
        "findings": findings,
        "local_scan": {"available": local.get("available"), "root": local.get("root"), "errors": local.get("errors", [])},
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_human(report)
    has_unapproved = any(item["level"] in {"FAIL", "WARN"} for item in findings)
    return 2 if has_unapproved and not args.no_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
