"""Validate source packaging and deployment contracts without network access."""

import importlib.util
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.tool_manager.test_engine import (
    cli,
    contracts,
    engine_module,
    make_release,
    storage,
)
from tests.tool_manager.test_engine import (
    deployment as deployment,  # explicit re-export of the shared pytest fixture
)

ROOT = Path(__file__).resolve().parents[2]
package_module = importlib.import_module("ceratops_tool_manager.packaging")
RUN_COMMAND = package_module.run


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
    module = "ceratops_tool_manager" if identity == "ceratops_tool_manager" else "fixture"
    (project / "tool.json").write_text(json.dumps({"schema": 2, "module": module}))
    (project / "pyproject.toml").write_text(f'[project]\nname="{identity}"\nversion="1.0.0"\n')
    (project / "pylock.toml").write_text('lock-version="1.0"\npackages=[]\n')
    runtime = engine_module.Runtime(tmp_path / "python.exe", tmp_path / "uv.exe", "3.14.7", "0.12.10")
    monkeypatch.setattr(package_module, "global_runtime", lambda: runtime)
    calls = []

    def build(command, **kwargs):
        if command[0] == "git":
            return RUN_COMMAND(command, **kwargs)
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
    identity = tomllib.loads((project / "pyproject.toml").read_text())["project"]["name"]
    outside = tmp_path / "another checkout"
    outside.mkdir()
    monkeypatch.chdir(outside)
    assert cli.main(["package", "--source", str(project)]) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert not output.err and len(output.out.splitlines()) == 1
    assert result["tool_name"] == identity and result["version"] == "1.0.0"
    assert len(calls) == 1 and calls[0][1]["cwd"] == project
    assert not (runtime_root / identity / "current.json").exists()
    assert cli.main(["install", "--source", str(project)]) == 0
    assert json.loads(capsys.readouterr().out)["installed_version"] == "1.0.0"
    assert len(calls) == 2
    assert not list((runtime_root / identity / "staging").iterdir())


@pytest.mark.usefixtures("deployment")
def test_package_wheel_prerequisite_is_registered_and_installed_without_package_source(source_package, tmp_path, capsys):
    """The tool build receives only its source; the separate package enters as a wheel."""
    project, runtime_root, calls = source_package
    (tmp_path / "package").mkdir()
    bundle = make_release(tmp_path / "package", "1.0.0", tool="claims_runtime", metadata_name="claims-runtime")
    wheel = next(bundle.glob("*.whl"))
    lock = tmp_path / "package" / "pylock.toml"
    lock.write_text('lock-version="1.0"\npackages=[]\n')
    (project / "pyproject.toml").write_text(
        '[project]\nname="fixture"\nversion="1.0.0"\ndependencies=["claims-runtime==1.0.0"]\n'
    )
    options = ["--source", str(project), "--package-wheel", str(wheel), "--package-lock", str(lock)]
    assert cli.main(["package", *options]) == 0
    registered = json.loads(capsys.readouterr().out)
    assert len(calls) == 1 and calls[0][0][1] == "build"
    release_dir = runtime_root / "fixture" / "artifacts" / "1.0.0" / registered["manifest_sha256"]
    release = json.loads((release_dir / "manifest.json").read_text())
    assert {entry["filename"] for entry in release["wheels"]} == {"fixture-1.0.0-py3-none-any.whl", wheel.name}
    assert (release_dir / wheel.name).read_bytes() == wheel.read_bytes()
    assert not (runtime_root / "fixture" / "current.json").exists()
    assert cli.main(["install", *options]) == 0
    assert json.loads(capsys.readouterr().out)["installed_version"] == "1.0.0"
    assert len(calls) == 2  # one tool build per command; neither builds the package


@pytest.mark.parametrize("case", ["missing-lock", "wrong-version", "undeclared"])
def test_package_wheel_prerequisite_rejects_invalid_contract_before_build(source_package, tmp_path, capsys, case):
    project, runtime_root, calls = source_package
    (tmp_path / "package").mkdir()
    bundle = make_release(tmp_path / "package", "2.0.0" if case == "wrong-version" else "1.0.0",
                          tool="claims_runtime", metadata_name="claims-runtime")
    wheel = next(bundle.glob("*.whl"))
    lock = tmp_path / "package" / "pylock.toml"
    lock.write_text('lock-version="1.0"\npackages=[]\n')
    if case != "undeclared":
        (project / "pyproject.toml").write_text(
            '[project]\nname="fixture"\nversion="1.0.0"\ndependencies=["claims-runtime==1.0.0"]\n'
        )
    options = ["package", "--source", str(project), "--package-wheel", str(wheel)]
    if case != "missing-lock":
        options.extend(["--package-lock", str(lock)])
    assert cli.main(options) == 2
    assert capsys.readouterr().err
    assert not calls and not (runtime_root / "fixture" / "registry.json").exists()


def test_cli_lock_refresh_does_not_build_register_or_activate(source_package, capsys):
    project, runtime_root, calls = source_package
    (project / "pylock.toml").unlink()
    assert cli.main(["package", "--source", str(project), "--lock"]) == 0
    assert json.loads(capsys.readouterr().out) == {"lock": str(project / "pylock.toml")}
    assert len(calls) == 1 and calls[0][0][1:3] == ["pip", "compile"]
    assert not (runtime_root / "fixture/registry.json").exists()
    assert not (runtime_root / "fixture/current.json").exists()
    assert not list((runtime_root / "fixture/staging").iterdir())


@pytest.mark.usefixtures("deployment")
@pytest.mark.parametrize("selection", ["directory", "cwd", "git-root", "git-subdirectory", "named"])
def test_repository_install_derives_name_and_version(source_package, tmp_path, monkeypatch, capsys, selection):
    project, runtime_root, calls = source_package
    arguments = ["install"]
    if selection in {"git-root", "git-subdirectory", "named"}:
        repo = tmp_path / "repository"
        tool = repo / "tools/selected tool"
        shutil.copytree(project, tool)
        # Real Git discovery must ignore environments and include both tracked
        # and non-ignored new tool declarations without requiring a commit.
        (repo / ".gitignore").write_text('.venv/\n')
        shutil.copytree(project, repo / ".venv/ignored tool")
        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
        if selection != "named":
            subprocess.run(["git", "-C", str(repo), "add", "tools"], check=True, capture_output=True)
        if selection == "named":
            other = repo / "tools/other"
            shutil.copytree(project, other)
            (other / "pyproject.toml").write_text('[project]\nname="other"\nversion="9.8.7"\n')
            arguments += ["--tool-name", "fixture"]
        monkeypatch.chdir(repo / "tools" if selection == "git-subdirectory" else repo)
        # Git environment overrides must not select a different checkout.
        monkeypatch.setenv("GIT_DIR", str(tmp_path / "absent.git"))
        project = tool
    elif selection == "cwd":
        monkeypatch.chdir(project)
    else:
        arguments += ["--source", str(project), "--tool-name", "fixture"]
    assert cli.main(arguments) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["tool_name"] == "fixture" and result["installed_version"] == "1.0.0"
    assert len(calls) == 1 and calls[0][1]["cwd"] == project
    selection_record = json.loads((runtime_root / "fixture/current.json").read_text())
    assert selection_record["schema"] == 1 and selection_record["tool_id"] == "fixture"
    assert not list((runtime_root / "fixture/staging").iterdir())


@pytest.mark.parametrize("case", ["ambiguous", "duplicate", "unknown", "unsafe-name", "not-git", "failed-git", "empty"])
def test_repository_selection_refuses_before_build_or_install(source_package, tmp_path, monkeypatch, capsys, case):
    project, runtime_root, calls = source_package
    repo = tmp_path / "repository"
    repo.mkdir()
    if case != "empty":
        shutil.copytree(project, repo / "tools/one")
    if case in {"ambiguous", "duplicate"}:
        other = repo / "tools/two"
        shutil.copytree(project, other)
        if case == "ambiguous":
            (other / "pyproject.toml").write_text('[project]\nname="other"\nversion="1.0.0"\n')
    if case != "not-git":
        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    if case == "failed-git":
        def fail(*args, **kwargs):
            raise contracts.DeploymentError("Git query failed")
        monkeypatch.setattr(package_module, "run", fail)
    arguments = ["install", "--source", str(repo)]
    if case in {"unknown", "unsafe-name"}:
        arguments += ["--tool-name", "absent" if case == "unknown" else "../escape"]
    assert cli.main(arguments) == 2
    output = capsys.readouterr()
    assert not output.out and output.err
    assert not calls and not list(runtime_root.iterdir())


@pytest.mark.parametrize("case", ["no-project", "dynamic-version", "invalid-name", "invalid-version", "wrong-schema", "extra-field", "invalid-module", "missing-lock", "wheel-version", "changed-metadata"])
def test_source_contract_and_build_failures_do_not_activate(source_package, monkeypatch, capsys, case):
    project, runtime_root, calls = source_package
    declarations = {
        "no-project": '[tool.fixture]\nvalue=1\n',
        "dynamic-version": '[project]\nname="fixture"\ndynamic=["version"]\n',
        "invalid-name": '[project]\nname="../escape"\nversion="1.0.0"\n',
        "invalid-version": '[project]\nname="fixture"\nversion="latest"\n',
        "wheel-version": '[project]\nname="fixture"\nversion="2.0.0"\n',
    }
    if case in declarations:
        (project / "pyproject.toml").write_text(declarations[case])
    configs = {"wrong-schema": {"schema": True, "module": "fixture"},
               "extra-field": {"schema": 2, "module": "fixture", "command": "whoami"},
               "invalid-module": {"schema": 2, "module": "../escape"}}
    if case in configs:
        (project / "tool.json").write_text(json.dumps(configs[case]))
    if case == "missing-lock":
        (project / "pylock.toml").unlink()
    if case == "changed-metadata":
        build = package_module.run
        def changing_build(*args, **kwargs):
            result = build(*args, **kwargs)
            (project / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="2.0.0"\n')
            return result
        monkeypatch.setattr(package_module, "run", changing_build)
    assert cli.main(["install", "--source", str(project)]) == 2
    assert capsys.readouterr().err
    assert len(calls) == (1 if case in {"wheel-version", "changed-metadata"} else 0)
    assert not list(runtime_root.glob("*/current.json"))
    assert not list(runtime_root.glob("*/registry.json"))
    assert not list(runtime_root.glob("*/staging/*"))


@pytest.mark.parametrize("filename", ["tool.json", "pyproject.toml", "pylock.toml"])
def test_source_files_cannot_escape_selected_directory(source_package, tmp_path, capsys, filename):
    project, runtime_root, calls = source_package
    target = tmp_path / filename
    target.write_bytes((project / filename).read_bytes())
    (project / filename).unlink()
    try:
        (project / filename).symlink_to(target)
    except OSError:
        pytest.skip("OS denied symlink creation")
    assert cli.main(["install", "--source", str(project)]) == 2
    assert "escapes" in capsys.readouterr().err
    assert not calls and not list(runtime_root.glob("*/current.json"))


@pytest.mark.parametrize("failure", ["build", "metadata-selection", "check"])
def test_repository_install_preserves_previous_selection_on_failure(deployment, source_package, monkeypatch, capsys, failure):
    engine, _, failures = deployment
    project, runtime_root, _ = source_package
    make_release(runtime_root, "0.9.0")
    engine.install("fixture", "0.9.0")
    current = runtime_root / "fixture/current.json"
    before = current.read_bytes()
    if failure == "build":
        def fail(*args, **kwargs):
            raise contracts.DeploymentError("build failed")
        monkeypatch.setattr(package_module, "run", fail)
    elif failure == "metadata-selection":
        monkeypatch.setattr(package_module, "package", lambda source, **_options: {"tool_name": "other", "version": "1.0.0"})
    else:
        failures["phase"] = "check"
    assert cli.main(["install", "--source", str(project)]) == 2
    assert capsys.readouterr().err
    assert current.read_bytes() == before
    assert not list(runtime_root.glob("*/staging/*"))
    assert not list(runtime_root.glob("*/versions/1.0.0/*"))


@pytest.mark.parametrize("source_package", ["ceratops_tool_manager"], indirect=True)
def test_manager_source_installer_upgrades_existing_selection(deployment, source_package, monkeypatch, capsys):
    engine, _, _ = deployment
    project, runtime_root, calls = source_package
    make_release(runtime_root, "0.9.0", tool="ceratops_tool_manager")
    engine.install("ceratops_tool_manager", "0.9.0")
    previous = engine.selected("ceratops_tool_manager")
    module = load("deploy-tool-manager")
    monkeypatch.setattr(module, "SOURCE", project)
    monkeypatch.setattr(module, "run", lambda *args, **kwargs: "")
    monkeypatch.setattr(module, "ensure_launchers", lambda layout: None)
    assert module.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["tool_name"] == "ceratops_tool_manager" and result["installed_version"] == "1.0.0"
    assert len(calls) == 1
    assert (runtime_root / "ceratops_tool_manager/versions/0.9.0" / previous["instance"]).is_dir()
    assert not list(runtime_root.glob("*/staging/*"))


@pytest.mark.parametrize("arguments", [
    ["package"], ["package", "--source", ".", "--root", "elsewhere"],
    ["install", "fixture", "1.0.0"], ["install", "--version", "1.0.0"],
    ["install", "--tool-id", "fixture"], ["install", "--lock"],
    ["install", "--root", "elsewhere"],
])
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
def test_source_install_uses_manager_packaging_and_cleans_temporary_libraries(tmp_path, monkeypatch, failure):
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
        return {"tool_name": "ceratops_tool_manager", "version": "0.2.3"}

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


@pytest.mark.parametrize("state", ["first-install", "already-installed", "packaging-failed", "wrong-name", "launcher-failed", "install-failed"])
def test_source_install_stops_before_later_mutation_on_failure(monkeypatch, capsys, state):
    module = load("deploy-tool-manager")
    events = []
    runtime = object()

    def install(identity, version):
        events.append("install")
        assert identity == "ceratops_tool_manager" and version == "0.2.3"
        if state == "install-failed":
            raise contracts.DeploymentError("install failed")
        return {"tool_name": identity, "installed_version": version}

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
        return {"tool_name": "other" if state == "wrong-name" else "ceratops_tool_manager", "version": "0.2.3"}

    def ensure_launchers(layout):
        events.append("launchers")
        if state == "launcher-failed":
            raise contracts.DeploymentError("launcher failed")

    monkeypatch.setattr(module, "global_runtime", lambda: runtime)
    monkeypatch.setattr(module, "Engine", lambda: engine)
    monkeypatch.setattr(module, "package_manager", package_manager)
    monkeypatch.setattr(module, "ensure_launchers", ensure_launchers)
    success = state in {"first-install", "already-installed"}
    assert module.main() == (0 if success else 2)
    output = capsys.readouterr()
    if success:
        assert events == ["package", "launchers", "install"]
        assert json.loads(output.out)["installed_version"] == "0.2.3" and not output.err
    else:
        expected = ["package"]
        if state in {"launcher-failed", "install-failed"}:
            expected.append("launchers")
        if state == "install-failed":
            expected.append("install")
        assert events == expected
        assert not output.out and output.err


def test_first_install_import_needs_no_third_party_site_packages(tmp_path):
    script = ROOT / "scripts/deploy-tool-manager.py"
    code = "import runpy,sys; sys.path.insert(0,sys.argv[1]); module=runpy.run_path(sys.argv[2]); assert callable(module['package_manager'])"
    result = subprocess.run([sys.executable, "-S", "-B", "-c", code, str(script.parent), str(script)],
                            cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("operation", ["package", "install"])
def test_source_cli_needs_only_tool_package_not_repository_scripts(tmp_path, operation):
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
    (project / "tool.json").write_text(json.dumps({"schema": 2, "module": "fixture"}))
    (project / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="1.0.0"\n')
    (project / "pylock.toml").write_text('lock-version="1.0"\npackages=[]\n')
    code = """
import shutil, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from ceratops_tool_manager import packaging, storage
from ceratops_tool_manager.cli import main
from ceratops_tool_manager.engine import Engine, Runtime
storage.INSTALL_ROOT = Path(sys.argv[2])
packaging.global_runtime = lambda: Runtime(Path(sys.executable), Path('uv.exe'), '3.14.7', '0.12.10')
def build(command, **kwargs):
    shutil.copyfile(sys.argv[4], Path(command[command.index('--out-dir') + 1]) / Path(sys.argv[4]).name)
    return ''
packaging.run = build
def install(self, tool_name, version):
    assert tool_name == 'fixture' and version == '1.0.0'
    assert (storage.INSTALL_ROOT / tool_name / 'registry.json').is_file()
    return {'tool_name': tool_name, 'installed_version': version}
Engine.install = install
raise SystemExit(main([sys.argv[5], '--source', sys.argv[3]]))
"""
    store = tmp_path / "installed"
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(isolated), str(store), str(project), str(next(bundle.glob("*.whl"))), operation],
                            cwd=isolated, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["tool_name"] == "fixture"
    assert (store / "fixture/registry.json").is_file()
    assert not (store / "fixture/current.json").exists()
