"""Collect local-repository facts for contract evaluation."""

from __future__ import annotations

import fnmatch
import json
import pathlib
import re
import subprocess
from typing import Any


USES_RE = re.compile(r"^\s*uses:\s*([^@\s]+)@([^\s#]+)", re.MULTILINE)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PUBLISH_RE = re.compile(
    r"(gh release|npm\s+(?:stage\s+)?publish|twine upload|pypa/gh-action-pypi-publish|docker/build-push-action|docker push|cargo publish|gem push|nuget push|mvn deploy|Publish-Module)",
    re.IGNORECASE,
)
NPM_PUBLISH_RE = re.compile(r"\bnpm\s+(?:stage\s+)?publish\b", re.IGNORECASE)
SITE_PUBLISH_RE = re.compile(
    r"(actions/(?:deploy-pages|upload-pages-artifact)@|peaceiris/actions-gh-pages@|github-pages-deploy-action@|mkdocs\s+gh-deploy\b|\bgh-pages\s+(?:-d|--dist)\b)",
    re.IGNORECASE,
)
SECRET_NAME_RE = re.compile(
    r"\b(?:ARG|ENV)\s+[A-Za-z0-9_]*(?:TOKEN|SECRET|PASSWORD|KEY)[A-Za-z0-9_]*\b",
    re.IGNORECASE,
)
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
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
}
DEPENDABOT_PATTERNS = {
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
ARTIFACT_DETECTOR_KEYS = {
    "artifact_type",
    "confidence",
    "when_any_path_matches",
    "and_when_any_path_matches",
    "and_when_matching_path_contains_any",
    "when_workflow_contains_any",
    "and_when_workflow_contains_any",
    "when_release_assets_count_gt",
    "when",
    "except_when_root_manifest_is_private_without_publish_surface",
}
ARTIFACT_DETECTOR_WHEN = {
    "repo.has_pages == true",
    "no_artifact_detectors_match && release_assets_count == 0 && no_publish_workflow_detected",
}
COLLECTION_KEYS = {"regex_patterns", "ignore_paths"}


def path_matches(paths: list[str], patterns: list[str]) -> bool:
    """Return whether any normalized repository path matches any glob."""

    return any(fnmatch.fnmatch(path, pattern) for path in paths for pattern in patterns)


def matching_paths(paths: list[str], patterns: list[str]) -> list[str]:
    """Return stable repository paths matching any glob."""

    return sorted(
        {
            path
            for path in paths
            for pattern in patterns
            if fnmatch.fnmatch(path, pattern)
        }
    )


def _readable_text(path: pathlib.Path) -> bool:
    return (
        path.name in {"Dockerfile", "Gemfile"}
        or path.suffix.lower() in TEXT_SUFFIXES
        or path.name.startswith("README")
    )


def scan_local(path: str | None) -> dict[str, Any]:
    """Read bounded in-repository text without following symlinks or build trees."""

    if not path:
        return {
            "available": False,
            "root": None,
            "files": [],
            "texts": {},
            "errors": ["local repository path was not provided"],
        }
    root = pathlib.Path(path).resolve()
    if not root.is_dir():
        return {
            "available": False,
            "root": str(root),
            "files": [],
            "texts": {},
            "errors": ["local repository path is not a directory"],
        }
    files: list[str] = []
    texts: dict[str, str] = {}
    errors: list[str] = []
    for candidate in root.rglob("*"):
        relative = candidate.relative_to(root)
        if (
            any(part in SKIP_DIRS for part in relative.parts)
            or candidate.is_symlink()
            or not candidate.is_file()
        ):
            continue
        name = relative.as_posix()
        files.append(name)
        if _readable_text(candidate) and candidate.stat().st_size <= 1_000_000:
            try:
                texts[name] = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"{name}: {exc}")
    return {
        "available": True,
        "root": str(root),
        "files": sorted(files),
        "texts": texts,
        "errors": errors,
    }


def _workflow_files(local: dict[str, Any]) -> dict[str, str]:
    return {
        path: text
        for path, text in local["texts"].items()
        if path.startswith(".github/workflows/")
        and path.lower().endswith((".yml", ".yaml"))
    }


def workflows_with_unpinned_refs(workflows: dict[str, str]) -> list[dict[str, str]]:
    """Find external Actions references that are not pinned to full SHAs."""

    result: list[dict[str, str]] = []
    for path, text in workflows.items():
        for action, ref in USES_RE.findall(text):
            if action.startswith(("./", "docker://")) or SHA_RE.fullmatch(ref):
                continue
            result.append({"path": path, "action": action, "ref": ref})
    return result


def _permission_matches(
    workflows: dict[str, str], permission: str, *, top_level: bool
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    permission_re = re.compile(
        rf"(?im)^([ \t]*){re.escape(permission)}\s*:\s*write\s*$"
    )
    jobs_re = re.compile(r"(?m)^jobs\s*:\s*$")
    for path, text in workflows.items():
        jobs = jobs_re.search(text)
        for match in permission_re.finditer(text):
            is_top_level = jobs is None or match.start() < jobs.start()
            if is_top_level == top_level:
                result.append({"path": path, "permission": permission})
    return result


def _visible_versions(text: str, tool: str) -> list[str]:
    """Extract explicitly visible runtime or CLI versions from workflow text."""

    patterns = (
        [
            r"(?im)node-version\s*:\s*['\"]?([^'\"\s#]+)",
            r"(?i)setup-node@[^\n]+\n(?:.*\n){0,8}?.*node-version\s*:\s*['\"]?([^'\"\s#]+)",
        ]
        if tool == "node"
        else [
            r"(?i)npm(?:@|\s+install\s+(?:--global\s+|-g\s+)?npm@)([0-9]+(?:\.[0-9]+){0,2}|latest|next)"
        ]
    )
    return sorted(
        {match for pattern in patterns for match in re.findall(pattern, text)}
    )


def _git_state(local: dict[str, Any], default_branch: str | None) -> dict[str, Any]:
    if not local["available"]:
        return {"available": False}
    root = local["root"]

    def run(*args: str) -> tuple[int, str]:
        process = subprocess.run(
            ["git", "-C", root, *args],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        return process.returncode, process.stdout.strip()

    status_code, status = run("status", "--porcelain")
    branch_code, branch = run("branch", "--show-current")
    upstream_code, upstream = run(
        "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    )
    return {
        "available": status_code == 0 and branch_code == 0,
        "worktree_clean": status_code == 0 and not status,
        "current_branch": branch if branch_code == 0 else None,
        "upstream": upstream if upstream_code == 0 else None,
        "tracks_remote_default_branch": bool(
            default_branch
            and upstream_code == 0
            and upstream.endswith(f"/{default_branch}")
        ),
        "raw_status": status,
    }


def _toml_key(text: str, key: str) -> bool:
    return re.search(rf"(?m)^\s*{re.escape(key)}\s*=", text) is not None


def _json(text: str) -> tuple[dict[str, Any], str | None]:
    try:
        value = json.loads(text or "{}")
        return (value if isinstance(value, dict) else {}), None
    except json.JSONDecodeError as exc:
        return {}, str(exc)


def _artifact_types(
    repo: dict[str, Any],
    local: dict[str, Any],
    type_system: dict[str, Any] | None,
    release_assets_count: int,
) -> list[str]:
    """Interpret contract-declared artifact detectors over factual local signals."""

    if not type_system:
        return ["no_artifact"]
    files, texts = local["files"], local["texts"]
    workflow_text = "\n".join(
        text for path, text in texts.items() if path.startswith(".github/workflows/")
    )
    package, _ = _json(texts.get("package.json", ""))
    result: set[str] = set()
    no_artifact_detector = False
    for detector in type_system.get("detectors", []):
        artifact_type = str(detector.get("artifact_type") or "")
        if artifact_type == "no_artifact":
            no_artifact_detector = True
            continue
        matched = True
        if detector.get("when_any_path_matches"):
            matched = matched and path_matches(files, detector["when_any_path_matches"])
        if detector.get("and_when_any_path_matches"):
            matched = matched and path_matches(
                files, detector["and_when_any_path_matches"]
            )
        detector_paths = matching_paths(
            files, detector.get("when_any_path_matches", [])
        )
        matching_text = "\n".join(texts.get(path, "") for path in detector_paths)
        if detector.get("and_when_matching_path_contains_any"):
            matched = matched and any(
                token.lower() in matching_text.lower()
                for token in detector["and_when_matching_path_contains_any"]
            )
        if detector.get("when_workflow_contains_any"):
            matched = matched and any(
                token.lower() in workflow_text.lower()
                for token in detector["when_workflow_contains_any"]
            )
        if detector.get("and_when_workflow_contains_any"):
            matched = matched and any(
                token.lower() in workflow_text.lower()
                for token in detector["and_when_workflow_contains_any"]
            )
        if detector.get("when_release_assets_count_gt") is not None:
            matched = matched and release_assets_count > int(
                detector["when_release_assets_count_gt"]
            )
        condition = detector.get("when")
        if condition == "repo.has_pages == true":
            matched = matched and repo.get("has_pages") is True
        elif condition is not None and condition not in ARTIFACT_DETECTOR_WHEN:
            raise ValueError(f"unsupported artifact detector condition: {condition}")
        if detector.get("except_when_root_manifest_is_private_without_publish_surface"):
            publish_surface = bool(package.get("workspaces")) or bool(
                NPM_PUBLISH_RE.search(workflow_text)
            )
            matched = matched and not (
                package.get("private") is True and not publish_surface
            )
        if matched and artifact_type:
            result.add(artifact_type)
    if not result and no_artifact_detector:
        result.add("no_artifact")
    return sorted(result)


def classify_repository(
    repo: dict[str, Any],
    local: dict[str, Any],
    topics: list[str],
    artifact_type_system: dict[str, Any] | None = None,
    release_assets_count: int = 0,
) -> dict[str, Any]:
    """Derive reusable type facts from raw repository, path, and topic signals."""

    files = local["files"]
    languages: set[str] = set()
    patterns = {
        "python": ["*.py", "pyproject.toml", "requirements*.txt"],
        "javascript_or_typescript": ["*.js", "*.ts", "*.tsx", "package.json"],
        "go": ["go.mod"],
        "dotnet": ["*.csproj", "*.fsproj", "*.vbproj", "*.sln"],
        "rust": ["Cargo.toml", "*.rs"],
        "ruby": ["Gemfile", "*.gemspec", "*.rb"],
        "powershell": ["*.ps1", "*.psm1", "*.psd1"],
        "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "terraform": ["*.tf"],
        "helm": ["Chart.yaml", "charts/**/Chart.yaml"],
        "github_actions": [
            ".github/workflows/*.yml",
            ".github/workflows/*.yaml",
        ],
    }
    for language, globs in patterns.items():
        if path_matches(files, globs):
            languages.add(language)
    yaml_text = "\n".join(
        text
        for path, text in local["texts"].items()
        if path.lower().endswith((".yml", ".yaml"))
    )
    if "apiVersion:" in yaml_text and re.search(
        r"(?m)^kind:\s*(?:Deployment|Service|Ingress)\s*$", yaml_text
    ):
        languages.add("kubernetes")
    artifacts = _artifact_types(repo, local, artifact_type_system, release_assets_count)
    project: set[str] = set()
    if path_matches(
        files,
        [
            "Dockerfile",
            "**/Dockerfile",
            "Procfile",
            "docker-compose.yml",
            "compose.yml",
            "compose.yaml",
            "app/**",
        ],
    ):
        project.add("service_or_app")
    if set(artifacts) & {
        "pypi_python_package",
        "npm_package",
        "maven_package",
        "gradle_maven_package",
        "nuget_package",
        "crates_package",
        "rubygems_package",
        "powershell_gallery_module",
    }:
        project.add("library_or_sdk")
    if languages & {"terraform", "helm", "kubernetes"}:
        project.add("iac")
    if set(artifacts) & {"github_pages_site", "static_docs_site"}:
        project.add("website")
    if "github_actions" in languages or path_matches(
        files, ["action.yml", "action.yaml", "scripts/**"]
    ):
        project.add("automation")
    if path_matches(files, ["src/**", "app/**", "lib/**"]):
        project.add("software")
    if not project and path_matches(files, ["README*", "docs/**"]):
        project.add("documentation_only")
    if not project:
        project.add("unknown")
    return {
        "visibility": repo.get("visibility"),
        "origin": "fork"
        if repo.get("fork")
        else "template"
        if repo.get("is_template")
        else "source",
        "lifecycle": "archived"
        if repo.get("archived")
        else "disabled"
        if repo.get("disabled")
        else "active",
        "topic_signals": topics,
        "workflow_surface": {
            "has_workflows": path_matches(
                files, [".github/workflows/*.yml", ".github/workflows/*.yaml"]
            )
        },
        "language_or_iac": sorted(languages),
        "artifact_surface": artifacts,
        "project_surface": sorted(project),
    }


def _manifest_facts(local: dict[str, Any]) -> dict[str, Any]:
    files, texts = local["files"], local["texts"]
    pyproject = texts.get("pyproject.toml", "")
    package, package_error = _json(texts.get("package.json", ""))
    dockerfiles = matching_paths(files, ["Dockerfile", "**/Dockerfile"])
    docker_details: list[dict[str, Any]] = []
    for path in dockerfiles:
        text = texts.get(path, "")
        docker_details.append(
            {
                "path": path,
                "readable": bool(text),
                "has_from": bool(re.search(r"(?im)^FROM\s+\S+", text)),
                "latest_base_images": re.findall(
                    r"(?im)^FROM\s+(\S+:latest)(?:\s|$)", text
                ),
                "secret_like_arguments": bool(SECRET_NAME_RE.search(text)),
                "stage_count": len(re.findall(r"(?im)^FROM\s+", text)),
            }
        )
    pom = texts.get("pom.xml", "")
    cargo = texts.get("Cargo.toml", "")
    gemspec_text = "\n".join(
        texts.get(path, "") for path in matching_paths(files, ["*.gemspec"])
    )
    powershell_text = "\n".join(
        texts.get(path, "") for path in matching_paths(files, ["*.psd1"])
    )
    return {
        "pypi": {
            "pyproject_present": "pyproject.toml" in files,
            "build_system_present": "[build-system]" in pyproject,
            "project_table_present": "[project]" in pyproject,
            "name_present": _toml_key(pyproject, "name"),
            "version_present": _toml_key(pyproject, "version")
            or _toml_key(pyproject, "dynamic"),
            "description_present": _toml_key(pyproject, "description"),
            "readme_present": _toml_key(pyproject, "readme")
            or _toml_key(pyproject, "description"),
            "license_present": _toml_key(pyproject, "license")
            or _toml_key(pyproject, "license-files"),
            "requires_python_present": _toml_key(pyproject, "requires-python"),
            "maintainer_present": _toml_key(pyproject, "authors")
            or _toml_key(pyproject, "maintainers"),
            "urls_present": _toml_key(pyproject, "urls"),
            "classifiers_present": _toml_key(pyproject, "classifiers"),
        },
        "npm": {
            "valid_json": package_error is None,
            "parse_error": package_error,
            "name_present": bool(package.get("name")),
            "version_present": bool(package.get("version"))
            or bool(package.get("private") and package.get("workspaces")),
            "license_present": bool(package.get("license")),
            "repository_present": bool(package.get("repository")),
            "contents_constrained": bool(package.get("files"))
            or ".npmignore" in files
            or bool(package.get("private") and package.get("workspaces")),
            "reproducible_install": bool(package.get("packageManager"))
            or path_matches(
                files,
                [
                    "package-lock.json",
                    "npm-shrinkwrap.json",
                    "pnpm-lock.yaml",
                    "yarn.lock",
                ],
            ),
            "workspace_root": bool(
                package.get("private") and package.get("workspaces")
            ),
            "name": package.get("name"),
            "version": package.get("version"),
        },
        "docker": {
            "dockerfiles": docker_details,
            "dockerignore_present": ".dockerignore" in files,
            "all_readable": bool(docker_details)
            and all(item["readable"] for item in docker_details),
            "all_have_from": bool(docker_details)
            and all(item["has_from"] for item in docker_details),
            "latest_base_images": [
                image for item in docker_details for image in item["latest_base_images"]
            ],
            "secret_like_arguments": [
                item["path"] for item in docker_details if item["secret_like_arguments"]
            ],
        },
        "maven": {
            "pom_present": "pom.xml" in files,
            "group_present": bool(re.search(r"<groupId>[^<]+</groupId>", pom)),
            "artifact_present": bool(re.search(r"<artifactId>[^<]+</artifactId>", pom)),
            "version_present": bool(re.search(r"<version>[^<]+</version>", pom)),
            "license_present": "<licenses>" in pom,
            "url_present": "<url>" in pom,
        },
        "nuget": {
            "project_files": matching_paths(
                files, ["*.csproj", "*.fsproj", "*.vbproj", "*.nuspec"]
            ),
            "metadata_text": "\n".join(
                texts.get(path, "")
                for path in matching_paths(
                    files, ["*.csproj", "*.fsproj", "*.vbproj", "*.nuspec"]
                )
            ),
        },
        "crates": {
            "cargo_toml_present": "Cargo.toml" in files,
            "name_present": _toml_key(cargo, "name"),
            "version_present": _toml_key(cargo, "version"),
            "license_present": _toml_key(cargo, "license")
            or _toml_key(cargo, "license-file"),
            "description_present": _toml_key(cargo, "description"),
            "readme_present": _toml_key(cargo, "readme") or "README.md" in files,
            "source_link_present": _toml_key(cargo, "repository")
            or _toml_key(cargo, "homepage"),
        },
        "rubygems": {
            "gemspec_files": matching_paths(files, ["*.gemspec"]),
            "name_present": bool(re.search(r"\.name\s*=", gemspec_text)),
            "version_present": bool(re.search(r"\.version\s*=", gemspec_text)),
            "description_present": bool(
                re.search(r"\.(?:summary|description)\s*=", gemspec_text)
            ),
            "license_present": bool(re.search(r"\.licenses?\s*=", gemspec_text)),
            "source_link_present": bool(
                re.search(r"\.(?:homepage|metadata)\s*=", gemspec_text)
            ),
        },
        "powershell_gallery": {
            "manifest_files": matching_paths(files, ["*.psd1"]),
            "version_present": "ModuleVersion" in powershell_text,
            "module_present": "RootModule" in powershell_text
            or "NestedModules" in powershell_text,
            "description_present": "Description" in powershell_text,
            "license_present": "LicenseUri" in powershell_text or "LICENSE" in files,
            "project_uri_present": "ProjectUri" in powershell_text,
            "tags_present": "Tags" in powershell_text,
        },
        "iac": {
            "chart_present": "Chart.yaml" in files,
            "terraform_files": matching_paths(files, ["*.tf"]),
        },
    }


def collect_local_repository(
    path: str | None, rules: list[dict[str, Any]], default_branch: str | None = None
) -> dict[str, Any]:
    """Collect local paths, text-derived facts, configured scans, and git state."""

    local = scan_local(path)
    workflows = _workflow_files(local)
    workflow_text = "\n".join(workflows.values())
    scans: dict[str, Any] = {}
    for rule in rules:
        patterns = rule.get("collection", {}).get("regex_patterns")
        if not patterns:
            continue
        ignored = set(rule.get("collection", {}).get("ignore_paths", []))
        matches: list[dict[str, str]] = []
        for pattern in patterns:
            regex = re.compile(pattern)
            matches.extend(
                {"path": name, "pattern": pattern}
                for name, text in local["texts"].items()
                if name not in ignored and regex.search(text)
            )
        scans[rule["id"]] = {"matches": matches}
    permission_names = ("id-token", "attestations", "artifact-metadata", "packages")
    return {
        **local,
        "workflows": {
            "files": sorted(workflows),
            "text": workflow_text,
            "unpinned_external_refs": workflows_with_unpinned_refs(workflows),
            "permissions_write_all": [
                path
                for path, text in workflows.items()
                if re.search(r"(?im)^\s*permissions\s*:\s*write-all\s*$", text)
            ],
            "top_level_write": {
                name: _permission_matches(workflows, name, top_level=True)
                for name in permission_names
            },
            "any_write": {
                name: _permission_matches(workflows, name, top_level=False)
                + _permission_matches(workflows, name, top_level=True)
                for name in permission_names
            },
            "publish_detected": bool(PUBLISH_RE.search(workflow_text)),
            "attestation_detected": bool(
                re.search(
                    r"(?i)(actions/attest|attestations:\s*write|--provenance\b|sbom|cosign)",
                    workflow_text,
                )
            ),
            "verification_command_detected": bool(
                re.search(
                    r"(?i)(gh attestation verify|cosign verify|cosign verify-attestation)",
                    workflow_text,
                )
            ),
            "contents_read_present": "contents: read" in workflow_text,
            "node_versions": _visible_versions(workflow_text, "node"),
            "npm_versions": _visible_versions(workflow_text, "npm"),
        },
        "dependabot": {
            "config_path": next(
                (
                    name
                    for name in (".github/dependabot.yml", ".github/dependabot.yaml")
                    if name in local["files"]
                ),
                None,
            ),
            "ecosystems": {
                name: matching_paths(local["files"], patterns)
                for name, patterns in DEPENDABOT_PATTERNS.items()
                if path_matches(local["files"], patterns)
            },
        },
        "manifests": _manifest_facts(local),
        "git": _git_state(local, default_branch),
        "scans": scans,
    }
