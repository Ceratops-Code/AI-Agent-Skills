"""Resolve explicitly assigned runtime files for skill and tool consumers.

The repository section manifest is the only editable file-assignment owner.
Markdown sections remain with the section renderer. This module resolves data;
it never installs, activates, executes, or imports a consumer's payload. Build
outputs are disposable; installed runtime records belong to the owning installer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import tomllib
from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath

IGNORED = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}


def relative(value, label="payload path") -> str:
    """Reject portable path escapes before resolving or creating files."""
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"Invalid {label}")
    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).drive or ".." in path.parts:
        raise ValueError(f"Unsafe {label}: {value}")
    return value


def declarations(manifest: Mapping, kind: str, name: str) -> list:
    """Expand named groups; tool consumers never inherit skill assignments."""
    groups = manifest.get("payload_groups", {})
    if not isinstance(groups, Mapping):
        raise ValueError("payload_groups must be an object")
    if kind == "skill":
        if name not in manifest.get("skills", {}):
            raise ValueError(f"Unknown skill consumer: {name}")
        payloads = manifest.get("runtime_payloads", {})
        selected = [*payloads.get("*", []), *payloads.get(name, [])]
    elif kind == "tool":
        tool = manifest.get("tools", {}).get(name)
        if not isinstance(tool, Mapping) or set(tool) != {"source", "package", "payloads"}:
            raise ValueError(f"Invalid tool consumer: {name}")
        relative(tool["source"], "tool source")
        relative(tool["package"], "tool package")
        selected = tool["payloads"]
    else:
        raise ValueError("Consumer kind must be skill or tool")

    def expand(items, prefix="", parents=()):
        if not isinstance(items, list):
            raise ValueError("Consumer payloads must be a list")
        result = []
        for item in items:
            if isinstance(item, Mapping) and "group" in item:
                if set(item) != {"group", "target"}:
                    raise ValueError("Group assignment requires group and target")
                group = item["group"]
                if not isinstance(group, str) or group in parents or group not in groups:
                    raise ValueError(f"Unknown or cyclic payload group: {group}")
                definition = groups[group]
                if not isinstance(definition, Mapping) or set(definition) - {"files", "version_source"} or "files" not in definition:
                    raise ValueError(f"Invalid payload group: {group}")
                target = relative(item["target"])
                result.extend(expand(definition["files"], str(PurePosixPath(prefix) / target), (*parents, group)))
            elif isinstance(item, str):
                source = relative(item)
                result.append({"source": source, "target": str(PurePosixPath(prefix) / source)} if prefix else source)
            elif isinstance(item, Mapping) and set(item) == {"source", "target"}:
                result.append({"source": relative(item["source"]),
                               "target": str(PurePosixPath(prefix) / relative(item["target"]))})
            else:
                raise ValueError("Payload requires a path, source/target, or group/target")
        return result

    return expand(selected)


def _safe_file(path: Path, root: Path) -> None:
    path.resolve().relative_to(root.resolve())
    for part in (path, *path.parents):
        if part == root.parent:
            break
        info = part.lstat()
        if part.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise ValueError(f"Linked payload source: {path}")


def files(root: Path, manifest: Mapping, kind: str, name: str) -> dict[str, str]:
    """Return destination-to-source files, rejecting missing groups and collisions."""
    result: dict[str, str] = {}
    for item in declarations(manifest, kind, name):
        source = item if isinstance(item, str) else item["source"]
        target = None if isinstance(item, str) else item["target"]
        if target and any(char in source + target for char in "*?["):
            raise ValueError("Mapped payload paths must be exact")
        matches = sorted(root.glob(source))
        if not matches:
            raise ValueError(f"Missing runtime payload: {source}")
        for match in matches:
            _safe_file(match, root)
            if match.resolve() == root.resolve():
                raise ValueError("Payload cannot select repository root")
            children = sorted(match.rglob("*")) if match.is_dir() else [match]
            for child in children:
                if any(part in IGNORED for part in child.relative_to(root).parts):
                    continue
                _safe_file(child, root)
                if not child.is_file():
                    continue
                destination = PurePosixPath(target or match.relative_to(root).as_posix())
                if match.is_dir():
                    destination /= child.relative_to(match).as_posix()
                key = relative(destination.as_posix())
                prior = result.get(key)
                actual = child.relative_to(root).as_posix()
                if prior is not None and prior != actual:
                    raise ValueError(f"Multiple payload sources for {key}")
                if any(key.startswith(other + "/") or other.startswith(key + "/") for other in result):
                    raise ValueError(f"Payload file/directory collision: {key}")
                result[key] = actual
    return dict(sorted(result.items()))


def versions(root: Path, manifest: Mapping, kind: str, name: str) -> dict:
    """Read version declarations; never manufacture an independent version."""
    declarations(manifest, kind, name)
    result = {}
    groups = manifest.get("payload_groups", {})
    selected = manifest.get("runtime_payloads", {}).get(name, []) if kind == "skill" else manifest["tools"][name]["payloads"]
    if kind == "skill":
        selected = [*manifest.get("runtime_payloads", {}).get("*", []), *selected]
    def visit(items):
        for item in items:
            if not isinstance(item, Mapping) or "group" not in item:
                continue
            group = item["group"]
            definition = groups[group]
            source = definition.get("version_source")
            if source:
                path = root / relative(source)
                _safe_file(path, root)
                version = tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"]
                if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
                    raise ValueError("Payload version must be numeric major.minor.patch")
                result[group] = version
            visit(definition["files"])
    visit(selected)
    return result


def requirements(root: Path, manifest: Mapping, kind: str, name: str) -> dict:
    """Read the Python requirement contract shared by every consumer."""
    declarations(manifest, kind, name)
    result = {}
    groups = manifest.get("payload_groups", {})
    selected = manifest.get("runtime_payloads", {}).get(name, []) if kind == "skill" else manifest["tools"][name]["payloads"]
    if kind == "skill":
        selected = [*manifest.get("runtime_payloads", {}).get("*", []), *selected]

    def visit(items):
        for item in items:
            if not isinstance(item, Mapping) or "group" not in item:
                continue
            group = item["group"]
            definition = groups[group]
            source = definition.get("version_source")
            if source:
                path = root / relative(source)
                _safe_file(path, root)
                project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
                requires_python = project.get("requires-python")
                dependencies = project.get("dependencies", [])
                if not isinstance(requires_python, str) or not isinstance(dependencies, list) or not all(
                    isinstance(dependency, str) for dependency in dependencies
                ):
                    raise ValueError("runtime project has invalid Python requirements")
                result[group] = {"source": source, "requires_python": requires_python,
                                 "dependencies": dependencies}
            visit(definition["files"])

    visit(selected)
    return result


def receipt(root: Path, manifest: Mapping, kind: str, name: str) -> dict:
    mapping = files(root, manifest, kind, name)
    return {"schema": "ceratops-consumer-runtime.v1", "consumer": {"kind": kind, "name": name},
            "runtime_source_id": manifest["runtime_source_id"], "versions": versions(root, manifest, kind, name),
            "requirements": requirements(root, manifest, kind, name),
            "files": {target: {"source": source, "sha256": hashlib.sha256((root / source).read_bytes()).hexdigest()}
                      for target, source in mapping.items()}}


def inspect(installed: Path, evidence: Mapping) -> dict:
    """Report one consumer only; inspection cannot update any installation."""
    if evidence.get("schema") != "ceratops-consumer-runtime.v1":
        raise ValueError("Unsupported consumer runtime record")
    missing, stale = [], []
    for target, entry in evidence["files"].items():
        path = installed / relative(target)
        if not path.is_file():
            missing.append(target)
        elif hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            stale.append(target)
    return {"consumer": evidence["consumer"], "versions": evidence["versions"],
            "requirements": evidence.get("requirements", {}), "missing": missing, "stale": stale,
            "ready": not missing and not stale}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--kind", required=True, choices=["skill", "tool"])
    parser.add_argument("--consumer", required=True)
    parser.add_argument("--receipt", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((args.repo_root / "skills/skill-sections.json").read_text(encoding="utf-8"))
    value = receipt(args.repo_root, manifest, args.kind, args.consumer) if args.receipt else files(args.repo_root, manifest, args.kind, args.consumer)
    print(json.dumps(value, ensure_ascii=True))


if __name__ == "__main__":
    main()
