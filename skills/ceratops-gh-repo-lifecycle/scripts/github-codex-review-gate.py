#!/usr/bin/env python3
"""Wait for or resolve active Codex review threads on a GitHub pull request."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from typing import Any


DEFAULT_CODEX_AUTHORS = ("chatgpt-codex-connector[bot]", "chatgpt-codex-connector")
PR_URL_RE = re.compile(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)(?:\b|/|#|\?)")


class CommandError(RuntimeError):
    """Raised when GitHub CLI state cannot be fetched or mutated."""


def run_gh(args: list[str], *, stdin: str | None = None) -> str:
    """Run a GitHub CLI command and return stdout, raising compact failures."""

    completed = subprocess.run(
        ["gh", *args],
        input=stdin,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "command failed"
        raise CommandError(f"gh {' '.join(args)}: {detail}")
    return completed.stdout.strip()


def gh_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Run a GraphQL request through gh so existing auth and host config apply."""

    payload = json.dumps({"query": query, "variables": variables}, separators=(",", ":"))
    raw = run_gh(["api", "graphql", "--input", "-"], stdin=payload)
    data = json.loads(raw or "{}")
    if data.get("errors"):
        raise CommandError(json.dumps(data["errors"], ensure_ascii=True))
    return data


def default_repo() -> str:
    """Return the current checkout repository in owner/name form."""

    raw = run_gh(["repo", "view", "--json", "nameWithOwner"])
    data = json.loads(raw or "{}")
    name = data.get("nameWithOwner")
    if not isinstance(name, str) or "/" not in name:
        raise CommandError("could not infer repository; pass --repo OWNER/REPO")
    return name


def resolve_pr(selector: str, repo: str | None) -> tuple[str, str, int]:
    """Resolve PR selector and repository into owner, repo name, and number."""

    match = PR_URL_RE.search(selector)
    if match:
        owner, name, number = match.groups()
        return owner, name, int(number)
    selected_repo = repo or default_repo()
    if "/" not in selected_repo:
        raise CommandError("--repo must use OWNER/REPO")
    owner, name = selected_repo.split("/", 1)
    try:
        number = int(selector)
    except ValueError as exc:
        raise CommandError("PR selector must be a PR URL or number with --repo") from exc
    return owner, name, number


def parse_utc(value: str) -> dt.datetime:
    """Parse GitHub timestamps as timezone-aware UTC datetimes."""

    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def fetch_pr(owner: str, name: str, number: int) -> dict[str, Any]:
    """Fetch PR metadata and review threads with pagination."""

    query = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      number
      url
      createdAt
      headRefOid
      reviewThreads(first: 100, after: $cursor) {
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          startLine
          diffSide
          startDiffSide
          comments(first: 30) {
            nodes {
              id
              databaseId
              body
              url
              createdAt
              author {
                login
              }
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}
"""
    cursor: str | None = None
    pr_data: dict[str, Any] | None = None
    threads: list[dict[str, Any]] = []
    while True:
        data = gh_graphql(query, {"owner": owner, "name": name, "number": number, "cursor": cursor})
        pr = ((data.get("data") or {}).get("repository") or {}).get("pullRequest")
        if not isinstance(pr, dict):
            raise CommandError(f"pull request not found: {owner}/{name}#{number}")
        if pr_data is None:
            pr_data = {key: pr.get(key) for key in ("number", "url", "createdAt", "headRefOid")}
        review_threads = pr.get("reviewThreads") or {}
        threads.extend(review_threads.get("nodes") or [])
        page = review_threads.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        cursor = page.get("endCursor")
    assert pr_data is not None
    pr_data["reviewThreads"] = threads
    return pr_data


def comment_author(comment: dict[str, Any]) -> str:
    """Return a normalized comment author login."""

    author = comment.get("author")
    if not isinstance(author, dict):
        return ""
    return str(author.get("login") or "")


def active_codex_threads(pr_data: dict[str, Any], authors: set[str]) -> list[dict[str, Any]]:
    """Return unresolved, current review threads that contain a Codex comment."""

    active: list[dict[str, Any]] = []
    for thread in pr_data.get("reviewThreads") or []:
        if thread.get("isResolved") or thread.get("isOutdated"):
            continue
        comments = ((thread.get("comments") or {}).get("nodes")) or []
        codex_comments = [comment for comment in comments if comment_author(comment).lower() in authors]
        if not codex_comments:
            continue
        active.append(
            {
                "id": thread.get("id"),
                "path": thread.get("path"),
                "line": thread.get("line"),
                "start_line": thread.get("startLine"),
                "diff_side": thread.get("diffSide"),
                "start_diff_side": thread.get("startDiffSide"),
                "comments": codex_comments,
            }
        )
    return active


def wait(args: argparse.Namespace) -> int:
    """Wait until active Codex review threads appear or the creation window expires."""

    owner, name, number = resolve_pr(args.pr, args.repo)
    authors = {author.lower() for author in args.author}
    start = dt.datetime.now(dt.timezone.utc)
    waited = 0.0
    last_pr: dict[str, Any] | None = None
    threads: list[dict[str, Any]] = []
    deadline: dt.datetime | None = None

    while True:
        last_pr = fetch_pr(owner, name, number)
        created_at = parse_utc(str(last_pr["createdAt"]))
        deadline = created_at + dt.timedelta(seconds=args.wait_seconds)
        threads = active_codex_threads(last_pr, authors)
        if threads:
            break
        now = dt.datetime.now(dt.timezone.utc)
        if now >= deadline:
            break
        sleep_for = min(float(args.interval_seconds), (deadline - now).total_seconds())
        if sleep_for > 0:
            time.sleep(sleep_for)
            waited = (dt.datetime.now(dt.timezone.utc) - start).total_seconds()

    assert last_pr is not None
    output = {
        "repo": f"{owner}/{name}",
        "pr": number,
        "url": last_pr.get("url"),
        "head_oid": last_pr.get("headRefOid"),
        "created_at": last_pr.get("createdAt"),
        "wait_seconds": args.wait_seconds,
        "interval_seconds": args.interval_seconds,
        "deadline": deadline.isoformat() if deadline else None,
        "waited_seconds": round(waited, 3),
        "status": "found_active_codex_threads" if threads else "no_active_codex_threads",
        "active_codex_thread_count": len(threads),
        "active_codex_threads": threads,
    }
    print(json.dumps(output, indent=2 if args.pretty else None, ensure_ascii=True))
    return 1 if threads else 0


def resolve(args: argparse.Namespace) -> int:
    """Resolve selected review threads after their issues have been fixed."""

    mutation = """
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread {
      id
      isResolved
    }
  }
}
"""
    results = []
    for thread_id in args.thread_id:
        data = gh_graphql(mutation, {"threadId": thread_id})
        thread = (((data.get("data") or {}).get("resolveReviewThread") or {}).get("thread")) or {}
        results.append({"id": thread.get("id", thread_id), "is_resolved": thread.get("isResolved")})
    print(json.dumps({"resolved": results}, indent=2 if args.pretty else None, ensure_ascii=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    wait_parser = subparsers.add_parser("wait", help="poll for active Codex review threads")
    wait_parser.add_argument("--pr", required=True, help="PR URL or number")
    wait_parser.add_argument("--repo", help="OWNER/REPO, required when --pr is a number outside a checkout")
    wait_parser.add_argument("--wait-seconds", type=int, default=180)
    wait_parser.add_argument("--interval-seconds", type=int, default=10)
    wait_parser.add_argument("--author", action="append", default=list(DEFAULT_CODEX_AUTHORS))
    wait_parser.add_argument("--json", action="store_true", help="accepted for compatibility; output is always JSON")
    wait_parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    wait_parser.set_defaults(func=wait)

    resolve_parser = subparsers.add_parser("resolve", help="resolve fixed Codex review threads")
    resolve_parser.add_argument("--thread-id", action="append", required=True, help="GraphQL PullRequestReviewThread ID")
    resolve_parser.add_argument("--json", action="store_true", help="accepted for compatibility; output is always JSON")
    resolve_parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    resolve_parser.set_defaults(func=resolve)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the selected Codex review gate operation."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except CommandError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
