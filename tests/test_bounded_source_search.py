import contextlib
import importlib.util
import io
import json
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "hooks" / "bounded-source-search.py"
SPEC = importlib.util.spec_from_file_location("bounded_source_search", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
BOUNDED = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BOUNDED
SPEC.loader.exec_module(BOUNDED)

OPENAI_DOCS_SCRIPT = (
    ROOT
    / "skills"
    / "openai-docs-managed"
    / "scripts"
    / "openai_docs_retrieval.py"
)
OPENAI_DOCS_SPEC = importlib.util.spec_from_file_location(
    "openai_docs_retrieval",
    OPENAI_DOCS_SCRIPT,
)
assert OPENAI_DOCS_SPEC is not None and OPENAI_DOCS_SPEC.loader is not None
OPENAI_DOCS = importlib.util.module_from_spec(OPENAI_DOCS_SPEC)
sys.modules[OPENAI_DOCS_SPEC.name] = OPENAI_DOCS
OPENAI_DOCS_SPEC.loader.exec_module(OPENAI_DOCS)


@unittest.skipUnless(shutil.which("rg"), "ripgrep is required")
class BoundedSourceSearchTests(unittest.TestCase):
    def test_search_ranks_files_and_bounds_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "one.py").write_text(
                "needle one\nneedle two\nneedle three\n",
                encoding="utf-8",
            )
            (root / "two.py").write_text("needle once\n", encoding="utf-8")
            (root / "three.py").write_text(
                "needle first\nplain\nneedle second\n",
                encoding="utf-8",
            )

            payload = BOUNDED.search(
                root,
                "needle",
                max_files=2,
                matches_per_file=2,
                context=0,
                max_bytes=4_000,
            )

        self.assertEqual(payload["schema"], "bounded-source-search.v1")
        self.assertTrue(payload["truncated"])
        files = payload["files"]
        self.assertEqual([item["path"] for item in files], ["one.py", "three.py"])
        for item in files:
            matches = [
                snippet
                for snippet in item["snippets"]
                if snippet["kind"] == "match"
            ]
            self.assertLessEqual(len(matches), 2)

    def test_search_enforces_total_output_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            for index in range(5):
                (root / f"file-{index}.txt").write_text(
                    ("needle " + "x" * 300 + "\n") * 4,
                    encoding="utf-8",
                )

            payload = BOUNDED.search(root, "needle", max_bytes=700)

        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertLessEqual(len(encoded), 700)
        self.assertTrue(payload["truncated"])

    @staticmethod
    def hook_result(event, *, max_bytes=600):
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(event))):
            with contextlib.redirect_stdout(stdout):
                returncode = BOUNDED.run_hook(max_bytes)
        if returncode != 0:
            raise AssertionError(f"hook returned {returncode}")
        output = stdout.getvalue().strip()
        return json.loads(output) if output else None

    def test_hook_replaces_only_oversized_successful_rg_output(self):
        lines = [f"src/a.py:{index}:needle {'x' * 100}" for index in range(20)]
        event = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "rg -n needle src"},
            "tool_response": {"exit_code": 0, "output": "\n".join(lines)},
        }

        payload = self.hook_result(event)

        self.assertIsNotNone(payload)
        self.assertFalse(payload["continue"])
        self.assertIn("Bounded source-search output", payload["stopReason"])
        self.assertLessEqual(len(payload["stopReason"].encode("utf-8")), 600)

    def test_hook_bounds_successful_command_probe_rg_output(self):
        lines = [f"src/a.py:{index}:needle {'x' * 100}" for index in range(20)]
        probe_output = json.dumps(
            {
                "schema": "ceratops-command-probe-result.v1",
                "ok": True,
                "mode": "search",
                "matched": True,
                "tool_returncode": 0,
                "stdout": "\n".join(lines),
                "stderr": "",
            }
        )
        event = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {
                "command": "python C:\\hooks\\command-probe.py --encoded-request x"
            },
            "tool_response": {"exit_code": 0, "output": probe_output},
        }

        payload = self.hook_result(event)

        self.assertIsNotNone(payload)
        self.assertIn("Bounded source-search output", payload["stopReason"])
        self.assertLessEqual(len(payload["stopReason"].encode("utf-8")), 600)

    def test_hook_leaves_small_non_search_and_failed_output_unchanged(self):
        base = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "rg -n needle src"},
            "tool_response": {"exit_code": 0, "output": "src/a.py:1:needle"},
        }
        self.assertIsNone(self.hook_result(base))

        non_search = dict(base)
        non_search["tool_input"] = {"command": "git status"}
        non_search["tool_response"] = {"exit_code": 0, "output": "x" * 1_000}
        self.assertIsNone(self.hook_result(non_search))

        failed = dict(base)
        failed["tool_response"] = {"exit_code": 2, "output": "x" * 1_000}
        self.assertIsNone(self.hook_result(failed))


class FakeDocumentationSearch:
    def __init__(self, hits, *, error=None):
        self.hits = tuple(hits)
        self.error = error
        self.calls = []

    def __call__(
        self,
        *,
        query,
        requested_product,
        requested_model,
        route,
    ):
        self.calls.append(
            {
                "query": query,
                "requested_product": requested_product,
                "requested_model": requested_model,
                "route": route,
            }
        )
        return OPENAI_DOCS.SearchRun(self.hits, error=self.error)


class FakeDocumentationFetch:
    def __init__(self, responses):
        self.responses = dict(responses)
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        response = self.responses.get(url)
        if response is not None:
            return response
        return OPENAI_DOCS.FetchResult(
            requested_url=url,
            final_url=url,
            status=None,
            content_type=None,
            body="",
            error="network_unavailable",
        )


class FakeDocumentationModel:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return "Independent synthesis of the retained evidence."


class ManagedOpenAIDocsRetrievalTests(unittest.TestCase):
    GOOD_URL = "https://developers.openai.com/api/docs/models/example.md"

    @staticmethod
    def request(
        query="How do I configure Codex approval policy?",
        *,
        product="Codex",
        model=None,
        route=None,
        independent=False,
    ):
        return {
            "schema": OPENAI_DOCS.REQUEST_SCHEMA,
            "query": query,
            "requested_product": product,
            "requested_model": model,
            "route": route,
            "independent_synthesis": independent,
        }

    @staticmethod
    def hit(url, *, title="Official page", snippet="routing snippet"):
        return OPENAI_DOCS.SearchHit(url=url, title=title, snippet=snippet)

    @staticmethod
    def page(url, body, *, final_url=None, redirects=(), error=None):
        return OPENAI_DOCS.FetchResult(
            requested_url=url,
            final_url=final_url or url,
            status=None if error else 200,
            content_type=None if error else "text/markdown",
            body="" if error else body,
            redirects=tuple(redirects),
            bytes_received=len(body.encode("utf-8")) if not error else 0,
            error=error,
        )

    def test_allowlist_and_single_route_are_enforced(self):
        disallowed = "https://example.com/claim.md"
        search = FakeDocumentationSearch(
            [
                self.hit(disallowed, snippet="The forbidden result says anything."),
                self.hit(
                    self.GOOD_URL,
                    title="Codex configuration",
                    snippet="The index snippet is routing only.",
                ),
            ]
        )
        fetch = FakeDocumentationFetch(
            {
                self.GOOD_URL: self.page(
                    self.GOOD_URL,
                    "# Codex configuration\n\n"
                    "Codex approval policy is configured in config.toml.",
                )
            }
        )

        record = OPENAI_DOCS.retrieve_documentation(
            self.request(route="codex"),
            search_runner=search,
            fetch_runner=fetch,
        )

        self.assertEqual(record["selected_route"], "codex")
        self.assertEqual(len(search.calls), 1)
        self.assertEqual(search.calls[0]["route"], "codex")
        self.assertNotIn(disallowed, fetch.calls)
        self.assertEqual(
            record["fetch_telemetry"]["rejected_result_count"],
            1,
        )

    def test_claims_use_opened_page_evidence_and_citable_urls(self):
        escaped = r"\!" * 512
        for malformed in (
            '{{key:"!",type:"' + escaped,
            '{{key:"!",type:"",description:"' + escaped,
        ):
            self.assertFalse(
                any(
                    block.heading and block.heading.startswith("Configuration key ")
                    for block in OPENAI_DOCS._markdown_blocks(malformed)[1]
                )
            )
        _, config_blocks, _ = OPENAI_DOCS._markdown_blocks(
            r'{ key: "approval_policy", type: "string", '
            r'description: "Use \"never\".", }'
        )
        self.assertEqual(
            [
                (block.heading, block.text)
                for block in config_blocks
                if block.heading and block.heading.startswith("Configuration key ")
            ],
            [
                (
                    "Configuration key approval_policy",
                    r'approval_policy (string): Use \"never\".',
                )
            ],
        )
        search = FakeDocumentationSearch(
            [
                self.hit(
                    self.GOOD_URL,
                    snippet="SNIPPET_ONLY says approval policy is somewhere else.",
                )
            ]
        )
        fetch = FakeDocumentationFetch(
            {
                self.GOOD_URL: self.page(
                    self.GOOD_URL,
                    "# Configuration Reference\n\n"
                    "## approval_policy\n\n"
                    "The Codex approval_policy setting controls approval behavior.",
                )
            }
        )

        record = OPENAI_DOCS.retrieve_documentation(
            self.request(),
            search_runner=search,
            fetch_runner=fetch,
        )

        self.assertEqual(record["status"], "ok")
        evidence_text = " ".join(
            claim["claim"] for claim in record["claim_evidence"]
        )
        self.assertIn("approval_policy", evidence_text)
        self.assertNotIn("SNIPPET_ONLY", evidence_text)
        for claim in record["claim_evidence"]:
            self.assertIn(claim["source"]["url"], record["opened_urls"])
            self.assertEqual(
                claim["source"]["evidence_kind"],
                "opened_page_excerpt",
            )

    def test_exact_requested_model_is_preserved(self):
        requested = "gpt-5.6-LuNa-preview"
        search = FakeDocumentationSearch([self.hit(self.GOOD_URL)])
        fetch = FakeDocumentationFetch(
            {
                self.GOOD_URL: self.page(
                    self.GOOD_URL,
                    "# Model support\n\n"
                    f"The exact model {requested} is supported for tool use.",
                )
            }
        )

        record = OPENAI_DOCS.retrieve_documentation(
            self.request(
                query=f"Does {requested} support tools?",
                product="OpenAI API",
                model=requested,
                route="model-selection",
            ),
            search_runner=search,
            fetch_runner=fetch,
        )

        self.assertEqual(record["requested_model"], requested)
        self.assertEqual(search.calls[0]["requested_model"], requested)
        self.assertIn(
            requested,
            " ".join(claim["claim"] for claim in record["claim_evidence"]),
        )

    def test_model_routes_search_detailed_pages_not_nested_indexes(self):
        index_url = "https://developers.openai.com/api/docs/llms.txt"
        nested_index = "https://developers.openai.com/api/reference/llms.txt"
        models_page = "https://developers.openai.com/api/docs/models.md"
        fetch = FakeDocumentationFetch(
            {
                index_url: self.page(
                    index_url,
                    "# OpenAI API guides\n\n"
                    f"- [Reference index]({nested_index}): Endpoint schemas.\n"
                    f"- [Models]({models_page}): Compare current models.\n",
                )
            }
        )

        search = OPENAI_DOCS.OfficialIndexSearchRunner(fetch)
        result = search(
            query="Which model fits cost-sensitive high-volume work?",
            requested_product="OpenAI API",
            requested_model="gpt-5.6-luna",
            route="model-selection",
        )

        self.assertEqual(fetch.calls, [index_url])
        urls = [hit.url for hit in result.hits]
        self.assertEqual(
            urls[0],
            "https://developers.openai.com/api/docs/models/gpt-5.6-luna.md",
        )
        self.assertIn(models_page, urls)
        self.assertNotIn(nested_index, urls)
        self.assertEqual(result.rejected_results, 1)

    def test_mcp_identifier_drives_ranking_and_opened_claim_evidence(self):
        index_url = "https://learn.chatgpt.com/llms.txt"
        generic = "https://learn.chatgpt.com/docs/reference/troubleshooting.md"
        app_server = "https://learn.chatgpt.com/docs/app-server.md"
        security = "https://learn.chatgpt.com/docs/security/setup.md"
        mcp = "https://learn.chatgpt.com/docs/mcp-server.md"
        index_body = (
            "# Codex\n\n"
            f"- [Troubleshooting]({generic}): Troubleshooting Codex.\n"
            f"- [Codex App Server]({app_server}): Rich client interface.\n"
            f"- [Codex Security setup]({security}): Set up scanning.\n"
            f"- [Use Codex with the Agents SDK]({mcp}): Run an MCP server.\n"
        )
        fetch = FakeDocumentationFetch(
            {
                index_url: self.page(index_url, index_body),
                generic: self.page(
                    generic,
                    "# Troubleshooting\n\nGeneral Codex troubleshooting steps.",
                ),
                app_server: self.page(
                    app_server,
                    "# App Server\n\nCodex app-server powers rich clients.",
                ),
                security: self.page(
                    security,
                    "# Security setup\n\nSet up a repository security scan.",
                ),
                mcp: self.page(
                    mcp,
                    "# Codex MCP Server\n\n"
                    "Run codex mcp-server and inspect the MCP tools list. "
                    "Troubleshooting MCP setup starts by listing tools.",
                ),
            }
        )

        record = OPENAI_DOCS.retrieve_documentation(
            self.request(
                query="Codex MCP server setup/troubleshooting",
                route="troubleshooting",
            ),
            fetch_runner=fetch,
        )

        self.assertEqual(record["status"], "ok")
        self.assertIn(mcp, record["opened_urls"])
        self.assertIn(
            "MCP",
            " ".join(claim["claim"] for claim in record["claim_evidence"]),
        )

    def test_missing_identifier_is_an_insufficient_evidence_blocker(self):
        generic = "https://learn.chatgpt.com/docs/app-server.md"
        search = FakeDocumentationSearch([self.hit(generic)])
        fetch = FakeDocumentationFetch(
            {
                generic: self.page(
                    generic,
                    "# App Server setup\n\n"
                    "Codex app-server setup supports rich clients.",
                )
            }
        )

        record = OPENAI_DOCS.retrieve_documentation(
            self.request(
                query="Codex MCP server setup",
                route="troubleshooting",
            ),
            search_runner=search,
            fetch_runner=fetch,
        )

        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["blocker"]["code"], "insufficient_evidence")
        self.assertIn("mcp", " ".join(record["unresolved_ambiguity"]))

    def test_followup_group_must_share_the_named_surface(self):
        mcp = "https://learn.chatgpt.com/docs/mcp-server.md"
        generic = "https://learn.chatgpt.com/docs/reference/troubleshooting.md"
        search = FakeDocumentationSearch([self.hit(mcp), self.hit(generic)])
        fetch = FakeDocumentationFetch(
            {
                mcp: self.page(
                    mcp,
                    "# Codex MCP Server\n\nRun codex mcp-server for setup.",
                ),
                generic: self.page(
                    generic,
                    "# Troubleshooting\n\nGeneral Codex troubleshooting guidance.",
                ),
            }
        )

        record = OPENAI_DOCS.retrieve_documentation(
            self.request(
                query="Codex MCP server setup/troubleshooting",
                route="troubleshooting",
            ),
            search_runner=search,
            fetch_runner=fetch,
        )

        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["blocker"]["code"], "insufficient_evidence")
        self.assertIn(
            "troubleshooting",
            " ".join(record["unresolved_ambiguity"]),
        )

    def test_each_explicit_content_group_requires_opened_claim_evidence(self):
        structured = (
            "https://developers.openai.com/api/docs/guides/"
            "structured-outputs.md"
        )
        search = FakeDocumentationSearch([self.hit(structured)])
        fetch = FakeDocumentationFetch(
            {
                structured: self.page(
                    structured,
                    "# Structured Outputs\n\n"
                    "The Responses API can return schema-constrained output.",
                )
            }
        )

        record = OPENAI_DOCS.retrieve_documentation(
            self.request(
                query="Responses API structured outputs/tool use",
                product="OpenAI API",
                route="api",
            ),
            search_runner=search,
            fetch_runner=fetch,
        )

        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["blocker"]["code"], "insufficient_evidence")
        self.assertIn("tool use", " ".join(record["unresolved_ambiguity"]))

    def test_named_surface_requires_a_payload_concept_on_the_same_page(self):
        auth = "https://learn.chatgpt.com/docs/auth.md"
        cli = "https://learn.chatgpt.com/docs/codex/cli.md"
        security = "https://learn.chatgpt.com/docs/security/setup.md"
        search = FakeDocumentationSearch(
            [self.hit(auth), self.hit(cli), self.hit(security)]
        )
        fetch = FakeDocumentationFetch(
            {
                auth: self.page(
                    auth,
                    "# Authentication\n\nCodex CLI supports ChatGPT sign-in.",
                ),
                cli: self.page(
                    cli,
                    "# Codex CLI\n\nReview authentication options.",
                ),
                security: self.page(
                    security,
                    "# Codex Security setup\n\nSet up repository scanning.",
                ),
            }
        )

        record = OPENAI_DOCS.retrieve_documentation(
            self.request(
                query="Codex CLI setup and authentication",
                product="Codex CLI",
                route="codex",
            ),
            search_runner=search,
            fetch_runner=fetch,
        )

        self.assertEqual(record["status"], "blocked")
        self.assertIn("codex cli setup", " ".join(record["unresolved_ambiguity"]))

    def test_model_availability_accepts_supported_endpoint_alias(self):
        model = "gpt-5.6-luna"
        page = f"https://developers.openai.com/api/docs/models/{model}.md"
        search = FakeDocumentationSearch([self.hit(page)])
        fetch = FakeDocumentationFetch(
            {
                page: self.page(
                    page,
                    f"# {model}\n\nCurrent snapshot with supported endpoints.",
                )
            }
        )

        record = OPENAI_DOCS.retrieve_documentation(
            self.request(
                query=f"Exact model {model} capabilities/availability",
                product="OpenAI API",
                model=model,
                route="model-selection",
            ),
            search_runner=search,
            fetch_runner=fetch,
        )

        self.assertEqual(record["status"], "ok")

    def test_compositional_capitalized_terms_are_not_literal_phrases(self):
        windows = "https://learn.chatgpt.com/docs/windows/windows-sandbox.md"
        auth = "https://learn.chatgpt.com/docs/auth.md"
        search = FakeDocumentationSearch([self.hit(windows), self.hit(auth)])
        fetch = FakeDocumentationFetch(
            {
                windows: self.page(
                    windows,
                    "# Windows troubleshooting\n\n"
                    "Troubleshoot Codex sandbox behavior on Windows.",
                ),
                auth: self.page(
                    auth,
                    "# Codex authentication\n\n"
                    "Troubleshoot authentication with device code login.",
                ),
            }
        )

        record = OPENAI_DOCS.retrieve_documentation(
            self.request(
                query="Codex Windows authentication troubleshooting",
                route="troubleshooting",
            ),
            search_runner=search,
            fetch_runner=fetch,
        )

        self.assertNotIn("codex windows", " ".join(record["unresolved_ambiguity"]))

    def test_conflict_polarity_uses_only_anchor_bearing_sentences(self):
        migration = (
            "https://developers.openai.com/api/docs/guides/"
            "migrate-to-responses.md"
        )
        structured = (
            "https://developers.openai.com/api/docs/guides/"
            "structured-outputs.md"
        )
        search = FakeDocumentationSearch(
            [self.hit(migration), self.hit(structured)]
        )
        fetch = FakeDocumentationFetch(
            {
                migration: self.page(
                    migration,
                    "# Responses API\n\n"
                    "Responses API supports tool calling. Tool calling with "
                    "reasoning is not supported in Chat Completions.",
                ),
                structured: self.page(
                    structured,
                    "# Structured Outputs\n\n"
                    "Responses API supports Structured Outputs and tools.",
                ),
            }
        )

        record = OPENAI_DOCS.retrieve_documentation(
            self.request(
                query="Responses API structured outputs/tool use",
                product="Responses API",
                route="api",
            ),
            search_runner=search,
            fetch_runner=fetch,
        )

        self.assertNotEqual(record["blocker"], {"code": "conflicting_documentation"})
        self.assertNotEqual(record["status"], "ambiguous")

    def test_content_group_terms_cannot_be_pooled_across_pages(self):
        first = "https://developers.openai.com/api/docs/guides/tools.md"
        second = "https://developers.openai.com/api/docs/guides/outputs.md"
        search = FakeDocumentationSearch([self.hit(first), self.hit(second)])
        fetch = FakeDocumentationFetch(
            {
                first: self.page(
                    first,
                    "# Tools\n\nThe Responses API supports tool calling.",
                ),
                second: self.page(
                    second,
                    "# Outputs\n\nSchema-constrained outputs are supported.",
                ),
            }
        )

        record = OPENAI_DOCS.retrieve_documentation(
            self.request(
                query="Responses API and tool outputs",
                product="OpenAI API",
                route="api",
            ),
            search_runner=search,
            fetch_runner=fetch,
        )

        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["blocker"]["code"], "insufficient_evidence")

    def test_requested_products_remain_required_cross_route_anchors(self):
        administration = "https://learn.chatgpt.com/docs/administration.md"
        auth = "https://learn.chatgpt.com/docs/auth.md"
        ci = "https://learn.chatgpt.com/docs/security/cli/ci.md"
        search = FakeDocumentationSearch(
            [self.hit(administration), self.hit(auth), self.hit(ci)]
        )
        fetch = FakeDocumentationFetch(
            {
                administration: self.page(
                    administration,
                    "# ChatGPT workspace administration\n\n"
                    "Workspace members receive assigned roles and permissions.",
                ),
                auth: self.page(
                    auth,
                    "# Codex CLI authentication\n\n"
                    "Codex CLI supports ChatGPT sign-in authentication.",
                ),
                ci: self.page(
                    ci,
                    "# CI setup\n\nConfigure outputs and repository permissions.",
                ),
            }
        )

        record = OPENAI_DOCS.retrieve_documentation(
            self.request(
                query=(
                    "Compare ChatGPT workspace member administration with "
                    "Codex CLI authentication and Responses API structured "
                    "outputs: what setup and permissions differ?"
                ),
                product="ChatGPT, Codex CLI, and Responses API",
                route="chatgpt",
            ),
            search_runner=search,
            fetch_runner=fetch,
        )

        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["blocker"]["code"], "insufficient_evidence")
        self.assertIn("responses api", " ".join(record["unresolved_ambiguity"]))

    def test_route_search_prefers_each_named_architecture_surface(self):
        index_url = "https://learn.chatgpt.com/llms.txt"
        surfaces = {
            "Codex CLI": "https://learn.chatgpt.com/docs/codex-cli.md",
            "Codex SDK": "https://learn.chatgpt.com/docs/codex-sdk.md",
            "App Server": "https://learn.chatgpt.com/docs/app-server.md",
            "MCP Server": "https://learn.chatgpt.com/docs/mcp-server.md",
        }
        body = "# Codex\n\n" + "\n".join(
            f"- [{title}]({url}): Codex integration surface."
            for title, url in surfaces.items()
        )
        fetch = FakeDocumentationFetch({index_url: self.page(index_url, body)})

        result = OPENAI_DOCS.OfficialIndexSearchRunner(fetch)(
            query="How do Codex CLI, Codex SDK, and Codex App Server differ?",
            requested_product="Codex",
            requested_model=None,
            route="codex",
        )

        selected = {hit.url for hit in result.hits[:3]}
        self.assertEqual(
            selected,
            {
                surfaces["Codex CLI"],
                surfaces["Codex SDK"],
                surfaces["App Server"],
            },
        )

    def test_multiword_app_server_surface_gets_an_open_page_slot(self):
        index_url = "https://learn.chatgpt.com/llms.txt"
        cli = "https://learn.chatgpt.com/docs/codex/cli.md"
        sdk = "https://learn.chatgpt.com/docs/codex-sdk.md"
        app_server = "https://learn.chatgpt.com/docs/app-server.md"
        security = "https://learn.chatgpt.com/docs/security.md"
        body = (
            "# Codex\n\n"
            f"- [Codex CLI]({cli}): Run Codex locally.\n"
            f"- [Codex SDK]({sdk}): Automate coding threads.\n"
            f"- [App Server]({app_server}): Integrate rich clients.\n"
            f"- [Codex Security]({security}): Scan repositories.\n"
        )
        fetch = FakeDocumentationFetch({index_url: self.page(index_url, body)})

        result = OPENAI_DOCS.OfficialIndexSearchRunner(fetch)(
            query="Codex architecture: CLI vs SDK vs App Server",
            requested_product="Codex",
            requested_model=None,
            route="codex",
        )

        self.assertEqual(
            {hit.url for hit in result.hits[:3]},
            {cli, sdk, app_server},
        )

    def test_current_migration_does_not_fill_with_older_version_guides(self):
        index_url = "https://developers.openai.com/api/docs/llms.txt"
        current = (
            "https://developers.openai.com/api/docs/guides/"
            "latest-model/gpt-5.6.md"
        )
        older = (
            "https://developers.openai.com/api/docs/guides/"
            "latest-model/gpt-5.2.md"
        )
        older_codex = (
            "https://developers.openai.com/api/docs/guides/"
            "latest-model/gpt-5.3-codex.md"
        )
        older_integer = (
            "https://developers.openai.com/api/docs/guides/"
            "latest-model/gpt-5.md"
        )
        general = "https://developers.openai.com/api/docs/guides/models.md"
        body = (
            "# Models\n\n"
            f"- [GPT-5.6 migration]({current}): Current model guide.\n"
            f"- [GPT-5.2 migration]({older}): Older model guide.\n"
            f"- [GPT-5.3-Codex migration]({older_codex}): Older guide.\n"
            f"- [GPT-5 migration]({older_integer}): Older guide.\n"
            f"- [Model migration]({general}): General model guidance.\n"
        )
        fetch = FakeDocumentationFetch({index_url: self.page(index_url, body)})

        result = OPENAI_DOCS.OfficialIndexSearchRunner(fetch)(
            query="Migration to a newer GPT-5 family model",
            requested_product="OpenAI API",
            requested_model=None,
            route="model-migration",
        )

        urls = [hit.url for hit in result.hits]
        self.assertIn(current, urls)
        self.assertNotIn(older, urls)
        self.assertNotIn(older_codex, urls)
        self.assertNotIn(older_integer, urls)

    def test_representative_questions_select_one_expected_route(self):
        cases = (
            ("How do I install and configure Codex CLI?", "Codex", "codex"),
            (
                "How do Codex SDK and App Server differ?",
                "Codex",
                "codex",
            ),
            (
                "Which model should I choose for high-volume API work?",
                "OpenAI API",
                "model-selection",
            ),
            (
                "How do I migrate from Chat Completions to Responses?",
                "OpenAI API",
                "model-migration",
            ),
            ("Why does Codex authentication fail?", "Codex", "troubleshooting"),
            (
                "How do I manage ChatGPT workspace members?",
                "ChatGPT",
                "chatgpt",
            ),
            ("How do I stream Responses API output?", "OpenAI API", "api"),
        )

        for query, product, expected in cases:
            with self.subTest(query=query):
                request = OPENAI_DOCS.validate_request(
                    self.request(query=query, product=product)
                )
                self.assertEqual(OPENAI_DOCS.select_route(request), expected)

    def test_non_policy_failures_fall_through_to_later_same_route_page(self):
        urls = [
            f"https://developers.openai.com/api/docs/guides/candidate-{index}.md"
            for index in range(1, 5)
        ]
        search = FakeDocumentationSearch([self.hit(url) for url in urls])
        fetch = FakeDocumentationFetch(
            {
                **{
                    url: self.page(url, "", error="http_404")
                    for url in urls[:3]
                },
                urls[3]: self.page(
                    urls[3],
                    "# Codex approval policy\n\n"
                    "Codex approval policy is configured in config.toml.",
                ),
            }
        )

        record = OPENAI_DOCS.retrieve_documentation(
            self.request(route="codex"),
            search_runner=search,
            fetch_runner=fetch,
        )

        self.assertEqual(record["status"], "ok")
        self.assertEqual(fetch.calls, urls[:4])
        self.assertEqual(record["opened_urls"], [urls[3]])
        self.assertEqual(len(record["fetch_telemetry"]["fetch_attempts"]), 4)

    def test_fetching_stops_after_three_opened_pages(self):
        urls = [
            f"https://developers.openai.com/api/docs/guides/open-{index}.md"
            for index in range(1, 6)
        ]
        search = FakeDocumentationSearch([self.hit(url) for url in urls])
        fetch = FakeDocumentationFetch(
            {
                url: self.page(
                    url,
                    "# Codex approval policy\n\n"
                    "Codex approval policy is configured in config.toml.",
                )
                for url in urls
            }
        )

        record = OPENAI_DOCS.retrieve_documentation(
            self.request(route="codex"),
            search_runner=search,
            fetch_runner=fetch,
        )

        self.assertEqual(fetch.calls, urls[: OPENAI_DOCS.MAX_OPENED_PAGES])
        self.assertEqual(
            len(record["opened_urls"]),
            OPENAI_DOCS.MAX_OPENED_PAGES,
        )

    def test_failed_fetch_attempts_and_record_remain_bounded(self):
        urls = [
            f"https://developers.openai.com/api/docs/guides/missing-{index}.md"
            for index in range(1, OPENAI_DOCS.MAX_SEARCH_RESULTS + 1)
        ]
        search = FakeDocumentationSearch([self.hit(url) for url in urls])
        fetch = FakeDocumentationFetch({})

        record = OPENAI_DOCS.retrieve_documentation(
            self.request(route="codex"),
            search_runner=search,
            fetch_runner=fetch,
        )

        self.assertEqual(
            len(fetch.calls),
            OPENAI_DOCS.MAX_FETCH_ATTEMPTS,
        )
        self.assertEqual(
            record["blocker"]["code"],
            "documentation_unavailable",
        )
        encoded = json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertLessEqual(len(encoded), OPENAI_DOCS.MAX_RECORD_BYTES)

    def test_policy_redirect_stops_without_falling_through(self):
        first = "https://developers.openai.com/api/docs/guides/redirect.md"
        second = "https://developers.openai.com/api/docs/guides/usable.md"
        search = FakeDocumentationSearch([self.hit(first), self.hit(second)])
        fetch = FakeDocumentationFetch(
            {
                first: self.page(
                    first,
                    "# Redirected",
                    final_url="https://example.com/redirected.md",
                    redirects=("https://example.com/redirected.md",),
                ),
                second: self.page(
                    second,
                    "# Codex approval policy\n\n"
                    "Codex approval policy is configured in config.toml.",
                ),
            }
        )

        record = OPENAI_DOCS.retrieve_documentation(
            self.request(route="codex"),
            search_runner=search,
            fetch_runner=fetch,
        )

        self.assertEqual(record["blocker"]["code"], "disallowed_redirect")
        self.assertEqual(fetch.calls, [first])
        self.assertEqual(record["opened_urls"], [])

    def test_allowed_and_disallowed_redirects_are_distinguished(self):
        requested = "https://developers.openai.com/codex/config-reference"
        allowed_final = "https://learn.chatgpt.com/docs/config-file/config-reference.md"
        search = FakeDocumentationSearch([self.hit(requested)])
        allowed_fetch = FakeDocumentationFetch(
            {
                requested: self.page(
                    requested,
                    "# Configuration Reference\n\n"
                    "Codex config.toml contains the approval policy setting.",
                    final_url=allowed_final,
                    redirects=(allowed_final,),
                )
            }
        )

        allowed = OPENAI_DOCS.retrieve_documentation(
            self.request(route="codex"),
            search_runner=search,
            fetch_runner=allowed_fetch,
        )

        self.assertIn(allowed_final, allowed["opened_urls"])
        self.assertEqual(
            allowed["fetch_telemetry"]["fetch_attempts"][0]["redirects"],
            [allowed_final],
        )

        disallowed_final = "https://example.com/config.md"
        disallowed_fetch = FakeDocumentationFetch(
            {
                requested: self.page(
                    requested,
                    "# Configuration Reference\n\n"
                    "Codex config.toml contains the approval policy setting.",
                    final_url=disallowed_final,
                    redirects=(disallowed_final,),
                )
            }
        )
        blocked = OPENAI_DOCS.retrieve_documentation(
            self.request(route="codex"),
            search_runner=search,
            fetch_runner=disallowed_fetch,
        )
        self.assertEqual(blocked["blocker"]["code"], "disallowed_redirect")
        self.assertEqual(blocked["opened_urls"], [])

    def test_conflict_reports_ambiguity_and_semantic_escalation(self):
        first = "https://developers.openai.com/api/docs/models/first.md"
        second = "https://developers.openai.com/api/docs/models/second.md"
        model = "gpt-test-exact"
        search = FakeDocumentationSearch([self.hit(first), self.hit(second)])
        fetch = FakeDocumentationFetch(
            {
                first: self.page(
                    first,
                    f"# Availability\n\nThe model {model} is supported and available.",
                ),
                second: self.page(
                    second,
                    f"# Availability\n\nThe model {model} is not supported.",
                ),
            }
        )

        record = OPENAI_DOCS.retrieve_documentation(
            self.request(
                query=f"Is {model} supported?",
                product="OpenAI API",
                model=model,
                route="model-selection",
            ),
            search_runner=search,
            fetch_runner=fetch,
        )

        self.assertEqual(record["status"], "ambiguous")
        self.assertEqual(
            record["blocker"]["code"],
            "conflicting_documentation",
        )
        self.assertTrue(record["unresolved_ambiguity"])
        self.assertEqual(
            record["escalation"]["reason"],
            "semantic_reconciliation_required",
        )
        self.assertTrue(record["escalation"]["eligible"])

    def test_semantic_conflict_makes_exactly_one_luna_low_call(self):
        first = "https://developers.openai.com/api/docs/models/first.md"
        second = "https://developers.openai.com/api/docs/models/second.md"
        requested = "gpt-test-exact"
        search = FakeDocumentationSearch([self.hit(first), self.hit(second)])
        fetch = FakeDocumentationFetch(
            {
                first: self.page(
                    first,
                    f"# Availability\n\nThe model {requested} is supported.",
                ),
                second: self.page(
                    second,
                    f"# Availability\n\nThe model {requested} is not supported.",
                ),
            }
        )
        model = FakeDocumentationModel()

        record = OPENAI_DOCS.orchestrate_retrieval(
            self.request(
                query=f"Is {requested} supported?",
                product="OpenAI API",
                model=requested,
                route="model-selection",
            ),
            search_runner=search,
            fetch_runner=fetch,
            model_runner=model,
        )

        self.assertEqual(len(model.calls), 1)
        self.assertEqual(model.calls[0]["model"], "gpt-5.6-luna")
        self.assertEqual(model.calls[0]["reasoning_effort"], "low")
        self.assertEqual(record["fetch_telemetry"]["model_calls"], 1)

    def test_offline_and_insufficient_results_do_not_invent_answers(self):
        search = FakeDocumentationSearch([self.hit(self.GOOD_URL)])
        offline_fetch = FakeDocumentationFetch(
            {
                self.GOOD_URL: self.page(
                    self.GOOD_URL,
                    "",
                    error="network_unavailable",
                )
            }
        )
        offline = OPENAI_DOCS.retrieve_documentation(
            self.request(),
            search_runner=search,
            fetch_runner=offline_fetch,
        )
        self.assertEqual(
            offline["blocker"]["code"],
            "documentation_unavailable",
        )
        self.assertEqual(offline["claim_evidence"], [])

        insufficient_fetch = FakeDocumentationFetch(
            {
                self.GOOD_URL: self.page(
                    self.GOOD_URL,
                    "# Image generation\n\n"
                    "This page describes image rendering and canvas dimensions.",
                )
            }
        )
        insufficient = OPENAI_DOCS.retrieve_documentation(
            self.request(query="Codex approval policy configuration"),
            search_runner=search,
            fetch_runner=insufficient_fetch,
        )
        self.assertEqual(
            insufficient["blocker"]["code"],
            "insufficient_evidence",
        )
        self.assertTrue(insufficient["unresolved_ambiguity"])

    def test_routine_retrieval_makes_zero_model_calls(self):
        search = FakeDocumentationSearch([self.hit(self.GOOD_URL)])
        fetch = FakeDocumentationFetch(
            {
                self.GOOD_URL: self.page(
                    self.GOOD_URL,
                    "# Configuration\n\n"
                    "Codex approval policy configuration is in config.toml.",
                )
            }
        )
        model = FakeDocumentationModel()

        record = OPENAI_DOCS.orchestrate_retrieval(
            self.request(),
            search_runner=search,
            fetch_runner=fetch,
            model_runner=model,
        )

        self.assertEqual(model.calls, [])
        self.assertEqual(record["fetch_telemetry"]["model_calls"], 0)
        self.assertIsNone(record["synthesis"])

    def test_explicit_synthesis_makes_one_luna_low_call_over_record_only(self):
        search = FakeDocumentationSearch([self.hit(self.GOOD_URL)])
        fetch = FakeDocumentationFetch(
            {
                self.GOOD_URL: self.page(
                    self.GOOD_URL,
                    "# Configuration\n\n"
                    "Codex approval policy configuration is in config.toml.",
                )
            }
        )
        model = FakeDocumentationModel()

        record = OPENAI_DOCS.orchestrate_retrieval(
            self.request(independent=True),
            search_runner=search,
            fetch_runner=fetch,
            model_runner=model,
        )

        self.assertEqual(len(model.calls), 1)
        call = model.calls[0]
        self.assertEqual(call["model"], "gpt-5.6-luna")
        self.assertEqual(call["reasoning_effort"], "low")
        self.assertTrue(call["analysis_only"])
        self.assertFalse(call["tools_allowed"])
        self.assertFalse(call["mutations_allowed"])
        retained = json.loads(call["record_json"])
        self.assertEqual(retained["query"], record["query"])
        self.assertIsNone(retained["synthesis"])
        self.assertEqual(record["fetch_telemetry"]["model_calls"], 1)
        self.assertEqual(record["synthesis"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
