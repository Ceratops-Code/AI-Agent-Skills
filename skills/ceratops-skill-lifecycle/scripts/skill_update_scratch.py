"""Own temporary subprocess data for one skill-update check phase."""

from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager

SCRATCH_SCHEMA = "ceratops-skill-update-scratch.v1"


def _remove_scratch(root: pathlib.Path, scratch: pathlib.Path) -> None:
    """Remove only an owned child; reset a proven read-only bit when needed."""

    if scratch.is_symlink() or scratch.is_junction() or scratch.resolve().parent != root:
        raise OSError(f"test scratch path changed; cleanup retained: {scratch}")

    def remove_readonly(function: Callable[..., object], path: str, error: BaseException) -> None:
        entry = pathlib.Path(path)
        if (
            not isinstance(error, PermissionError)
            or function not in {os.unlink, os.rmdir}
            or entry.is_symlink() or entry.is_junction()
            or not entry.resolve().is_relative_to(scratch)
        ):
            raise error
        mode = entry.stat().st_mode
        if mode & stat.S_IWRITE:
            raise error
        entry.chmod(mode | stat.S_IWRITE)
        function(path)

    if scratch.exists():
        shutil.rmtree(scratch, onexc=remove_readonly)
    if scratch.exists() or scratch.is_symlink():
        raise OSError(f"test scratch cleanup left a folder: {scratch}")


def _resume_cleanup(root: pathlib.Path) -> None:
    """Resume only recorded, finished check phases; never scan folder contents."""

    for marker in sorted(root.glob(".check-*.cleanup.json")):
        if marker.is_symlink() or not marker.is_file():
            raise OSError(f"unsafe test scratch cleanup record: {marker}")
        name = marker.name[1:-len(".cleanup.json")]
        scratch = root / name
        try:
            record = json.loads(marker.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise OSError(f"invalid test scratch cleanup record: {marker}") from exc
        if (
            re.fullmatch(r"check-[A-Za-z0-9_-]+", name) is None
            or record != {"schema": SCRATCH_SCHEMA, "path": str(scratch)}
        ):
            raise OSError(f"test scratch cleanup ownership mismatch: {marker}")
        _remove_scratch(root, scratch)
        marker.unlink(missing_ok=True)


@contextmanager
def check_environment(task_temp_root: pathlib.Path) -> Iterator[dict[str, str]]:
    """Yield child-only temp settings and remove our folder on every normal exit.

    The workflow supplies its already-verified task temp root. Python owns the
    unique child directory. A cleanup record is written only after the check
    phase ends, so retries may remove its residue before starting another phase.
    Caller-selected paths in check arguments remain caller-owned.
    """

    root = task_temp_root.resolve(strict=True)
    _resume_cleanup(root)
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="check-", dir=root))
    try:
        environment = dict(os.environ)
        for name in ("TMPDIR", "TEMP", "TMP", "PYTEST_DEBUG_TEMPROOT"):
            environment[name] = str(scratch)
        # Pytest validates every basetemp occurrence, even one later overridden.
        # Remove inherited locations while preserving the remaining arguments.
        try:
            options = iter(shlex.split(environment.get("PYTEST_ADDOPTS", "")))
        except ValueError as exc:
            raise OSError(f"invalid inherited PYTEST_ADDOPTS: {exc}") from exc
        retained = []
        for option in options:
            if option == "--basetemp":
                next(options, None)
            elif not option.startswith("--basetemp="):
                retained.append(option)
        environment["PYTEST_ADDOPTS"] = shlex.join(
            [*retained, "--basetemp", str(scratch / "pytest")]
        )
        yield environment
    finally:
        marker = root / f".{scratch.name}.cleanup.json"
        # Exclusive creation preserves an unexpected caller-owned collision.
        with marker.open("x", encoding="utf-8") as stream:
            json.dump({"schema": SCRATCH_SCHEMA, "path": str(scratch)}, stream)
        try:
            _remove_scratch(root, scratch)
        except OSError as exc:
            raise OSError(f"test scratch cleanup failed at {scratch}: {exc}") from exc
        marker.unlink(missing_ok=True)
