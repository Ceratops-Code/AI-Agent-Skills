#!/usr/bin/env python3
"""Plan or apply file renames and exact references in a Git worktree.

Git supplies rename detection; this helper owns bounded file edits, not language
symbol refactoring. The default is a read-only plan. --apply preserves the index
and compensates caught write/move failures. No temporary files or rename catalog
are created. A caller-selected --report is retained for the caller to remove.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import pathlib
import posixpath
import re
import subprocess
import sys
from typing import Any
from urllib.parse import quote, unquote


class RenameError(RuntimeError):
    """An invalid or ambiguous plan must not change repository files."""


def git(root: pathlib.Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments], capture_output=True, check=False,
    )
    if result.returncode:
        raise RenameError(result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


def relative_name(value: str) -> str:
    """Reject traversal, metadata, alternate streams and platform-specific roots."""
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if (not normalized or any(part in {"", ".", ".."} for part in parts)
            or any(part.casefold() == ".git" for part in parts)
            or any(character in normalized for character in ":\x00\r\n")):
        raise RenameError(f"Expected a repository-relative file path: {value!r}")
    return normalized


def safe_path(root: pathlib.Path, name: str) -> pathlib.Path:
    path = root
    for part in pathlib.PurePosixPath(relative_name(name)).parts:
        path = path / part
        if path.is_symlink() or path.is_junction():
            raise RenameError(f"Links and junctions are not editable: {name}")
    if not path.resolve().is_relative_to(root):
        raise RenameError(f"Path leaves repository: {name}")
    return path


def git_renames(root: pathlib.Path, base: str | None, head: str | None) -> list[tuple[str, str]]:
    """Use NUL records; a copy or a delete/add pair is never guessed to be a rename."""
    arguments = ["diff", "--name-status", "-z", "--find-renames"]
    if base is not None and head is not None:
        revisions = [
            git(root, "rev-parse", "--verify", "--end-of-options", f"{value}^{{commit}}")
            .decode("ascii").strip() for value in (base, head)
        ]
        current = git(root, "rev-parse", "--verify", "HEAD^{commit}").decode("ascii").strip()
        if revisions[1] != current:
            raise RenameError("The rename comparison head must be the current checkout's HEAD.")
        arguments.append("...".join(revisions))
    else:
        arguments.extend(("--cached", "HEAD"))
    fields = git(root, *arguments, "--").decode("utf-8").split("\0")
    pairs: list[tuple[str, str]] = []
    index = 0
    while index < len(fields) - 1:
        status = fields[index]
        count = 2 if status.startswith(("R", "C")) else 1
        if index + count >= len(fields) - 1:
            raise RenameError("Git returned incomplete change records.")
        if status.startswith("R"):
            pairs.append((fields[index + 1], fields[index + 2]))
        index += count + 1
    if not pairs:
        raise RenameError("Git detected no renames; supply an explicit --rename OLD NEW pair.")
    return pairs


def reference_edits(
    text: str, name: str, final_name: str, renames: dict[str, str],
    explicit: list[tuple[str, str]], tracked: set[str],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Rewrite whole path tokens and resolved Markdown links simultaneously.

    Bare nested filenames and computed expressions need an explicit reference
    pair. Remaining old-name occurrences block apply instead of being guessed.
    """
    replacements: dict[str, str] = {}
    for old, new in [*renames.items(), *explicit]:
        if not old or old == new:
            raise RenameError("Reference pairs must have distinct, nonempty values.")
        variants = [(old, new)]
        if (old, new) in renames.items():
            variants.append(("./" + old, "./" + new))
            if "/" in old:
                variants.extend((
                    (old.replace("/", "\\"), new.replace("/", "\\")),
                    (old.replace("/", "\\\\"), new.replace("/", "\\\\")),
                ))
        for before, after in variants:
            if before in replacements and replacements[before] != after:
                raise RenameError(f"Conflicting reference replacements: {before!r}")
            replacements[before] = after
    pattern = re.compile(
        r"(?<![\w./\\:-])(?:" + "|".join(
            re.escape(value) for value in sorted(replacements, key=len, reverse=True)
        ) + r")(?![\w./\\-])"
    )
    edits = [(match.start(), match.end(), replacements[match.group()])
             for match in pattern.finditer(text)]
    if name.lower().endswith((".md", ".markdown")):
        # Leave remote URLs, titles and fragments intact; resolve local links
        # against both the old and new containing file locations.
        for match in re.finditer(r"\]\(<?(?P<path>[^\s)>#]+)(?:#[^\s)>]*)?>?", text):
            start, end = match.span("path")
            raw = match["path"]
            if ":" in raw or raw.startswith("//"):
                continue
            decoded = unquote(raw)
            target = posixpath.normpath(
                decoded.lstrip("/") if decoded.startswith("/") else
                posixpath.join(posixpath.dirname(name), decoded)
            )
            destination = renames.get(target, target)
            if target not in renames and (name == final_name or target not in tracked):
                continue
            updated = ("/" + destination if decoded.startswith("/") else
                       posixpath.relpath(destination, posixpath.dirname(final_name) or "."))
            if decoded.startswith("./") and not updated.startswith("."):
                updated = "./" + updated
            if "%" in raw:
                updated = quote(updated, safe="/.-_")
            # A Markdown destination has stronger ownership than a root token.
            edits = [item for item in edits if item[1] <= start or item[0] >= end]
            if updated != raw:
                edits.append((start, end, updated))
    edits.sort()
    unresolved = []
    names = sorted({pathlib.PurePosixPath(old).name for old in renames})
    for basename in names:
        for match in re.finditer(r"(?<![\w.-])" + re.escape(basename) + r"(?![\w.-])", text):
            if not any(start <= match.start() and end >= match.end() for start, end, _ in edits):
                unresolved.append({"path": name, "line": text.count("\n", 0, match.start()) + 1,
                                   "reference": basename})
    records = [{"line": text.count("\n", 0, start) + 1,
                "old": text[start:end], "new": value} for start, end, value in edits]
    for start, end, value in reversed(edits):
        text = text[:start] + value + text[end:]
    return text, records, unresolved


def build_plan(
    root: pathlib.Path, pairs: list[tuple[str, str]], explicit: list[tuple[str, str]],
    excluded: set[str],
) -> tuple[dict[str, Any], dict[pathlib.Path, bytes], dict[pathlib.Path, bytes], list[tuple[pathlib.Path, pathlib.Path]]]:
    """Capture exact source bytes before making a complete, reviewable plan."""
    tracked = set(git(root, "ls-files", "-z").decode("utf-8").rstrip("\0").split("\0"))
    renames: dict[str, str] = {}
    moves = []
    originals: dict[pathlib.Path, bytes] = {}
    for raw_old, raw_new in pairs:
        old, new = relative_name(raw_old), relative_name(raw_new)
        if old in renames or old.casefold() == new.casefold():
            raise RenameError(f"Duplicate or case-only rename: {old}")
        source, destination = safe_path(root, old), safe_path(root, new)
        if any(name != new and name.casefold() == new.casefold() for name in tracked):
            raise RenameError(f"Destination conflicts with another tracked path's case: {new}")
        if source.exists():
            if not source.is_file() or old not in tracked or destination.exists():
                raise RenameError(f"Rename needs a tracked file and absent destination: {old} -> {new}")
            moves.append((source, destination))
            originals[source] = source.read_bytes()
        elif not destination.is_file() or not ({old, new} & tracked):
            raise RenameError(f"Neither the tracked source nor moved destination exists: {old} -> {new}")
        renames[old] = new
    folded_old = {name.casefold() for name in renames}
    folded_new = {name.casefold() for name in renames.values()}
    if (len(folded_old) != len(renames) or len(folded_new) != len(renames)
            or folded_old & folded_new):
        raise RenameError("Overlapping rename pairs need separate operations.")
    if excluded - tracked or excluded & (set(renames) | set(renames.values())):
        raise RenameError("Exclusions must name tracked reference files, not rename endpoints.")
    changes = {}
    records = []
    unresolved: list[dict[str, Any]] = []
    for name in sorted(tracked | set(renames.values())):
        if name in excluded:
            continue
        path = safe_path(root, name)
        if not path.exists():
            continue
        if not path.is_file():
            raise RenameError(f"Tracked entry is not a regular file: {name}")
        raw = path.read_bytes()
        try:
            if b"\0" in raw:
                raise UnicodeError("binary file")
            text = raw.decode("utf-8")
        except UnicodeError:
            if any(pathlib.PurePosixPath(old).name.encode("utf-8") in raw for old in renames):
                unresolved.append({"path": name, "reference": "non-UTF-8 content"})
            continue
        final_name = renames.get(name, name)
        # Already moved files still resolve old relative Markdown links from
        # their original containing directory.
        origin = next((old for old, new in renames.items() if new == name), name)
        updated, edits, missing = reference_edits(text, origin, final_name, renames, explicit, tracked)
        unresolved.extend(missing)
        if updated != text:
            originals[path] = raw
            changes[path] = updated.encode("utf-8")
            records.append({"path": final_name, "edits": edits})
    report = {"schema": "ceratops-repository-rename.v1", "status": "needs-references" if unresolved else "ready",
              "renames": [{"old": old, "new": new} for old, new in renames.items()],
              "updates": records, "unresolved": unresolved, "excluded": sorted(excluded)}
    return report, originals, changes, moves


def apply_plan(
    originals: dict[pathlib.Path, bytes], changes: dict[pathlib.Path, bytes],
    moves: list[tuple[pathlib.Path, pathlib.Path]], *, root: pathlib.Path,
) -> None:
    """Apply a complete plan; restore bytes/paths and remove owned empty dirs on error.

    This compensation covers caught errors, not process termination. Git remains
    the recovery source after interruption. No staging or commit occurs here.
    """
    for path in {*originals, *(destination for _, destination in moves)}:
        safe_path(root, path.relative_to(root).as_posix())
    if any(path.read_bytes() != content for path, content in originals.items()):
        raise RenameError("A source changed after planning; rebuild the plan.")
    made: list[pathlib.Path] = []
    moved: list[tuple[pathlib.Path, pathlib.Path]] = []
    written: list[pathlib.Path] = []
    try:
        for _source, destination in moves:
            if destination.exists():
                raise RenameError(f"Destination appeared after planning: {destination}")
            missing = []
            parent = destination.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir()
                made.append(directory)
        for path, content in changes.items():
            written.append(path)
            path.write_bytes(content)
        for source, destination in moves:
            if destination.exists():
                raise RenameError(f"Destination appeared after planning: {destination}")
            source.rename(destination)
            moved.append((source, destination))
    except OSError as exc:
        failure: Exception = exc
    except RenameError as exc:
        failure = exc
    else:
        return
    failures = []
    for source, destination in reversed(moved):
        try:
            destination.rename(source)
        except OSError as exc:
            failures.append(str(exc))
    for path in written:
        try:
            path.write_bytes(originals[path])
        except OSError as exc:
            failures.append(str(exc))
    for directory in reversed(made):
        try:
            directory.rmdir()
        except OSError as exc:
            failures.append(str(exc))
    detail = f"; rollback incomplete: {'; '.join(failures)}" if failures else "; rolled back"
    raise RenameError(str(failure) + detail)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path.cwd())
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--rename", nargs=2, action="append", metavar=("OLD", "NEW"))
    mode.add_argument("--from-git", action="store_true", help="Read staged renames, or committed renames with --base/--head.")
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--reference", nargs=2, action="append", default=[], metavar=("OLD", "NEW"))
    parser.add_argument("--exclude", action="append", default=[], help="Explicit tracked reference file to preserve, such as historical records.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=pathlib.Path, help="Write a new report file; the caller owns its retention and cleanup.")
    args = parser.parse_args(argv)
    try:
        root = args.repo_root.resolve(strict=True)
        actual = pathlib.Path(git(root, "rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
        if root != actual or bool(args.base) != bool(args.head) or (args.base and not args.from_git):
            raise RenameError("Use the repository root; --base and --head are paired and require --from-git.")
        if args.report and (args.report.exists() or args.report.resolve().is_relative_to(root)):
            raise RenameError("Report must be a new file outside the repository.")
        pairs = git_renames(root, args.base, args.head) if args.from_git else args.rename
        report, originals, changes, moves = build_plan(
            root, pairs, [tuple(pair) for pair in args.reference], {relative_name(path) for path in args.exclude},
        )
        # Prove report creation/writing works before changing repository files.
        # On a caught apply error the retained report records the failed plan.
        with (args.report.open("x", encoding="utf-8", newline="\n")
              if args.report else contextlib.nullcontext()) as output:
            def save_report() -> None:
                if output is not None:
                    output.seek(0)
                    json.dump(report, output, ensure_ascii=False, indent=2)
                    output.write("\n")
                    output.truncate()
                    output.flush()

            save_report()
            if args.apply and not report["unresolved"]:
                try:
                    apply_plan(originals, changes, moves, root=root)
                except (OSError, RenameError) as exc:
                    report.update(status="failed", message=str(exc))
                    save_report()
                    raise
                report["status"] = "applied"
                try:
                    save_report()
                except OSError as exc:
                    raise RenameError(f"Repository changes applied, but report update failed: {exc}") from exc
        if args.report:
            print("OK" if not report["unresolved"] else "error: unresolved references; inspect the report.")
        elif args.apply and not report["unresolved"]:
            print("OK")
        else:
            print(json.dumps(report, ensure_ascii=False))
        return 2 if report["unresolved"] else 0
    except (RenameError, OSError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
