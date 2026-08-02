#!/usr/bin/env python3
"""Apply one classified direct-release skill change with compensation.

One JSON request declares the exact patch, selected runtime skills, existing
behavior tests, and commit. The helper classifies the complete request before
mutation, owns patch-to-commit orchestration, and touches only declared paths.
Markdown patches run repository-declared lint; broad source and runtime
validation remain outside this helper.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


REQUEST_VERSION = 1
REQUIRED_ROOT_FIELDS = {
    "version",
    "repo_root",
    "release_branch",
    "patch",
    "selected_skills",
    "removed_skills",
    "classification",
    "tests",
    "commit_message",
}
ROOT_FIELDS = REQUIRED_ROOT_FIELDS | {"install_root"}
CLASSIFICATIONS = {"rules-only", "helper"}
RELEASE_BRANCH = "release/local"
PYTEST_NODE_RE = re.compile(r"^tests/[A-Za-z0-9_./-]+\.py::\S+$")
SKILL_NAME_RE = re.compile(
    r"^(?![a-z0-9-]*--)[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$"
)
EXECUTABLE_SUFFIXES = {
    ".py",
    ".ps1",
    ".sh",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
}


class FastChangeError(RuntimeError):
    """One compact orchestration or compensation failure."""


class DecisionRequired(FastChangeError):
    """The complete request is outside deterministic fast-change scope."""


@dataclass(frozen=True)
class ChangeSpec:
    """Validated request plus mechanically extracted patch paths."""

    repo_root: pathlib.Path
    release_branch: str
    patch: str
    selected_skills: tuple[str, ...]
    classification: str
    tests: tuple[str, ...]
    run_markdown_lint: bool
    commit_message: str
    install_root: pathlib.Path | None
    paths: tuple[str, ...]


def _runtime_installer(repo_root: pathlib.Path) -> pathlib.Path:
    """Resolve this repository's lifecycle runtime, then installed fallback."""

    codex_home = pathlib.Path(
        os.environ.get("CODEX_HOME", pathlib.Path.home() / ".codex")
    ).expanduser()
    candidates = (
        repo_root
        / "skills"
        / "ceratops-skill-lifecycle"
        / "scripts"
        / "runtime"
        / "install-managed-skills.py",
        codex_home
        / "skills"
        / "ceratops-skill-lifecycle"
        / "scripts"
        / "runtime"
        / "install-managed-skills.py",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise DecisionRequired("managed lifecycle runtime installer is missing")


def _run(
    arguments: Sequence[str],
    *,
    cwd: pathlib.Path,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    if input_text is not None:
        raw = subprocess.run(
            list(arguments),
            cwd=cwd,
            input=input_text.encode("utf-8"),
            capture_output=True,
            check=False,
        )
        return subprocess.CompletedProcess(
            raw.args,
            raw.returncode,
            raw.stdout.decode("utf-8", errors="replace"),
            raw.stderr.decode("utf-8", errors="replace"),
        )
    return subprocess.run(
        list(arguments),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _checked(
    arguments: Sequence[str],
    *,
    cwd: pathlib.Path,
    failure: str,
    input_text: str | None = None,
) -> str:
    result = _run(arguments, cwd=cwd, input_text=input_text)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise FastChangeError(f"{failure}: {detail}" if detail else failure)
    return result.stdout.strip()


def _git(
    repo_root: pathlib.Path,
    *arguments: str,
    failure: str | None = None,
    input_text: str | None = None,
) -> str:
    return _checked(
        ["git", "-C", str(repo_root), *arguments],
        cwd=repo_root,
        failure=failure or f"git {' '.join(arguments)} failed",
        input_text=input_text,
    )


def _request(path: pathlib.Path) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DecisionRequired(f"request is unreadable: {exc}") from exc
    if not isinstance(value, Mapping):
        raise DecisionRequired("request must be a JSON object")
    if not REQUIRED_ROOT_FIELDS.issubset(value) or not set(value).issubset(
        ROOT_FIELDS
    ):
        missing = sorted(REQUIRED_ROOT_FIELDS - set(value))
        extra = sorted(set(value) - ROOT_FIELDS)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("unknown " + ", ".join(extra))
        raise DecisionRequired("request fields are invalid: " + "; ".join(detail))
    if value.get("version") != REQUEST_VERSION:
        raise DecisionRequired(f"request version must be {REQUEST_VERSION}")
    return value


def _string_list(value: object, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise DecisionRequired(f"{label} must be a list of nonempty strings")
    result = tuple(value)
    if len(set(result)) != len(result):
        raise DecisionRequired(f"{label} values must be unique")
    return result


def _patch_paths(repo_root: pathlib.Path, patch: str) -> tuple[str, ...]:
    if not patch.strip():
        raise DecisionRequired("patch must not be empty")
    check = _run(
        ["git", "-C", str(repo_root), "apply", "--check", "-"],
        cwd=repo_root,
        input_text=patch,
    )
    if check.returncode:
        detail = (check.stderr or check.stdout).strip()
        raise DecisionRequired(f"patch does not apply cleanly: {detail}")
    summary = _checked(
        ["git", "-C", str(repo_root), "apply", "--summary", "-"],
        cwd=repo_root,
        failure="patch summary failed",
        input_text=patch,
    )
    if summary:
        raise DecisionRequired(
            "fast-change patch cannot create, delete, rename, or change file modes"
        )
    numstat = _checked(
        ["git", "-C", str(repo_root), "apply", "--numstat", "-"],
        cwd=repo_root,
        failure="patch path extraction failed",
        input_text=patch,
    )
    paths: list[str] = []
    for line in numstat.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3 or parts[0] == "-" or parts[1] == "-":
            raise DecisionRequired("fast-change patch must contain text-file modifications")
        paths.append(parts[2])
    if not paths or len(set(paths)) != len(paths):
        raise DecisionRequired("patch paths must be nonempty and unique")
    return tuple(paths)


def _inside_skill(path: pathlib.PurePosixPath, skill: str) -> bool:
    root = pathlib.PurePosixPath("skills") / skill
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _declares_markdown_lint(
    repo_root: pathlib.Path, paths: Sequence[str]
) -> bool:
    """Select the repository-owned Markdown check only for Markdown patches."""

    if not any(
        pathlib.PurePosixPath(path).suffix.lower() == ".md" for path in paths
    ):
        return False
    package_path = repo_root / "package.json"
    if not package_path.is_file():
        return False
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DecisionRequired(f"package.json is unreadable: {exc}") from exc
    if not isinstance(package, Mapping):
        raise DecisionRequired("package.json must contain an object")
    scripts = package.get("scripts")
    if scripts is None:
        return False
    if not isinstance(scripts, Mapping):
        raise DecisionRequired("package.json scripts must contain an object")
    command = scripts.get("lint:markdown")
    if command is None:
        return False
    if not isinstance(command, str) or not command.strip():
        raise DecisionRequired("package.json lint:markdown must be nonempty text")
    return True


def _working_paths(repo_root: pathlib.Path) -> set[str]:
    """Return every tracked or untracked non-ignored working-tree path."""

    result = _run(
        [
            "git",
            "-C",
            str(repo_root),
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ],
        cwd=repo_root,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise FastChangeError(
            f"could not inspect working-tree paths: {detail}"
            if detail
            else "could not inspect working-tree paths"
        )
    paths: set[str] = set()
    for entry in result.stdout.split("\0"):
        if not entry:
            continue
        if len(entry) < 4 or entry[2] != " ":
            raise FastChangeError("working-tree status contains an unsupported entry")
        paths.add(entry[3:].replace("\\", "/"))
    return paths


def classify_request(path: pathlib.Path) -> ChangeSpec:
    """Validate and classify the complete request before any mutation."""

    request = _request(path)
    repo_value = request["repo_root"]
    release_branch = request["release_branch"]
    patch = request["patch"]
    classification = request["classification"]
    commit_message = request["commit_message"]
    install_value = request.get("install_root")
    if not isinstance(repo_value, str) or not repo_value:
        raise DecisionRequired("repo_root must be nonempty text")
    if release_branch != RELEASE_BRANCH:
        raise DecisionRequired(f"release_branch must be {RELEASE_BRANCH}")
    if not isinstance(patch, str):
        raise DecisionRequired("patch must be text")
    if classification not in CLASSIFICATIONS:
        raise DecisionRequired(
            "classification must be rules-only or helper"
        )
    if not isinstance(commit_message, str) or not commit_message.strip():
        raise DecisionRequired("commit_message must be nonempty text")
    if install_value is not None and not isinstance(install_value, str):
        raise DecisionRequired("install_root must be text or null")

    selected = _string_list(request["selected_skills"], "selected_skills")
    removed = _string_list(request["removed_skills"], "removed_skills")
    tests = _string_list(request["tests"], "tests")
    if not selected:
        raise DecisionRequired("fast-change requires selected existing skills")
    if removed:
        raise DecisionRequired(
            "skill removal requires update; the request remains the change specification"
        )
    repo_root = pathlib.Path(repo_value).expanduser().resolve(strict=True)
    if not repo_root.is_dir():
        raise DecisionRequired("repo_root must be a directory")
    if (
        _git(repo_root, "rev-parse", "--is-inside-work-tree").strip()
        != "true"
    ):
        raise DecisionRequired("repo_root is not a Git worktree")
    branch = _git(repo_root, "branch", "--show-current").strip()
    if branch != release_branch:
        raise DecisionRequired(
            f"expected branch {release_branch}, got {branch or 'detached HEAD'}"
        )
    if _git(repo_root, "status", "--porcelain").strip():
        raise DecisionRequired("release checkout must be clean")

    for skill in selected:
        if SKILL_NAME_RE.fullmatch(skill) is None:
            raise DecisionRequired(f"selected skill name is unsafe: {skill}")
        root = (repo_root / "skills" / skill).resolve()
        if (
            root.parent != (repo_root / "skills").resolve()
            or not (root / "SKILL.md").is_file()
        ):
            raise DecisionRequired(f"selected skill is not an existing source: {skill}")
    paths = _patch_paths(repo_root, patch)
    owners: set[str] = set()
    has_helper = False
    for value in paths:
        pure = pathlib.PurePosixPath(value.replace("\\", "/"))
        windows = pathlib.PureWindowsPath(value)
        if (
            pure.is_absolute()
            or windows.is_absolute()
            or windows.drive
            or ".." in pure.parts
        ):
            raise DecisionRequired(f"patch path is unsafe: {value}")
        target = repo_root / pathlib.Path(*pure.parts)
        try:
            target.resolve(strict=True).relative_to(repo_root)
        except (FileNotFoundError, ValueError) as exc:
            raise DecisionRequired(
                f"patch target must stay inside the repository: {value}"
            ) from exc
        if target.is_symlink() or not target.is_file():
            raise DecisionRequired(f"patch target must be an existing file: {value}")
        matches = [
            skill for skill in selected if _inside_skill(pure, skill)
        ]
        if len(matches) != 1:
            raise DecisionRequired(
                f"patch target must stay inside one selected skill: {value}"
            )
        owner = matches[0]
        owners.add(owner)
        relative = pure.relative_to(pathlib.PurePosixPath("skills") / owner)
        if "contracts" in relative.parts:
            raise DecisionRequired(
                f"contract changes require update: {value}"
            )
        if (
            "scripts" in relative.parts
            or pure.suffix.lower() in EXECUTABLE_SUFFIXES
        ):
            has_helper = True
    missing = sorted(set(selected) - owners)
    if missing:
        raise DecisionRequired(
            "every selected skill requires a patch path: " + ", ".join(missing)
        )
    if classification == "rules-only":
        if has_helper:
            raise DecisionRequired(
                "executable paths require helper classification and exact tests"
            )
        if tests:
            raise DecisionRequired("rules-only fast-change must not run tests")
    else:
        if not has_helper:
            raise DecisionRequired(
                "helper classification requires an executable skill-local path"
            )
        if not tests or any(PYTEST_NODE_RE.fullmatch(test) is None for test in tests):
            raise DecisionRequired(
                "helper classification requires existing pytest node IDs"
            )
        for test in tests:
            test_path = pathlib.PurePosixPath(test.split("::", 1)[0])
            windows_test_path = pathlib.PureWindowsPath(str(test_path))
            if (
                test_path.is_absolute()
                or windows_test_path.is_absolute()
                or windows_test_path.drive
                or ".." in test_path.parts
            ):
                raise DecisionRequired(f"pytest node path is unsafe: {test}")
            test_file = repo_root / pathlib.Path(*test_path.parts)
            try:
                test_file.resolve(strict=True).relative_to(repo_root)
            except (FileNotFoundError, ValueError) as exc:
                raise DecisionRequired(
                    f"pytest node file does not exist: {test}"
                ) from exc
            if test_file.is_symlink() or not test_file.is_file():
                raise DecisionRequired(f"pytest node file does not exist: {test}")
    _runtime_installer(repo_root)
    run_markdown_lint = _declares_markdown_lint(repo_root, paths)
    return ChangeSpec(
        repo_root=repo_root,
        release_branch=release_branch,
        patch=patch,
        selected_skills=selected,
        classification=classification,
        tests=tests,
        run_markdown_lint=run_markdown_lint,
        commit_message=commit_message.strip(),
        install_root=(
            pathlib.Path(install_value).expanduser().resolve()
            if isinstance(install_value, str) and install_value
            else None
        ),
        paths=paths,
    )


def _installer_command(spec: ChangeSpec) -> list[str]:
    command = [
        sys.executable,
        str(_runtime_installer(spec.repo_root)),
        "--repo-root",
        str(spec.repo_root),
    ]
    if spec.install_root is not None:
        command.extend(("--install-root", str(spec.install_root)))
    for skill in spec.selected_skills:
        command.extend(("--skill", skill))
    return command


def _run_installer(spec: ChangeSpec) -> bool:
    """Run the installer once and report whether activation likely committed."""

    result = _run(_installer_command(spec), cwd=spec.repo_root)
    if result.returncode == 0:
        return True
    raw = (result.stderr or result.stdout).strip()
    activated = False
    candidates = [raw]
    if "{" in raw:
        candidates.append(raw[raw.find("{") :])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            rollback = str(payload.get("rollback", ""))
            activated = payload.get("status") == "cleanup_blocked" or (
                rollback.startswith("incomplete")
            )
        break
    error = FastChangeError(
        f"targeted installation failed: {raw}"
        if raw
        else "targeted installation failed"
    )
    setattr(error, "runtime_activated", activated)
    raise error


def _reverse_patch(spec: ChangeSpec, *, staged: bool) -> None:
    if staged:
        _git(
            spec.repo_root,
            "restore",
            "--staged",
            "--",
            *spec.paths,
            failure="could not unstage helper-owned paths",
        )
    _git(
        spec.repo_root,
        "apply",
        "-R",
        "-",
        input_text=spec.patch,
        failure="could not reverse helper-owned patch",
    )


def execute(spec: ChangeSpec) -> dict[str, object]:
    """Apply, test, install, stage, and commit one classified change."""

    patch_applied = False
    staged = False
    runtime_activated = False
    committed = False
    phase = "patch"
    try:
        _git(
            spec.repo_root,
            "apply",
            "-",
            input_text=spec.patch,
            failure="patch application failed",
        )
        patch_applied = True
        changed = _working_paths(spec.repo_root)
        if changed != set(spec.paths):
            raise FastChangeError(
                "applied diff escaped the declared patch paths"
            )
        _git(
            spec.repo_root,
            "diff",
            "--check",
            failure="git diff --check failed",
        )
        if spec.run_markdown_lint:
            phase = "markdown_lint"
            _checked(
                [
                    "npm.cmd" if sys.platform == "win32" else "npm",
                    "run",
                    "lint:markdown",
                ],
                cwd=spec.repo_root,
                failure="repository Markdown lint failed",
            )
        if spec.classification == "helper":
            phase = "tests"
            _checked(
                [sys.executable, "-m", "pytest", "-q", *spec.tests],
                cwd=spec.repo_root,
                failure="targeted helper tests failed",
            )
        phase = "installation"
        runtime_activated = _run_installer(spec)
        phase = "staging"
        if _working_paths(spec.repo_root) != set(spec.paths):
            raise FastChangeError(
                "tests or installation changed undeclared working-tree paths"
            )
        _git(
            spec.repo_root,
            "add",
            "--",
            *spec.paths,
            failure="could not stage declared paths",
        )
        staged = True
        cached = set(
            _git(spec.repo_root, "diff", "--cached", "--name-only").splitlines()
        )
        unstaged = set(
            _git(spec.repo_root, "diff", "--name-only").splitlines()
        )
        if (
            cached != set(spec.paths)
            or unstaged
            or _working_paths(spec.repo_root) != set(spec.paths)
        ):
            raise FastChangeError(
                "Git staging contains undeclared or unstaged patch paths"
            )
        phase = "commit"
        _git(
            spec.repo_root,
            "commit",
            "-m",
            spec.commit_message,
            failure="commit failed",
        )
        committed = True
        commit = _git(spec.repo_root, "rev-parse", "HEAD").splitlines()[0]
        return {
            "status": "committed",
            "branch": spec.release_branch,
            "commit": commit,
            "skills": list(spec.selected_skills),
        }
    except (FastChangeError, OSError, subprocess.SubprocessError) as exc:
        if committed:
            raise FastChangeError(
                json.dumps(
                    {
                        "phase": "post_commit",
                        "reason": str(exc),
                        "compensation": ["not_attempted_after_commit"],
                    },
                    separators=(",", ":"),
                )
            ) from exc
        runtime_activated = runtime_activated or bool(
            getattr(exc, "runtime_activated", False)
        )
        compensation: list[str] = []
        if patch_applied:
            try:
                _reverse_patch(spec, staged=staged)
                compensation.append("source_restored")
            except (FastChangeError, OSError, subprocess.SubprocessError):
                compensation.append("source_restore_failed")
        if runtime_activated and "source_restored" in compensation:
            try:
                _run_installer(spec)
                compensation.append("runtime_restored")
            except (FastChangeError, OSError, subprocess.SubprocessError):
                compensation.append("runtime_restore_failed")
        raise FastChangeError(
            json.dumps(
                {
                    "phase": phase,
                    "reason": str(exc),
                    "compensation": compensation,
                },
                separators=(",", ":"),
            )
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    """Create the one-request fast-change parser."""

    parser = argparse.ArgumentParser(
        description="Apply one classified direct-release skill change."
    )
    parser.add_argument("--request", required=True, type=pathlib.Path)
    return parser


def _preserved_request_context(path: pathlib.Path) -> dict[str, object]:
    """Return bounded routing fields from a rejected request without mutation."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, Mapping):
        return {}
    patch = value.get("patch")
    files: list[str] = []
    if isinstance(patch, str):
        for line in patch.splitlines():
            if not line.startswith("+++ b/"):
                continue
            candidate = line[6:]
            if candidate and candidate not in files:
                files.append(candidate)
    skills: list[str] = []
    for field in ("selected_skills", "removed_skills"):
        values = value.get(field)
        if isinstance(values, Sequence) and not isinstance(
            values, (str, bytes)
        ):
            for item in values:
                if isinstance(item, str) and item and item not in skills:
                    skills.append(item)
    tests = value.get("tests")
    checks = (
        list(tests)
        if isinstance(tests, Sequence)
        and not isinstance(tests, (str, bytes))
        and all(isinstance(item, str) for item in tests)
        else []
    )
    return {
        "affected_files": files,
        "affected_skills": skills,
        "required_checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    """Classify before mutation, then run the complete fast-change workflow."""

    args = build_parser().parse_args(argv)
    request_path = args.request.expanduser().resolve()
    try:
        spec = classify_request(request_path)
    except (DecisionRequired, OSError, ValueError) as exc:
        preserved = _preserved_request_context(request_path)
        print(
            json.dumps(
                {
                    "status": "decision_required",
                    "reason": str(exc),
                    **preserved,
                    "route": "update",
                    "change_specification": str(request_path),
                },
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    try:
        result = execute(spec)
    except (FastChangeError, OSError, ValueError) as exc:
        detail: object = str(exc)
        try:
            detail = json.loads(str(exc))
        except json.JSONDecodeError:
            pass
        print(
            json.dumps(
                {"status": "error", "detail": detail},
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
