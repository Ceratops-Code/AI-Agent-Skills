"""Select repository tools and build exact packages for the public CLI.

Packaging alone never activates an installation. Repository installation calls
packaging then the deployment engine with the source-declared name and version.
Lock refresh is explicit. These build capabilities are not exposed over MCP.
Ordinary PEP 517 tooling executes reviewed tool source during a build. A declared
local package may supply a prebuilt wheel and its third-party lock; the package
source is never copied into the tool build. Build scratch is owned here and
removed on success or failure. Nothing requires a skills directory or an
AI-Agent-Skills checkout after the manager is installed.
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
from packaging.requirements import Requirement
from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

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


def install_from_source(source: Path, tool_name: str | None = None, *,
                        package_wheel: Path | None = None,
                        package_lock: Path | None = None) -> dict:
    """Build the tool source, include its declared package wheel, then activate."""
    selected = resolve_source(source, tool_name)
    result = package(selected.path, package_wheel=package_wheel,
                     package_lock=package_lock)
    if (result["tool_name"], result["version"]) != (selected.tool_name, selected.version):
        raise DeploymentError("source name or version changed during packaging; installation stopped")
    return Engine().install(result["tool_name"], result["version"])


def package(source: Path, *, lock_only: bool = False,
            package_wheel: Path | None = None,
            package_lock: Path | None = None) -> dict:
    """Register a tool wheel plus an optional exact local package prerequisite."""
    selected = source_metadata(source)
    source, identity, version = selected.path, selected.tool_name, selected.version
    if (package_wheel is None) != (package_lock is None) or (lock_only and package_wheel is not None):
        raise DeploymentError("package wheel and lock must be supplied together, without --lock")
    required_package: tuple[str, str] | None = None
    if package_wheel is not None:
        # The wheel is a release input, not a source directory. Check its exact
        # distribution/version against the tool's PEP 508 dependency before any
        # registry mutation, and retain a private copy during packaging.
        assert package_lock is not None
        if package_wheel.is_symlink() or package_lock.is_symlink():
            raise DeploymentError("package wheel and lock must be regular files")
        package_wheel = package_wheel.resolve(strict=True)
        package_lock = package_lock.resolve(strict=True)
        if not package_wheel.is_file() or not package_lock.is_file():
            raise DeploymentError("package wheel and lock must be regular files")
        token(package_wheel.name, "wheel")
        required_package = wheel_metadata(package_wheel)
        try:
            filename_name, filename_version, _, filename_tags = parse_wheel_filename(package_wheel.name)
        except ValueError as exc:
            raise DeploymentError("package prerequisite must be a standard wheel") from exc
        supported_tags = set(cpython_tags((3, 14), ["cp314"], ["win_amd64"]))
        supported_tags.update(compatible_tags((3, 14), "cp314", ["win_amd64"]))
        if (canonicalize_name(filename_name) != canonicalize_name(required_package[0])
                or str(filename_version) != required_package[1]
                or not filename_tags.intersection(supported_tags)):
            raise DeploymentError("package wheel filename, metadata, or platform does not match")
        project = tomllib.loads(source_file(source, "pyproject.toml").read_text(encoding="utf-8"))["project"]
        dependencies = project.get("dependencies", [])
        if not isinstance(dependencies, list) or not all(isinstance(value, str) for value in dependencies):
            raise DeploymentError("tool project dependencies must be a list of requirements")
        matching = [requirement for requirement in map(Requirement, dependencies)
                    if canonicalize_name(requirement.name) == canonicalize_name(required_package[0])]
        if len(matching) != 1 or matching[0].url or matching[0].extras or matching[0].marker:
            raise DeploymentError("tool must declare the supplied package as one direct dependency")
        specifications = list(matching[0].specifier)
        if len(specifications) != 1 or specifications[0].operator != "==" or specifications[0].version != required_package[1]:
            raise DeploymentError("tool package dependency must pin the supplied wheel version")
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
        lock = package_lock if package_lock is not None else source / "pylock.toml"
        if package_lock is None and (lock.exists() or lock.is_symlink()):
            source_file(source, "pylock.toml")
        if lock_only:
            run([str(uv), "pip", "compile", "pyproject.toml", "--python", str(python), "--python-platform", "windows",
                 "--format", "pylock.toml", "--output-file", "pylock.toml", "--no-header", "--no-config", "--no-sources"], cwd=source, env=env)
            return {"lock": str(lock)}
        locked = tomllib.loads(lock.read_text(encoding="utf-8") if package_lock is not None
                              else source_file(source, "pylock.toml").read_text(encoding="utf-8"))
        run([str(uv), "build", str(source), "--wheel", "--out-dir", str(temporary), "--python", str(python), "--no-config", "--no-sources"], cwd=source, env=env)
        wheels = list(temporary.glob("*.whl"))
        if len(wheels) != 1 or wheel_metadata(wheels[0]) != (identity.replace("-", "_"), version):
            raise DeploymentError("built wheel does not match source identity and version")
        if package_wheel is not None:
            if wheel_metadata(package_wheel) != required_package:
                raise DeploymentError("package wheel changed before registration")
            copied = temporary / package_wheel.name
            if copied.exists():
                raise DeploymentError("package wheel filename collides with tool wheel")
            shutil.copyfile(package_wheel, copied)
            if wheel_metadata(copied) != required_package or digest(copied) != digest(package_wheel):
                raise DeploymentError("package wheel changed during copying")
            wheels.append(copied)
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
            if required_package is not None and canonicalize_name(dependency["name"]) == canonicalize_name(required_package[0]):
                raise DeploymentError("package lock must not duplicate the supplied package wheel")
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
