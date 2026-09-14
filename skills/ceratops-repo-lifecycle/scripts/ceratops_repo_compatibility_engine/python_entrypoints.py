"""Bind script entrypoints to the repository environment without changing imports.

Compatibility owns these edits inside its existing rollback transaction. A
bootstrap runs only for direct execution; importing repository modules retains
the caller's interpreter. Parsing locates the legal insertion point after the
module docstring and future imports, not evidence of functional compliance.
"""
from __future__ import annotations

import ast
import os
import pathlib

BOOTSTRAP = """# Bootstrap precedes dependency imports; imported modules keep their caller's Python.
# ruff: noqa: E402
if __name__ == "__main__":
    import pathlib as _bootstrap_pathlib
    import runpy as _bootstrap_runpy

    _bootstrap = next((parent / "scripts/python_environment.py"
                       for parent in _bootstrap_pathlib.Path(__file__).resolve().parents
                       if (parent / "scripts/python_environment.py").is_file()), None)
    if _bootstrap is None:
        raise SystemExit(
            "error: missing scripts/python_environment.py; apply repository setup first"
        )
    _bootstrap_runpy.run_path(str(_bootstrap))["ensure_environment"](__file__)

"""


def bind_entrypoint(source: str) -> str:
    """Insert the shared bootstrap after the docstring and future imports."""
    if BOOTSTRAP.strip() in source:
        return source
    tree = ast.parse(source)
    last = 0
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            last = node.end_lineno or last
        elif isinstance(node, ast.ImportFrom) and node.module == "__future__":
            last = node.end_lineno or last
        else:
            break
    lines = source.splitlines(keepends=True)
    if not last:
        while last < len(lines) and (lines[last].startswith("#") or not lines[last].strip()):
            last += 1
    return "".join(lines[:last]) + "\n" + BOOTSTRAP + "".join(lines[last:]).lstrip("\n")


def existing_entrypoints(root: pathlib.Path) -> dict[pathlib.Path, str]:
    """Plan bindings for repository Python files, skipping generated environments."""
    files: dict[pathlib.Path, str] = {}
    for directory, names, filenames in os.walk(root / "scripts", followlinks=False):
        base = pathlib.Path(directory)
        names[:] = sorted(name for name in names if name not in {".venv", "venv", "__pycache__", "runtime"}
                          and not (base / name).is_symlink()
                          and not getattr(base / name, "is_junction", lambda: False)())
        for name in sorted(filenames):
            path = base / name
            if path.suffix != ".py" or name == "python_environment.py":
                continue
            if path.is_symlink():
                raise RuntimeError(f"Python entrypoint must not be a link: {path}")
            original = path.read_text(encoding="utf-8")
            try:
                bound = bind_entrypoint(original)
            except SyntaxError as exc:
                raise RuntimeError(f"Cannot bind Python entrypoint {path}: {exc}") from exc
            if bound != original:
                files[path] = bound
    return files
