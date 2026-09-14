"""Select repository tools and build exact packages for the public CLI.

Packaging alone never activates an installation. Repository installation calls
packaging then the deployment engine with the source-declared name and version.
Lock refresh is explicit. These build capabilities are not exposed over MCP.
Ordinary PEP 517 tooling executes reviewed source during a build. Build scratch
is owned here and removed on success or failure. Nothing requires a skills
directory or an AI-Agent-Skills checkout after the manager is installed.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import tomllib
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from packaging.markers import Marker
from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import parse_wheel_filename

from .contracts import (
    DeploymentError,
    digest,
    fields,
    manifest,
    read_json,
    registry,
    schema,
    token,
)
from .engine import Engine, global_runtime, run, wheel_metadata
from .storage import Layout


@dataclass(frozen=True)
class ToolSource:
    """A selected checkout's static metadata, never a caller version override."""

    path: Path
    tool_name: str
    version: str
    module: str


def source_file(source: Path, name: str) -> Path:
    """Keep source metadata and locks inside the selected tool directory."""
    path = (source / name).resolve(strict=True)
    if not path.is_relative_to(source) or not path.is_file():
        raise DeploymentError(f"source file escapes tool directory or is not a file: {name}")
    return path


def source_metadata(source: Path) -> ToolSource:
    """Read identity from pyproject and the readiness module from tool.json."""
    source = source.resolve(strict=True)
    config = fields(read_json(source_file(source, "tool.json")), {"schema", "module"})
    schema(config, expected=2)
    project = tomllib.loads(source_file(source, "pyproject.toml").read_text(encoding="utf-8")).get("project")
    if not isinstance(project, dict) or not {"name", "version"} <= project.keys():
        raise DeploymentError("pyproject.toml must declare static project.name and project.version")
    return ToolSource(source, token(project["name"]), token(project["version"], "version"), token(config["module"], "module"))


def resolve_source(source: Path, tool_name: str | None = None) -> ToolSource:
    """Select one declared tool; ambiguity and failed discovery stop before builds.

    A direct tool directory needs no Git. Repository discovery uses Git's tracked
    and non-ignored untracked files, so ignored environments are never scanned.
    The caller's Git environment cannot redirect discovery to another checkout.
    """
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise DeploymentError("source must be a repository or tool directory")
    if tool_name is not None:
        token(tool_name)
    marker = source / "tool.json"
    if marker.exists() or marker.is_symlink():
        candidates = [source_metadata(source)]
    else:
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
        output = run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "tool.json", "**/tool.json"],
                     cwd=source, env=env, timeout=30)
        candidates = []
        for relative in sorted(set(output.split("\0")) - {""}):
            declared = (source / relative).resolve(strict=True)
            if not declared.is_relative_to(source) or declared.name != "tool.json":
                raise DeploymentError("declared tool escapes source directory")
            candidates.append(source_metadata(declared.parent))
    names = [candidate.tool_name for candidate in candidates]
    if len(names) != len(set(names)):
        raise DeploymentError("multiple tool directories declare the same project.name")
    selected = [item for item in candidates if tool_name is None or item.tool_name == tool_name]
    if not selected:
        raise DeploymentError("no declared tool matches the source and tool name")
    if len(selected) != 1:
        raise DeploymentError(f"multiple tools; select --tool-name from: {', '.join(sorted(names))}")
    return selected[0]


def install_from_source(source: Path, tool_name: str | None = None) -> dict:
    """Build the selected checkout release, then activate only that exact release."""
    selected = resolve_source(source, tool_name)
    result = package(selected.path)
    if (result["tool_name"], result["version"]) != (selected.tool_name, selected.version):
        raise DeploymentError("source name or version changed during packaging; installation stopped")
    return Engine().install(result["tool_name"], result["version"])


def package(source: Path, *, lock_only: bool = False) -> dict:
    """Prepare reviewed source without changing any tool's active selection."""
    selected = source_metadata(source)
    source, identity, version = selected.path, selected.tool_name, selected.version
    # The stable installed launcher and readiness protocol consume schema 1.
    # Its legacy field spelling is storage, not a second source of identity.
    config = {"schema": 1, "tool_id": identity, "distribution": identity, "module": selected.module}
    layout = Layout(identity)
    runtime = global_runtime()
    python, uv = runtime.python, runtime.uv
    layout.directory("staging")
    with tempfile.TemporaryDirectory(prefix="package_", dir=layout.path("staging")) as work:
        temporary = Path(work)
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("UV_", "PIP_", "PYTHON"))}
        env.update({"UV_CACHE_DIR": str(layout.directory("cache")), "UV_NO_CONFIG": "1", "UV_PYTHON_DOWNLOADS": "never", "TEMP": work, "TMP": work})
        lock = source / "pylock.toml"
        if lock.exists() or lock.is_symlink():
            source_file(source, "pylock.toml")
        if lock_only:
            run([str(uv), "pip", "compile", "pyproject.toml", "--python", str(python), "--python-platform", "windows",
                 "--format", "pylock.toml", "--output-file", "pylock.toml", "--no-header", "--no-config", "--no-sources"], cwd=source, env=env)
            return {"lock": str(lock)}
        locked = tomllib.loads(source_file(source, "pylock.toml").read_text(encoding="utf-8"))
        run([str(uv), "build", str(source), "--wheel", "--out-dir", str(temporary), "--python", str(python), "--no-config", "--no-sources"], cwd=source, env=env)
        wheels = list(temporary.glob("*.whl"))
        if len(wheels) != 1 or wheel_metadata(wheels[0]) != (identity.replace("-", "_"), version):
            raise DeploymentError("built wheel does not match source identity and version")
        if source_metadata(source) != selected:
            raise DeploymentError("source metadata changed during the build")
        supported = list(cpython_tags((3, 14), ["cp314"], ["win_amd64"])) + list(compatible_tags((3, 14), "cp314", ["win_amd64"]))
        ranks = {tag: index for index, tag in enumerate(supported)}
        marker_environment = {"implementation_name": "cpython", "implementation_version": runtime.python_version,
                              "os_name": "nt", "platform_machine": "AMD64", "platform_python_implementation": "CPython",
                              "platform_system": "Windows", "python_full_version": runtime.python_version,
                              "python_version": "3.14", "sys_platform": "win32", "extra": ""}
        for dependency in locked.get("packages", []):
            if dependency.get("marker") and not Marker(dependency["marker"]).evaluate(marker_environment):
                continue
            if not dependency.get("version"):
                raise DeploymentError("lock requires an exact package version")
            candidates = []
            for wheel in dependency.get("wheels", []):
                url = urllib.parse.urlparse(wheel["url"])
                filename = Path(urllib.parse.unquote(url.path)).name
                if url.scheme != "https" or url.hostname != "files.pythonhosted.org":
                    raise DeploymentError("release dependencies must use official PyPI wheel artifacts")
                _, _, _, tags = parse_wheel_filename(filename)
                compatible = tags.intersection(ranks)
                if compatible:
                    candidates.append((min(ranks[t] for t in compatible), filename, wheel))
            if not candidates:
                raise DeploymentError(f"no compatible locked wheel for {dependency['name']}")
            _, filename, wheel = min(candidates, key=lambda value: (value[0], value[1]))
            token(filename, "wheel")
            destination = temporary / filename
            with urllib.request.urlopen(wheel["url"], timeout=60) as response, destination.open("xb") as output:
                if urllib.parse.urlparse(response.url).hostname != "files.pythonhosted.org":
                    raise DeploymentError("dependency artifact redirect escaped PyPI")
                shutil.copyfileobj(response, output)
            if digest(destination) != wheel["hashes"]["sha256"]:
                raise DeploymentError("locked dependency digest mismatch")
            wheels.append(destination)
        release = manifest({**config, "version": version, "wheels": [{"filename": p.name, "sha256": digest(p)} for p in sorted(wheels)]})
        manifest_path = temporary / "manifest.json"
        manifest_path.write_text(json.dumps(release, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        release_hash = digest(manifest_path)
        with layout.lock("registry"):
            catalog_path = layout.path("registry.json")
            catalog = registry(read_json(catalog_path) if catalog_path.exists() else {"schema": 1, "tool_id": identity, "versions": {}}, identity)
            versions = catalog["versions"]
            if version in versions and versions[version] != release_hash:
                raise DeploymentError("version already identifies another artifact; publish a new version")
            target = layout.path("artifacts", version, release_hash)
            if not target.exists():
                layout.directory("artifacts", version)
                # Source is the verified temporary root; destination cannot be
                # caller-selected and the registry is committed only afterwards.
                staged = temporary / "release"
                staged.mkdir()
                for file in [*wheels, manifest_path]:
                    shutil.copyfile(file, staged / file.name)
                os.replace(staged, target)
            for file in [*wheels, manifest_path]:
                if digest(layout.path("artifacts", version, release_hash, file.name)) != digest(file):
                    raise DeploymentError("existing immutable artifact is incomplete or changed")
            versions[version] = release_hash
            layout.atomic_json(catalog_path, registry(catalog, identity))
        return {"tool_name": identity, "version": version, "manifest_sha256": release_hash}
