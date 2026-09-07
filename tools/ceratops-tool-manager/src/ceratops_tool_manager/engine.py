"""One deployment engine shared by bootstrap, CLI, and MCP.

Only locally registered, hash-selected wheel sets may execute. A package's
fixed readiness entry point is trusted release code, not a sandbox. The local
registry is a development capability and must never be exposed to Forms.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any

from . import TOOL_ID, __version__
from .contracts import (
    DeploymentError,
    active,
    digest,
    manifest,
    read_json,
    registry,
    token,
)
from .storage import INSTALL_ROOT, Layout


def child_environment(layout: Layout, temporary: Path) -> dict[str, str]:
    """Do not inherit Python, pip, uv, proxy, or user-site execution overrides."""
    env = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC"}}
    env.update({
        "PATH": str(Path(sys.executable).parent),
        "TEMP": str(temporary), "TMP": str(temporary),
        "UV_CACHE_DIR": str(layout.directory("cache")),
        "UV_PYTHON_DOWNLOADS": "never", "UV_NO_CONFIG": "1",
        "UV_LINK_MODE": "copy", "PYTHONDONTWRITEBYTECODE": "1",
    })
    return env


def run(command: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 120) -> str:
    try:
        result = subprocess.run(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=timeout, check=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeploymentError(f"candidate command unavailable or timed out: {Path(command[0]).name}") from exc
    if result.returncode:
        raise DeploymentError(f"candidate validation failed: {result.stderr[-1800:].strip()}")
    return result.stdout


@dataclass(frozen=True)
class Runtime:
    """Validated existing global prerequisites; deployment never provisions them."""

    python: Path
    uv: Path
    python_version: str
    uv_version: str


def global_runtime() -> Runtime:
    """Resolve global CPython and uv without using a tool's private environment.

    A virtual environment records its base interpreter in sys.base_prefix.
    Both prerequisites must remain outside the deployment store. Probes are
    fixed commands, take no caller paths, and run before candidate creation.
    """
    if os.name != "nt":
        raise DeploymentError("deployment supports Windows x64")
    python = Path(sys.base_prefix) / "python.exe"
    selected_uv = shutil.which("uv")
    if not python.is_file() or selected_uv is None:
        raise DeploymentError("install global CPython 3.14 and uv 0.12.10 or newer 0.12.x first")
    python, uv = python.resolve(), Path(selected_uv).resolve()
    if any(path.is_relative_to(INSTALL_ROOT.resolve()) for path in (python, uv)) or not uv.is_file():
        raise DeploymentError("Python and uv must be global installations outside the tool store")
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith(("PYTHON", "PIP_", "UV_"))}
    probe = "import json,struct,sys; print(json.dumps([sys.implementation.name,list(sys.version_info[:3]),struct.calcsize('P')*8]))"
    try:
        implementation, version, bits = json.loads(run([str(python), "-I", "-B", "-c", probe], cwd=python.parent, env=env, timeout=15))
        valid_version = isinstance(version, list) and len(version) == 3 and all(type(part) is int for part in version)
        if implementation != "cpython" or not valid_version or version[:2] != [3, 14] or bits != 64:
            raise DeploymentError("global Python must be 64-bit CPython 3.14.x")
        output = run([str(uv), "--version"], cwd=uv.parent, env=env, timeout=15)
        match = re.match(r"uv (0\.12\.([0-9]+))(?:\s|$)", output)
        if match is None or int(match[2]) < 10:
            raise DeploymentError("global uv must be 0.12.10 or a newer 0.12.x release")
    except (TypeError, ValueError) as exc:
        if isinstance(exc, DeploymentError):
            raise
        raise DeploymentError("invalid global prerequisite probe") from exc
    return Runtime(python, uv, ".".join(map(str, version)), match[1])


def wheel_metadata(path: Path) -> tuple[str, str]:
    """Reject unsafe archives before handing supported wheel installs to uv."""
    try:
        with zipfile.ZipFile(path) as archive:
            seen: set[str] = set()
            metadata = []
            size = 0
            for item in archive.infolist():
                name = item.orig_filename
                parts = PurePosixPath(name).parts
                if (not parts or name.startswith("/") or "\\" in name or ":" in name
                        or any(p in {".", ".."} or p.endswith((".", " ")) for p in parts)
                        or (item.external_attr >> 16) & 0o170000 == 0o120000
                        or name.casefold() in seen):
                    raise DeploymentError("unsafe wheel member")
                seen.add(name.casefold())
                size += item.file_size
                if size > 1_000_000_000 or len(seen) > 20000:
                    raise DeploymentError("wheel exceeds resource limits")
                if name.endswith(".dist-info/METADATA") and len(parts) == 2:
                    metadata.append(name)
            if len(metadata) != 1:
                raise DeploymentError("wheel must contain one distribution metadata record")
            data = BytesParser().parsebytes(archive.read(metadata[0]))
            return str(data["Name"]).lower().replace("_", "-"), str(data["Version"])
    except (OSError, zipfile.BadZipFile) as exc:
        raise DeploymentError("invalid wheel") from exc


class Engine:
    def __init__(self) -> None:
        self.layout = Layout()
        self.running_version = __version__ if __version__ != "source" else None

    def selected(self, identity: str) -> dict[str, Any] | None:
        token(identity)
        layout = Layout(identity)
        path = layout.path("current.json")
        if not path.exists():
            return None
        value = active(read_json(path), identity)
        directory = layout.path("versions", value["version"], value["instance"])
        if not directory.is_dir():
            raise DeploymentError("selected installation is missing")
        if not layout.path("versions", value["version"], value["instance"], "environment", "Scripts", "python.exe").is_file():
            raise DeploymentError("selected installation interpreter is missing")
        receipt = active(read_json(layout.path("versions", value["version"], value["instance"], "receipt.json")), identity)
        if receipt != value:
            raise DeploymentError("selected installation receipt mismatch")
        return value

    def versions(self, tool_id: str = TOOL_ID) -> dict[str, Any]:
        """Inspect registry selections and this process without launching a tool."""
        token(tool_id)
        selected = self.selected(tool_id)
        registry_path = Layout(tool_id).path("registry.json")
        catalog = registry(read_json(registry_path), tool_id) if registry_path.exists() else {"versions": {}}
        available = sorted(catalog["versions"], key=lambda v: tuple(map(int, v.split("."))))
        installed = selected["version"] if selected else None
        running = self.running_version if tool_id == TOOL_ID else None
        return {"tool_id": tool_id, "installed_version": installed,
                "running_version": running, "available_versions": available,
                "manifest_sha256": selected["manifest_sha256"] if selected else None,
                "reconnection_required": bool(running and installed and running != installed)}

    def install(self, tool_id: str, version: str) -> dict[str, Any]:
        return self._deploy(tool_id, version, require_installed=False)

    def update(self, tool_id: str, version: str) -> dict[str, Any]:
        return self._deploy(tool_id, version, require_installed=True)

    def _deploy(self, tool_id: str, version: str, *, require_installed: bool) -> dict[str, Any]:
        token(tool_id)
        token(version, "version")
        layout = Layout(tool_id)
        with layout.lock("deployment"):
            previous = self.selected(tool_id)
            if require_installed and previous is None:
                raise DeploymentError("update requires an installed tool; use install first")
            catalog = registry(read_json(layout.path("registry.json")), tool_id)
            sha256 = catalog["versions"].get(version)
            if sha256 is None:
                raise DeploymentError("exact tool version is not registered")
            manifest_path = layout.path("artifacts", version, sha256, "manifest.json")
            if digest(manifest_path) != sha256:
                raise DeploymentError("manifest digest mismatch")
            release = manifest(read_json(manifest_path))
            if (release["tool_id"], release["version"]) != (tool_id, version):
                raise DeploymentError("release selection mismatch")
            if tool_id == TOOL_ID and (release["module"], release["distribution"]) != ("ceratops_tool_manager", TOOL_ID):
                raise DeploymentError("manager entry point is fixed")
            requirements = []
            distributions: dict[str, str] = {}
            for wheel in release["wheels"]:
                path = layout.path("artifacts", version, sha256, wheel["filename"])
                if digest(path) != wheel["sha256"]:
                    raise DeploymentError("wheel digest mismatch")
                name, wheel_version = wheel_metadata(path)
                if name in distributions:
                    raise DeploymentError("duplicate distribution in release")
                distributions[name] = wheel_version
                requirements.append(f"{path.as_uri()} --hash=sha256:{wheel['sha256']}")
            if distributions.get(release["distribution"]) != version:
                raise DeploymentError("tool distribution version mismatch")
            runtime = global_runtime()
            python, uv = runtime.python, runtime.uv
            instance = uuid.uuid4().hex
            candidate = layout.directory("versions", version, instance)
            committed = False
            try:
                temporary = candidate / "tmp"
                temporary.mkdir()
                env = child_environment(layout, temporary)
                lock = candidate / "requirements.txt"
                lock.write_text("\n".join(requirements) + "\n", encoding="utf-8")
                environment = candidate / "environment"
                run([str(uv), "venv", "--no-config", "--python", str(python), str(environment)], cwd=candidate, env=env)
                executable = environment / "Scripts" / "python.exe"
                run([str(uv), "pip", "sync", "--python", str(executable), "--no-config", "--no-index",
                     "--require-hashes", "--only-binary", ":all:", str(lock)], cwd=candidate, env=env)
                run([str(uv), "pip", "check", "--python", str(executable), "--no-config"], cwd=candidate, env=env)
                output = run([str(executable), "-I", "-B", "-m", release["module"], "--deployment-check"], cwd=candidate, env=env, timeout=30)
                try:
                    ready = json.loads(output)
                except json.JSONDecodeError as exc:
                    raise DeploymentError("invalid readiness response") from exc
                if ready != {"tool_id": tool_id, "version": version, "ready": True}:
                    raise DeploymentError("tool readiness failed")
                layout.remove_scratch(temporary)
                selection = {"schema": 1, "tool_id": tool_id, "version": version, "manifest_sha256": sha256,
                             "instance": instance, "module": release["module"]}
                layout.atomic_json(candidate / "receipt.json", selection)
                layout.atomic_json(layout.path("current.json"), selection)
                committed = True
            finally:
                if not committed:
                    layout.remove_candidate(candidate)
            # No fallible post-commit registry reads:  a successful activation is success.
            running = self.running_version if tool_id == TOOL_ID else None
            return {"tool_id": tool_id, "installed_version": version, "running_version": running,
                    "manifest_sha256": sha256, "reconnection_required": bool(running and running != version)}
