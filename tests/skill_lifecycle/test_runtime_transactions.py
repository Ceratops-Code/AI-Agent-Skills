from __future__ import annotations

import errno
import json
import pathlib
import shutil
import subprocess
import sys
import threading

import pytest

from tests.skill_lifecycle.support import (
    RUNTIME_INSTALLER,
    RUNTIME_MANIFEST,
    load_runtime_builder,
    load_runtime_installer,
    run_builder,
    runtime_owner,
    runtime_skill_text,
)
from tests.support.repositories import (
    add_skill,
    create_compatible_repo,
    run_git,
    write_manifest,
)


def test_full_install_removes_only_same_source_stale_skills(tmp_path: pathlib.Path) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo_a, "example/source-a", ["alpha-tool", "retired-tool"])
    create_compatible_repo(repo_b, "example/source-b", ["beta-tool"])

    assert run_builder(repo_a, install_root, "--all-managed").returncode == 0
    assert run_builder(repo_b, install_root, "--all-managed").returncode == 0
    shutil.rmtree(repo_a / "skills" / "retired-tool")
    write_manifest(repo_a, "example/source-a")

    result = run_builder(repo_a, install_root, "--all-managed")

    assert result.returncode == 0, result.stderr
    assert not (install_root / "retired-tool").exists()
    assert runtime_owner(install_root, "alpha-tool") == "example/source-a"
    assert runtime_owner(install_root, "beta-tool") == "example/source-b"


def test_targeted_install_keeps_stale_and_rejects_other_source_collision(tmp_path: pathlib.Path) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo_a, "example/source-a", ["alpha-tool", "retired-tool"])
    create_compatible_repo(repo_b, "example/source-b", ["beta-tool"])
    assert run_builder(repo_a, install_root, "--all-managed").returncode == 0
    assert run_builder(repo_b, install_root, "--all-managed").returncode == 0

    shutil.rmtree(repo_a / "skills" / "retired-tool")
    write_manifest(repo_a, "example/source-a")
    targeted = run_builder(repo_a, install_root, "--skill", "alpha-tool")
    assert targeted.returncode == 0, targeted.stderr
    assert (install_root / "retired-tool").is_dir()

    add_skill(repo_b, "alpha-tool")
    write_manifest(repo_b, "example/source-b")
    collision = run_builder(repo_b, install_root, "--skill", "alpha-tool")
    assert collision.returncode == 1
    assert "owned by 'example/source-a'" in collision.stderr
    assert runtime_owner(install_root, "alpha-tool") == "example/source-a"

    unmanaged = install_root / "unmanaged-tool"
    unmanaged.mkdir()
    (unmanaged / "sentinel.txt").write_text("keep\n", encoding="utf-8")
    add_skill(repo_b, "unmanaged-tool")
    write_manifest(repo_b, "example/source-b")
    unmanaged_collision = run_builder(repo_b, install_root, "--skill", "unmanaged-tool")
    assert unmanaged_collision.returncode == 1
    assert "unmanaged runtime skill folder" in unmanaged_collision.stderr
    assert (unmanaged / "sentinel.txt").is_file()

    legacy = install_root / "legacy-tool"
    legacy.mkdir()
    (legacy / RUNTIME_MANIFEST).write_text(
        json.dumps({"schema": "ceratops-runtime-skill.v2", "skill": "legacy-tool"}) + "\n",
        encoding="utf-8",
    )
    add_skill(repo_b, "legacy-tool")
    write_manifest(repo_b, "example/source-b")
    legacy_collision = run_builder(repo_b, install_root, "--skill", "legacy-tool")
    assert legacy_collision.returncode == 1
    assert "unsupported ownership manifest" in legacy_collision.stderr


def test_transaction_stages_complete_batch_before_canonical_mutation(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool", "beta-tool"])
    assert run_builder(repo, install_root, "--all-managed").returncode == 0
    before = {
        name: runtime_skill_text(install_root, name)
        for name in ("alpha-tool", "beta-tool")
    }
    for name in before:
        source = repo / "skills" / name / "SKILL.md"
        source.write_text(
            source.read_text(encoding="utf-8") + f"\nUpdated {name}.\n",
            encoding="utf-8",
            newline="\n",
        )

    builder = load_runtime_builder()
    original_write = builder["write_expected_skill"]
    observed: list[tuple[str, dict[str, str]]] = []

    def traced_write(skill: str, *args: object, **kwargs: object) -> None:
        observed.append(
            (
                skill,
                {
                    name: runtime_skill_text(install_root, name)
                    for name in before
                },
            )
        )
        original_write(skill, *args, **kwargs)

    monkeypatch.setitem(
        builder["install_transaction"].__globals__,
        "write_expected_skill",
        traced_write,
    )
    result = builder["install_transaction"](
        repo,
        install_root,
        selected=("alpha-tool", "beta-tool"),
    )

    assert result.status == "ok"
    assert [skill for skill, _ in observed] == ["alpha-tool", "beta-tool"]
    assert all(snapshot == before for _, snapshot in observed)
    assert all(
        f"Updated {name}." in runtime_skill_text(install_root, name)
        for name in before
    )


def test_transaction_staging_or_activation_failure_restores_prior_batch(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool", "beta-tool"])
    assert run_builder(repo, install_root, "--all-managed").returncode == 0
    before = {
        name: runtime_skill_text(install_root, name)
        for name in ("alpha-tool", "beta-tool")
    }
    for name in before:
        source = repo / "skills" / name / "SKILL.md"
        source.write_text(
            source.read_text(encoding="utf-8") + "\nChanged.\n",
            encoding="utf-8",
            newline="\n",
        )

    staging_builder = load_runtime_builder()
    original_write = staging_builder["write_expected_skill"]

    def fail_second_stage(skill: str, *args: object, **kwargs: object) -> None:
        if skill == "beta-tool":
            raise OSError("staging failed")
        original_write(skill, *args, **kwargs)

    monkeypatch.setitem(
        staging_builder["install_transaction"].__globals__,
        "write_expected_skill",
        fail_second_stage,
    )
    with pytest.raises(staging_builder["TransactionError"]) as staging_error:
        staging_builder["install_transaction"](
            repo,
            install_root,
            selected=("alpha-tool", "beta-tool"),
        )
    assert staging_error.value.phase == "staging"
    assert staging_error.value.rollback_state == "complete"
    assert {
        name: runtime_skill_text(install_root, name)
        for name in before
    } == before
    assert not list(install_root.glob(".*-deployed-*"))

    activation_builder = load_runtime_builder()
    original_rename = activation_builder["rename_with_retry"]

    def fail_second_activation(
        source: pathlib.Path, target: pathlib.Path
    ) -> None:
        if source.name.startswith(".beta-tool-deployed-"):
            raise PermissionError("activation denied")
        original_rename(source, target)

    monkeypatch.setitem(
        activation_builder["install_transaction"].__globals__,
        "rename_with_retry",
        fail_second_activation,
    )
    with pytest.raises(activation_builder["TransactionError"]) as activation_error:
        activation_builder["install_transaction"](
            repo,
            install_root,
            selected=("alpha-tool", "beta-tool"),
        )
    assert activation_error.value.phase == "activation"
    assert activation_error.value.rollback_state == "complete"
    assert {
        name: runtime_skill_text(install_root, name)
        for name in before
    } == before


def test_transaction_retry_policy_and_acl_order(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = load_runtime_builder()

    class RenameError(OSError):
        winerror: int

    class RenameProbe:
        def __init__(self, failures: int, *, transient: bool) -> None:
            self.failures = failures
            self.transient = transient
            self.calls = 0

        def replace(self, _target: object) -> None:
            self.calls += 1
            if self.calls <= self.failures:
                error = RenameError(
                    errno.EBUSY if self.transient else errno.EACCES,
                    "rename failure",
                )
                error.winerror = 32 if self.transient else 5
                raise error

    monkeypatch.setattr(builder["time"], "sleep", lambda _seconds: None)
    transient = RenameProbe(2, transient=True)
    builder["rename_with_retry"](transient, pathlib.Path("unused"))
    assert transient.calls == 3
    permanent = RenameProbe(2, transient=False)
    with pytest.raises(OSError):
        builder["rename_with_retry"](permanent, pathlib.Path("unused"))
    assert permanent.calls == 1

    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    order: list[str] = []
    original_rename = builder["rename_with_retry"]

    def record_acl(path: pathlib.Path) -> None:
        order.append(f"acl:{path.name}")

    def record_rename(source: pathlib.Path, target: pathlib.Path) -> None:
        if "-deployed-" in source.name:
            order.append(f"activate:{source.name}")
        original_rename(source, target)

    monkeypatch.setitem(
        builder["install_transaction"].__globals__,
        "enable_windows_acl_inheritance",
        record_acl,
    )
    monkeypatch.setitem(
        builder["install_transaction"].__globals__,
        "rename_with_retry",
        record_rename,
    )
    builder["install_transaction"](
        repo,
        install_root,
        selected=("alpha-tool",),
    )
    assert order[0].startswith("acl:.alpha-tool-deployed-")
    assert order[1].startswith("activate:.alpha-tool-deployed-")


def test_transaction_recovers_interrupted_and_blocks_ambiguous_remnants(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool", "beta-tool"])
    assert run_builder(repo, install_root, "--all-managed").returncode == 0
    source = repo / "skills" / "alpha-tool" / "SKILL.md"
    source.write_text(
        source.read_text(encoding="utf-8") + "\nRecovered update.\n",
        encoding="utf-8",
        newline="\n",
    )
    builder = load_runtime_builder()
    builder["configure_repo"](repo)
    manifest = builder["load_manifest"]()
    transaction = "a" * 32
    retired = install_root / f".alpha-tool-retired-{transaction}"
    deployed = install_root / f".alpha-tool-deployed-{transaction}"
    (install_root / "alpha-tool").replace(retired)
    builder["write_expected_skill"](
        "alpha-tool",
        deployed,
        manifest,
    )

    recovered = builder["install_transaction"](
        repo,
        install_root,
        selected=("alpha-tool",),
    )

    assert recovered.status == "ok"
    assert "Recovered update." in runtime_skill_text(install_root, "alpha-tool")
    assert not retired.exists()
    assert not deployed.exists()

    ambiguous = install_root / f".alpha-tool-retired-{'b' * 32}"
    (install_root / "alpha-tool").replace(ambiguous)
    with pytest.raises(builder["TransactionError"]) as blocked:
        builder["install_transaction"](
            repo,
            install_root,
            selected=("beta-tool",),
        )
    assert blocked.value.phase == "recovery"
    assert "same affected set" in str(blocked.value)


def test_transaction_rejects_conflicting_remnant_ids(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    assert run_builder(repo, install_root, "--all-managed").returncode == 0
    for transaction in ("c" * 32, "d" * 32):
        shutil.copytree(
            install_root / "alpha-tool",
            install_root / f".alpha-tool-retired-{transaction}",
        )
    builder = load_runtime_builder()

    with pytest.raises(builder["TransactionError"]) as blocked:
        builder["install_transaction"](
            repo,
            install_root,
            selected=("alpha-tool",),
        )

    assert blocked.value.phase == "recovery"
    assert "conflicting transaction IDs" in str(blocked.value)


def test_transaction_supports_explicit_add_remove_and_rename(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool", "old-tool"])
    assert run_builder(repo, install_root, "--all-managed").returncode == 0

    add_skill(repo, "beta-tool")
    write_manifest(repo, "example/compatible")
    added = run_builder(repo, install_root, "--skill", "beta-tool")
    assert added.returncode == 0, added.stderr
    assert (install_root / "beta-tool").is_dir()

    shutil.rmtree(repo / "skills" / "old-tool")
    write_manifest(repo, "example/compatible")
    removed = run_builder(repo, install_root, "--remove-skill", "old-tool")
    assert removed.returncode == 0, removed.stderr
    assert not (install_root / "old-tool").exists()

    (repo / "skills" / "alpha-tool").replace(repo / "skills" / "renamed-tool")
    skill_md = repo / "skills" / "renamed-tool" / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8").replace(
            "name: alpha-tool", "name: renamed-tool"
        ),
        encoding="utf-8",
        newline="\n",
    )
    write_manifest(repo, "example/compatible")
    renamed = run_builder(
        repo,
        install_root,
        "--skill",
        "renamed-tool",
        "--remove-skill",
        "alpha-tool",
    )
    assert renamed.returncode == 0, renamed.stderr
    assert (install_root / "renamed-tool").is_dir()
    assert not (install_root / "alpha-tool").exists()


def test_base_revision_resolves_structured_add_remove_rename_and_sections(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    create_compatible_repo(
        repo,
        "example/compatible",
        ["alpha-tool", "beta-tool", "old-tool"],
    )
    assert run_git(repo, "init", "-b", "main").returncode == 0
    assert run_git(repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(repo, "config", "user.name", "Test Agent").returncode == 0
    assert run_git(repo, "add", ".").returncode == 0
    assert run_git(repo, "commit", "-m", "base").returncode == 0
    base = run_git(repo, "rev-parse", "HEAD").stdout.strip()

    (repo / "skills" / "old-tool").replace(repo / "skills" / "renamed-tool")
    renamed_skill = repo / "skills" / "renamed-tool" / "SKILL.md"
    renamed_skill.write_text(
        renamed_skill.read_text(encoding="utf-8").replace(
            "name: old-tool", "name: renamed-tool"
        ),
        encoding="utf-8",
        newline="\n",
    )
    section = repo / "skills" / "sections" / "core.md"
    section.write_text(
        section.read_text(encoding="utf-8") + "\nUpdated shared rule.\n",
        encoding="utf-8",
        newline="\n",
    )
    write_manifest(repo, "example/compatible")
    assert run_git(repo, "add", "-A").returncode == 0
    assert run_git(repo, "commit", "-m", "rename and section").returncode == 0
    installer = load_runtime_installer()

    affected = installer["affected_from_base"](repo, base)

    assert affected.deploy == ("alpha-tool", "beta-tool", "renamed-tool")
    assert affected.remove == ("old-tool",)
    assert affected.all_managed is False


def test_base_revision_resolves_payload_global_and_ambiguous_changes(
    tmp_path: pathlib.Path,
) -> None:
    installer = load_runtime_installer()

    payload_repo = tmp_path / "payload"
    create_compatible_repo(
        payload_repo,
        "example/payload",
        ["alpha-tool", "beta-tool"],
    )
    payload = payload_repo / "skills" / "sections" / "scripts" / "payload-alpha.py"
    payload.parent.mkdir()
    payload.write_text("one\n", encoding="utf-8", newline="\n")
    manifest_path = payload_repo / "skills" / "skill-sections.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mapped_payload = {
        "source": "skills/sections/scripts/payload-alpha.py",
        "target": "scripts/payload-alpha.py",
    }
    manifest["runtime_payloads"] = {"alpha-tool": [mapped_payload]}
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(payload_repo, "init", "-b", "main").returncode == 0
    assert run_git(payload_repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(payload_repo, "config", "user.name", "Test Agent").returncode == 0
    assert run_git(payload_repo, "add", ".").returncode == 0
    assert run_git(payload_repo, "commit", "-m", "base").returncode == 0
    payload_base = run_git(payload_repo, "rev-parse", "HEAD").stdout.strip()
    payload.write_text("two\n", encoding="utf-8", newline="\n")
    with pytest.raises(installer["DecisionRequired"], match="clean checkout"):
        installer["affected_from_base"](payload_repo, payload_base)
    assert (
        run_git(
            payload_repo,
            "add",
            "skills/sections/scripts/payload-alpha.py",
        ).returncode
        == 0
    )
    assert run_git(payload_repo, "commit", "-m", "payload").returncode == 0

    payload_affected = installer["affected_from_base"](
        payload_repo, payload_base
    )
    assert payload_affected.deploy == ("alpha-tool",)
    assert payload_affected.remove == ()
    assert payload_affected.all_managed is False
    wildcard_base = run_git(payload_repo, "rev-parse", "HEAD").stdout.strip()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtime_payloads"] = {"*": [mapped_payload]}
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(payload_repo, "add", "skills/skill-sections.json").returncode == 0
    assert run_git(payload_repo, "commit", "-m", "wildcard payload").returncode == 0
    wildcard_affected = installer["affected_from_base"](
        payload_repo, wildcard_base
    )
    assert wildcard_affected.deploy == ("alpha-tool", "beta-tool")
    assert wildcard_affected.all_managed is True

    global_repo = tmp_path / "global"
    create_compatible_repo(
        global_repo,
        "example/global",
        ["alpha-tool", "beta-tool"],
    )
    assert run_git(global_repo, "init", "-b", "main").returncode == 0
    assert run_git(global_repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(global_repo, "config", "user.name", "Test Agent").returncode == 0
    assert run_git(global_repo, "add", ".").returncode == 0
    assert run_git(global_repo, "commit", "-m", "base").returncode == 0
    global_base = run_git(global_repo, "rev-parse", "HEAD").stdout.strip()
    bootstrap = global_repo / "scripts" / "install-skills-bootstrap.py"
    bootstrap.write_text(
        bootstrap.read_text(encoding="utf-8") + "\n# changed generator\n",
        encoding="utf-8",
        newline="\n",
    )
    assert (
        run_git(
            global_repo,
            "add",
            "scripts/install-skills-bootstrap.py",
        ).returncode
        == 0
    )
    assert run_git(global_repo, "commit", "-m", "global").returncode == 0
    global_affected = installer["affected_from_base"](global_repo, global_base)
    assert global_affected.deploy == ("alpha-tool", "beta-tool")
    assert global_affected.all_managed is True
    global_install_root = tmp_path / "global-installed"
    global_install = subprocess.run(
        [
            sys.executable,
            str(RUNTIME_INSTALLER),
            "--repo-root",
            str(global_repo),
            "--install-root",
            str(global_install_root),
            "--base-revision",
            global_base,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert global_install.returncode == 0, global_install.stderr
    assert {
        path.name
        for path in global_install_root.iterdir()
        if not path.name.startswith(".")
    } == {"alpha-tool", "beta-tool"}

    ambiguous_repo = tmp_path / "ambiguous"
    create_compatible_repo(ambiguous_repo, "example/ambiguous", ["alpha-tool"])
    assert run_git(ambiguous_repo, "init", "-b", "main").returncode == 0
    assert run_git(ambiguous_repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert run_git(ambiguous_repo, "config", "user.name", "Test Agent").returncode == 0
    assert run_git(ambiguous_repo, "add", ".").returncode == 0
    assert run_git(ambiguous_repo, "commit", "-m", "base").returncode == 0
    ambiguous_base = run_git(ambiguous_repo, "rev-parse", "HEAD").stdout.strip()
    ambiguous_manifest = ambiguous_repo / "skills" / "skill-sections.json"
    value = json.loads(ambiguous_manifest.read_text(encoding="utf-8"))
    value["unowned_effect"] = {"value": True}
    ambiguous_manifest.write_text(
        json.dumps(value, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    assert run_git(ambiguous_repo, "add", "skills/skill-sections.json").returncode == 0
    assert run_git(ambiguous_repo, "commit", "-m", "ambiguous").returncode == 0
    with pytest.raises(installer["DecisionRequired"]):
        installer["affected_from_base"](ambiguous_repo, ambiguous_base)


def test_transaction_hard_crash_converges_only_matching_scope(
    tmp_path: pathlib.Path,
) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool", "beta-tool"])
    assert run_builder(repo, install_root, "--skill", "alpha-tool").returncode == 0
    builder = load_runtime_builder()
    builder["configure_repo"](repo)
    manifest = builder["load_manifest"]()
    builder["write_expected_skill"](
        "beta-tool",
        install_root / "beta-tool",
        manifest,
    )
    source = repo / "skills" / "beta-tool" / "SKILL.md"
    source.write_text(
        source.read_text(encoding="utf-8") + "\nAfter crash.\n",
        encoding="utf-8",
        newline="\n",
    )

    unrelated = run_builder(repo, install_root, "--skill", "alpha-tool")
    assert unrelated.returncode == 0, unrelated.stderr
    assert "After crash." not in runtime_skill_text(install_root, "beta-tool")

    matching = run_builder(repo, install_root, "--skill", "beta-tool")
    assert matching.returncode == 0, matching.stderr
    assert "After crash." in runtime_skill_text(install_root, "beta-tool")


def test_transaction_cleanup_blocker_keeps_new_batch_and_serializes_writers(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "compatible"
    install_root = tmp_path / "installed"
    create_compatible_repo(repo, "example/compatible", ["alpha-tool"])
    assert run_builder(repo, install_root, "--all-managed").returncode == 0
    source = repo / "skills" / "alpha-tool" / "SKILL.md"
    source.write_text(
        source.read_text(encoding="utf-8") + "\nCommitted update.\n",
        encoding="utf-8",
        newline="\n",
    )
    builder = load_runtime_builder()
    original_remove = builder["_remove_tree"]

    def block_retired(path: pathlib.Path, root: pathlib.Path) -> None:
        if "-retired-" in path.name:
            raise PermissionError("cleanup blocked")
        original_remove(path, root)

    monkeypatch.setitem(
        builder["install_transaction"].__globals__,
        "_remove_tree",
        block_retired,
    )
    result = builder["install_transaction"](
        repo,
        install_root,
        selected=("alpha-tool",),
    )
    assert result.status == "cleanup_blocked"
    assert "Committed update." in runtime_skill_text(install_root, "alpha-tool")
    assert result.retained_retired
    monkeypatch.setitem(
        builder["install_transaction"].__globals__,
        "_remove_tree",
        original_remove,
    )
    recovered = builder["install_transaction"](
        repo,
        install_root,
        selected=("alpha-tool",),
    )
    assert recovered.status == "ok"
    assert not list(install_root.glob(".*-retired-*"))

    lock_builder = load_runtime_builder()
    errors: list[BaseException] = []

    def competing_install() -> None:
        try:
            lock_builder["install_transaction"](
                repo,
                install_root,
                selected=("alpha-tool",),
            )
        except BaseException as exc:
            errors.append(exc)

    with lock_builder["runtime_lock"](install_root):
        thread = threading.Thread(target=competing_install)
        thread.start()
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], lock_builder["InstallBusy"])
