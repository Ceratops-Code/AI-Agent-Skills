"""Validate source packaging and deployment contracts without network access."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.tool_manager.test_engine import (
    cli,
    contracts,
    deployment,  # noqa: F401 - shared offline deployment fixture
    engine_module,
    make_release,
    storage,
)

ROOT = Path(__file__).resolve().parents[2]
package_module = importlib.import_module("ceratops_tool_manager.packaging")


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(sys.platform != "win32", reason="Global runtime prerequisites require Windows")
@pytest.mark.parametrize("case", ["valid", "missing-python", "missing-uv", "private-runtime", "old-python", "old-uv", "invalid-probe"])
def test_deploy_completes_launchers_after_runtime_record(tmp_path, monkeypatch, case):
    """Validate the global Runtime record before provisioning either launcher."""
    module = load("deploy-tool-manager")
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
    assert layout.path("bin", "ceratops_tool_manager.py").is_file()
    assert layout.path("bin", "ceratops_tool_manager.cmd").is_file()
    layout.path("bin", "ceratops_tool_manager.py").write_text("retained launcher")
    module.ensure_launchers(layout)
    assert layout.path("bin", "ceratops_tool_manager.py").read_text() == "retained launcher"


@pytest.fixture
def source_package(tmp_path, monkeypatch, request):
    """Provide reviewed source and an offline wheel builder; writes stay in tmp_path."""
    runtime_root = tmp_path / "installed"
    runtime_root.mkdir()
    monkeypatch.setattr(storage, "INSTALL_ROOT", runtime_root)
    seed = tmp_path / "seed"
    seed.mkdir()
    identity = getattr(request, "param", "fixture")
    bundle = make_release(seed, "1.0.0", tool=identity)
    project = tmp_path / "reviewed source"
    project.mkdir()
    (project / "tool.json").write_text(json.dumps({"schema": 1, "tool_id": identity, "distribution": identity, "module": "fixture"}))
    (project / "pyproject.toml").write_text(f'[project]\nname="{identity}"\nversion="1.0.0"\n')
    (project / "pylock.toml").write_text('lock-version="1.0"\npackages=[]\n')
    runtime = engine_module.Runtime(tmp_path / "python.exe", tmp_path / "uv.exe", "3.14.7", "0.12.10")
    monkeypatch.setattr(package_module, "global_runtime", lambda: runtime)
    calls = []

    def build(command, **kwargs):
        calls.append((command, kwargs))
        if "compile" in command:
            (project / "pylock.toml").write_text('lock-version="1.0"\npackages=[]\n')
            return ""
        destination = Path(command[command.index("--out-dir") + 1])
        source = next(bundle.glob("*.whl"))
        (destination / source.name).write_bytes(source.read_bytes())
        return ""

    monkeypatch.setattr(package_module, "run", build)
    return project, runtime_root, calls


def test_packaging_refuses_changed_version_and_publishes_atomically(source_package):
    project, runtime_root, _ = source_package
    make_release(runtime_root, "1.0.0")
    with pytest.raises(contracts.DeploymentError, match="another artifact"):
        package_module.package(project)
    registry_path = runtime_root / "fixture/registry.json"
    registry_path.write_text('{"schema":1,"tool_id":"fixture","versions":{}}')
    result = package_module.package(project)
    assert json.loads(registry_path.read_text())["versions"]["1.0.0"] == result["manifest_sha256"]
    assert not list((runtime_root / "fixture/staging").iterdir())
    assert package_module.package(project) == result
    assert not (runtime_root / "fixture/current.json").exists()


@pytest.mark.usefixtures("deployment")
@pytest.mark.parametrize("source_package", ["fixture", "form-filling"], indirect=True)
def test_cli_packages_then_installs_through_existing_engine(source_package, tmp_path, monkeypatch, capsys):
    project, runtime_root, calls = source_package
    identity = json.loads((project / "tool.json").read_text())["tool_id"]
    outside = tmp_path / "another checkout"
    outside.mkdir()
    monkeypatch.chdir(outside)
    assert cli.main(["package", "--source", str(project)]) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert not output.err and len(output.out.splitlines()) == 1
    assert result["tool_id"] == identity and result["version"] == "1.0.0"
    assert len(calls) == 1 and calls[0][1]["cwd"] == project
    assert not (runtime_root / identity / "current.json").exists()
    assert cli.main(["install", identity, "1.0.0"]) == 0
    assert json.loads(capsys.readouterr().out)["installed_version"] == "1.0.0"


def test_cli_lock_refresh_does_not_build_register_or_activate(source_package, capsys):
    project, runtime_root, calls = source_package
    (project / "pylock.toml").unlink()
    assert cli.main(["package", "--source", str(project), "--lock"]) == 0
    assert json.loads(capsys.readouterr().out) == {"lock": str(project / "pylock.toml")}
    assert len(calls) == 1 and calls[0][0][1:3] == ["pip", "compile"]
    assert not (runtime_root / "fixture/registry.json").exists()
    assert not (runtime_root / "fixture/current.json").exists()
    assert not list((runtime_root / "fixture/staging").iterdir())


@pytest.mark.parametrize("arguments", [["package"], ["package", "--source", ".", "--root", "elsewhere"]])
def test_cli_package_requires_explicit_source_and_rejects_extra_inputs(arguments, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_cli_package_failure_keeps_bounded_diagnostics(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise contracts.DeploymentError("x" * 5000 + " useful diagnostic")

    monkeypatch.setattr(package_module, "package", fail)
    assert cli.main(["package", "--source", "."]) == 2
    output = capsys.readouterr()
    diagnostic = json.loads(output.err)["error"]
    assert output.out == "" and len(diagnostic) == 1800
    assert diagnostic.endswith("useful diagnostic")


@pytest.mark.parametrize("failure", [None, "libraries", "package"])
def test_first_install_uses_manager_packaging_and_cleans_temporary_libraries(tmp_path, monkeypatch, failure):
    module = load("deploy-tool-manager")
    monkeypatch.setattr(storage, "INSTALL_ROOT", tmp_path / "installed")
    engine = engine_module.Engine()
    runtime = engine_module.Runtime(tmp_path / "python.exe", tmp_path / "uv.exe", "3.14.7", "0.12.10")
    calls = []
    original_path = sys.path.copy()

    def provision(command, **kwargs):
        libraries = Path(command[command.index("--target") + 1])
        calls.append(libraries)
        assert command[:4] == [str(runtime.uv), "pip", "sync", str(module.SOURCE / "pylock.toml")]
        assert "--require-hashes" in command and "--only-binary" in command
        libraries.mkdir()
        if failure == "libraries":
            raise contracts.DeploymentError("library provisioning failed")
        return ""

    def package(source):
        assert source == module.SOURCE
        assert sys.path[0] == str(calls[0])
        if failure == "package":
            raise contracts.DeploymentError("package failed")
        return {"tool_id": "ceratops_tool_manager", "version": "0.2.3"}

    monkeypatch.setattr(module, "run", provision)
    monkeypatch.setattr(package_module, "package", package)
    if failure:
        with pytest.raises(contracts.DeploymentError, match="failed"):
            module.package_manager(engine, runtime)
    else:
        assert module.package_manager(engine, runtime)["version"] == "0.2.3"
    assert sys.path == original_path
    assert len(calls) == 1 and not calls[0].parent.exists()
    assert not list(engine.layout.path("staging").iterdir())


@pytest.mark.parametrize("state", ["first-install", "already-installed", "packaging-failed"])
def test_first_install_stops_before_later_mutation_on_failure(monkeypatch, capsys, state):
    module = load("deploy-tool-manager")
    events = []
    runtime = object()

    def install(identity, version):
        events.append("install")
        return {"tool_id": identity, "installed_version": version}

    engine = SimpleNamespace(
        selected=lambda identity: {} if state == "already-installed" else None,
        layout=object(),
        install=install,
    )

    def package_manager(selected_engine, selected_runtime):
        assert selected_engine is engine and selected_runtime is runtime
        events.append("package")
        if state == "packaging-failed":
            raise contracts.DeploymentError("package failed")
        return {"version": "0.2.3"}

    monkeypatch.setattr(module, "global_runtime", lambda: runtime)
    monkeypatch.setattr(module, "Engine", lambda: engine)
    monkeypatch.setattr(module, "package_manager", package_manager)
    monkeypatch.setattr(module, "ensure_launchers", lambda layout: events.append("launchers"))
    assert module.main() == (0 if state == "first-install" else 2)
    output = capsys.readouterr()
    if state == "first-install":
        assert events == ["package", "launchers", "install"]
        assert json.loads(output.out)["installed_version"] == "0.2.3" and not output.err
    else:
        assert events == ([] if state == "already-installed" else ["package"])
        assert not output.out and output.err


def test_first_install_import_needs_no_third_party_site_packages(tmp_path):
    script = ROOT / "scripts/deploy-tool-manager.py"
    code = "import runpy,sys; sys.path.insert(0,sys.argv[1]); module=runpy.run_path(sys.argv[2]); assert callable(module['package_manager'])"
    result = subprocess.run([sys.executable, "-S", "-B", "-c", code, str(script.parent), str(script)],
                            cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_packaging_cli_needs_only_tool_package_not_repository_scripts(tmp_path):
    """Exercise the public command with only the tool package on its import path."""
    isolated = tmp_path / "standalone"
    isolated.mkdir()
    package_root = ROOT / "tools/ceratops_tool_manager"
    shutil.copytree(package_root, isolated / "ceratops_tool_manager", ignore=shutil.ignore_patterns("__pycache__"))
    seed = tmp_path / "seed"
    seed.mkdir()
    bundle = make_release(seed, "1.0.0")
    project = tmp_path / "reviewed source"
    project.mkdir()
    (project / "tool.json").write_text(json.dumps({"schema": 1, "tool_id": "fixture", "distribution": "fixture", "module": "fixture"}))
    (project / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="1.0.0"\n')
    (project / "pylock.toml").write_text('lock-version="1.0"\npackages=[]\n')
    code = """
import shutil, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from ceratops_tool_manager import packaging, storage
from ceratops_tool_manager.cli import main
from ceratops_tool_manager.engine import Runtime
storage.INSTALL_ROOT = Path(sys.argv[2])
packaging.global_runtime = lambda: Runtime(Path(sys.executable), Path('uv.exe'), '3.14.7', '0.12.10')
def build(command, **kwargs):
    shutil.copyfile(sys.argv[4], Path(command[command.index('--out-dir') + 1]) / Path(sys.argv[4]).name)
    return ''
packaging.run = build
raise SystemExit(main(['package', '--source', sys.argv[3]]))
"""
    store = tmp_path / "installed"
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(isolated), str(store), str(project), str(next(bundle.glob("*.whl")))],
                            cwd=isolated, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["tool_id"] == "fixture"
    assert (store / "fixture/registry.json").is_file()
    assert not (store / "fixture/current.json").exists()
