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
