"""Validate source packaging and bootstrap contracts without network access."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tests.tool_manager.test_engine import (
    contracts,
    engine_module,
    make_release,
    storage,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / (name + ".py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(sys.platform != "win32", reason="Global runtime prerequisites require Windows")
@pytest.mark.parametrize("case", ["valid", "missing-python", "missing-uv", "private-runtime", "old-python", "old-uv", "invalid-probe"])
def test_bootstrap_completes_launchers_after_runtime_record(tmp_path, monkeypatch, case):
    """Validate the global Runtime record before provisioning either launcher."""
    module = load("bootstrap-tool-manager")
    store = tmp_path / "installed"
    monkeypatch.setattr(storage, "INSTALL_ROOT", store)
    monkeypatch.setattr(engine_module, "INSTALL_ROOT", store)
    python_root = store / "private" if case == "private-runtime" else tmp_path / "global"
    python_root.mkdir(parents=True)
    python = python_root / "python.exe"
    if case != "missing-python":
        python.write_bytes(b"stub")
    uv = tmp_path / "uv.exe"
    uv.write_bytes(b"stub")
    monkeypatch.setattr(engine_module.sys, "base_prefix", str(python_root))
    monkeypatch.setattr(engine_module.shutil, "which", lambda command: None if case == "missing-uv" else str(uv))

    def probe(command, **kwargs):
        if "--version" in command:
            return "uv 0.12.9" if case == "old-uv" else "uv 0.12.10 (test)"
        return "invalid" if case == "invalid-probe" else json.dumps(["cpython", [3, 13, 12] if case == "old-python" else [3, 14, 7], 64])

    monkeypatch.setattr(engine_module, "run", probe)
    layout = storage.Layout()
    if case != "valid":
        with pytest.raises(contracts.DeploymentError):
            module.ensure_launchers(layout)
        assert not layout.root.exists()
        return
    runtime = module.global_runtime()
    assert runtime.python == python and runtime.uv == uv
    module.ensure_launchers(layout)
    assert layout.path("bin", "ceratops-tool-manager.py").is_file()
    assert layout.path("bin", "ceratops-tool-manager.cmd").is_file()
    layout.path("bin", "ceratops-tool-manager.py").write_text("retained launcher")
    module.ensure_launchers(layout)
    assert layout.path("bin", "ceratops-tool-manager.py").read_text() == "retained launcher"


def test_packaging_refuses_changed_version_and_publishes_atomically(tmp_path, monkeypatch):
    module = load("package-tool-release")
    runtime_root = tmp_path / "installed"
    runtime_root.mkdir()
    monkeypatch.setattr(storage, "INSTALL_ROOT", runtime_root)
    bundle = make_release(runtime_root, "1.0.0")
    project = tmp_path / "source"
    project.mkdir()
    (project / "tool.json").write_text(json.dumps({"schema": 1, "tool_id": "fixture", "distribution": "fixture", "module": "fixture"}))
    (project / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="1.0.0"\n')
    (project / "pylock.toml").write_text('lock-version="1.0"\npackages=[]\n')
    runtime = engine_module.Runtime(tmp_path / "python.exe", tmp_path / "uv.exe", "3.14.7", "0.12.10")
    monkeypatch.setattr(module, "global_runtime", lambda: runtime)

    def build(command, **kwargs):
        destination = Path(command[command.index("--out-dir") + 1])
        source = next(bundle.glob("*.whl"))
        (destination / source.name).write_bytes(source.read_bytes())
        return ""

    monkeypatch.setattr(module, "run", build)
    with pytest.raises(contracts.DeploymentError, match="another artifact"):
        module.package(project)
    registry_path = runtime_root / "fixture/registry.json"
    registry_path.write_text('{"schema":1,"tool_id":"fixture","versions":{}}')
    result = module.package(project)
    assert json.loads(registry_path.read_text())["versions"]["1.0.0"] == result["manifest_sha256"]
    assert not list((runtime_root / "fixture/staging").iterdir())
    assert module.package(project) == result
