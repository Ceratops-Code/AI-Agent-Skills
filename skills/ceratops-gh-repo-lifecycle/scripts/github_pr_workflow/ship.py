"""Resume-safe orchestration for publishing, gating, merging, and syncing one PR.

Checkpoints live under the repository's Git metadata and are keyed by the
GitHub repository plus the exact shipped commit. GitHub mutations retain their
existing module owners; this module only sequences them and records completed
state transitions.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import pathlib
import re
import sys
import time
from typing import Any

from github_contract_engine.github_api import run_json_command
from github_contract_engine.levels import ERROR, WARN

from . import codex_review, ensure_pr, merge, readiness, sync
from .command import CommandError, require_output, require_success


PHASES = ("prepared", "pr_ready", "gates_passed", "merged", "synchronized")
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ShipError(RuntimeError):
    """Raised when an exact-state shipping invariant is not satisfied."""


def _git(repo_root: pathlib.Path, *args: str) -> list[str]:
    return ["git", "-C", str(repo_root), *args]


def _phase_at_least(state: dict[str, Any], phase: str) -> bool:
    return PHASES.index(str(state["phase"])) >= PHASES.index(phase)


def _require_api_data(result: Any, operation: str) -> Any:
    if not result.ok:
        detail = result.message or result.status or "unknown GitHub error"
        raise ShipError(f"{operation} failed: {detail}")
    return result.data


def _repository_name(repo_root: pathlib.Path, requested: str | None) -> str:
    if requested:
        if requested.count("/") != 1:
            raise ShipError("--repo must use OWNER/REPO.")
        return requested
    result = run_json_command(
        ["gh", "repo", "view", "--json", "nameWithOwner"],
        "gh repo view",
        cwd=repo_root,
    )
    data = _require_api_data(result, "repository discovery")
    name = data.get("nameWithOwner") if isinstance(data, dict) else None
    if not isinstance(name, str) or name.count("/") != 1:
        raise ShipError("Could not infer GitHub repository; pass --repo OWNER/REPO.")
    return name


def _checkpoint_directory(repo_root: pathlib.Path, repository: str) -> pathlib.Path:
    raw = require_output(
        _git(repo_root, "rev-parse", "--git-common-dir"), cwd=repo_root
    ).splitlines()[0]
    common_dir = pathlib.Path(raw)
    if not common_dir.is_absolute():
        common_dir = repo_root / common_dir
    repo_key = re.sub(r"[^A-Za-z0-9._-]+", "__", repository)
    return (
        common_dir.resolve()
        / "codex"
        / "github-pr-workflow"
        / "ship"
        / repo_key
    )


def _checkpoint_path(
    repo_root: pathlib.Path, repository: str, commit: str
) -> pathlib.Path:
    return _checkpoint_directory(repo_root, repository) / f"{commit}.json"


def _read_checkpoint(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShipError(f"Could not read ship checkpoint {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("phase") not in PHASES:
        raise ShipError(f"Ship checkpoint has an invalid state: {path}")
    return value


def _write_checkpoint(path: pathlib.Path, state: dict[str, Any]) -> None:
    """Atomically persist a compact checkpoint without touching tracked files."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _find_incomplete_commit(
    repo_root: pathlib.Path, repository: str, head_branch: str
) -> str | None:
    directory = _checkpoint_directory(repo_root, repository)
    if not directory.is_dir():
        return None
    candidates: list[str] = []
    for path in directory.glob("*.json"):
        state = _read_checkpoint(path)
        if (
            state.get("repository") == repository
            and state.get("head_branch") == head_branch
            and state.get("phase") != "synchronized"
            and isinstance(state.get("commit"), str)
        ):
            candidates.append(str(state["commit"]))
    if len(candidates) > 1:
        raise ShipError(
            "Multiple incomplete checkpoints exist for this branch; pass --commit."
        )
    return candidates[0] if candidates else None


def _resolve_commit(
    args: argparse.Namespace, repo_root: pathlib.Path, repository: str
) -> str:
    if args.commit:
        commit = args.commit.lower()
    else:
        current_branch = require_output(
            _git(repo_root, "branch", "--show-current"), cwd=repo_root
        ).strip()
        if current_branch == args.head_branch:
            commit = require_output(
                _git(repo_root, "rev-parse", "HEAD"), cwd=repo_root
            ).splitlines()[0]
        else:
            commit = _find_incomplete_commit(
                repo_root, repository, args.head_branch
            ) or ""
            if not commit:
                raise ShipError(
                    f"Expected active branch {args.head_branch!r}; pass --commit "
                    "only when resuming its existing checkpoint."
                )
    if not FULL_SHA_RE.fullmatch(commit):
        raise ShipError("--commit must be a full 40-character Git commit SHA.")
    require_success(
        _git(repo_root, "cat-file", "-e", f"{commit}^{{commit}}"), cwd=repo_root
    )
    return commit


def _new_checkpoint(
    args: argparse.Namespace,
    repo_root: pathlib.Path,
    repository: str,
    commit: str,
) -> dict[str, Any]:
    current_branch = require_output(
        _git(repo_root, "branch", "--show-current"), cwd=repo_root
    ).strip()
    current_head = require_output(
        _git(repo_root, "rev-parse", "HEAD"), cwd=repo_root
    ).splitlines()[0]
    if current_branch != args.head_branch or current_head != commit:
        raise ShipError(
            "A new ship checkpoint requires the requested head branch at the "
            "exact requested commit."
        )
    return {
        "version": 1,
        "repository": repository,
        "commit": commit,
        "head_branch": args.head_branch,
        "base_branch": args.base_branch,
        "phase": "prepared",
    }


def _load_or_create_checkpoint(
    args: argparse.Namespace,
    repo_root: pathlib.Path,
    repository: str,
    commit: str,
) -> tuple[pathlib.Path, dict[str, Any]]:
    path = _checkpoint_path(repo_root, repository, commit)
    state = _read_checkpoint(path) if path.is_file() else _new_checkpoint(
        args, repo_root, repository, commit
    )
    expected = {
        "repository": repository,
        "commit": commit,
        "head_branch": args.head_branch,
        "base_branch": args.base_branch,
    }
    drift = {
        key: {"expected": value, "actual": state.get(key)}
        for key, value in expected.items()
        if state.get(key) != value
    }
    if drift:
        raise ShipError(f"Ship checkpoint identity drift: {json.dumps(drift)}")
    if not path.is_file():
        _write_checkpoint(path, state)
    return path, state


def _transient_readiness(finding: readiness.Finding) -> bool:
    if finding.check == "pr.mergeable" and finding.level == WARN:
        return True
    if finding.check == "pr.status_checks" and "pending" in finding.message.lower():
        return True
    if (
        finding.check == "pr.review_decision"
        and finding.actual == "REVIEW_REQUIRED"
    ):
        return True
    return False


def wait_for_ci_gate(
    pr: str,
    repo_root: pathlib.Path,
    expected_head: str,
    *,
    wait_seconds: int,
    interval_seconds: int,
    allow_admin_review_bypass: bool,
) -> dict[str, Any]:
    """Poll readiness until all blocking state for the exact PR head passes."""

    deadline = time.monotonic() + wait_seconds
    while True:
        summary, findings = readiness.validate_readiness(
            pr,
            repo_root,
            readiness.default_contract_path().resolve(),
            allow_admin_review_bypass=allow_admin_review_bypass,
        )
        if summary.get("head_oid") != expected_head:
            raise ShipError(
                f"PR head {summary.get('head_oid')!r} does not match shipped "
                f"commit {expected_head!r}."
            )
        terminal = [
            finding
            for finding in findings
            if finding.level == ERROR and not _transient_readiness(finding)
        ]
        if terminal:
            detail = "; ".join(
                f"{finding.check}: {finding.message}" for finding in terminal[:8]
            )
            raise ShipError(f"PR readiness failed: {detail}")
        pending = [finding for finding in findings if _transient_readiness(finding)]
        if not pending:
            return {
                "pr": summary.get("number"),
                "head_oid": summary.get("head_oid"),
                "pending": 0,
            }
        if time.monotonic() >= deadline:
            checks = sorted({finding.check for finding in pending})
            raise ShipError(
                f"PR readiness timed out with pending checks: {', '.join(checks)}"
            )
        time.sleep(max(0, interval_seconds))


def run_parallel_gates(
    args: argparse.Namespace,
    pr: str,
    repository: str,
    commit: str,
    *,
    ci_wait_seconds: int,
    review_wait_seconds: int,
) -> dict[str, Any]:
    """Wait on independent CI/readiness and Codex-review reads concurrently."""

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        ci_future = executor.submit(
            wait_for_ci_gate,
            pr,
            args.repo_root,
            commit,
            wait_seconds=ci_wait_seconds,
            interval_seconds=args.interval_seconds,
            allow_admin_review_bypass=args.admin,
        )
        review_future = executor.submit(
            codex_review.wait_for_codex_threads,
            pr,
            repository,
            wait_seconds=review_wait_seconds,
            interval_seconds=args.interval_seconds,
            authors=codex_review.DEFAULT_CODEX_AUTHORS,
            cwd=args.repo_root,
        )
        ci_result = ci_future.result()
        review_result = review_future.result()
    if review_result.get("head_oid") != commit:
        raise ShipError(
            f"Codex review head {review_result.get('head_oid')!r} does not "
            f"match shipped commit {commit!r}."
        )
    active_count = int(review_result.get("active_codex_thread_count") or 0)
    if active_count:
        raise ShipError(f"Codex review gate found {active_count} active thread(s).")
    return {
        "ci": ci_result,
        "codex": {
            "head_oid": review_result.get("head_oid"),
            "active_threads": active_count,
        },
    }


def _live_pr(
    repo_root: pathlib.Path, repository: str, pr: str
) -> dict[str, Any]:
    result = run_json_command(
        [
            "gh",
            "pr",
            "view",
            pr,
            "--repo",
            repository,
            "--json",
            "number,url,state,headRefOid,mergedAt,mergeCommit",
        ],
        "gh pr view",
        cwd=repo_root,
    )
    data = _require_api_data(result, "PR state read")
    if not isinstance(data, dict):
        raise ShipError("GitHub returned an invalid PR state.")
    return data


def _remote_head(
    repo_root: pathlib.Path, remote_name: str, branch: str
) -> str | None:
    output = require_output(
        _git(
            repo_root,
            "ls-remote",
            "--heads",
            remote_name,
            f"refs/heads/{branch}",
        ),
        cwd=repo_root,
    )
    if not output:
        return None
    return output.split()[0]


def restore_reusable_branch(
    repo_root: pathlib.Path,
    *,
    remote_name: str,
    branch: str,
    shipped_commit: str,
    synchronized_head: str,
) -> dict[str, Any]:
    """Restore or align only the unchanged reusable remote head branch."""

    local_head = require_output(
        _git(repo_root, "rev-parse", f"refs/heads/{branch}"), cwd=repo_root
    ).splitlines()[0]
    if local_head != synchronized_head:
        raise ShipError(
            f"Reusable local branch {branch!r} is not at synchronized main."
        )
    remote_head = _remote_head(repo_root, remote_name, branch)
    if remote_head == synchronized_head:
        return {"branch": branch, "status": "already_aligned", "head": remote_head}
    if remote_head is None:
        require_success(
            _git(
                repo_root,
                "push",
                "-u",
                remote_name,
                f"{branch}:{branch}",
            ),
            cwd=repo_root,
        )
        return {"branch": branch, "status": "restored", "head": synchronized_head}
    if remote_head != shipped_commit:
        raise ShipError(
            f"Reusable remote branch {branch!r} moved to {remote_head!r}; "
            "refusing to overwrite it."
        )
    require_success(
        _git(
            repo_root,
            "push",
            f"--force-with-lease=refs/heads/{branch}:{shipped_commit}",
            remote_name,
            f"{branch}:{branch}",
        ),
        cwd=repo_root,
    )
    return {"branch": branch, "status": "aligned", "head": synchronized_head}


def ship(args: argparse.Namespace) -> dict[str, Any]:
    """Advance one exact commit through PR publication, gates, merge, and sync."""

    repo_root = args.repo_root.expanduser().resolve(strict=True)
    if not repo_root.is_dir():
        raise ShipError(f"Repository root is not a directory: {repo_root}")
    args.repo_root = repo_root
    repository = _repository_name(repo_root, args.repo)
    commit = _resolve_commit(args, repo_root, repository)
    checkpoint_path, state = _load_or_create_checkpoint(
        args, repo_root, repository, commit
    )
    changes: list[str] = []

    if not _phase_at_least(state, "pr_ready"):
        pr_result = ensure_pr.ensure_pr(
            argparse.Namespace(
                repo_root=repo_root,
                head_branch=args.head_branch,
                base_branch=args.base_branch,
                remote_name=args.remote_name,
                title=args.title,
                body=args.body,
            )
        )
        state.update(
            {
                "phase": "pr_ready",
                "pr": pr_result.get("pr"),
                "url": pr_result.get("url"),
            }
        )
        _write_checkpoint(checkpoint_path, state)
        changes.append("pr_ready")

    pr = str(state["pr"])
    if not _phase_at_least(state, "merged"):
        live = _live_pr(repo_root, repository, pr)
        if live.get("headRefOid") != commit:
            raise ShipError("Live PR no longer points at the checkpointed commit.")
        if live.get("state") == "MERGED":
            merge_commit = live.get("mergeCommit")
            state.update(
                {
                    "phase": "merged",
                    "merged_at": live.get("mergedAt"),
                    "merge_commit": (
                        merge_commit.get("oid")
                        if isinstance(merge_commit, dict)
                        else None
                    ),
                }
            )
            _write_checkpoint(checkpoint_path, state)
            changes.append("merged_reconciled")
        elif live.get("state") != "OPEN":
            raise ShipError(f"Live PR state is {live.get('state')!r}, not OPEN.")

    if not _phase_at_least(state, "merged"):
        if not _phase_at_least(state, "gates_passed"):
            run_parallel_gates(
                args,
                pr,
                repository,
                commit,
                ci_wait_seconds=args.ci_wait_seconds,
                review_wait_seconds=args.review_wait_seconds,
            )
            # The two waits can finish at different times. Re-read both gates
            # immediately before recording permission to merge.
            run_parallel_gates(
                args,
                pr,
                repository,
                commit,
                ci_wait_seconds=0,
                review_wait_seconds=0,
            )
            state["phase"] = "gates_passed"
            _write_checkpoint(checkpoint_path, state)
            changes.append("gates_passed")
        else:
            run_parallel_gates(
                args,
                pr,
                repository,
                commit,
                ci_wait_seconds=0,
                review_wait_seconds=0,
            )

        merge_result = merge.merge_verified_pr(
            argparse.Namespace(
                pr=pr,
                repo_root=repo_root,
                repo=repository,
                merge_method=args.merge_method,
                admin=args.admin,
                auto=False,
                delete_branch=args.delete_branch,
                wait_seconds=args.review_wait_seconds,
                interval_seconds=args.interval_seconds,
            ),
            expected_head=commit,
        )
        if merge_result.get("status") != "merged":
            raise ShipError("Ship requires a verified immediate merge result.")
        state.update(
            {
                "phase": "merged",
                "merged_at": merge_result.get("merged_at"),
                "merge_commit": merge_result.get("merge_commit"),
            }
        )
        _write_checkpoint(checkpoint_path, state)
        changes.append("merged")

    if not _phase_at_least(state, "synchronized"):
        sync_result = sync.sync_main(
            argparse.Namespace(
                repo_root=repo_root,
                main_branch=args.base_branch,
                remote_name=args.remote_name,
                align_branch=[args.head_branch] if args.reusable_head else [],
            )
        )
        branch_result: dict[str, Any] | None = None
        if args.reusable_head:
            branch_result = restore_reusable_branch(
                repo_root,
                remote_name=args.remote_name,
                branch=args.head_branch,
                shipped_commit=commit,
                synchronized_head=str(sync_result["head"]),
            )
            if branch_result["status"] in {"restored", "aligned"}:
                changes.append(f"reusable_branch_{branch_result['status']}")
        state.update(
            {
                "phase": "synchronized",
                "synchronized_head": sync_result.get("head"),
                "reusable_branch": branch_result,
            }
        )
        _write_checkpoint(checkpoint_path, state)
        changes.append("synchronized")

    return {
        "status": "shipped" if changes else "already_shipped",
        "repository": repository,
        "commit": commit,
        "pr": state.get("pr"),
        "url": state.get("url"),
        "merge_commit": state.get("merge_commit"),
        "synchronized_head": state.get("synchronized_head"),
        "changes": changes,
    }


def build_parser() -> argparse.ArgumentParser:
    """Create the end-to-end ship parser."""

    parser = argparse.ArgumentParser(
        prog="python -m github_pr_workflow ship",
        description="Resume one exact commit through PR publication and merge.",
    )
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--repo", help="OWNER/REPO; inferred from the checkout")
    parser.add_argument("--head-branch", required=True)
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--remote-name", default="origin")
    parser.add_argument("--commit", help="full head SHA for exact checkpoint resume")
    parser.add_argument("--title")
    parser.add_argument("--body")
    parser.add_argument(
        "--merge-method", choices=("merge", "squash", "rebase"), default="merge"
    )
    parser.add_argument("--admin", action="store_true")
    parser.add_argument("--delete-branch", action="store_true")
    parser.add_argument(
        "--reusable-head",
        action="store_true",
        help="align the local head to main and safely restore its remote ref",
    )
    parser.add_argument("--ci-wait-seconds", type=int, default=900)
    parser.add_argument("--review-wait-seconds", type=int, default=260)
    parser.add_argument("--interval-seconds", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run shipping and emit exactly one compact state-change document."""

    args = build_parser().parse_args(argv)
    try:
        print(json.dumps(ship(args), separators=(",", ":"), ensure_ascii=True))
        return 0
    except (
        CommandError,
        ShipError,
        ensure_pr.EnsurePrError,
        merge.WorkflowError,
        sync.SyncError,
        readiness.CommandError,
        codex_review.CommandError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(
            json.dumps(
                {"status": "error", "message": str(exc)},
                separators=(",", ":"),
                ensure_ascii=True,
            ),
            file=sys.stderr,
        )
        return 1
