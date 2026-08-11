"""Wait for, address, or resolve Codex review threads on a pull request."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import time
from collections.abc import Mapping, Sequence
from typing import Any

from github_contract_engine.github_api import (
    run_gh_api,
    run_gh_graphql,
    run_json_command,
)

DEFAULT_CODEX_AUTHORS = ("chatgpt-codex-connector[bot]", "chatgpt-codex-connector")
PR_URL_RE = re.compile(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)(?:\b|/|#|\?)")
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ADDRESS_SCHEMA = "ceratops-review-thread-replies.v1"
ADDRESS_FIELDS = {"schema", "repo", "pr", "head_oid", "replies"}
REPLY_FIELDS = {"thread_id", "top_comment_database_id", "reply"}


class CommandError(RuntimeError):
    """Raised when GitHub CLI state cannot be fetched or mutated."""


def gh_graphql(
    query: str,
    variables: dict[str, Any],
    *,
    cwd: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Use the contract engine's authenticated GitHub GraphQL client."""

    result = run_gh_graphql(query, variables, "pull-request-review", cwd=cwd)
    if not result.ok:
        raise CommandError(result.message or "GitHub GraphQL request failed")
    data = result.data
    if not isinstance(data, dict):
        raise CommandError("GitHub GraphQL returned an invalid response")
    return data


def default_repo(cwd: pathlib.Path | None = None) -> str:
    """Return the current checkout repository in owner/name form."""

    result = run_json_command(
        ["gh", "repo", "view", "--json", "nameWithOwner"],
        "gh repo view",
        cwd=cwd,
    )
    if not result.ok:
        raise CommandError(result.message or "GitHub repository lookup failed")
    data = result.data
    if not isinstance(data, dict):
        raise CommandError("GitHub repository lookup returned an invalid response")
    name = data.get("nameWithOwner")
    if not isinstance(name, str) or "/" not in name:
        raise CommandError("could not infer repository; pass --repo OWNER/REPO")
    return name


def resolve_pr(
    selector: str,
    repo: str | None,
    *,
    cwd: pathlib.Path | None = None,
) -> tuple[str, str, int]:
    """Resolve PR selector and repository into owner, repo name, and number."""

    match = PR_URL_RE.search(selector)
    if match:
        owner, name, number = match.groups()
        return owner, name, int(number)
    selected_repo = repo or default_repo(cwd)
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


def fetch_pr(
    owner: str,
    name: str,
    number: int,
    *,
    cwd: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Fetch PR metadata and review threads with pagination."""

    query = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  viewer {
    login
  }
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
          comments(first: 100) {
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
            pageInfo {
              hasNextPage
              endCursor
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
        data = gh_graphql(
            query,
            {"owner": owner, "name": name, "number": number, "cursor": cursor},
            cwd=cwd,
        )
        response = data.get("data") or {}
        pr = (response.get("repository") or {}).get("pullRequest")
        if not isinstance(pr, dict):
            raise CommandError(f"pull request not found: {owner}/{name}#{number}")
        if pr_data is None:
            pr_data = {key: pr.get(key) for key in ("number", "url", "createdAt", "headRefOid")}
            viewer = response.get("viewer")
            pr_data["viewer_login"] = (
                viewer.get("login") if isinstance(viewer, dict) else None
            )
        review_threads = pr.get("reviewThreads") or {}
        threads.extend(review_threads.get("nodes") or [])
        page = review_threads.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        cursor = page.get("endCursor")
    assert pr_data is not None
    comment_query = """
query($thread: ID!, $cursor: String) {
  node(id: $thread) {
    ... on PullRequestReviewThread {
      comments(first: 100, after: $cursor) {
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
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}
"""
    for thread in threads:
        comments = thread.get("comments") or {}
        nodes = list(comments.get("nodes") or [])
        page = comments.get("pageInfo") or {}
        while page.get("hasNextPage"):
            cursor = page.get("endCursor")
            thread_id = thread.get("id")
            if not isinstance(thread_id, str) or not thread_id:
                raise CommandError("review thread id is unavailable during comment pagination")
            if not isinstance(cursor, str) or not cursor:
                raise CommandError(
                    f"review thread {thread_id} comment cursor is unavailable"
                )
            data = gh_graphql(
                comment_query,
                {"thread": thread_id, "cursor": cursor},
                cwd=cwd,
            )
            node = (data.get("data") or {}).get("node")
            if not isinstance(node, dict):
                raise CommandError(f"review thread not found during pagination: {thread_id}")
            next_comments = node.get("comments") or {}
            nodes.extend(next_comments.get("nodes") or [])
            next_page = next_comments.get("pageInfo") or {}
            next_cursor = next_page.get("endCursor")
            if next_page.get("hasNextPage") and next_cursor == cursor:
                raise CommandError(
                    f"review thread {thread_id} comment cursor did not advance"
                )
            page = next_page
        thread["comments"] = {"nodes": nodes, "pageInfo": page}
    pr_data["reviewThreads"] = threads
    return pr_data


def comment_author(comment: dict[str, Any]) -> str:
    """Return a normalized comment author login."""

    author = comment.get("author")
    if not isinstance(author, dict):
        return ""
    return str(author.get("login") or "")


def active_codex_threads(pr_data: dict[str, Any], authors: set[str]) -> list[dict[str, Any]]:
    """Return compact reply-ready identities for current Codex threads."""

    active: list[dict[str, Any]] = []
    for thread in pr_data.get("reviewThreads") or []:
        if thread.get("isResolved") or thread.get("isOutdated"):
            continue
        comments = ((thread.get("comments") or {}).get("nodes")) or []
        codex_comments = [comment for comment in comments if comment_author(comment).lower() in authors]
        if not codex_comments:
            continue
        codex_comment = codex_comments[0]
        top_comment = comments[0]
        active.append(
            {
                "id": thread.get("id"),
                "thread_id": thread.get("id"),
                "path": thread.get("path"),
                "line": thread.get("line"),
                "start_line": thread.get("startLine"),
                "diff_side": thread.get("diffSide"),
                "start_diff_side": thread.get("startDiffSide"),
                "body": codex_comment.get("body"),
                "top_comment_database_id": top_comment.get("databaseId"),
                "comment_url": codex_comment.get("url"),
            }
        )
    return active


def unresolved_review_threads(pr_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return compact reply-ready identities, including outdated threads."""

    unresolved: list[dict[str, Any]] = []
    for thread in pr_data.get("reviewThreads") or []:
        if thread.get("isResolved"):
            continue
        comments = ((thread.get("comments") or {}).get("nodes")) or []
        top_comment = comments[0] if comments else {}
        unresolved.append(
            {
                "id": thread.get("id"),
                "thread_id": thread.get("id"),
                "path": thread.get("path"),
                "line": thread.get("line"),
                "is_outdated": bool(thread.get("isOutdated")),
                "body": top_comment.get("body"),
                "top_comment_database_id": top_comment.get("databaseId"),
                "comment_url": top_comment.get("url"),
            }
        )
    return unresolved


def wait_for_codex_threads(
    selector: str,
    repo: str | None,
    *,
    wait_seconds: int,
    interval_seconds: int,
    authors: list[str] | tuple[str, ...],
    cwd: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Return the bounded Codex review wait result without printing it."""

    owner, name, number = resolve_pr(selector, repo, cwd=cwd)
    normalized_authors = {author.lower() for author in authors}
    start = dt.datetime.now(dt.timezone.utc)
    waited = 0.0
    last_pr: dict[str, Any] | None = None
    threads: list[dict[str, Any]] = []
    deadline = start + dt.timedelta(seconds=wait_seconds)

    while True:
        last_pr = fetch_pr(owner, name, number, cwd=cwd)
        threads = active_codex_threads(last_pr, normalized_authors)
        if threads:
            break
        now = dt.datetime.now(dt.timezone.utc)
        if now >= deadline:
            break
        sleep_for = min(float(interval_seconds), (deadline - now).total_seconds())
        if sleep_for > 0:
            time.sleep(sleep_for)
            waited = (dt.datetime.now(dt.timezone.utc) - start).total_seconds()

    assert last_pr is not None
    unresolved_threads = unresolved_review_threads(last_pr)
    return {
        "repo": f"{owner}/{name}",
        "pr": number,
        "url": last_pr.get("url"),
        "head_oid": last_pr.get("headRefOid"),
        "created_at": last_pr.get("createdAt"),
        "wait_seconds": wait_seconds,
        "interval_seconds": interval_seconds,
        "deadline": deadline.isoformat(),
        "waited_seconds": round(waited, 3),
        "status": "found_active_codex_threads" if threads else "no_active_codex_threads",
        "active_codex_thread_count": len(threads),
        "active_codex_threads": threads,
        "unresolved_review_thread_count": len(unresolved_threads),
        "unresolved_review_threads": unresolved_threads,
    }


def wait(args: argparse.Namespace) -> int:
    """Wait until active Codex review threads appear or the creation window expires."""

    output = wait_for_codex_threads(
        args.pr,
        args.repo,
        wait_seconds=args.wait_seconds,
        interval_seconds=args.interval_seconds,
        authors=args.author,
        cwd=args.cwd,
    )
    print(json.dumps(output, indent=2 if args.pretty else None, ensure_ascii=True))
    return 1 if output["active_codex_thread_count"] else 0


def _closed_fields(
    value: Mapping[str, object],
    expected: set[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        detail = "; ".join(
            part
            for part in (
                f"missing {', '.join(missing)}" if missing else "",
                f"unknown {', '.join(extra)}" if extra else "",
            )
            if part
        )
        raise CommandError(f"{label} fields are invalid: {detail}")


def _address_request(path: pathlib.Path) -> dict[str, Any]:
    """Load one closed prepared-reply request without implicit scope."""

    expanded = path.expanduser()
    if expanded.is_symlink():
        raise CommandError("address request must be a regular file")
    resolved = expanded.resolve(strict=True)
    if not resolved.is_file():
        raise CommandError("address request must be a regular file")
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CommandError(f"address request is unreadable: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise CommandError("address request must be a JSON object")
    _closed_fields(raw, ADDRESS_FIELDS, "address request")
    if raw.get("schema") != ADDRESS_SCHEMA:
        raise CommandError(f"address request schema must be {ADDRESS_SCHEMA}")
    repo = raw.get("repo")
    if (
        not isinstance(repo, str)
        or repo.count("/") != 1
        or any(
            not part or any(character.isspace() for character in part)
            for part in repo.split("/")
        )
    ):
        raise CommandError("address request repo must use OWNER/REPO")
    pr = raw.get("pr")
    if not isinstance(pr, int) or isinstance(pr, bool) or pr < 1:
        raise CommandError("address request pr must be a positive integer")
    head_oid = raw.get("head_oid")
    if not isinstance(head_oid, str) or FULL_SHA_RE.fullmatch(head_oid) is None:
        raise CommandError("address request head_oid must be a full lowercase SHA")
    raw_replies = raw.get("replies")
    if (
        not isinstance(raw_replies, Sequence)
        or isinstance(raw_replies, (str, bytes))
        or not raw_replies
    ):
        raise CommandError("address request replies must be a nonempty list")
    replies: list[dict[str, object]] = []
    thread_ids: set[str] = set()
    comment_ids: set[int] = set()
    for index, item in enumerate(raw_replies, start=1):
        if not isinstance(item, Mapping):
            raise CommandError(f"address reply {index} must be an object")
        _closed_fields(item, REPLY_FIELDS, f"address reply {index}")
        thread_id = item.get("thread_id")
        comment_id = item.get("top_comment_database_id")
        reply = item.get("reply")
        if not isinstance(thread_id, str) or not thread_id or len(thread_id) > 256:
            raise CommandError(f"address reply {index} thread_id is invalid")
        if (
            not isinstance(comment_id, int)
            or isinstance(comment_id, bool)
            or comment_id < 1
        ):
            raise CommandError(
                f"address reply {index} top_comment_database_id is invalid"
            )
        if not isinstance(reply, str) or not reply.strip() or len(reply) > 65_536:
            raise CommandError(f"address reply {index} reply is invalid")
        if thread_id in thread_ids or comment_id in comment_ids:
            raise CommandError("address request thread and comment IDs must be unique")
        thread_ids.add(thread_id)
        comment_ids.add(comment_id)
        replies.append(
            {
                "thread_id": thread_id,
                "top_comment_database_id": comment_id,
                "reply": reply,
            }
        )
    return {
        "repo": repo,
        "pr": pr,
        "head_oid": head_oid,
        "replies": replies,
    }


def _resolve_review_thread(
    thread_id: str,
    *,
    cwd: pathlib.Path | None = None,
) -> dict[str, Any]:
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
    data = gh_graphql(mutation, {"threadId": thread_id}, cwd=cwd)
    thread = (
        ((data.get("data") or {}).get("resolveReviewThread") or {}).get("thread")
    ) or {}
    if thread.get("id") != thread_id or thread.get("isResolved") is not True:
        raise CommandError(f"review thread did not resolve: {thread_id}")
    return {"id": thread_id, "is_resolved": True}


def address_request(
    request_path: pathlib.Path,
    *,
    cwd: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Post prepared replies and resolve exact threads without CLI output."""

    request = _address_request(request_path)
    repo = str(request["repo"])
    owner, name = repo.split("/", 1)
    pr = int(request["pr"])
    current = fetch_pr(owner, name, pr, cwd=cwd)
    if current.get("headRefOid") != request["head_oid"]:
        raise CommandError(
            f"PR head {current.get('headRefOid')!r} does not match prepared head "
            f"{request['head_oid']!r}"
        )
    viewer = current.get("viewer_login")
    if not isinstance(viewer, str) or not viewer:
        raise CommandError("GitHub viewer identity is unavailable")
    raw_threads = current.get("reviewThreads") or []
    threads = {
        thread.get("id"): thread
        for thread in raw_threads
        if isinstance(thread, dict) and isinstance(thread.get("id"), str)
    }
    prepared: list[tuple[dict[str, object], bool, bool]] = []
    raw_replies = request["replies"]
    assert isinstance(raw_replies, list)
    for reply in raw_replies:
        thread_id = str(reply["thread_id"])
        thread = threads.get(thread_id)
        if thread is None:
            raise CommandError(f"prepared review thread no longer exists: {thread_id}")
        comments = ((thread.get("comments") or {}).get("nodes")) or []
        top_comment = comments[0] if comments else {}
        if top_comment.get("databaseId") != reply["top_comment_database_id"]:
            raise CommandError(f"top comment changed for review thread: {thread_id}")
        matching_reply = any(
            comment.get("body") == reply["reply"]
            and comment_author(comment).lower() == viewer.lower()
            for comment in comments
            if isinstance(comment, dict)
        )
        resolved = bool(thread.get("isResolved"))
        if resolved and not matching_reply:
            raise CommandError(
                f"review thread resolved without the prepared reply: {thread_id}"
            )
        prepared.append((reply, matching_reply, resolved))

    posted = 0
    resolved_now = 0
    already_addressed = 0
    for reply, matching_reply, resolved in prepared:
        thread_id = str(reply["thread_id"])
        if resolved:
            already_addressed += 1
            continue
        if not matching_reply:
            comment_id = reply["top_comment_database_id"]
            assert isinstance(comment_id, int)
            result = run_gh_api(
                "POST",
                f"/repos/{repo}/pulls/{pr}/comments/{comment_id}/replies",
                {"body": reply["reply"]},
                cwd=cwd,
            )
            if not result.ok:
                raise CommandError(
                    f"review reply failed for {thread_id}: "
                    f"{result.message or result.status or 'unknown GitHub error'}"
                )
            posted += 1
        _resolve_review_thread(thread_id, cwd=cwd)
        resolved_now += 1
    return {
        "status": "addressed",
        "repo": repo,
        "pr": pr,
        "head_oid": request["head_oid"],
        "reply_count": len(prepared),
        "posted": posted,
        "resolved": resolved_now,
        "already_addressed": already_addressed,
    }


def address(args: argparse.Namespace) -> int:
    """Run the prepared-reply library operation and preserve the CLI contract."""

    address_request(args.request, cwd=args.cwd)
    print("OK")
    return 0


def resolve(args: argparse.Namespace) -> int:
    """Resolve selected review threads after their issues have been fixed."""

    results = [
        _resolve_review_thread(thread_id, cwd=args.cwd)
        for thread_id in args.thread_id
    ]
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
    wait_parser.add_argument("--cwd", type=pathlib.Path, default=pathlib.Path.cwd())
    wait_parser.add_argument("--json", action="store_true", help="accepted for compatibility; output is always JSON")
    wait_parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    wait_parser.set_defaults(func=wait)

    resolve_parser = subparsers.add_parser("resolve", help="resolve fixed Codex review threads")
    resolve_parser.add_argument("--thread-id", action="append", required=True, help="GraphQL PullRequestReviewThread ID")
    resolve_parser.add_argument("--cwd", type=pathlib.Path, default=pathlib.Path.cwd())
    resolve_parser.add_argument("--json", action="store_true", help="accepted for compatibility; output is always JSON")
    resolve_parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    resolve_parser.set_defaults(func=resolve)
    address_parser = subparsers.add_parser(
        "address",
        help="post prepared replies and resolve their exact review threads",
    )
    address_parser.add_argument("--request", required=True, type=pathlib.Path)
    address_parser.add_argument("--cwd", type=pathlib.Path, default=pathlib.Path.cwd())
    address_parser.set_defaults(func=address)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the selected Codex review gate operation."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (CommandError, OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
