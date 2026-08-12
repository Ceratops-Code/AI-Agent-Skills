#!/usr/bin/env python3
"""Retrieve bounded evidence from official OpenAI documentation.

The public library boundary accepts a closed JSON-compatible request and
injectable search, fetch, and optional model runners. The CLI uses only
standard-library HTTPS retrieval against the declared allowlist, requires no
API key, and emits one bounded JSON record. Search-index descriptions are used
only to rank candidate URLs; claim evidence is extracted exclusively from
successfully opened source pages.

Optional synthesis is deliberately separate from retrieval. The orchestrator
may call one injected analysis runner only when the request explicitly asks for
independent synthesis or deterministic evidence reports a semantic conflict.
The runner receives only the retained record and fixed no-tool, non-mutating
constraints.
"""

from __future__ import annotations

import argparse
import html
import http.client
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol

REQUEST_SCHEMA = "openai-docs-retrieval-request.v1"
RECORD_SCHEMA = "openai-docs-retrieval-record.v1"
REQUEST_FIELDS = {
    "schema",
    "query",
    "requested_product",
    "requested_model",
    "route",
    "independent_synthesis",
}
ALLOWED_DOMAINS = frozenset(
    {
        "developers.openai.com",
        "platform.openai.com",
        "learn.chatgpt.com",
    }
)
ALLOWED_ROUTES = frozenset(
    {
        "api",
        "codex",
        "chatgpt",
        "model-selection",
        "model-migration",
        "troubleshooting",
    }
)
MAX_QUERY_CHARS = 2_000
MAX_NAME_CHARS = 200
MAX_SEARCH_RESULTS = 12
MAX_OPENED_PAGES = 3
MAX_CLAIMS = 8
MAX_EVIDENCE_CHARS = 700
MAX_AMBIGUITIES = 4
MAX_FETCH_BYTES = 1_500_000
MAX_RECORD_BYTES = 32_768
MAX_SYNTHESIS_CHARS = 4_000
MAX_REDIRECTS = 5

LINK_PATTERN = re.compile(
    r"^\s*-\s*\[([^]]+)]\((https://[^)]+)\)(?::\s*(.*))?\s*$"
)
TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.+-]*", re.IGNORECASE)
MODEL_PATH_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*", re.IGNORECASE)
MODEL_FAMILY_PATTERN = re.compile(r"^(gpt-\d+(?:\.\d+)+)", re.IGNORECASE)
HEADING_PATTERN = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
MARKDOWN_LINK_PATTERN = re.compile(r"!?\[([^]]*)]\(([^)]+)\)")
SPACE_PATTERN = re.compile(r"\s+")
MDX_CONFIG_PATTERN = re.compile(
    r'\{\s*key:\s*"(?P<key>[^"]+)",\s*'
    r'type:\s*"(?P<type>(?:\\.|[^"])*)",\s*'
    r'description:\s*"(?P<description>(?:\\.|[^"])*)",\s*\}',
    re.DOTALL,
)

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "can",
        "do",
        "does",
        "for",
        "how",
        "i",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "what",
        "when",
        "where",
        "with",
    }
)
NEGATIVE_CUES = (
    "not supported",
    "isn't supported",
    "is not available",
    "unavailable",
    "cannot",
    "can't",
    "deprecated",
    "no longer",
    "disabled",
)
POSITIVE_CUES = (
    "supported",
    "available",
    "recommended",
    "can use",
    "allows",
    "enabled",
)


@dataclass(frozen=True)
class RetrievalRequest:
    """Validated closed request with exact caller-provided names."""

    query: str
    requested_product: str | None
    requested_model: str | None
    route: str | None
    independent_synthesis: bool


@dataclass(frozen=True)
class SearchHit:
    """One routing-only search result; its snippet is never evidence."""

    url: str
    title: str
    snippet: str
    score: int = 0


@dataclass(frozen=True)
class SearchRun:
    """Bounded output from one primary documentation route search."""

    hits: tuple[SearchHit, ...]
    attempts: tuple[Mapping[str, Any], ...] = ()
    rejected_results: int = 0
    error: str | None = None


@dataclass(frozen=True)
class FetchResult:
    """One fetch attempt including every observed redirect."""

    requested_url: str
    final_url: str
    status: int | None
    content_type: str | None
    body: str
    redirects: tuple[str, ...] = ()
    bytes_received: int = 0
    error: str | None = None


@dataclass(frozen=True)
class RouteConfig:
    """Search index and ranking hints for one semantic route."""

    index_url: str
    path_hints: tuple[str, ...]
    title_hints: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceBlock:
    """A source-page text block with its nearest heading."""

    heading: str | None
    text: str


@dataclass(frozen=True)
class OpenedPage:
    """Opened source page retained for deterministic evidence extraction."""

    url: str
    title: str
    body_text: str
    blocks: tuple[EvidenceBlock, ...]


class SearchRunner(Protocol):
    """Injectable search boundary used by behavior tests and the CLI."""

    def __call__(
        self,
        *,
        query: str,
        requested_product: str | None,
        requested_model: str | None,
        route: str,
    ) -> SearchRun: ...


class FetchRunner(Protocol):
    """Injectable page-opening boundary used by search and retrieval."""

    def __call__(self, url: str) -> FetchResult: ...


class ModelRunner(Protocol):
    """Analysis-only retained-record synthesis boundary."""

    def __call__(
        self,
        *,
        record_json: str,
        model: str,
        reasoning_effort: str,
        analysis_only: bool,
        tools_allowed: bool,
        mutations_allowed: bool,
    ) -> str: ...


ROUTES: dict[str, RouteConfig] = {
    "api": RouteConfig(
        "https://developers.openai.com/api/docs/llms.txt",
        ("/api/", "/reference/"),
        ("api", "responses", "guide", "reference"),
    ),
    "codex": RouteConfig(
        "https://learn.chatgpt.com/llms.txt",
        ("/docs/codex", "/docs/config", "/docs/build-skills", "/docs/developers"),
        ("codex", "configuration", "skills", "developers"),
    ),
    "chatgpt": RouteConfig(
        "https://learn.chatgpt.com/llms.txt",
        ("/docs/",),
        ("chatgpt", "work", "workspace"),
    ),
    "model-selection": RouteConfig(
        "https://developers.openai.com/api/docs/llms.txt",
        ("/models", "/latest-model", "/model"),
        ("models", "model selection", "compare"),
    ),
    "model-migration": RouteConfig(
        "https://developers.openai.com/api/docs/llms.txt",
        ("/migration", "/latest-model", "/responses"),
        ("migration", "upgrade", "model guidance"),
    ),
    "troubleshooting": RouteConfig(
        "https://learn.chatgpt.com/llms.txt",
        ("/troubleshooting", "/windows", "/auth", "/sandbox"),
        ("troubleshooting", "windows", "authentication", "sandbox"),
    ),
}


class RequestError(ValueError):
    """Closed request validation failure."""


class UrlPolicyError(ValueError):
    """URL or redirect outside the HTTPS allowlist."""

    def __init__(self, code: str, url: str) -> None:
        super().__init__(f"{code}: {url}")
        self.code = code
        self.url = url


def _require_allowed_url(url: str, *, redirect: bool = False) -> str:
    """Return a canonical allowed HTTPS URL or raise a policy error."""

    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise UrlPolicyError("invalid_url", url) from exc
    host = (parsed.hostname or "").casefold()
    code = "disallowed_redirect" if redirect else "disallowed_url"
    if (
        parsed.scheme.casefold() != "https"
        or host not in ALLOWED_DOMAINS
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise UrlPolicyError(code, url)
    netloc = host if port is None else f"{host}:{port}"
    return urllib.parse.urlunsplit(
        ("https", netloc, parsed.path or "/", parsed.query, "")
    )


def _bounded_text(value: str, limit: int) -> str:
    """Normalize whitespace and bound retained evidence without adding text."""

    normalized = SPACE_PATTERN.sub(" ", html.unescape(value)).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _tokens(*values: str | None) -> tuple[str, ...]:
    """Return stable significant search terms without rewriting caller fields."""

    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        for token in TOKEN_PATTERN.findall(value.casefold()):
            candidates = [token]
            candidates.extend(
                part for part in re.split(r"[-_.+]", token) if part
            )
            if token.startswith("configur"):
                candidates.append("config")
            if token.startswith("migrat"):
                candidates.extend(("migrate", "migration"))
            if token.startswith("troubleshoot"):
                candidates.append("troubleshooting")
            for candidate in candidates:
                if candidate in STOPWORDS or len(candidate) < 2 or candidate in seen:
                    continue
                seen.add(candidate)
                ordered.append(candidate)
    return tuple(ordered)


def _term_weight(term: str) -> int:
    """Give specific identifiers more weight than broad product words."""

    return min(12, max(2, len(term)))


def validate_request(value: Mapping[str, Any]) -> RetrievalRequest:
    """Validate the helper's closed JSON request."""

    missing = sorted(REQUEST_FIELDS - set(value))
    extra = sorted(set(value) - REQUEST_FIELDS)
    if missing or extra:
        raise RequestError(f"request fields invalid; missing={missing} extra={extra}")
    if value.get("schema") != REQUEST_SCHEMA:
        raise RequestError(f"schema must be {REQUEST_SCHEMA}")
    query = value.get("query")
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
        raise RequestError("query must be nonempty text within 2000 characters")

    def optional_name(field: str) -> str | None:
        item = value.get(field)
        if item is None:
            return None
        if (
            not isinstance(item, str)
            or not item.strip()
            or len(item) > MAX_NAME_CHARS
        ):
            raise RequestError(
                f"{field} must be null or nonempty text within 200 characters"
            )
        return item

    requested_product = optional_name("requested_product")
    requested_model = optional_name("requested_model")
    route = value.get("route")
    if route is not None and (
        not isinstance(route, str) or route not in ALLOWED_ROUTES
    ):
        raise RequestError(
            "route must be null or one of "
            + ", ".join(sorted(ALLOWED_ROUTES))
        )
    independent = value.get("independent_synthesis")
    if not isinstance(independent, bool):
        raise RequestError("independent_synthesis must be boolean")
    return RetrievalRequest(
        query=query,
        requested_product=requested_product,
        requested_model=requested_model,
        route=route,
        independent_synthesis=independent,
    )


def select_route(request: RetrievalRequest) -> str:
    """Select exactly one route, preserving an explicit valid route."""

    if request.route is not None:
        return request.route
    text = " ".join(
        part
        for part in (
            request.query,
            request.requested_product,
            request.requested_model,
        )
        if part
    ).casefold()
    if any(term in text for term in ("migrate", "migration", "upgrade")):
        return "model-migration"
    if any(
        term in text
        for term in ("choose model", "which model", "model selection", "compare model")
    ):
        return "model-selection"
    if any(
        term in text
        for term in ("troubleshoot", "error", "fails", "failure", "not working")
    ):
        return "troubleshooting"
    if "chatgpt" in text or "workspace" in text or "chatgpt work" in text:
        return "chatgpt"
    if any(
        term in text
        for term in (
            "codex",
            "config.toml",
            "skill",
            "automation",
            "desktop app",
            "app server",
        )
    ):
        return "codex"
    return "api"


class _AllowedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow only bounded redirects that stay inside the allowlist."""

    def __init__(self) -> None:
        super().__init__()
        self.redirects: list[str] = []

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        absolute = urllib.parse.urljoin(req.full_url, newurl)
        canonical = _require_allowed_url(absolute, redirect=True)
        self.redirects.append(canonical)
        if len(self.redirects) > MAX_REDIRECTS:
            raise UrlPolicyError("too_many_redirects", canonical)
        return super().redirect_request(req, fp, code, msg, headers, canonical)


class UrlLibFetcher:
    """No-key HTTPS fetcher with bounded content and redirect enforcement."""

    def __init__(self, *, timeout_seconds: float = 15.0) -> None:
        self.timeout_seconds = timeout_seconds

    def __call__(self, url: str) -> FetchResult:
        try:
            requested = _require_allowed_url(url)
        except UrlPolicyError as exc:
            return FetchResult(
                requested_url=url,
                final_url=url,
                status=None,
                content_type=None,
                body="",
                error=exc.code,
            )
        handler = _AllowedRedirectHandler()
        opener = urllib.request.build_opener(handler)
        request = urllib.request.Request(
            requested,
            headers={
                "Accept": "text/markdown,text/plain,text/html;q=0.9",
                "User-Agent": "openai-docs-managed/1.0",
            },
            method="GET",
        )
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                raw = response.read(MAX_FETCH_BYTES + 1)
                if len(raw) > MAX_FETCH_BYTES:
                    return FetchResult(
                        requested_url=requested,
                        final_url=response.geturl(),
                        status=response.getcode(),
                        content_type=response.headers.get_content_type(),
                        body="",
                        redirects=tuple(handler.redirects),
                        bytes_received=len(raw),
                        error="response_too_large",
                    )
                final_url = _require_allowed_url(
                    response.geturl(),
                    redirect=response.geturl() != requested,
                )
                charset = response.headers.get_content_charset() or "utf-8"
                body = raw.decode(charset, errors="replace")
                return FetchResult(
                    requested_url=requested,
                    final_url=final_url,
                    status=response.getcode(),
                    content_type=response.headers.get_content_type(),
                    body=body,
                    redirects=tuple(handler.redirects),
                    bytes_received=len(raw),
                )
        except UrlPolicyError as exc:
            return FetchResult(
                requested_url=requested,
                final_url=exc.url,
                status=None,
                content_type=None,
                body="",
                redirects=tuple(handler.redirects) + (exc.url,),
                error=exc.code,
            )
        except urllib.error.HTTPError as exc:
            return FetchResult(
                requested_url=requested,
                final_url=exc.geturl(),
                status=exc.code,
                content_type=exc.headers.get_content_type() if exc.headers else None,
                body="",
                redirects=tuple(handler.redirects),
                error=f"http_{exc.code}",
            )
        except (
            urllib.error.URLError,
            TimeoutError,
            socket.timeout,
            ConnectionError,
            OSError,
        ):
            return FetchResult(
                requested_url=requested,
                final_url=requested,
                status=None,
                content_type=None,
                body="",
                redirects=tuple(handler.redirects),
                error="network_unavailable",
            )


def _search_score(
    hit: SearchHit,
    *,
    terms: Sequence[str],
    requested_model: str | None,
    config: RouteConfig,
) -> int:
    text = f"{hit.title} {hit.snippet} {hit.url}".casefold()
    score = sum(
        _term_weight(term) * (2 if term in hit.title.casefold() else 1)
        for term in terms
        if term in text
    )
    score += sum(5 for hint in config.path_hints if hint in hit.url.casefold())
    score += sum(3 for hint in config.title_hints if hint in text)
    title_terms = _tokens(hit.title)
    if title_terms and all(term in terms for term in title_terms):
        score += sum(_term_weight(term) * 3 for term in title_terms)
    if requested_model and requested_model.casefold() in text:
        score += 30
    if requested_model:
        family = MODEL_FAMILY_PATTERN.match(requested_model)
        if family is not None and family.group(1).casefold() in text:
            score += 18
    if (
        "/codex-manual" in hit.url.casefold()
        and not any(term in terms for term in ("manual", "orientation", "system"))
    ):
        score -= 30
    return score


class OfficialIndexSearchRunner:
    """Search one official route index and return routing-only candidates."""

    def __init__(self, fetch_runner: FetchRunner) -> None:
        self.fetch_runner = fetch_runner

    def __call__(
        self,
        *,
        query: str,
        requested_product: str | None,
        requested_model: str | None,
        route: str,
    ) -> SearchRun:
        config = ROUTES[route]
        response = self.fetch_runner(config.index_url)
        attempt = {
            "url": response.requested_url,
            "final_url": response.final_url,
            "status": response.status,
            "redirects": list(response.redirects[:MAX_REDIRECTS]),
            "error": response.error,
        }
        if response.error is not None or response.status != 200 or not response.body:
            return SearchRun((), (attempt,), error=response.error or "index_unavailable")
        terms = _tokens(query, requested_product, requested_model)
        hits: list[SearchHit] = []
        rejected = 0
        seen: set[str] = set()
        for line in response.body.splitlines():
            match = LINK_PATTERN.match(line)
            if match is None:
                continue
            title, raw_url, snippet = match.groups()
            try:
                url = _require_allowed_url(raw_url)
            except UrlPolicyError:
                rejected += 1
                continue
            path = urllib.parse.urlsplit(url).path.casefold()
            if path.endswith("/llms.txt") or path.endswith("/llms-full.txt"):
                rejected += 1
                continue
            if url in seen:
                continue
            seen.add(url)
            base_hit = SearchHit(
                url=url,
                title=_bounded_text(title, 200),
                snippet=_bounded_text(snippet or "", 300),
            )
            hits.append(
                SearchHit(
                    url=base_hit.url,
                    title=base_hit.title,
                    snippet=base_hit.snippet,
                    score=_search_score(
                        base_hit,
                        terms=terms,
                        requested_model=requested_model,
                        config=config,
                    ),
                )
            )
        if (
            requested_model
            and route in {"model-selection", "model-migration"}
            and MODEL_PATH_PATTERN.fullmatch(requested_model)
        ):
            # The guide index lists the model catalog but not every model page.
            # Retain the caller's exact identifier when probing its official page.
            exact_url = (
                "https://developers.openai.com/api/docs/models/"
                f"{urllib.parse.quote(requested_model, safe='._-')}.md"
            )
            if exact_url not in seen:
                exact_hit = SearchHit(
                    url=exact_url,
                    title=requested_model,
                    snippet="Exact requested model documentation.",
                )
                hits.append(
                    SearchHit(
                        url=exact_hit.url,
                        title=exact_hit.title,
                        snippet=exact_hit.snippet,
                        score=_search_score(
                            exact_hit,
                            terms=terms,
                            requested_model=requested_model,
                            config=config,
                        ),
                    )
                )
        hits.sort(key=lambda hit: (-hit.score, hit.url))
        return SearchRun(
            tuple(hits[:MAX_SEARCH_RESULTS]),
            (attempt,),
            rejected_results=rejected,
        )


class _HTMLExtractor(HTMLParser):
    """Extract bounded document text while omitting non-content containers."""

    BLOCK_TAGS = frozenset(
        {
            "article",
            "blockquote",
            "br",
            "div",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "li",
            "main",
            "p",
            "pre",
            "section",
            "td",
            "th",
            "tr",
        }
    )
    SKIP_TAGS = frozenset({"script", "style", "svg", "noscript", "nav", "footer"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
        elif self.skip_depth == 0 and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        elif self.skip_depth == 0 and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth == 0:
            self.parts.append(data)


def _clean_markdown(value: str) -> str:
    without_links = MARKDOWN_LINK_PATTERN.sub(lambda match: match.group(1), value)
    return _bounded_text(
        without_links.replace(chr(96), ""),
        MAX_EVIDENCE_CHARS * 2,
    )


def _markdown_blocks(text: str) -> tuple[str, tuple[EvidenceBlock, ...], str]:
    """Extract title and headed blocks from one opened Markdown page."""

    lines = text.splitlines()
    if lines[:1] == ["---"]:
        for index in range(1, min(len(lines), 100)):
            if lines[index] == "---":
                lines = lines[index + 1 :]
                break
    title = ""
    heading: str | None = None
    buffer: list[str] = []
    blocks = [
        EvidenceBlock(
            f"Configuration key {match.group('key')}",
            _clean_markdown(
                f"{match.group('key')} ({match.group('type')}): "
                f"{match.group('description')}"
            ),
        )
        for match in MDX_CONFIG_PATTERN.finditer(text)
    ]
    in_config_table = False

    def flush() -> None:
        if not buffer:
            return
        cleaned = _clean_markdown(" ".join(buffer))
        buffer.clear()
        if len(cleaned) >= 24:
            blocks.append(EvidenceBlock(heading, cleaned))

    for line in lines:
        match = HEADING_PATTERN.match(line)
        if match is not None:
            flush()
            heading = _clean_markdown(match.group(2))
            if not title and len(match.group(1)) == 1:
                title = heading
            continue
        if not line.strip():
            flush()
            continue
        stripped = line.strip()
        if stripped.startswith("<ConfigTable"):
            in_config_table = not stripped.endswith("/>")
            continue
        if in_config_table:
            if stripped.endswith("/>"):
                in_config_table = False
            continue
        if stripped.startswith(("<!--", "<script", "<style")):
            continue
        buffer.append(stripped)
    flush()
    body = "\n".join(block.text for block in blocks)
    return title or "OpenAI documentation", tuple(blocks), body


def _html_blocks(text: str) -> tuple[str, tuple[EvidenceBlock, ...], str]:
    extractor = _HTMLExtractor()
    extractor.feed(text)
    chunks = [
        _bounded_text(chunk, MAX_EVIDENCE_CHARS * 2)
        for chunk in re.split(r"\n{2,}", "".join(extractor.parts))
    ]
    blocks = tuple(EvidenceBlock(None, chunk) for chunk in chunks if len(chunk) >= 24)
    title = blocks[0].text[:200] if blocks else "OpenAI documentation"
    body = "\n".join(block.text for block in blocks)
    return title, blocks, body


def _opened_page(response: FetchResult) -> OpenedPage | None:
    content_type = (response.content_type or "").casefold()
    if content_type and not any(
        allowed in content_type
        for allowed in ("text/html", "text/plain", "text/markdown")
    ):
        return None
    if not response.body.strip():
        return None
    is_html = "text/html" in content_type or bool(
        re.search(r"<(?:html|body|main|article)\b", response.body[:4_000], re.I)
    )
    title, blocks, body = (
        _html_blocks(response.body)
        if is_html
        else _markdown_blocks(response.body)
    )
    if not blocks:
        return None
    return OpenedPage(
        url=response.final_url,
        title=title,
        body_text=body,
        blocks=blocks,
    )


def _claim_score(
    block: EvidenceBlock,
    *,
    terms: Sequence[str],
    requested_product: str | None,
    requested_model: str | None,
) -> int:
    text = f"{block.heading or ''} {block.text}".casefold()
    score = sum(_term_weight(term) for term in terms if term in text)
    if requested_product and requested_product.casefold() in text:
        score += 2
    if requested_model and requested_model.casefold() in text:
        score += 40
    if block.heading and any(term in block.heading.casefold() for term in terms):
        score += 5
    return score


def _claim_evidence(
    pages: Sequence[OpenedPage],
    request: RetrievalRequest,
) -> list[dict[str, Any]]:
    terms = _tokens(
        request.query,
        request.requested_product,
        request.requested_model,
    )
    specific_terms = set(_tokens(request.query))
    specific_terms.difference_update(
        _tokens(request.requested_product, request.requested_model)
    )
    ranked: list[tuple[int, str, str, str | None, str]] = []
    for page in pages:
        for block in page.blocks:
            block_text = f"{block.heading or ''} {block.text}".casefold()
            if specific_terms and not any(
                term in block_text for term in specific_terms
            ):
                continue
            score = _claim_score(
                block,
                terms=terms,
                requested_product=request.requested_product,
                requested_model=request.requested_model,
            )
            if score <= 0:
                continue
            ranked.append((score, page.url, page.title, block.heading, block.text))
    ranked.sort(key=lambda item: (-item[0], item[1], item[4]))
    claims: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    per_page: dict[str, int] = {}
    for _, url, title, heading, text in ranked:
        key = (url, text.casefold())
        if key in seen or per_page.get(url, 0) >= 3:
            continue
        seen.add(key)
        per_page[url] = per_page.get(url, 0) + 1
        claims.append(
            {
                "claim_id": f"claim-{len(claims) + 1}",
                "claim": _bounded_text(text, MAX_EVIDENCE_CHARS),
                "source": {
                    "url": url,
                    "title": _bounded_text(title, 200),
                    "locator": _bounded_text(heading, 200) if heading else None,
                    "evidence_kind": "opened_page_excerpt",
                },
            }
        )
        if len(claims) >= MAX_CLAIMS:
            break
    return claims


def _polarity(text: str) -> str | None:
    lowered = text.casefold()
    if any(cue in lowered for cue in NEGATIVE_CUES):
        return "negative"
    if any(cue in lowered for cue in POSITIVE_CUES):
        return "positive"
    return None


def _semantic_conflict(
    claims: Sequence[Mapping[str, Any]],
    request: RetrievalRequest,
) -> bool:
    anchor = request.requested_model or request.requested_product
    positive_urls: set[str] = set()
    negative_urls: set[str] = set()
    for claim in claims:
        text = str(claim.get("claim", ""))
        if anchor and anchor.casefold() not in text.casefold():
            continue
        source = claim.get("source")
        if not isinstance(source, Mapping):
            continue
        url = str(source.get("url", ""))
        polarity = _polarity(text)
        if polarity == "positive":
            positive_urls.add(url)
        elif polarity == "negative":
            negative_urls.add(url)
    return bool(positive_urls and negative_urls and positive_urls != negative_urls)


def _fetch_attempt(response: FetchResult, *, opened: bool) -> dict[str, Any]:
    return {
        "url": response.requested_url,
        "final_url": response.final_url,
        "status": response.status,
        "redirects": list(response.redirects[:MAX_REDIRECTS]),
        "bytes_received": response.bytes_received,
        "opened": opened,
        "error": response.error,
    }


def _blocker(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": _bounded_text(message, 500)}


def _base_record(
    request: RetrievalRequest | None,
    route: str | None,
) -> dict[str, Any]:
    return {
        "schema": RECORD_SCHEMA,
        "status": "blocked",
        "query": request.query if request else None,
        "requested_product": request.requested_product if request else None,
        "requested_model": request.requested_model if request else None,
        "selected_route": route,
        "opened_urls": [],
        "claim_evidence": [],
        "unresolved_ambiguity": [],
        "escalation": {
            "eligible": False,
            "reason": None,
            "model": None,
            "reasoning_effort": None,
            "max_calls": 0,
            "analysis_only": True,
            "tools_allowed": False,
            "mutations_allowed": False,
        },
        "fetch_telemetry": {
            "search_attempts": [],
            "fetch_attempts": [],
            "search_result_count": 0,
            "rejected_result_count": 0,
            "opened_count": 0,
            "bytes_received": 0,
            "model_calls": 0,
        },
        "blocker": None,
        "synthesis": None,
    }


def _bound_record(record: dict[str, Any]) -> dict[str, Any]:
    """Enforce the public record size without discarding blocker state."""

    def size() -> int:
        return len(
            json.dumps(
                record,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )

    claims = record["claim_evidence"]
    while size() > MAX_RECORD_BYTES and isinstance(claims, list) and len(claims) > 1:
        claims.pop()
    telemetry = record["fetch_telemetry"]
    if isinstance(telemetry, dict):
        for field in ("fetch_attempts", "search_attempts"):
            attempts = telemetry.get(field)
            while (
                size() > MAX_RECORD_BYTES
                and isinstance(attempts, list)
                and len(attempts) > 1
            ):
                attempts.pop()
    if size() > MAX_RECORD_BYTES:
        record["claim_evidence"] = []
        record["status"] = "blocked"
        record["blocker"] = _blocker(
            "record_limit_exceeded",
            "The bounded record could not retain evidence safely.",
        )
    return record


def retrieve_documentation(
    request_value: Mapping[str, Any],
    *,
    search_runner: SearchRunner | None = None,
    fetch_runner: FetchRunner | None = None,
) -> dict[str, Any]:
    """Run one deterministic search route and open bounded source pages."""

    try:
        request = validate_request(request_value)
    except RequestError as exc:
        record = _base_record(None, None)
        record["blocker"] = _blocker("invalid_request", str(exc))
        return _bound_record(record)

    route = select_route(request)
    record = _base_record(request, route)
    fetcher = fetch_runner or UrlLibFetcher()
    searcher = search_runner or OfficialIndexSearchRunner(fetcher)
    telemetry = record["fetch_telemetry"]
    try:
        search = searcher(
            query=request.query,
            requested_product=request.requested_product,
            requested_model=request.requested_model,
            route=route,
        )
    except Exception as exc:
        record["blocker"] = _blocker(
            "search_unavailable",
            f"The primary documentation route search failed: {type(exc).__name__}.",
        )
        return _bound_record(record)

    telemetry["search_attempts"] = [
        dict(attempt) for attempt in search.attempts[:MAX_OPENED_PAGES]
    ]
    telemetry["search_result_count"] = min(len(search.hits), MAX_SEARCH_RESULTS)
    telemetry["rejected_result_count"] = search.rejected_results
    allowed_hits: list[SearchHit] = []
    seen_urls: set[str] = set()
    for hit in search.hits[:MAX_SEARCH_RESULTS]:
        try:
            url = _require_allowed_url(hit.url)
        except UrlPolicyError:
            telemetry["rejected_result_count"] += 1
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        allowed_hits.append(
            SearchHit(url=url, title=hit.title, snippet=hit.snippet, score=hit.score)
        )
    if not allowed_hits:
        code = "search_unavailable" if search.error else "no_search_results"
        message = (
            "The selected official documentation route was unavailable."
            if search.error
            else "The selected official documentation route returned no allowed pages."
        )
        record["blocker"] = _blocker(code, message)
        return _bound_record(record)

    pages: list[OpenedPage] = []
    fetch_attempts: list[dict[str, Any]] = []
    fatal_redirect: FetchResult | None = None
    for hit in allowed_hits[:MAX_OPENED_PAGES]:
        response = fetcher(hit.url)
        try:
            _require_allowed_url(response.requested_url)
            _require_allowed_url(
                response.final_url,
                redirect=response.final_url != response.requested_url,
            )
            for redirect_url in response.redirects:
                _require_allowed_url(redirect_url, redirect=True)
        except UrlPolicyError:
            fatal_redirect = response
            fetch_attempts.append(_fetch_attempt(response, opened=False))
            break
        if response.error == "disallowed_redirect":
            fatal_redirect = response
            fetch_attempts.append(_fetch_attempt(response, opened=False))
            break
        page = (
            _opened_page(response)
            if response.error is None and response.status == 200
            else None
        )
        opened = page is not None
        fetch_attempts.append(_fetch_attempt(response, opened=opened))
        if opened and page is not None:
            pages.append(page)

    telemetry["fetch_attempts"] = fetch_attempts
    telemetry["bytes_received"] = sum(
        int(attempt["bytes_received"]) for attempt in fetch_attempts
    )
    if fatal_redirect is not None:
        record["blocker"] = _blocker(
            "disallowed_redirect",
            "A documentation request redirected outside the allowed domains.",
        )
        return _bound_record(record)
    if not pages:
        offline = bool(fetch_attempts) and all(
            attempt.get("error") == "network_unavailable"
            for attempt in fetch_attempts
        )
        record["blocker"] = _blocker(
            "documentation_unavailable" if offline else "page_open_failed",
            (
                "Official documentation was unavailable from the current network."
                if offline
                else "Search returned candidates, but no actual source page opened."
            ),
        )
        return _bound_record(record)

    record["opened_urls"] = [page.url for page in pages]
    telemetry["opened_count"] = len(pages)
    claims = _claim_evidence(pages, request)
    record["claim_evidence"] = claims
    ambiguities: list[str] = []
    blocker: dict[str, str] | None = None
    if not claims:
        ambiguities.append(
            "Opened documentation did not contain query-matched claim evidence."
        )
        blocker = _blocker(
            "insufficient_evidence",
            "Opened pages did not establish a source-backed answer.",
        )
    elif request.requested_model and not any(
        request.requested_model.casefold() in page.body_text.casefold()
        for page in pages
    ):
        ambiguities.append(
            f"The opened documentation did not mention the exact requested model "
            f"{request.requested_model!r}."
        )
        blocker = _blocker(
            "insufficient_evidence",
            "Opened pages did not establish the exact requested model.",
        )
    conflict = _semantic_conflict(claims, request)
    if conflict:
        ambiguities.append(
            "Opened official pages contain opposing availability or support claims."
        )
        blocker = _blocker(
            "conflicting_documentation",
            "Opened official pages require semantic reconciliation.",
        )

    record["unresolved_ambiguity"] = ambiguities[:MAX_AMBIGUITIES]
    record["blocker"] = blocker
    if conflict:
        record["status"] = "ambiguous"
    elif blocker is not None:
        record["status"] = "blocked"
    else:
        record["status"] = "ok"

    escalation_reason: str | None = None
    if conflict:
        escalation_reason = "semantic_reconciliation_required"
    elif request.independent_synthesis:
        escalation_reason = "explicit_independent_synthesis"
    if escalation_reason is not None and claims:
        record["escalation"] = {
            "eligible": True,
            "reason": escalation_reason,
            "model": "gpt-5.6-luna",
            "reasoning_effort": "low",
            "max_calls": 1,
            "analysis_only": True,
            "tools_allowed": False,
            "mutations_allowed": False,
        }
    return _bound_record(record)


def orchestrate_retrieval(
    request_value: Mapping[str, Any],
    *,
    search_runner: SearchRunner | None = None,
    fetch_runner: FetchRunner | None = None,
    model_runner: ModelRunner | None = None,
) -> dict[str, Any]:
    """Retrieve evidence and optionally perform one bounded retained-record call."""

    record = retrieve_documentation(
        request_value,
        search_runner=search_runner,
        fetch_runner=fetch_runner,
    )
    escalation = record.get("escalation")
    if not isinstance(escalation, Mapping) or not escalation.get("eligible"):
        return record
    if model_runner is None:
        record["synthesis"] = {
            "status": "unavailable",
            "text": None,
            "blocker": "model_runner_unavailable",
        }
        return _bound_record(record)

    retained_record = json.dumps(
        record,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    record["fetch_telemetry"]["model_calls"] = 1
    try:
        synthesis = model_runner(
            record_json=retained_record,
            model="gpt-5.6-luna",
            reasoning_effort="low",
            analysis_only=True,
            tools_allowed=False,
            mutations_allowed=False,
        )
    except Exception as exc:
        record["synthesis"] = {
            "status": "blocked",
            "text": None,
            "blocker": f"child_model_failed:{type(exc).__name__}",
        }
        return _bound_record(record)
    if not isinstance(synthesis, str) or not synthesis.strip():
        record["synthesis"] = {
            "status": "blocked",
            "text": None,
            "blocker": "child_model_returned_no_text",
        }
        return _bound_record(record)
    record["synthesis"] = {
        "status": "ok",
        "text": _bounded_text(synthesis, MAX_SYNTHESIS_CHARS),
        "model": "gpt-5.6-luna",
        "reasoning_effort": "low",
    }
    return _bound_record(record)


def _load_request(path: Path) -> Mapping[str, Any]:
    if not path.is_file() or path.stat().st_size > 16_384:
        raise RequestError("request file must be a regular JSON file within 16384 bytes")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RequestError(f"request file is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, Mapping):
        raise RequestError("request root must be an object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Retrieve bounded official OpenAI documentation evidence."
    )
    parser.add_argument("--request", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        request = _load_request(args.request)
    except RequestError as exc:
        record = _base_record(None, None)
        record["blocker"] = _blocker("invalid_request", str(exc))
        print(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        return 2
    record = retrieve_documentation(request)
    print(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
