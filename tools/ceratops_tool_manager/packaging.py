"""Build and register exact local tool packages for the manager's public CLI.

Packaging is explicit and never activates an installation. It writes the source
lock (with lock_only) or immutable artifacts and registry records in the tool
store. This capability is not exposed over the deployment-only MCP interface.
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
from .engine import global_runtime, run, wheel_metadata
from .storage import Layout


def package(source: Path, *, lock_only: bool = False) -> dict:
    """Prepare reviewed source without changing any tool's active selection."""
    source = source.resolve(strict=True)
    config = fields(read_json(source / "tool.json"), {"schema", "tool_id", "distribution", "module"})
    schema(config)
    for key in ("tool_id", "distribution"):
        token(config[key])
    token(config["module"], "module")
    project = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = token(project["version"], "version")
    if project["name"] != config["distribution"]:
        raise DeploymentError("source distribution identity mismatch")
    identity = config["tool_id"]
    layout = Layout(identity)
    runtime = global_runtime()
    python, uv = runtime.python, runtime.uv
    layout.directory("staging")
    with tempfile.TemporaryDirectory(prefix="package_", dir=layout.path("staging")) as work:
        temporary = Path(work)
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("UV_", "PIP_", "PYTHON"))}
        env.update({"UV_CACHE_DIR": str(layout.directory("cache")), "UV_NO_CONFIG": "1", "UV_PYTHON_DOWNLOADS": "never", "TEMP": work, "TMP": work})
        lock = source / "pylock.toml"
        if lock_only:
            run([str(uv), "pip", "compile", "pyproject.toml", "--python", str(python), "--python-platform", "windows",
                 "--format", "pylock.toml", "--output-file", "pylock.toml", "--no-header", "--no-config", "--no-sources"], cwd=source, env=env)
            return {"lock": str(lock)}
        locked = tomllib.loads(lock.read_text(encoding="utf-8"))
        run([str(uv), "build", str(source), "--wheel", "--out-dir", str(temporary), "--python", str(python), "--no-config", "--no-sources"], cwd=source, env=env)
        wheels = list(temporary.glob("*.whl"))
        if len(wheels) != 1 or wheel_metadata(wheels[0]) != (config["distribution"].replace("-", "_"), version):
            raise DeploymentError("built wheel does not match source identity and version")
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
            catalog = registry(read_json(catalog_path), identity) if catalog_path.exists() else {"schema": 1, "tool_id": identity, "versions": {}}
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
        return {"tool_id": identity, "version": version, "manifest_sha256": release_hash}
